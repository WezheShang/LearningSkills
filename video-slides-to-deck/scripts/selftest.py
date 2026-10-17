#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
selftest.py -- build a synthetic slide-lecture video WITH ground truth and
CALIBRATE the scene threshold against it.

Why this exists
---------------
ffmpeg's scene score is normalised over the WHOLE frame, so its value depends on
how much of the picture actually changes at a cut. Measured on a full-bleed
colour change, hard cuts score 0.15-0.29. But a real lecture slide has a fixed
title bar and a fixed subtitle band -- roughly a third of the frame that never
changes -- which DILUTES the signal and pushes some real cuts below 0.12.

So there is no single correct threshold; there is a workable RANGE that depends
on the deck's chrome. This tool sweeps the range and reports which values give a
clean result, instead of hard-failing on one magic number.

  python selftest.py                  # sweep and report the usable range
  python selftest.py --threshold 0.08 # pin one value and PASS/FAIL it
  python selftest.py --quiet          # one-line summary only (for CI-ish use)

Exit 0 = the pinned threshold (or the sweep default) passes. 1 = none pass.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

W, H, FPS = 1280, 720, 25
SCENE_SECONDS = 4.0
SCENES = [
    {"id": 1, "color": (26, 58, 92), "label": "SLIDE ONE", "kind": "circle"},
    {"id": 2, "color": (122, 32, 46), "label": "SLIDE TWO", "kind": "square"},
    {"id": 3, "color": (24, 92, 56), "label": "SLIDE THREE", "kind": "triangle"},
    {"id": 4, "color": (110, 70, 20), "label": "SLIDE FOUR", "kind": "diamond"},
    {"id": 5, "color": (70, 30, 110), "label": "SLIDE FIVE", "kind": "circle"},
    {"id": 6, "color": (30, 90, 110), "label": "SLIDE SIX", "kind": "square"},
]

SWEEP = [0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]


