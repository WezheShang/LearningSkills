#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
render_storyboard.py -- turn storyboard.json into a single self-contained HTML
deck: an overview section on top (clickable source link + the video's core
points), then one page per segment whose right column is a summary of what was
actually said in that time span.

Images are inlined as base64 data URIs so the file works offline, from email, or
off a USB stick. Print at 16:9 from any browser to get a PDF.

Run:  python render_storyboard.py <storyboard.json>
"""
import argparse
import base64
import html
import json
import mimetypes
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


# -------- video seek link --------------------------------------------------

def video_jump(url, t):
    """Build a URL that jumps to the source video at second ``t``.

    B 站: ``?p=N&t=N`` (preserves any existing p=), YouTube: ``&t=Ns``,
    anything else falls back to ``#t=N``. Strips a pre-existing t= so calls
    don't stack, and rounds to int seconds.
    """
    if not url:
        return None
    base = url.partition("#")[0]
    base = re.sub(r"([?&])t=[^&]*", "", base).rstrip("?&")
    if "bilibili.com" in base:
        sep = "&" if "?" in base else "?"
        return "%s%st=%d" % (base, sep, int(t))
    if "youtube.com" in base or "youtu.be" in base:
        sep = "&" if "?" in base else "?"
        return "%s%st=%ds" % (base, sep, int(t))
    return "%s#t=%d" % (base, int(t))


# --------------------------------------------------------------------- utils

def ts(sec):
    sec = float(sec or 0)
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def data_uri(path, max_w=1500):
    if not path or not os.path.exists(path):
        return None
    mime = mimetypes.guess_type(path)[0] or "image/png"
    try:
        from PIL import Image
        im = Image.open(path)
        if im.width > max_w:
            r = max_w / im.width
            im = im.resize((max_w, max(1, int(im.height * r))))
            path2 = path + ".thumb.jpg"
            im.convert("RGB").save(path2, "JPEG", quality=88)
            path, mime = path2, "image/jpeg"
    except Exception:
        pass
    with open(path, "rb") as fh:
        return f"data:{mime};base64," + base64.b64encode(fh.read()).decode("ascii")


def clean(s):
    if not s:
        return ""
    s = str(s).strip()
    while s.startswith(("*", "_", "`", "#", "-", ">")):
        s = s.lstrip("*_`#-> ").strip()
    return s.strip(" *_`\"").strip()


def esc(s):
    return html.escape(clean(s) or "")


# ------------------------------------------------------------------------ CSS

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d0e12;--card:#161822;--card2:#1c1f2b;--ink:#eef0f6;--dim:#99a0b0;
  --accent:#5b8cff;--accent2:#7aa2ff;--line:#272b39;--gold:#e8b44a;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--ink);
  font-family:"Segoe UI","Microsoft YaHei","PingFang SC",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{display:flex;flex-direction:column;align-items:center;gap:24px;padding:32px 20px 80px}

/* ---------- overview ---------- */
.ov{width:min(1180px,96vw);background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:34px 38px 30px}
.ov .kicker{display:inline-block;padding:5px 13px;border-radius:999px;
  background:rgba(91,140,255,.14);color:var(--accent2);font-size:12.5px;
  font-weight:700;letter-spacing:1.1px}
.ov h1{font-size:clamp(24px,3.4vw,42px);line-height:1.18;margin:14px 0 10px;
  letter-spacing:-.6px}
.ov .meta{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;
  color:var(--dim);font-size:14px;margin-bottom:6px}
.ov .meta .dot{width:3px;height:3px;border-radius:50%;background:#4a5060}
.srclink{display:inline-flex;align-items:center;gap:7px;color:var(--accent2);
  text-decoration:none;font-weight:600;border-bottom:1px solid rgba(123,162,255,.35);
  padding-bottom:1px;transition:border-color .15s,color .15s}
.srclink:hover{color:#9dbcff;border-color:#9dbcff}
.srclink::before{content:"▶";font-size:11px;opacity:.85}

.core{margin-top:24px;padding-top:22px;border-top:1px solid var(--line)}
.core h2{font-size:13px;letter-spacing:1.4px;color:var(--gold);
  font-weight:700;margin-bottom:14px}
.pts{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px 30px}
.pt{display:flex;gap:11px;align-items:flex-start;font-size:14.5px;line-height:1.6;
  color:#d2d7e4}
.pt i{flex:none;width:21px;height:21px;border-radius:6px;margin-top:1px;
  background:rgba(91,140,255,.16);color:var(--accent2);font-style:normal;
  font-size:11.5px;font-weight:700;display:flex;align-items:center;
  justify-content:center;font-variant-numeric:tabular-nums}
.pt b{color:#fff;font-weight:600}

.toc{margin-top:24px;padding-top:20px;border-top:1px solid var(--line)}
.toc h2{font-size:13px;letter-spacing:1.4px;color:var(--dim);font-weight:700;margin-bottom:12px}
.toc ol{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));
  gap:7px 26px;list-style:none;counter-reset:t}
.toc li{counter-increment:t;font-size:13.5px;line-height:1.45}
.toc li{display:flex;align-items:baseline;gap:10px}
.toc li a.jmp{margin-left:auto;display:inline-flex;align-items:center;color:var(--accent2);
 text-decoration:none;font:600 11px/1 ui-monospace,monospace;letter-spacing:.4px;
 padding:3px 8px;border:1px solid #2c3549;border-radius:6px;transition:all .15s;
 white-space:nowrap}
.toc li a.jmp:hover{color:#fff;border-color:var(--accent);background:rgba(91,140,255,.12)}
.toc li a.jmp::before{content:"↗ ";font-weight:700}
.toc a{color:#b9c1d4;text-decoration:none;display:flex;gap:9px;align-items:baseline;flex:1;min-width:0}
.toc a:hover{color:#fff}
.toc a::before{content:counter(t,decimal-leading-zero);color:#5c6379;
  font-variant-numeric:tabular-nums;font-size:12px;flex:none}
.toc .tt{color:#6d7488;font-variant-numeric:tabular-nums;font-size:12px;flex:none}

/* ---------- slides ---------- */
.slide{width:min(1180px,96vw);aspect-ratio:16/9;background:var(--card);
  border:1px solid var(--line);border-radius:14px;overflow:hidden;
  display:flex;flex-direction:column;box-shadow:0 10px 34px rgba(0,0,0,.4);
  scroll-margin-top:20px}
.body{flex:1;display:grid;grid-template-columns:1.24fr .96fr;min-height:0}
.shot{background:#05060a;display:flex;align-items:center;justify-content:center;
  overflow:hidden;border-right:1px solid var(--line)}
.shot img{width:100%;height:100%;object-fit:contain}
.side{padding:22px 26px;display:flex;flex-direction:column;gap:11px;
  min-width:0;overflow-y:auto}
.num{font-size:11.5px;color:var(--accent2);font-weight:700;letter-spacing:1.3px;
  display:flex;justify-content:space-between;align-items:baseline;flex:none}
.num span{color:#6d7488;letter-spacing:.2px;font-weight:600;
  font-variant-numeric:tabular-nums}
.num a.sl{color:#9aa0b0;text-decoration:none;letter-spacing:.2px;font-weight:600;
  font-variant-numeric:tabular-nums;border-bottom:1px dashed transparent;
  transition:color .15s,border-bottom-color .15s}
.num a.sl:hover{color:var(--accent2);border-bottom-color:var(--accent2)}
.side h2{font-size:clamp(17px,1.95vw,25px);line-height:1.26;letter-spacing:-.3px;
  flex:none;color:#fff}
.tag{display:inline-block;font-size:11px;color:var(--gold);background:rgba(232,180,74,.12);
  border-radius:5px;padding:3px 8px;font-weight:600;letter-spacing:.3px;flex:none;
  align-self:flex-start}

/* ---- summary / subtitle toggle ---- */
.tabs{display:inline-flex;gap:2px;background:#1e2230;border:1px solid var(--line);
  border-radius:8px;padding:3px;flex:none;align-self:flex-start}
.tabs button{appearance:none;border:0;background:transparent;color:var(--dim);
  font:inherit;font-size:12.5px;font-weight:600;padding:5px 15px;border-radius:6px;
  cursor:pointer;transition:background .14s,color .14s;letter-spacing:.3px}
.tabs button:hover{color:#dfe4ef}
.tabs button.on{background:rgba(91,140,255,.2);color:#a9c4ff}
.tabs button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}

.views{flex:1;min-height:0;display:flex;flex-direction:column;overflow-y:auto}
.view{flex:none}
.sum{color:#dbe0ec;font-size:clamp(13px,1.3vw,15.5px);line-height:1.68}
.subs{list-style:none;display:flex;flex-direction:column;gap:9px}
.subs li{position:relative;padding-left:19px;color:#c2c9da;
  font-size:13px;line-height:1.6}
.subs li::before{content:"";position:absolute;left:2px;top:9px;width:5px;height:5px;
  border-radius:50%;background:rgba(91,140,255,.55)}
.subs .none{color:var(--dim);font-style:italic}
.sp{flex:1;min-height:6px}
.strip{flex:none;height:4px;border-radius:2px;background:#20242f;overflow:hidden}
.strip i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2))}

@media screen and (max-width:880px){
  .slide{aspect-ratio:auto;height:auto}
  .body{grid-template-columns:1fr}
  .shot{aspect-ratio:16/9;border-right:0;border-bottom:1px solid var(--line)}
  .side{overflow:visible}
}
@media print{
  @page{size:338mm 190.5mm;margin:0}
  html,body{background:#fff}
  .wrap{gap:0;padding:0}
  .ov,.slide{width:100%;height:100vh;aspect-ratio:auto;border:0;border-radius:0;
    box-shadow:none;page-break-after:always;break-after:page;background:#fff;
    color:#15171d}
  .slide{--card:#fff}
  .side h2,.sum{color:#15171d}
  .num,.num span{color:#5B8CFF}
  .shot{background:#f5f6f9}
  .sp{display:none}
  /* print the summary, never the raw subtitle dump */
  .tabs{display:none !important}
  .views{overflow:visible}
  .view-sub{display:none !important}
  .view-sum{display:block !important}
  .subs li{color:#333}
}
"""

