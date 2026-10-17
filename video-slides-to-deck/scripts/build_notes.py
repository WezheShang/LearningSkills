#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a text-first study-notes page from a segment map + authored notes.

This is the text-first branch of video-slides-to-deck. Use it when the video is
NOT a static slide deck: you have real subtitles, but the frames carry no
information (screen recordings, talking-head + screen, mostly-static demos).
In that case screenshots are decoration, and the deliverable is a readable page
built from the transcript instead.

The mechanical work and the authored work are kept in separate files on
purpose, so batch runs cannot silently ship a half-written page:

    segmap.json   <- srt_segmap.py, from the subtitle file (times + lines)
    notes.json    <- written by you (titles, summaries, core points, meta)

Every segment in segmap.json must have an entry in notes.json["sections"],
otherwise this exits non-zero. A missing section means a blank page.

Usage:
    build_notes.py --segmap segmap.json --notes notes.json --out notes.html \
                   [--root .] [--min-summary 80]

notes.json schema:
    {
      "title":           "page title",
      "author":          "uploader / source line",
      "url":             "original video URL",
      "source_label":    "link text (default: 在 B 站观看原视频 →)",
      "subtitle_source": "provenance note shown in the meta line",
      "note_paragraphs": ["<b>Why this page has no screenshots:</b> ...",
                          "optional second paragraph"],
      "assets":          [{"heading": "...", "path": "map.png", "alt": "..."}],
      "core_points":     ["...", "..."],
      "sections":        {"s1": {"title": "...", "summary": "**bold** is fine",
                                  "image": "frames/s1.png",
                                  "caption": "what the frame shows"},
                          ...},
      "footer":          "optional HTML, replaces the default footnote"
    }

`image` is optional per section. Supply it when the frames carry information --
progressive-annotation screen recordings (drawing pens/segments on a live chart)
land here, and the picture is usually *more* useful than the prose. Omit it when
the frames are decoration.

