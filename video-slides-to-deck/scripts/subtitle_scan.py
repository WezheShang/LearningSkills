#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
subtitle_scan.py -- recover each segment's spoken/subtitled content by reading
the burned-in subtitle band across the WHOLE segment.

Why this exists: the storyboard's `on_screen_text` comes from a single keyframe,
so on a 90-second segment it represents one instant, not the segment. To write a
per-page summary that actually covers the page, the subtitle band has to be
sampled densely across the segment and stitched into one tall strip the vision
model can read top-to-bottom in order.

Pipeline
  1. sample ~1 frame every `--per` seconds inside each segment (capped)
  2. one ffmpeg pass: select those frames, crop the subtitle band, downscale
  3. per segment: stack the crops vertically with a timestamp gutter
  4. upload the strip, ask the vision model to transcribe in order and dedupe
  5. write `subtitles` + `subtitle_strip` back into storyboard.json

Run:  python subtitle_scan.py <storyboard.json> [--per 4] [--max 12]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vlm_pick import upload, describe  # noqa: E402

from PIL import Image, ImageDraw, ImageFont

GUTTER = 62


def _font(sz=17):
    for n in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(n, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def sample_times(start, end, per, cap, inset=0.35):
    """Even samples strictly inside the segment, never on a transition."""
    lo, hi = start + inset, max(start + inset, end - inset)
    span = hi - lo
    if span <= 0.5:
        return [(start + end) / 2.0]
    n = max(1, min(cap, int(round(span / float(per))) + 1))
    return [lo + span * i / (n - 1) for i in range(n)]


def crop_band(video, times, fps, band, width, out_dir, batch=16, back=0.6):
    """Subtitle-band crops for every requested time.

    One giant select expression blows past ffmpeg's parser with more than a few
    dozen terms, so this works in batches. Each batch seeks to just before its
    first target and uses frame numbers RELATIVE to that seek point (a fresh
    -ss restarts the frame counter at 0), which also avoids re-decoding the whole
    file once per batch.
    """
    os.makedirs(out_dir, exist_ok=True)
    wanted = sorted({round(t, 3) for t in times})
    if not wanted:
        return []

    results = []
    nb = (len(wanted) + batch - 1) // batch
    for bi in range(nb):
        chunk = wanted[bi * batch:(bi + 1) * batch]
        t0 = max(0.0, chunk[0] - back)
        local = [max(0, int(round((t - t0) * fps))) for t in chunk]
        expr = "+".join(f"eq(n\\,{n})" for n in local)
        vf = (f"select='{expr}',crop=iw:ih*{band}:0:ih*(1-{band}),"
              f"scale={width}:-2")
        pat = os.path.join(out_dir, f"b{bi:03d}_%05d.png")
        p = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{t0:.3f}", "-i", video, "-vf", vf,
             "-fps_mode", "passthrough", pat],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        if p.returncode != 0:
            raise RuntimeError(
                f"ffmpeg batch {bi} failed: {p.stderr.decode('utf-8','replace')[:300]}")
        for i, n in enumerate(local):
            f = pat % (i + 1)
            if os.path.exists(f):
                # keep the ORIGINAL requested time -- the caller keys its map by
                # that, and t0 + n/fps drifts by up to a frame
                results.append({"t": chunk[i], "path": f})
    return results