JS = """
document.querySelectorAll('.tabs').forEach(function (t) {
  var host = t.parentNode;
  t.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    t.querySelectorAll('button').forEach(function (x) {
      x.classList.toggle('on', x === b);
    });
    var want = b.getAttribute('data-view');
    host.querySelectorAll('.view').forEach(function (v) {
      if (v.getAttribute('data-view') === want) { v.removeAttribute('hidden'); }
      else { v.setAttribute('hidden', ''); }
    });
  });
});
"""


# ---------------------------------------------------------------------- HTML

def render_overview(sb, out_id="deck"):
    meta = sb.get("meta") or {}
    dur = sb.get("probe", {}).get("duration", 0)
    segs = sb["segments"]
    points = meta.get("core_points") or []
    url = meta.get("url")

    parts = ['<div class="ov">']
    parts.append('<span class="kicker">VIDEO STORYBOARD</span>')
    parts.append(f'<h1>{esc(meta.get("title") or "视频要点")}</h1>')

    bits = [f"{len(segs)} 页", f"总时长 {ts(dur)}"]
    if meta.get("author"):
        bits.append(str(meta["author"]))
    bits.append(f"生成于 {sb.get('generated_at','')}")
    meta_html = "".join(
        f'<span class="dot"></span><span>{esc(b)}</span>' if i else f'<span>{esc(b)}</span>'
        for i, b in enumerate(bits))
    parts.append(f'<div class="meta">{meta_html}</div>')

    if url:
        parts.append(
            f'<div class="meta"><a class="srclink" href="{html.escape(url, quote=True)}" '
            f'target="_blank" rel="noopener">'
            f'{esc(meta.get("source_label") or url)}</a></div>')

    if points:
        parts.append('<div class="core"><h2>核心观点</h2><div class="pts">')
        for i, p in enumerate(points, 1):
            head, body = (p if isinstance(p, (list, tuple)) else (None, p))
            inner = (f"<b>{esc(head)}</b> {esc(body)}" if head else esc(body))
            parts.append(f'<div class="pt"><i>{i}</i><span>{inner}</span></div>')
        parts.append("</div></div>")

    parts.append('<div class="toc"><h2>目录</h2><ol>')
    for s in segs:
        t = s.get("title") or f"段落 {s['index']}"
        jump = video_jump(url, s["start"])
        parts.append(f'<li><a href="#{out_id}{s["index"]:03d}">'
                     f'<span class="tt">{ts(s["start"])}</span><span>{esc(t)}</span></a>')
        if jump:
            parts.append(
                f'<a class="jmp" href="{html.escape(jump, quote=True)}" '
                f'target="_blank" rel="noopener" '
                f'title="跳到原视频该段位置（{ts(s["start"])}）">跳视频</a>')
        parts.append('</li>')
    parts.append("</ol></div>")

    parts.append("</div>")
    return "".join(parts)


