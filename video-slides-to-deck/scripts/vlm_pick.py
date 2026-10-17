#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
vlm_pick.py -- for each segment, ask a vision model to choose the best keyframe
and to name the segment. Writes results back into storyboard.json.

Flow per segment:
  1. upload that segment's contact sheet  (mcode-tools upload_temp_url)
  2. one vision call on the sheet        (connector__matrix__describe_images)
  3. parse PICK / TITLE / SUMMARY, write keyframe + title + summary back

Design notes
  * One sheet per call, not N frames: the vision tool answers each image
    independently, so "which of these 3 is best?" needs them in one image with
    visible numbers.
  * Resumable: segments that already have a keyframe are skipped.
  * Fault tolerant: one failed segment is recorded and the run continues.

Run:  python vlm_pick.py <storyboard.json> [--force] [--limit N]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

DESCRIBE_TOOL = "connector__matrix__describe_images"


def resolve_cli():
    """mcode-tools is a .cmd shim under the runtime bin dir, which is not on the
    PATH a Python child process inherits -- and .cmd needs cmd.exe anyway."""
    cands = []
    env = os.environ.get("MCODE_TOOLS")
    if env:
        cands.append(env)
    cands += [
        os.path.expanduser("~/.minimax/bin/mcode-tools.cmd"),
        os.path.expanduser("~/.minimax/bin/mcode-tools"),
        os.path.expanduser("~/.mavis/bin/mcode-tools.cmd"),
    ]
    w = shutil.which("mcode-tools")
    if w:
        cands.append(w)
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("mcode-tools not found; set MCODE_TOOLS to its full path")


CLI = resolve_cli()
IS_SHIM = CLI.lower().endswith((".cmd", ".bat"))
HERE = os.path.dirname(os.path.abspath(__file__))


def run(argv, timeout=600):
    if IS_SHIM:
        argv = ["cmd", "/c", CLI] + list(argv[1:])
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def _json_from(text):
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in output")
    return json.loads(text[start:])


def upload(path, timeout=300):
    """Return a temporary HTTPS URL for a local file."""
    if not os.path.exists(path):
        raise RuntimeError(f"file not found: {path}")
    code, out, err = run(["mcode-tools", "upload_temp_url", path,
                          "--mime-type", "image/png"], timeout=timeout)
    if code != 0:
        raise RuntimeError(f"upload rc={code}: {err[:300]}")
    data = _json_from(out)
    url = data.get("temp_url")
    if not isinstance(url, str) or not url.startswith("http"):
        raise RuntimeError(f"upload returned no usable temp_url: {str(data)[:200]}")
    return url