Asset paths are resolved relative to --root and embedded as base64, so the
resulting HTML is a single self-contained offline file.
"""
import argparse
import base64
import html
import io
import json
import mimetypes
import os
import re
import sys

CSS = """
:root{--bg:#0b0d12;--card:#141824;--line:#252b3a;--fg:#e8ecf6;--dim:#9aa3b8;--accent:#5B8CFF}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.75 "PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:40px 28px 90px}
.kicker{color:var(--accent);font:700 11px/1 ui-monospace,monospace;letter-spacing:.18em}
h1{font-size:32px;line-height:1.35;margin:14px 0 10px}
.meta{color:var(--dim);font-size:13.5px;margin-bottom:18px}
.meta a{color:#9dbcff;text-decoration:none;border-bottom:1px solid #3a4a70}
.meta a:hover{color:#fff}
h2.sec{font-size:17px;color:#ffd479;margin:38px 0 14px;letter-spacing:.02em}
.core{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.core li{list-style:none;background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:13px 15px;font-size:13.8px;line-height:1.68;color:#d6dcec}
.core .n{display:inline-block;min-width:20px;color:var(--accent);font-weight:700;font-family:ui-monospace,monospace}
.note{background:#1a2030;border:1px solid #2c3549;border-left:3px solid var(--accent);
 border-radius:8px;padding:13px 16px;font-size:13.6px;color:#c7cee0;line-height:1.7;margin:18px 0}
.map{width:100%;border:1px solid var(--line);border-radius:10px;margin:8px 0 4px;display:block}
.shot{width:100%;border:1px solid var(--line);border-radius:10px;margin:16px 0 0;display:block}
.cap{color:var(--dim);font-size:12.5px;margin:7px 0 0;line-height:1.6}
.toc{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:7px 26px;margin:6px 0}
.toc a{display:flex;gap:10px;align-items:baseline;color:#c3cbdd;text-decoration:none;
 font-size:14px;padding:5px 0;border-bottom:1px solid #1b2130}
.toc a:hover{color:#fff}
.toc .tt{color:#6d7488;font:12px ui-monospace,monospace;flex:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px 26px;margin:20px 0}
.hd{display:flex;justify-content:space-between;align-items:baseline;gap:14px;margin-bottom:14px;flex-wrap:wrap}
.hd .tag{color:var(--accent);font:700 11px ui-monospace,monospace;letter-spacing:.12em}
.hd .sp{color:var(--dim);font:12.5px ui-monospace,monospace}
.card h3{margin:0;font-size:21px;line-height:1.4}
.sum{margin:14px 0 0;color:#dde2ef;font-size:15px;line-height:1.8}
.sum b{color:#ffd479;font-weight:600}
details{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}
summary{cursor:pointer;color:var(--dim);font-size:13.5px;list-style:none}
summary::-webkit-details-marker{display:none}
summary:before{content:"\\25B8 ";color:var(--accent)}
details[open] summary:before{content:"\\25BE "}
.subs{margin:12px 0 0;padding:0;list-style:none}
.subs li{position:relative;padding-left:18px;color:#bcc4d6;font-size:13.4px;line-height:1.62;margin-bottom:6px}
.subs li:before{content:"";position:absolute;left:2px;top:9px;width:5px;height:5px;border-radius:50%;
 background:rgba(91,140,255,.55)}
.foot{color:var(--dim);font-size:12.5px;border-top:1px solid var(--line);margin-top:48px;padding-top:18px;line-height:1.8}
@media print{@page{size:A4;margin:14mm}body{background:#fff;color:#15171d}.card{background:#fff;border-color:#ccc;
 page-break-inside:avoid}.sum{color:#15171d}.sum b{color:#b45309}.card h3{color:#15171d}
 .hd .tag{color:#5B8CFF}.subs li{color:#333}details{display:none}}
"""

DEFAULT_FOOTER = (
    '本页由 <code>video-slides-to-deck</code> 的判定流程改道生成：'
    '该 skill 的默认路径依赖<b>画面里的幻灯片</b>与<b>烧录字幕条</b>，'
    '而本视频的画面不承载信息，因此改用<b>纯文字版</b>——内容全部来自字幕轨，逐节改写为可独立阅读的知识点。<br>'
    '字幕为 AI 生成轨，存在少量识别误差；各节总结由字幕改写。'
)


def fmt(sec):
    return "%d:%02d" % (int(sec) // 60, int(sec) % 60)


def esc(s):
    return html.escape(str(s), quote=False)


def md(s):
    """Minimal inline markup: **bold** and `code`. Everything else is escaped."""
    out = []
    for chunk in re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", str(s)):
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            out.append("<b>%s</b>" % esc(chunk[2:-2]))
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            out.append("<code>%s</code>" % esc(chunk[1:-1]))
        else:
            out.append(esc(chunk))
    return "".join(out)


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        return "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode("ascii"))


def load(path, label, errors):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        errors.append("%s not found: %s" % (label, path))
    except ValueError as exc:
        errors.append("%s is not valid JSON (%s): %s" % (label, exc, path))
    return None


def validate(segmap, notes, root, min_summary):
    errors, warnings = [], []
    for key in ("title", "url", "sections"):
        if not notes.get(key):
            errors.append("notes.json missing required key: %s" % key)

    sections = notes.get("sections") or {}
    if not isinstance(sections, dict):
        errors.append("notes.json sections must be an object keyed by segment name")
        return errors, warnings

    seen = set()
    prev_end = None
    for seg in segmap:
        name = seg.get("name")
        seen.add(name)
        entry = sections.get(name)
        if not entry:
            errors.append("segment %s has no entry in notes.json sections" % name)
            continue
        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or "").strip()
        if not title:
            errors.append("%s: empty title" % name)
        elif len(title) < 4:
            warnings.append("%s: title is very short (%r) -- titles must name the "
                            "knowledge point, not restate the section number" % (name, title))
        if not summary:
            errors.append("%s: empty summary" % name)
        elif len(summary) < min_summary:
            warnings.append("%s: summary is only %d chars (<%d) -- a summary must be "
                            "self-sufficient, not a restatement of the title"
                            % (name, len(summary), min_summary))
        if not seg.get("lines"):
            errors.append("%s: no subtitle lines -- check the cut times in segmap.json" % name)
        start, end = seg.get("start"), seg.get("end")
        if start is None or end is None or end <= start:
            errors.append("%s: bad time range %r-%r" % (name, start, end))
        elif prev_end is not None and abs(start - prev_end) > 0.01:
            warnings.append("%s: starts at %.2f but previous segment ended at %.2f "
                            "(gap or overlap)" % (name, start, prev_end))
        if end is not None:
            prev_end = end

    for extra in sorted(set(sections) - seen):
        errors.append("notes.json sections has %r which is not in the segment map" % extra)

    for asset in notes.get("assets") or []:
        ap = asset.get("path")
        if not ap:
            errors.append("asset entry missing 'path'")
            continue
        full = ap if os.path.isabs(ap) else os.path.join(root, ap)
        if not os.path.isfile(full):
            errors.append("asset file not found: %s" % full)

    for seg in segmap:
        img = (sections.get(seg.get("name")) or {}).get("image")
        if img and not (img if os.path.isabs(img) else os.path.join(root, img)):
            errors.append("%s: image file not found: %s"
                          % (seg.get("name"), img if os.path.isabs(img)
                             else os.path.join(root, img)))

    return errors, warnings


def render(segmap, notes, root):
    o = []
    a = o.append
    title = notes["title"]
    a("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a("<title>%s</title>" % esc(title))
    a("<style>%s</style></head><body><div class=\"wrap\">" % CSS)

    total = segmap[-1]["end"] if segmap else 0
    n_lines = sum(len(s["lines"]) for s in segmap)
    a('<div class="kicker">STUDY NOTES · 文字版</div>')
    a("<h1>%s</h1>" % esc(title))
    meta_bits = ["%d 节" % len(segmap), "总时长 %s" % fmt(total), "%d 条字幕" % n_lines]
    if notes.get("author"):
        meta_bits.append(str(notes["author"]))
    if notes.get("subtitle_source"):
        meta_bits.append("字幕来源：%s" % notes["subtitle_source"])
    a('<div class="meta">%s</div>' % esc(" · ".join(meta_bits)))
    a('<div class="meta"><a href="%s" target="_blank" rel="noopener">%s</a></div>'
      % (esc(notes["url"]), esc(notes.get("source_label") or "打开原视频 →")))

    for para in notes.get("note_paragraphs") or []:
        a('<div class="note">%s</div>' % para)

    for asset in notes.get("assets") or []:
        ap = asset["path"]
        full = ap if os.path.isabs(ap) else os.path.join(root, ap)
        if asset.get("heading"):
            a('<h2 class="sec">%s</h2>' % esc(asset["heading"]))
        a('<img class="map" alt="%s" src="%s">'
          % (esc(asset.get("alt") or asset.get("heading") or "figure"), data_uri(full)))

    core = notes.get("core_points") or []
    if core:
        a('<h2 class="sec">核心观点</h2><ol class="core">')
        for i, p in enumerate(core, 1):
            a('<li><span class="n">%02d</span> %s</li>' % (i, md(p)))
        a("</ol>")

    a('<h2 class="sec">目录</h2><nav class="toc">')
    for seg in segmap:
        st = (notes["sections"].get(seg["name"]) or {}).get("title", seg["name"])
        a('<a href="#s%s"><span class="tt">%s</span>%s</a>'
          % (seg["name"], fmt(seg["start"]), esc(st)))
    a("</nav>")

    for seg in segmap:
        entry = notes["sections"].get(seg["name"]) or {}
        a('<section class="card" id="s%s">' % seg["name"])
        a('<div class="hd"><h3>%s</h3><span class="sp">%s → %s · %ds</span></div>'
          % (esc(entry.get("title", "")), fmt(seg["start"]), fmt(seg["end"]),
             int(seg["end"] - seg["start"])))
        img = entry.get("image")
        if img:
            full = img if os.path.isabs(img) else os.path.join(root, img)
            a('<img class="shot" alt="%s" src="%s">'
              % (esc(entry.get("caption") or entry.get("title") or "frame"), data_uri(full)))
            if entry.get("caption"):
                a('<div class="cap">%s</div>' % esc(entry["caption"]))
        a('<div class="sum">%s</div>' % md(entry.get("summary", "")))
        a("<details><summary>展开本节原始字幕（%d 条）</summary><ul class=\"subs\">"
          % len(seg["lines"]))
        for line in seg["lines"]:
            a("<li>%s</li>" % esc(line))
        a("</ul></details></section>")

    a('<div class="foot">%s</div>' % (notes.get("footer") or DEFAULT_FOOTER))
    a("</div></body></html>")
    return "".join(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--segmap", required=True, help="segmap.json from srt_segmap.py")
    ap.add_argument("--notes", required=True, help="notes.json you authored")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--root", default=".", help="base dir for relative asset paths")
    ap.add_argument("--min-summary", type=int, default=80,
                    help="warn when a summary is shorter than this (default 80)")
    ap.add_argument("--force", action="store_true",
                    help="write the file even when errors remain (for drafts)")
    args = ap.parse_args(argv)

    errors, warnings = [], []
    segmap = load(args.segmap, "segmap", errors)
    notes = load(args.notes, "notes", errors)
    if segmap is None or notes is None:
        for e in errors:
            sys.stderr.write("ERROR: %s\n" % e)
        return 2
    if not isinstance(segmap, list) or not segmap:
        sys.stderr.write("ERROR: segmap must be a non-empty JSON array\n")
        return 2

    errors, warnings = validate(segmap, notes, args.root, args.min_summary)
    for w in warnings:
        sys.stderr.write("WARNING: %s\n" % w)
    if errors:
        for e in errors:
            sys.stderr.write("ERROR: %s\n" % e)
        if not args.force:
            sys.stderr.write("\n%d error(s); nothing written. Fix notes.json or pass --force "
                             "for a draft.\n" % len(errors))
            return 1

    page = render(segmap, notes, args.root)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with io.open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)

    print("wrote %s (%d bytes)" % (args.out, os.path.getsize(args.out)))
    print("sections: %d   subtitle lines: %d   core points: %d"
          % (len(segmap), sum(len(s["lines"]) for s in segmap),
             len(notes.get("core_points") or [])))
    if warnings:
        print("%d warning(s) -- review them before shipping." % len(warnings))
    if errors:
        print("%d error(s) suppressed by --force." % len(errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