def render_slide(s, dur, url=None):
    pct = (s["duration"] / dur * 100) if dur else 0
    uri = data_uri(s.get("keyframe") or (s.get("candidates") or [{}])[0].get("path"))
    shot = (f'<img src="{uri}" alt="">' if uri
            else '<div style="color:#6d7488;padding:20px">no keyframe</div>')

    title = esc(s.get("title")) or f"段落 {s['index']}"
    time_str = f'{ts(s["start"])} → {ts(s["end"])} · {s["duration"]:.0f}s'
    jump = video_jump(url, s["start"])
    if jump:
        time_html = (f'<a class="sl" href="{html.escape(jump, quote=True)}" '
                     f'target="_blank" rel="noopener" '
                     f'title="跳到原视频该段位置（{ts(s["start"])}）">{time_str}</a>')
    else:
        time_html = f'<span>{time_str}</span>'
    bits = [f'<div class="num"><span>SEGMENT {s["index"]:02d}</span>{time_html}</div>']

    if s.get("tags"):
        bits.append("".join(f'<span class="tag">{esc(t)}</span>' for t in s["tags"]))
    bits.append(f'<h2>{title}</h2>')

    # summary / raw-subtitle switcher -- summary is the default view.
    # on_screen_text is intentionally NOT rendered: it is already legible in the
    # keyframe, and it stays in storyboard.json for downstream use.
    subs = [clean(x) for x in (s.get("subtitles") or []) if clean(x)]
    sub_label = "字幕" if not subs else f"字幕 {len(subs)}"
    bits.append(
        '<div class="tabs" role="tablist">'
        '<button type="button" class="on" data-view="sum" role="tab">总结</button>'
        f'<button type="button" data-view="sub" role="tab">{sub_label}</button>'
        '</div>')
    sub_html = ("".join(f'<li>{esc(x)}</li>' for x in subs) if subs
                else '<li class="none">该时段未识别到字幕</li>')
    bits.append(
        '<div class="views">'
        '<div class="view view-sum" data-view="sum">'
        f'<div class="sum">{esc(s.get("summary")) or "—"}</div></div>'
        '<div class="view view-sub" data-view="sub" hidden>'
        f'<ul class="subs">{sub_html}</ul></div>'
        '</div>')

    bits.append('<div class="sp"></div>')
    bits.append(f'<div class="strip"><i style="width:{pct:.2f}%"></i></div>')

    return (f'<div class="slide" id="deck{s["index"]:03d}"><div class="body">'
            f'<div class="shot">{shot}</div>'
            f'<div class="side">{"".join(bits)}</div></div></div>')


