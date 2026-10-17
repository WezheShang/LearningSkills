#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pick, for each segment, the frame carrying the most hand-drawn annotation.

Why this exists: progressive-annotation screen recordings (instructor drawing
pens/segments on a live chart) are neither static slides nor fast-cut montage.
Scene detection is useless on them -- every frame is "different" because a pen
stroke was just added, and no frame is a clean slide. But the *content* grows
monotonically: the frame at the end of a topic carries every mark made while
explaining it, while the frame at the start carries almost nothing.

So: sample several frames per segment and score them by how much non-background
drawing ink is on screen. High ink wins. This is a cheap, objective proxy that
needs no vision model and no download of anything but the frames themselves.

Score = fraction of pixels that read as annotation ink, measured over the chart
area only (the top chrome bar and the bottom taskbar are excluded). Two terms:
  red   -- R clearly dominant (pen strokes, highlights)
  light -- bright pixels on an otherwise dark frame (white pen on a dark chart)

Usage:
    pick_annotated_frame.py VIDEO --segmap segmap.json --out frames_dir [--per 8]
"""
import argparse
import json
import os
import subprocess
import sys

try:
    from PIL import Image, ImageChops
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: Pillow is required (pip install pillow)\n")
    raise

FFMPEG = "ffmpeg"
# Chrome bars that never change: a window title bar up top, the Windows taskbar
# at the bottom. Including them just adds a constant to every candidate.
CHROME_TOP = 0.06
CHROME_BOTTOM = 0.94


def probe_duration(video):
    out = subprocess.run([FFMPEG, "-i", video], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    for line in out.splitlines():
        if "Duration:" in line:
            hhmmss = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hhmmss.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise SystemExit("ERROR: could not read duration from %s" % video)


def grab(video, t, path, width):
    """Seek to t and write one frame scaled to `width`. Returns True on success."""
    cmd = [FFMPEG, "-v", "error", "-ss", "%.3f" % t, "-i", video,
           "-frames:v", "1", "-vf", "scale=%d:-1" % width, "-q:v", "3",
           "-y", path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0 and os.path.isfile(path)


DARK_MAX = 60        # luminance below this counts as chart background
BRIGHT_MIN = 95      # luminance above this counts as marks on a dark chart
RED_MIN = 110        # channel level for "this pixel is red"
RED_DOMINANCE = 55   # how far red must exceed green/blue to count as red ink


def analyse(path):
    """Return (dark_frac, bright_frac, red_frac) over the content area.

    A dark chart window is recognised by `dark_frac`: its background is nearly
    black. On such a frame, `bright_frac` grows as pen strokes and labels are
    added, so it ranks "most drawn on" correctly. On a light mind-map panel the
    background is white and `bright_frac` is meaningless (it saturates near 1),
    which is why the two window types must not share one score.
    """
    im = Image.open(path).convert("RGB")
    w, h = im.size
    crop = im.crop((0, int(h * CHROME_TOP), w, int(h * CHROME_BOTTOM)))
    n = crop.size[0] * crop.size[1]
    if not n:
        return 0.0, 0.0, 0.0

    gray = crop.convert("L").histogram()
    dark_frac = sum(gray[:DARK_MAX + 1]) / float(n)
    bright_frac = sum(gray[BRIGHT_MIN:]) / float(n)

    r, g, b = crop.split()

    def mask(chan, thresh):
        return chan.point(lambda v: 255 if v > thresh else 0)

    red = mask(r, RED_MIN)
    for chan, name in ((g, "g"), (b, "b")):
        red = ImageChops.darker(red, mask(ImageChops.subtract(r, chan), RED_DOMINANCE))
    red_frac = red.histogram()[255] / float(n)

    return dark_frac, bright_frac, red_frac


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--segmap", required=True)
    ap.add_argument("--out", required=True, help="directory for the chosen frames")
    ap.add_argument("--per", type=int, default=8,
                    help="candidate frames sampled per segment (default 8)")
    ap.add_argument("--scale", type=int, default=1280,
                    help="width of the saved frame (default 1280)")
    ap.add_argument("--probe-width", type=int, default=480,
                    help="width used while scoring; smaller is faster (default 480)")
    ap.add_argument("--skip-last", type=float, default=0.0,
                    help="seconds to back off the end of each segment (default 0)")
    ap.add_argument("--chart-dark", type=float, default=0.35,
                    help="dark_frac above which a frame counts as chart-dominant; "
                         "used to separate a dark chart from a light mind-map panel "
                         "(default 0.35)")
    args = ap.parse_args(argv)

    segmap = json.load(open(args.segmap, encoding="utf-8"))
    dur = probe_duration(args.video)
    os.makedirs(args.out, exist_ok=True)
    tmp = os.path.join(args.out, "_probe")
    os.makedirs(tmp, exist_ok=True)

    picks = []
    print("%s  (%.1fs, %d segments, %d candidates each)"
          % (os.path.basename(args.video), dur, len(segmap), args.per))
    print("%-4s %-13s %-8s %-8s %-7s %s" % ("name", "range", "window", "score",
                                             "spread", "chosen at"))
    print("-" * 66)

    for seg in segmap:
        lo, hi = seg["start"], seg["end"]
        hi = min(hi - args.skip_last, dur)
        if hi - lo < 1.0:
            hi = min(lo + 1.0, dur)
        n = max(2, args.per)
        # sample inside the segment, avoiding the exact boundaries
        times = [lo + (hi - lo) * (i + 0.5) / n for i in range(n)]
        cand = []
        for t in times:
            p = os.path.join(tmp, "probe.png")
            if not grab(args.video, t, p, args.probe_width):
                continue
            cand.append((t,) + analyse(p))
        if not cand:
            sys.stderr.write("WARNING: %s: no frame could be decoded\n" % seg["name"])
            continue

        # Two-tier: prefer a chart window and rank by marks on a dark background;
        # only when the whole segment is mind-map panel does red ink decide.
        chart = [c for c in cand if c[1] >= args.chart_dark]
        if chart:
            window = "chart"
            scored = [(c[2], c[0]) for c in chart]          # (bright_frac, t)
        else:
            window = "panel"
            scored = [(c[3], c[0]) for c in cand]           # (red_frac, t)
        scored.sort(reverse=True)
        best_score, best_t = scored[0]
        spread = best_score - scored[-1][0]

        dest = os.path.join(args.out, "%s.png" % seg["name"])
        grab(args.video, best_t, dest, args.scale)
        picks.append({"name": seg["name"], "time": round(best_t, 2),
                      "window": window, "score": round(best_score, 5),
                      "spread": round(spread, 5),
                      "path": dest, "start": lo, "end": hi})
        print("%-4s %-13s %-8s %-8.4f %-7.4f %6.1fs"
              % (seg["name"], "%.0f-%.0fs" % (lo, hi), window, best_score,
                 spread, best_t))

    with open(os.path.join(args.out, "frames.json"), "w", encoding="utf-8") as fh:
        json.dump(picks, fh, ensure_ascii=False, indent=1)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    print("-" * 62)
    print("picked %d frames -> %s" % (len(picks), os.path.abspath(args.out)))
    return 0 if len(picks) == len(segmap) else 1


if __name__ == "__main__":
    sys.exit(main())
