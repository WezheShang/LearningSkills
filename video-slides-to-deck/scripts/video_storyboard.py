#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
video_storyboard.py -- split a video into semantic segments and pull key
screenshots for each one. Output feeds a PPT or an HTML page.

Pipeline
--------
  1. probe     ffprobe -> duration / fps / size
  2. cuts      ffmpeg scene-score filter -> shot boundaries (deterministic, free)
  3. normalize merge too-short shots, split if we ended up with too few
  4. frames    one ffmpeg pass -> N candidate keyframes per segment
  5. speech    faster-whisper transcript, attached to segments by midpoint
               (optional, --no-transcript to skip)
  6. emit      storyboard.json ready for the VLM title/frame-pick step

Run with miniconda3 python (has PIL / faster_whisper / cv2).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------- ffmpeg utils

def run(cmd, timeout=3600):
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), \
        proc.stderr.decode("utf-8", "replace")


def probe(video):
    code, out, err = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,r_frame_rate,width,height",
        "-show_entries", "format=duration",
        "-of", "json", video,
    ])
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err[:500]}")
    info = json.loads(out)
    st = info["streams"][0]

    def rate(s):
        try:
            num, den = s.split("/")
            return float(num) / float(den) if float(den) else 0.0
        except Exception:
            return 0.0

    fps = rate(st.get("avg_frame_rate", "")) or rate(st.get("r_frame_rate", "")) or 25.0
    return {
        "duration": float(info["format"]["duration"]),
        "fps": fps,
        "width": int(st["width"]),
        "height": int(st["height"]),
    }


# ------------------------------------------------------------- stage 2: cuts

_PTS = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")

# The scene score is normalised over the WHOLE frame, so its value depends on
# how much of the picture changes at a cut. Measured (scripts/selftest.py):
#   full-bleed colour change          -> hard cuts score 0.15-0.29
#   chrome-heavy slide (title bar +
#     caption band = ~1/3 of frame)  -> weakest real cut only 0.076
#   intra-shot motion, both cases     -> < 0.005
# 0.06 sits ~12x above the noise floor and passes BOTH cases; verified on a real
# 8.6-minute lecture (33 cuts at 0.06 vs 31 at 0.12, same 28 segments, no
# false-positive explosion). Run selftest.py to re-derive this for other decks.
DEFAULT_SCENE_THRESHOLD = 0.06


def detect_cuts(video, threshold, max_seconds=3600):
    """Scene-boundary timestamps via ffmpeg's `scene` variable (0-1 scale).

    Uses metadata=print so we get the score alongside each timestamp, which
    makes the cut list inspectable and tunable after the fact.
    """
    code, out, err = run([
        "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info",
        "-t", str(max_seconds),
        "-i", video,
        "-an", "-sn", "-dn",
        "-filter:v", f"select='gt(scene,{threshold})',metadata=print:file=-",
        "-fps_mode", "passthrough",
        "-f", "null", "-",
    ])
    blob = out + "\n" + err

    hits = []
    pending_t = None
    for line in blob.splitlines():
        m = _PTS.search(line)
        if m:
            pending_t = float(m.group(1))
            continue
        m = _SCORE.search(line)
        if m and pending_t is not None:
            hits.append((round(pending_t, 3), round(float(m.group(1)), 4)))
            pending_t = None

    # de-dup by timestamp, keeping the strongest score
    best = {}
    for t, s in hits:
        best[t] = max(best.get(t, 0.0), s)
    return sorted(best.items())


# -------------------------------------------------------- stage 3: normalize