def render_html(sb, out_path):
    segs = sb["segments"]
    dur = sb.get("probe", {}).get("duration", 0)
    title = (sb.get("meta") or {}).get("title") or "视频要点"

    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f"<title>{esc(title)}</title>", f"<style>{CSS}</style></head><body>",
           '<div class="wrap">', render_overview(sb)]
    out += [render_slide(s, dur, (sb.get("meta") or {}).get("url")) for s in segs]
    out.append(f"</div><script>{JS}</script></body></html>")

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))
    return out_path


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("storyboard")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    sb_path = os.path.abspath(args.storyboard)
    out_dir = os.path.dirname(sb_path)
    out_path = args.out or os.path.join(out_dir, "storyboard.html")

    with open(sb_path, encoding="utf-8") as fh:
        sb = json.load(fh)

    segs = sb["segments"]
    kf = sum(1 for s in segs if s.get("keyframe"))
    sm = sum(1 for s in segs if s.get("summary"))
    st = sum(1 for s in segs if s.get("subtitles"))
    print(f"segments {len(segs)}   keyframes {kf}   summaries {sm}   subtitle-scans {st}")

    make_html = render_html(sb, out_path)
    size = os.path.getsize(make_html)
    print(f"  storyboard.html  {size/1048576:.2f} MB   {make_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
