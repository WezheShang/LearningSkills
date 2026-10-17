#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split a subtitle file into a segment map at explicit cut times.

This is the mechanical half of the text-first notes path. It does NOT decide
where to cut -- you do, by reading the subtitles and picking 6-12 boundaries
that match topic changes. It only guarantees that every line is assigned
exactly once and that each segment carries its own lines.

Accepts SRT, WebVTT, and bilibili's JSON subtitle blobs (which are often saved
with a .srt extension, so the format is sniffed, not trusted from the name).

Why cut times and not anchor text matching: AI subtitle tracks (`ai-zh` on
bilibili) contain homophone errors, so fuzzy text anchors silently miss and
shift boundaries. A number you chose while reading the transcript cannot.

Usage:
    srt_segmap.py SUBS --out segmap.json --cuts 118,258,394,534,606,675,781

Output schema:
    [{"name": "s1", "start": 0.0, "end": 118.0, "lines": ["...", ...]}, ...]
"""
import argparse
import io
import json
import os
import re
import sys

TIME_RE = re.compile(
    r"(\d+):(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*(\d+):(\d{1,2}):(\d{1,2})[.,](\d{1,3})"
)


def _hms(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_subtitles(path):
    """Return [{'start': float, 'end': float, 'text': str}, ...].

    Accepts SRT, WebVTT, and the JSON subtitle blobs bilibili serves from its
    `subtitle_url` field. The bilibili form looks like
        {"type": "AIsubtitle", "body": [{"from": 1.04, "to": 3.08, "content": "..."}]}
    and is commonly saved with a `.srt` extension, so sniffing the first
    character is the only reliable way to tell them apart.
    """
    with io.open(path, encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    if raw.lstrip().startswith("{"):
        return _parse_bilibili_json(raw)

    if raw.lstrip().upper().startswith("WEBVTT"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""

    cues = []
    for block in re.split(r"\n{2,}", raw):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        timing_at = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_at is None:
            continue
        m = TIME_RE.search(lines[timing_at])
        if not m:
            continue
        start = _hms(*m.group(1, 2, 3, 4))
        end = _hms(*m.group(5, 6, 7, 8))
        text = " ".join(ln.strip() for ln in lines[timing_at + 1:]).strip()
        # Drop VTT/SRT cue settings such as "align:start position:0%"
        text = re.sub(r"\s*(align|position|line|size|region):\S+", "", text).strip()
        if text:
            cues.append({"start": start, "end": max(end, start), "text": text})
    return cues


def _parse_bilibili_json(raw):
    try:
        body = json.loads(raw).get("body") or []
    except ValueError:
        sys.stderr.write("ERROR: file starts with '{' but is not valid JSON\n")
        return []
    cues = []
    for item in body:
        text = (item.get("content") or "").strip()
        if not text:
            continue
        start = float(item.get("from") or 0.0)
        cues.append({"start": start, "end": float(item.get("to") or start), "text": text})
    cues.sort(key=lambda c: c["start"])
    return cues


def build_segments(cues, cuts):
    bounds = [0.0] + sorted(float(c) for c in cuts)
    bounds.append(None)  # last segment runs to the end of the track
    segments = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        if hi is None:
            picked = [c for c in cues if c["start"] >= lo]
        else:
            picked = [c for c in cues if lo <= c["start"] < hi]
        segments.append({
            "name": "s%d" % (i + 1),
            "start": round(lo, 3),
            "end": round(hi if hi is not None else (cues[-1]["end"] if cues else lo), 3),
            "lines": [c["text"] for c in picked],
        })
    return segments


def fmt(sec):
    return "%d:%02d" % (int(sec) // 60, int(sec) % 60)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", help="subtitle file (.srt, .vtt, or bilibili JSON)")
    ap.add_argument("--out", required=True, help="segment map JSON to write")
    ap.add_argument("--cuts", required=True,
                    help="comma-separated cut times in seconds, e.g. 118,258,394")
    ap.add_argument("--min-lines", type=int, default=1,
                    help="fail if any segment has fewer lines than this (default 1)")
    args = ap.parse_args(argv)

    cues = parse_subtitles(args.srt)
    if not cues:
        sys.stderr.write("ERROR: no cues parsed from %s\n" % args.srt)
        return 2

    raw_cuts = [c.strip() for c in args.cuts.split(",") if c.strip()]
    try:
        cuts = [float(c) for c in raw_cuts]
    except ValueError:
        sys.stderr.write("ERROR: --cuts must be comma-separated numbers, got %r\n" % args.cuts)
        return 2

    last = cues[-1]["end"]
    bad = [c for c in cuts if c <= 0 or c >= last]
    if bad:
        sys.stderr.write("ERROR: cut(s) outside (0, %.1f): %s\n" % (last, bad))
        return 2
    if len(set(cuts)) != len(cuts):
        sys.stderr.write("ERROR: duplicate cut times\n")
        return 2

    segments = build_segments(cues, cuts)

    total = sum(len(s["lines"]) for s in segments)
    print("%s: %d cues, %d segments" % (os.path.basename(args.srt), len(cues), len(segments)))
    print("-" * 62)
    print("%-4s %-13s %-7s %s" % ("name", "range", "lines", "chars"))
    for s in segments:
        print("%-4s %-13s %-7d %d" % (
            s["name"],
            "%s-%s" % (fmt(s["start"]), fmt(s["end"])),
            len(s["lines"]),
            sum(len(x) for x in s["lines"])))
    print("-" * 62)
    print("assigned %d/%d cues" % (total, len(cues)))

    problems = []
    if total != len(cues):
        problems.append("cue assignment mismatch (%d of %d)" % (total, len(cues)))
    for s in segments:
        if len(s["lines"]) < args.min_lines:
            problems.append("%s has only %d line(s) -- check the cut times"
                            % (s["name"], len(s["lines"])))

    with io.open(args.out, "w", encoding="utf-8") as fh:
        json.dump(segments, fh, ensure_ascii=False, indent=1)
    print("wrote %s (%d bytes)" % (args.out, os.path.getsize(args.out)))

    if problems:
        for p in problems:
            sys.stderr.write("WARNING: %s\n" % p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