def build_segments(duration, cuts, min_len, max_segments):
    """Turn raw cut times into a usable segment list."""
    edges = [0.0] + [t for t in cuts if 0.0 < t < duration - 0.2] + [duration]
    segs = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    segs = [(a, b) for a, b in segs if b - a > 0.15]

    # merge too-short neighbours into the previous segment
    merged = []
    for a, b in segs:
        if merged and (b - a) < min_len:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    segs = merged

    if not segs:
        segs = [(0.0, duration)]

    # too many -> merge neighbours, halving until within budget
    while len(segs) > max_segments:
        # merge the shortest adjacent pair that keeps things balanced
        gaps = [(segs[i + 1][1] - segs[i + 1][0], i) for i in range(len(segs) - 1)]
        _, i = min(gaps)
        segs[i] = (segs[i][0], segs[i + 1][1])
        del segs[i + 1]

    # Fall back to duration-based splitting ONLY when scene detection found
    # essentially nothing. Static single-camera footage (a talking head, a
    # screen recording) has no cuts at all, and one 40-minute slide is useless.
    # When real cuts were found, trust them -- a duration heuristic must never
    # override detected structure.
    if len(segs) <= 2:
        target = min(max_segments, max(2, int(round(duration / max(min_len, 1.0)))))
        while len(segs) < target and len(segs) < max_segments:
            i = max(range(len(segs)), key=lambda k: segs[k][1] - segs[k][0])
            a, b = segs[i]
            m = (a + b) / 2.0
            segs[i:i + 1] = [(a, m), (m, b)]

    return segs


# ------------------------------------------------------------ stage 4: frames

def candidate_times(a, b, k, inset=0.12):
    """Evenly spread inside the segment, avoiding the transitions at both ends."""
    span = b - a
    if span <= 0.2:
        return [a + span / 2.0]
    lo, hi = a + span * inset, b - span * inset
    if hi <= lo:
        hi = lo + span * 0.5
    if k == 1:
        return [(lo + hi) / 2.0]
    return [lo + (hi - lo) * i / (k - 1) for i in range(k)]


def extract_frames(video, times, out_dir, fps, width=768):
    """One decode pass: select every wanted frame, downscale, write PNG."""
    os.makedirs(out_dir, exist_ok=True)
    wanted = []
    for t in sorted(times):
        n = int(round(t * fps))
        if n >= 0:
            wanted.append(n)
    wanted = sorted(set(wanted))
    if not wanted:
        return []

    expr = "+".join(f"eq(n\\,{n})" for n in wanted)
    vf = f"select='{expr}',scale={width}:-2"
    out_pat = os.path.join(out_dir, "cand_%04d.png")

    code, _o, err = run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", video,
        "-vf", vf,
        "-fps_mode", "passthrough",
        out_pat,
    ])
    if code != 0:
        raise RuntimeError(f"frame extraction failed: {err[:500]}")

    # select preserves presentation order, so file i == wanted[i]
    files = [out_pat % (i + 1) for i in range(len(wanted))]
    files = [f for f in files if os.path.exists(f)]
    return [{"time": wanted[i] / fps, "path": f} for i, f in enumerate(files)]


# ----------------------------------------------------------- stage 5: speech

def transcribe(video, model_size="small", language=None):
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover
        return None, f"faster_whisper unavailable: {exc}"

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, info = model.transcribe(
        video,
        language=language,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
    )
    out = []
    for s in segs:
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
    return out, None


def attach_transcript(segments, lines):
    """Give each segment the speech that happens inside it."""
    for seg in segments:
        mid = (seg["start"] + seg["end"]) / 2.0
        picked = [
            ln["text"] for ln in lines
            if ln["start"] < mid < ln["end"]
            or (ln["end"] > seg["start"] and ln["start"] < seg["end"])
        ]
        seg["transcript"] = " ".join(picked).strip()


# -------------------------------------------------------------------- main

