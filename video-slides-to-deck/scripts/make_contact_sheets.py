#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make_contact_sheets.py -- build one numbered contact sheet per segment.

Why a contact sheet instead of N separate image calls: the vision tool answers
each image independently, so passing 3 frames and asking "which is best?" gets
3 opinions, not a choice. Tiling them into ONE labelled sheet and asking for an
index gives a single, mappable answer.

Usage:
  python make_contact_sheets.py storyboard.json            # per-segment sheets
  python make_contact_sheets.py storyboard.json --probe     # one sheet mixing
                                                            # every scene, used
                                                            # to sanity-check the
                                                            # vision round-trip
"""
import argparse
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

TILE_W, TILE_H = 480, 270
PAD = 14
LABEL_H = 40


def _font(size=26):
    for name in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                 "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def contact_sheet(items, cols=2, title=None):
    """items: [{"label": str, "path": str}] -> (PIL image, order list)."""
    if not items:
        return None, []
    cols = max(1, min(cols, len(items)))
    rows = math.ceil(len(items) / cols)

    title_h = 56 if title else 0
    W = cols * TILE_W + PAD * (cols + 1)
    H = title_h + rows * (TILE_H + LABEL_H) + PAD * (rows + 1)

    sheet = Image.new("RGB", (W, H), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    f_big, f_num = _font(30), _font(30)

    if title:
        d.text((PAD, 14), title, fill=(235, 235, 240), font=f_big)

    order = []
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        x = PAD + c * (TILE_W + PAD)
        y = title_h + PAD + r * (TILE_H + LABEL_H + PAD)
        try:
            im = Image.open(it["path"]).convert("RGB")
            im = im.resize((TILE_W, TILE_H))
            sheet.paste(im, (x, y))
        except Exception as exc:
            d.rectangle([x, y, x + TILE_W, y + TILE_H], fill=(60, 30, 30))
            d.text((x + 10, y + 10), f"ERR {exc}"[:60], fill=(255, 120, 120), font=f_num)

        # number badge, big enough for a VLM to read reliably
        badge = (x, y, x + 46, y + 46)
        d.rectangle(badge, fill=(255, 60, 60))
        num = str(i + 1)
        try:
            tw = d.textlength(num, font=f_num)
        except Exception:
            tw = 20
        d.text((x + 23 - tw / 2, y + 6), num, fill=(255, 255, 255), font=f_num)

        d.rectangle([x, y, x + TILE_W - 1, y + TILE_H - 1], outline=(90, 90, 100))
        d.text((x + 6, y + TILE_H + 7), it["label"][:60], fill=(190, 190, 200), font=f_num)
        order.append(it["path"])

    return sheet, order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("storyboard")
    ap.add_argument("--out", default=None, help="default: <storyboard dir>/sheets")
    ap.add_argument("--probe", action="store_true",
                    help="one sheet mixing the first candidate of every segment")
    ap.add_argument("--cols", type=int, default=2)
    args = ap.parse_args()

    with open(args.storyboard, encoding="utf-8") as fh:
        sb = json.load(fh)

    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.storyboard)), "sheets")
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"storyboard": args.storyboard, "sheets": []}

    if args.probe:
        items = []
        for seg in sb["segments"]:
            if seg["candidates"]:
                c = seg["candidates"][0]
                items.append({"label": f"seg{seg['index']} @{c['time']}s", "path": c["path"]})
        sheet, order = contact_sheet(items, cols=args.cols,
                                     title="PROBE: first keyframe of each segment")
        p = os.path.join(out_dir, "probe.png")
        sheet.save(p)
        print(json.dumps({"sheet": p, "order": order}, ensure_ascii=False))
        return 0

    for seg in sb["segments"]:
        if not seg["candidates"]:
            continue
        items = [{
            "label": f"t={c['time']}s",
            "path": c["path"],
        } for c in seg["candidates"]]
        sheet, order = contact_sheet(
            items, cols=args.cols,
            title=f"Segment {seg['index']}  {seg['start']:.1f}-{seg['end']:.1f}s"
                  + (f"  |  speech: {seg['transcript'][:70]}" if seg.get("transcript") else ""),
        )
        p = os.path.join(out_dir, f"seg{seg['index']:03d}.png")
        sheet.save(p)
        manifest["sheets"].append({
            "segment": seg["index"],
            "sheet": p,
            "order": order,
            "start": seg["start"],
            "end": seg["end"],
            "transcript": seg.get("transcript", ""),
        })
        print(f"  {os.path.basename(p)}  {len(items)} candidates")

    mp = os.path.join(out_dir, "sheets_manifest.json")
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"\nmanifest -> {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