def build_strip(items, title):
    """Stack subtitle crops vertically, timestamp gutter on the left."""
    if not items:
        return None
    ims = []
    for it in items:
        try:
            ims.append((it["t"], Image.open(it["path"]).convert("RGB")))
        except Exception:
            pass
    if not ims:
        return None
    tw = max(im.width for _t, im in ims)
    th = max(im.height for _t, im in ims)
    head = 40
    W = GUTTER + tw + 8
    H = head + len(ims) * (th + 4) + 6

    sheet = Image.new("RGB", (W, H), (16, 16, 20))
    d = ImageDraw.Draw(sheet)
    f = _font(15)
    fh = _font(19)
    d.text((8, 10), title[:70], fill=(240, 240, 245), font=fh)

    for i, (t, im) in enumerate(ims):
        y = head + i * (th + 4)
        d.rectangle([0, y, GUTTER - 4, y + th], fill=(30, 34, 46))
        lab = f"{int(t)//60}:{int(t)%60:02d}"
        try:
            twd = d.textlength(lab, font=f)
        except Exception:
            twd = 22
        d.text(((GUTTER - 6 - twd) / 2, y + th / 2 - 9), lab,
               fill=(150, 200, 255), font=f)
        if im.size != (tw, th):
            bg = Image.new("RGB", (tw, th), (0, 0, 0))
            bg.paste(im, ((tw - im.width) // 2, (th - im.height) // 2))
            im = bg
        sheet.paste(im, (GUTTER, y))
        d.line([0, y + th + 2, W, y + th + 2], fill=(40, 44, 56))
    return sheet


PROMPT = (
    "The attached image is a vertical stack of subtitle strips sampled from ONE "
    "segment of a video, in chronological order top to bottom. The left gutter "
    "shows each strip's timestamp.\n\n"
    "TASK: copy out the subtitle text.\n\n"
    "STRICT OUTPUT RULES:\n"
    "- Do NOT describe the image, the task, or your process.\n"
    "- Do NOT start with an English sentence. Never write \"Okay\", \"So\", "
    "\"Here's my interpretation\", \"I need to\", or any similar preamble.\n"
    "- Do NOT add a heading, label or markdown.\n"
    "- Begin your reply immediately with the first subtitle line.\n"
    "- One subtitle per line, in the ORIGINAL language. Chinese stays Chinese, "
    "never translate it.\n"
    "- Adjacent strips often repeat the same subtitle: output each distinct "
    "subtitle exactly once.\n"
    "- Skip decorative labels, axis text and watermarks.\n"
    "- If no subtitle is visible anywhere, reply with exactly: NONE\n\n"
    "A correct reply looks like this:\n"
    "缠论的买卖点是从中枢和背驰推导出来的\n"
    "每一个级别都有自己独立的走势结构\n"
    "所以第一步是先确定你当前分析的是哪个级别\n\n"
    "Now output the subtitles for this strip stack:"
)

RETRY_PROMPT = (
    "You returned commentary instead of the subtitle text. Do it again, following "
    "these rules exactly:\n"
    "1. Output ONLY subtitle lines, nothing else.\n"
    "2. No preamble, no explanation, no heading, no English.\n"
    "3. Keep the original language (usually Chinese).\n"
    "4. One subtitle per line, duplicates removed.\n"
    "5. Your first characters must be the first subtitle itself.\n\n"
    "Output now:"
)

# reasoning / preamble leakage the model falls into
_THINK = re.compile(
    r"^\s*(okay|ok|so|alright|here'?s|here is|let me|i need|i have|i'?m|"
    r"the image|this image|the attached|in this|transcription|note that|"
    r"looking at|based on|it looks|appears to|task|image description)",
    re.I)
_ASCII_WORD = re.compile(r"[A-Za-z]{3,}")


_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD = re.compile(r"[A-Za-z]{3,}")
_TS_PREFIX = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[-–—:：|]?\s*")
_MD = re.compile(r"[*_`]+")


def clean_lines(text, lang="zh"):
    """Keep subtitle lines only.

    The model reliably contaminates its reply with its own scaffolding: a
    made-up heading ("Extracting Subtitle Text"), reasoning prose ("Right,
    based on the distinct subtitles..."), and a timestamp prefix copied from the
    gutter ("0:22 - 咱们先来讲第一趴啊"). Matching an English-preamble blacklist
    does NOT catch these -- they vary every call.

    The high-precision rule: for a Chinese-subtitle segment, a line carrying no
    CJK is not a subtitle, so drop it. For other languages the same filter drops
    nothing, and the structural checks below still apply.
    """
    out = []
    for raw in text.splitlines():
        ln = raw.strip()
        ln = _TS_PREFIX.sub("", ln).strip()
        ln = _MD.sub("", ln)
        ln = re.sub(r"^\d+[.)、]\s*", "", ln).strip()
        ln = ln.strip("-*·—:：#> ").strip()
        ln = re.sub(r"\s+", " ", ln)
        if not ln or len(ln) < 2:
            continue
        if ln in ("NONE", "none"):
            continue
        if lang == "zh" and not _CJK.search(ln):
            continue
        # an English-prose line that merely QUOTES Chinese still passes the CJK
        # test, so also reject lines where English words dominate: real subtitles
        # are monolingual, analysis sentences are a mix
        en = len(_ASCII_WORD.findall(ln))
        if en >= 8 and len(_CJK.findall(ln)) >= 3:
            continue
        if out and out[-1] == ln:
            continue
        out.append(ln)
    return out


def looks_like_reasoning(lines, lang="zh"):
    """True when what came back is prose about the task, not a transcription."""
    if not lines:
        return False
    if any(_THINK.match(l) for l in lines):
        return True
    if lang == "zh":
        return all(not _CJK.search(l) for l in lines)
    # non-Chinese: flag when most lines read like English prose sentences
    words = [l for l in lines if len(_ASCII_WORD.findall(l)) >= 3]
    return len(words) * 3 > len(lines) * 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("storyboard")
    ap.add_argument("--per", type=float, default=4.0, help="seconds between samples")
    ap.add_argument("--max", type=int, default=12, help="max samples per segment")
    ap.add_argument("--band", default="0.20", help="subtitle band height as fraction")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    sb_path = os.path.abspath(args.storyboard)
    sb_dir = os.path.dirname(sb_path)
    with open(sb_path, encoding="utf-8") as fh:
        sb = json.load(fh)

    fps = sb["probe"]["fps"]
    out_dir = os.path.join(sb_dir, "subcrops")
    strips_dir = os.path.join(sb_dir, "substrips")
    os.makedirs(strips_dir, exist_ok=True)

    todo = [s for s in sb["segments"]
            if args.force or not s.get("subtitles")]
    print(f"subtitle-scan {len(todo)} / {len(sb['segments'])} segments "
          f"(every {args.per}s, max {args.max}, band {args.band})\n", flush=True)
    if not todo:
        print("nothing to do")
        return 0

    times, owner = [], {}
    for seg in todo:
        ts_ = sample_times(seg["start"], seg["end"], args.per, args.max)
        owner[seg["index"]] = ts_
        times.extend(ts_)

    print(f"extracting {len(times)} cropped frames ...", flush=True)
    crops = crop_band(sb["video"], times, fps, args.band, args.width, out_dir)
    print(f"  got {len(crops)} crops\n", flush=True)

    pool = {round(c["t"], 3): c["path"] for c in crops}
    failures = []

    for i, seg in enumerate(todo, 1):
        try:
            items = [{"t": t, "path": pool[round(t, 3)]}
                     for t in owner[seg["index"]]
                     if round(t, 3) in pool]
            sheet = build_strip(
                items, f"seg{seg['index']:02d}  {seg['start']:.0f}-{seg['end']:.0f}s")
            if sheet is None:
                raise RuntimeError("no crops for this segment")
            sp = os.path.join(strips_dir, f"sub{seg['index']:03d}.png")
            sheet.save(sp)

            url = upload(sp)
            text = describe(url, PROMPT, timeout=600)
            lines = clean_lines(text)

            # one retry: the model sometimes narrates the task instead of
            # copying it. Store that garbage only if the retry also fails, and
            # mark it so it can be reviewed rather than silently trusted.
            bad = looks_like_reasoning(lines)
            if bad:
                text2 = describe(url, RETRY_PROMPT, timeout=600)
                lines2 = clean_lines(text2)
                if lines2 and not looks_like_reasoning(lines2):
                    lines, bad = lines2, False
                else:
                    lines = lines2 or lines
            if lines == ["NONE"]:
                lines = []

            seg["subtitles"] = lines
            seg["subtitle_strip"] = sp
            seg["subtitle_samples"] = len(items)
            if bad:
                seg["subtitle_needs_review"] = True
            head = " / ".join(lines[:2])[:78]
            flag = "  << REVIEW" if bad else ""
            print(f"  [{i}/{len(todo)}] seg{seg['index']:>3} {len(items):>2} crops "
                  f"-> {len(lines):>2} lines | {head}{flag}", flush=True)
        except Exception as exc:
            failures.append((seg["index"], str(exc)))
            print(f"  [{i}/{len(todo)}] seg{seg['index']:>3} FAILED: {exc}", flush=True)
        time.sleep(args.sleep)

    sb["subtitle_scan"] = {
        "per_seconds": args.per,
        "max_samples": args.max,
        "band": args.band,
        "segments_done": sum(1 for s in sb["segments"] if s.get("subtitles")),
        "segments_total": len(sb["segments"]),
        "failures": [{"segment": i, "error": e} for i, e in failures],
    }
    with open(sb_path, "w", encoding="utf-8") as fh:
        json.dump(sb, fh, ensure_ascii=False, indent=2)

    print(f"\nsegments with subtitles: "
          f"{sb['subtitle_scan']['segments_done']}/{sb['subtitle_scan']['segments_total']}")
    print(f"-> {sb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