def build(video, out_dir, scene_threshold, min_len, max_segments, k_frames,
          width, do_transcript, whisper_model, language):
    os.makedirs(out_dir, exist_ok=True)
    info = probe(video)
    print(f"[1/6] probe      {info['duration']:.2f}s  {info['width']}x{info['height']}"
          f"  {info['fps']:.3f}fps", flush=True)

    hits = detect_cuts(video, scene_threshold)
    cuts = [t for t, _s in hits]
    print(f"[2/6] scene cuts {len(cuts)} detected @ threshold {scene_threshold}", flush=True)
    if hits:
        shown = ", ".join(f"{t:.2f}s({s:.3f})" for t, s in hits[:8])
        print(f"      strengths  {shown}{' ...' if len(hits) > 8 else ''}", flush=True)

    segs = build_segments(info["duration"], cuts, min_len, max_segments)
    print(f"[3/6] segments   {len(segs)}", flush=True)

    wanted = []
    for a, b in segs:
        wanted.extend(candidate_times(a, b, k_frames))
    frames = extract_frames(video, wanted, os.path.join(out_dir, "candidates"),
                            info["fps"], width)
    print(f"[4/6] frames     {len(frames)} candidate keyframes", flush=True)

    lines, err = (None, None)
    if do_transcript:
        lines, err = transcribe(video, whisper_model, language)
        if err:
            print(f"[5/6] speech     SKIPPED ({err})", flush=True)
        else:
            print(f"[5/6] speech     {len(lines)} subtitle lines", flush=True)
    else:
        print("[5/6] speech     skipped by flag", flush=True)

    segments = []
    for i, (a, b) in enumerate(segs, 1):
        segments.append({
            "index": i,
            "start": round(a, 3),
            "end": round(b, 3),
            "duration": round(b - a, 3),
            "title": None,
            "summary": None,
            "keyframe": None,
            "candidates": [],
            "transcript": "",
        })

    # map each candidate back onto its segment
    for f in frames:
        for seg in segments:
            if seg["start"] <= f["time"] < seg["end"]:
                seg["candidates"].append({"time": round(f["time"], 3), "path": f["path"]})
                break

    if lines:
        attach_transcript(segments, lines)

    result = {
        "video": os.path.abspath(video),
        "out_dir": os.path.abspath(out_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "probe": info,
        "params": {
            "scene_threshold": scene_threshold,
            "min_segment_seconds": min_len,
            "max_segments": max_segments,
            "candidates_per_segment": k_frames,
        },
        "raw_cuts": [{"time": t, "score": s} for t, s in hits],
        "transcript_lines": lines,
        "segments": segments,
    }

    path = os.path.join(out_dir, "storyboard.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print(f"[6/6] wrote      {path}", flush=True)
    return result, path


def main():
    ap = argparse.ArgumentParser(description="video -> segmented storyboard with keyframes")
    ap.add_argument("video")
    ap.add_argument("--out", default="storyboard_out")
    ap.add_argument("--scene-threshold", type=float, default=DEFAULT_SCENE_THRESHOLD,
                    help="scene score 0-1; lower = more cuts. ~0.06 calibrated "
                         "default; run scripts/selftest.py to re-derive the usable "
                         "range for your deck. 0.05 sensitive, 0.20 skips slide "
                         "build animations")
    ap.add_argument("--min-segment", type=float, default=4.0,
                    help="shots shorter than this get merged away")
    ap.add_argument("--max-segments", type=int, default=40)
    ap.add_argument("--candidates", type=int, default=3,
                    help="keyframes extracted per segment for the VLM to choose from")
    ap.add_argument("--width", type=int, default=768, help="candidate frame width")
    ap.add_argument("--no-transcript", action="store_true")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--language", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.video):
        print(f"video not found: {args.video}", file=sys.stderr)
        return 2

    result, _ = build(
        args.video, args.out, args.scene_threshold, args.min_segment,
        args.max_segments, args.candidates, args.width,
        not args.no_transcript, args.whisper_model, args.language,
    )

    print("\n--- segments ---")
    for s in result["segments"]:
        n = len(s["candidates"])
        print(f"  {s['index']:>3}  {s['start']:>7.2f}-{s['end']:<7.2f} "
              f"({s['duration']:>5.2f}s)  {n} cand")
    return 0


if __name__ == "__main__":
    sys.exit(main())