def build_video(work):
    """A slide-like frame: white title bar on top, dark caption band at the
    bottom, changing body between slides. That chrome is what pulls the real
    scene scores down, so the calibration has to include it."""
    from PIL import Image, ImageDraw

    fdir = os.path.join(work, "_frames")
    os.makedirs(fdir, exist_ok=True)
    total = int(SCENE_SECONDS * FPS)
    truth, paths = [], []

    for sc in SCENES:
        start = len(paths)
        for i in range(total):
            img = Image.new("RGB", (W, H), sc["color"])
            d = ImageDraw.Draw(img)
            body_top, body_bot = 92, int(H * 0.80)
            cx, cy, s = W // 2, (body_top + body_bot) // 2, 130
            if sc["kind"] == "circle":
                d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=(255, 255, 255))
            elif sc["kind"] == "square":
                d.rectangle([cx - s, cy - s, cx + s, cy + s], fill=(255, 255, 255))
            elif sc["kind"] == "triangle":
                d.polygon([(cx, cy - s), (cx + s, cy + s), (cx - s, cy + s)],
                          fill=(255, 255, 255))
            else:
                d.polygon([(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)],
                          fill=(255, 255, 255))
            # fixed chrome -- identical on every slide
            d.rectangle([0, 0, W, body_top], fill=(250, 250, 252))
            d.text((28, 40), "SYNTHETIC LECTURE", fill=(20, 20, 30))
            d.rectangle([0, body_bot, W, H], fill=(0, 0, 0))
            d.text((40, body_bot + 26), sc["label"], fill=(255, 255, 255))
            # a little intra-slide motion so noise is non-zero
            frac = i / max(1, total - 1)
            d.rectangle([0, body_bot - 6, int(W * frac), body_bot - 2],
                        fill=(232, 180, 74))
            p = os.path.join(fdir, f"f{len(paths):05d}.png")
            img.save(p)
            paths.append(p)
        truth.append({"scene_id": sc["id"], "start": round(start / FPS, 3),
                      "end": round(len(paths) / FPS, 3), "label": sc["label"]})

    video = os.path.join(work, "_selftest.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", os.path.join(fdir, "f%05d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "20", video], check=True)
    gt = os.path.join(work, "_selftest_gt.json")
    with open(gt, "w", encoding="utf-8") as fh:
        json.dump({"video": video, "fps": FPS, "scenes": truth,
                   "total_seconds": len(paths) / FPS}, fh, ensure_ascii=False, indent=2)
    return video, gt


def measure(video, out_dir, threshold):
    """Run stage 1 at a given threshold and return the metrics."""
    cmd = [sys.executable, os.path.join(HERE, "video_storyboard.py"), video,
           "--out", out_dir, "--no-transcript", "--scene-threshold", str(threshold),
           "--min-segment", "2.0", "--max-segments", "20", "--candidates", "3"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    sb_path = os.path.join(out_dir, "storyboard.json")
    if not os.path.exists(sb_path):
        return None
    with open(sb_path, encoding="utf-8") as fh:
        return json.load(fh)


def metrics(gt, sb, tol=0.5):
    scenes = gt["scenes"]

    def which(t):
        for s in scenes:
            if s["start"] <= t < s["end"]:
                return s["scene_id"]
        return None

    true_cuts = [s["start"] for s in scenes if s["start"] > 0]
    det = [c["time"] for c in sb.get("raw_cuts", [])]
    matched = [tc for tc in true_cuts if any(abs(d - tc) <= tol for d in det)]
    recall = len(matched) / len(true_cuts) if true_cuts else 1.0
    prec = len(matched) / len(det) if det else (1.0 if not true_cuts else 0.0)

    segs = sb["segments"]
    pure = sum(1 for s in segs
               if len({which(s["start"]), which(s["end"] - 0.05)} - {None}) == 1)
    purity = pure / len(segs) if segs else 0.0

    tot = ok = 0
    for s in segs:
        want = which((s["start"] + s["end"]) / 2.0)
        for c in s.get("candidates", []):
            tot += 1
            ok += which(c["time"]) == want
    cand = ok / tot if tot else 0.0

    return {"threshold": None, "cuts": len(det), "recall": recall, "precision": prec,
            "purity": purity, "cand": cand,
            "scores": [c["score"] for c in sb.get("raw_cuts", [])]}


def is_clean(m):
    return (m["recall"] == 1.0 and m["precision"] == 1.0
            and m["purity"] == 1.0 and m["cand"] == 1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=os.path.join(os.getcwd(), "_selftest"))
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)
    if not args.quiet:
        print("building synthetic slide-lecture video (with title bar + caption band) ...")
    video, gt = build_video(work)
    with open(gt, encoding="utf-8") as fh:
        gtd = json.load(fh)

    thresholds = [args.threshold] if args.threshold is not None else SWEEP
    rows = []
    for th in thresholds:
        sb = measure(video, os.path.join(work, f"sb_{th}"), th)
        if sb is None:
            rows.append((th, None))
            continue
        m = metrics(gtd, sb)
        m["threshold"] = th
        rows.append((th, m))

    print()
    print("  th     cuts  recall   prec    purity  cand    verdict")
    print("  " + "-" * 56)
    good = []
    for th, m in rows:
        if m is None:
            print(f"  {th:<6}  --    (segmentation produced no storyboard)")
            continue
        v = "PASS" if is_clean(m) else "fail"
        if is_clean(m):
            good.append(th)
        print(f"  {th:<6}  {m['cuts']:>4}  {m['recall']:>6.1%}  {m['precision']:>6.1%}"
              f"  {m['purity']:>6.1%}  {m['cand']:>6.1%}  {v}")

    allm = [m for _t, m in rows if m]
    lo_scores = min((min(m["scores"]) for m in allm if m["scores"]), default=None)
    print()
    if allm and allm[0]["scores"]:
        print(f"  weakest detected cut scored "
              f"{min(min(m['scores']) for m in allm if m['scores']):.3f}")
    if good:
        print(f"  USABLE THRESHOLD RANGE: {min(good)} .. {max(good)}")
        print(f"  Recommended default for chrome-heavy slides: {min(good)}")
    else:
        print("  NO threshold in the sweep produced a clean split.")
    print(f"  (segment noise reference: real lecture footage measured < 0.005)")
    print(f"  work dir: {work}")

    if args.quiet:
        print("RESULT:", "PASS" if good else "FAIL")
    else:
        print("\nRESULT:", "PASS" if good else "FAIL")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
