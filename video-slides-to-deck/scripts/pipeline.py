#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pipeline.py -- run the whole mechanical half of the video->deck pipeline.

  stage 1  probe + scene-split + candidate keyframes   (video_storyboard.py)
  stage 2  numbered contact sheet per segment           (make_contact_sheets.py)
  stage 3  vision model picks the keyframe, names it    (vlm_pick.py)
  stage 4  per-segment burned-in subtitle transcription  (subtitle_scan.py)

Then it SCRUBS the subtitle output (models leak their own reasoning into
transcription replies) and prints the table the authoring step needs.

What it deliberately does NOT do: write titles or summaries. Those are judgement
calls that must be made from the actual content, not templated from the title.
The exit message tells the next step.

  python pipeline.py <video> --out <dir> [--lang zh] [--skip-subs]
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from subtitle_scan import clean_lines, looks_like_reasoning  # noqa: E402

PY = sys.executable


def run(script, *args, label=None):
    cmd = [PY, os.path.join(HERE, script)] + [str(a) for a in args]
    if label:
        print(f"\n>>> {label}", flush=True)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0:
        print(out)
        raise SystemExit(f"{script} failed (rc={p.returncode})")
    return out


def scrub(sb_path, lang="zh"):
    """Drop model chatter + duplicates from every subtitle list."""
    with open(sb_path, encoding="utf-8") as fh:
        sb = json.load(fh)
    changed = review = 0
    for s in sb["segments"]:
        raw = s.get("subtitles") or []
        clean = clean_lines("\n".join(raw), lang)
        seen, out = set(), []
        for l in clean:
            if l in seen:
                continue
            seen.add(l)
            out.append(l)
        if out != raw:
            changed += 1
        s["subtitles"] = out
        if out and looks_like_reasoning(out, lang):
            s["subtitle_needs_review"] = True
            review += 1
    sb["subtitle_scrub"] = {"segments_changed": changed, "flagged_for_review": review}
    with open(sb_path, "w", encoding="utf-8") as fh:
        json.dump(sb, fh, ensure_ascii=False, indent=2)
    return changed, review


def report(sb_path):
    with open(sb_path, encoding="utf-8") as fh:
        sb = json.load(fh)
    segs = sb["segments"]
    print("\n" + "=" * 78)
    print(f"{'#':>3}  {'start':>7} {'end':>7}  {'kf':>2}  {'subs':>4}  title / first subtitles")
    print("=" * 78)
    for s in segs:
        subs = s.get("subtitles") or []
        flag = "  !REVIEW" if s.get("subtitle_needs_review") else ""
        print(f"{s['index']:>3}  {s['start']:>7.1f} {s['end']:>7.1f}  "
              f"{'Y' if s.get('keyframe') else '-':>2}  {len(subs):>4}  "
              f"{s.get('title') or '(untitled)'}{flag}")
        for l in subs[:3]:
            print(f"           · {l}")
        if len(subs) > 3:
            print(f"           · … +{len(subs)-3} more")
    print("=" * 78)
    kf = sum(1 for s in segs if s.get("keyframe"))
    st = sum(1 for s in segs if s.get("subtitles"))
    print(f"segments {len(segs)} | keyframes {kf} | segments with subtitles {st}")
    empty = [s["index"] for s in segs if not s.get("subtitles")]
    if empty:
        print(f"no subtitles on segments: {empty}  (check --band, or that the")
        print("video has no burned-in captions at all)")
    bad = [s["index"] for s in segs if s.get("subtitle_needs_review")]
    if bad:
        print(f"flagged for review: {bad}  (model returned prose instead of text)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--scene-threshold", type=float, default=0.06,
                    help="scene score 0-1; lower = more cuts. 0.06 is the "
                         "calibrated default that survives slide chrome; run "
                         "selftest.py to re-derive it")
    ap.add_argument("--min-segment", type=float, default=5.0)
    ap.add_argument("--max-segments", type=int, default=45)
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--sub-band", default="0.20",
                    help="subtitle band height as a fraction of frame height")
    ap.add_argument("--scene-mask-bottom", type=float, default=0.0,
                    help="same fraction, but ignored when SCORING scene cuts so "
                         "caption lines are not mistaken for slide changes; "
                         "set it equal to --sub-band for large burned-in captions")
    ap.add_argument("--sub-per", type=float, default=4.0)
    ap.add_argument("--sub-max", type=int, default=12)
    ap.add_argument("--skip-subs", action="store_true")
    ap.add_argument("--cols", type=int, default=1,
                    help="contact sheet columns; 1 stacks frames vertically, "
                         "which OCRs better")
    args = ap.parse_args()

    video = os.path.abspath(args.video)
    out = os.path.abspath(args.out)
    if not os.path.exists(video):
        raise SystemExit(f"video not found: {video}")
    os.makedirs(out, exist_ok=True)
    sb_path = os.path.join(out, "storyboard.json")

    print(f"video {video}")
    print(f"out   {out}")

    run("video_storyboard.py", video, "--out", out, "--no-transcript",
        "--scene-threshold", args.scene_threshold,
        "--scene-mask-bottom", args.scene_mask_bottom,
        "--min-segment", args.min_segment,
        "--max-segments", args.max_segments,
        "--candidates", args.candidates,
        label="stage 1/4  scene split + candidate keyframes")

    run("make_contact_sheets.py", sb_path, "--cols", args.cols,
        label="stage 2/4  contact sheets")

    run("vlm_pick.py", sb_path, label="stage 3/4  vision picks the keyframe")

    if args.skip_subs:
        print("\nstage 4/4  subtitles SKIPPED by --skip-subs")
    else:
        run("subtitle_scan.py", sb_path, "--per", args.sub_per,
            "--max", args.sub_max, "--band", args.sub_band,
            label="stage 4/4  per-segment subtitle transcription")
        ch, rv = scrub(sb_path, args.lang)
        print(f"\nscrubbed subtitles on {ch} segment(s); {rv} flagged for review")

    report(sb_path)

    print(
        "\nNEXT STEP (judgement, not templating):\n"
        "  Read every segment's subtitles above and WRITE, in Chinese (or the\n"
        "  video's own language):\n"
        "    segments[i].title      -- the actual topic, not a restatement\n"
        "    segments[i].summary    -- must be SELF-SUFFICIENT: a reader who only\n"
        "                              reads summaries must learn the mechanism,\n"
        "                              definition or rule this page teaches\n"
        "    meta.title / meta.author / meta.url / meta.core_points\n"
        "  Then: python render_storyboard.py " + sb_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