def describe(url, prompt, timeout=600):
    """One vision Q&A on one image. Returns the model's text answer."""
    if not url:
        raise RuntimeError("describe() called with an empty url")
    args = {"image_info": [{"url": url, "mime_type": "image/png", "prompt": prompt}]}
    # per-process temp file: a fixed name inside the skill dir both litters the
    # install and gets clobbered when two runs overlap
    fd, args_file = tempfile.mkstemp(prefix="vlm_args_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(args, fh, ensure_ascii=False)
        code, out, err = run(["mcode-tools", "connector", "call", DESCRIBE_TOOL,
                              "--args-file", args_file], timeout=timeout)
    finally:
        try:
            os.unlink(args_file)
        except OSError:
            pass
    if code != 0:
        raise RuntimeError(f"vision call rc={code}: {err[:300]}")
    data = _json_from(out)
    if not data.get("success", True):
        raise RuntimeError(f"vision tool error: {str(data)[:300]}")
    for r in data.get("results", []):
        if r.get("success"):
            return r.get("description", "")
    raise RuntimeError(f"no successful result: {str(data)[:300]}")


PROMPT = (
    "This is a numbered contact sheet of candidate frames taken from one segment "
    "of a video. The frame you choose will become the key screenshot on a slide.\n\n"
    "Step 1 - PICK. Choose the single most informative frame: clearest subject, most "
    "content, no transition blur, no empty/black frame, no duplicate-looking frame.\n"
    "For slides or screen recordings, prefer the frame where the title/headline and the "
    "main diagram are both fully visible and unobstructed.\n\n"
    "Step 2 - TEXT. Read the text that is actually visible in the chosen frame "
    "(title, headings, labels, legend, captions). Transcribe it verbatim in the "
    "original language. If there is no text, write NONE.\n\n"
    "Step 3 - TITLE. If the chosen frame has a headline, COPY it verbatim as the "
    "title, in the SAME language as that headline (do NOT translate). Otherwise "
    "write a short descriptive title, again in the language of the frame's text. "
    "Max 8 words.\n\n"
    "Step 4 - SUMMARY. One sentence, max 25 words, on what this segment explains.\n"
    'Speech transcript for this segment, if any: "{speech}"\n\n'
    "Answer in EXACTLY this format and nothing else:\n"
    "PICK: <number>\n"
    "TITLE: <max 8 words>\n"
    "ONSCREEN: <verbatim visible text, or NONE>\n"
    "SUMMARY: <one sentence, max 25 words>"
)

_PICK = re.compile(r"PICK\s*[:：]\s*(\d+)", re.I)
_TITLE = re.compile(r"TITLE\s*[:：]\s*(.+)", re.I)
_ONSCREEN = re.compile(r"ONSCREEN\s*[:：]\s*(.+)", re.I)
_SUM = re.compile(r"SUMMARY\s*[:：]\s*(.+)", re.I)


def parse(text, n_candidates):
    m = _PICK.search(text)
    if m:
        n = int(m.group(1))
    else:
        # fall back to the first bare number that is a legal candidate index
        n = 0
        for mm in re.finditer(r"\b(\d+)\b", text):
            v = int(mm.group(1))
            if 1 <= v <= n_candidates:
                n = v
                break
        if not n:
            n = 1
    n = max(1, min(n, n_candidates))

    def field(rx):
        mm = rx.search(text)
        return mm.group(1).strip().strip('"') if mm else ""

    return n, field(_TITLE), field(_ONSCREEN), field(_SUM)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("storyboard")
    ap.add_argument("--force", action="store_true", help="re-pick segments that already have one")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    sb_path = os.path.abspath(args.storyboard)
    sb_dir = os.path.dirname(sb_path)
    with open(sb_path, encoding="utf-8") as fh:
        sb = json.load(fh)

    manifest_p = os.path.join(sb_dir, "sheets", "sheets_manifest.json")
    if not os.path.exists(manifest_p):
        print(f"missing {manifest_p} -- run make_contact_sheets.py first", file=sys.stderr)
        return 2
    with open(manifest_p, encoding="utf-8") as fh:
        man = json.load(fh)

    by_index = {s["index"]: s for s in sb["segments"]}
    todo = [s for s in man["sheets"]
            if args.force or not by_index[s["segment"]].get("keyframe")]
    if args.limit:
        todo = todo[:args.limit]

    print(f"vision-picking {len(todo)} / {len(man['sheets'])} segments")
    print(f"  cli: {CLI}\n", flush=True)
    failures = []

    for i, sheet in enumerate(todo, 1):
        seg = by_index[sheet["segment"]]
        n_cand = len(sheet["order"])
        try:
            url = upload(sheet["sheet"])
            text = describe(url, PROMPT.format(speech=(seg.get("transcript") or "")[:400]))
            n, title, onscreen, summary = parse(text, n_cand)
            seg["keyframe"] = sheet["order"][n - 1]
            seg["keyframe_pick"] = n
            if title:
                seg["title"] = title
            if onscreen and onscreen.upper() != "NONE":
                seg["on_screen_text"] = onscreen
            if summary:
                seg["summary"] = summary
            print(f"  [{i}/{len(todo)}] seg{seg['index']:>3} "
                  f"pick #{n}/{n_cand}  {title[:46]}", flush=True)
        except Exception as exc:
            failures.append((seg["index"], str(exc)))
            print(f"  [{i}/{len(todo)}] seg{seg['index']:>3} FAILED: {exc}", flush=True)
        time.sleep(args.sleep)

    sb["vision"] = {
        "tool": DESCRIBE_TOOL,
        "picked": sum(1 for s in sb["segments"] if s.get("keyframe")),
        "total": len(sb["segments"]),
        "failures": [{"segment": i, "error": e} for i, e in failures],
    }
    with open(sb_path, "w", encoding="utf-8") as fh:
        json.dump(sb, fh, ensure_ascii=False, indent=2)

    print(f"\npicked {sb['vision']['picked']}/{sb['vision']['total']} segments")
    if failures:
        print(f"{len(failures)} failed -- rerun without --force to retry only those")
    print(f"-> {sb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
