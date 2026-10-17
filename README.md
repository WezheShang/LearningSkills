# LearningSkills

Skills that make your learning more productive.

Each skill lives in its own folder and is self-contained: a `SKILL.md` that an AI
agent loads, plus whatever scripts and reference docs it needs.

---

## chanlun-kmerge

Build a **self-contained single-file HTML** for practising 缠论 K 线包含处理 (Chan
theology bar-containment merging), driven by real A-share index daily data.

**[Download 缠论K线合并练习.html](chanlun-kmerge/缠论K线合并练习.html)** — 1.8 MB,
double-click to open. No server, no network, no dependencies. Data is embedded.

### Quick start

```powershell
# just use it: open chanlun-kmerge/缠论K线合并练习.html in a browser

# or rebuild from source
$py = "$env:USERPROFILE\miniconda3\python.exe"   # needs requests
& $py -B scripts/fetch_index_daily.py            # refresh index data (Sina source)
& $py -B scripts/build_kmerge.py                 # inject data -> single-file HTML

# tests — all four must pass
node tests/check_refs.js templates/kmerge_template.html
node tests/test_merge_rule.js
node tests/test_check_rule.js
node tests/verify_built.js
```

### What it does

Click any bar → it selects that bar plus its right neighbour → merge them per the
缠论原文 rule. Bars are drawn **光头光脚** (solid body from high to low, *no wicks*) so
containment is visible at a glance. 7 indices, daily + weekly, 2005 to present.

Direction is decided by the original text: compare `b` against `a` — the nearest bar
to its left that does **not** contain it — and use `g_b > g_a` (up / 高高) or
`d_b < d_a` (down / 低低). Strict inequalities; the `≥`/`≤` in the original text is a
known typo, since equal highs necessarily constitute containment.

Two checks are built in:

- **Before merging** — refuses bars that don't actually contain each other, and (in
  manual-direction mode only) refuses a direction that contradicts the rule. Auto mode
  skips the direction check because the program derived it.
- **完成检查 / `F`** — scans the current view (or the whole series) for unprocessed
  containment pairs, lists them, and jumps to the first one.

### Why the direction rule is worth stating

An earlier version compared `c` against `b` and fell back to "up" when neither
strictly held. Measured against real data that made it return **up 635 times and down
0 times** out of 6688 containment pairs — it literally never produced a downtrend
merge. Comparing `b` against a valid referent `a` fixed 535 of those.

Full detail: **[chanlun-kmerge/SKILL.md](chanlun-kmerge/SKILL.md)**

---

## video-slides-to-deck

Turn a **static slide-lecture video** into a self-contained illustrated HTML deck:
a top overview with the source link and core points, then one page per slide
showing the best key screenshot, a substantive written summary, and a toggle to
reveal the burned-in subtitles for that time span.

Built and calibrated on a real 8.6-minute Chinese finance lecture (28 slides).

### Quick start

```powershell
$py = "$env:USERPROFILE\miniconda3\python.exe"   # needs PIL; the default python venv lacks it
$env:PYTHONIOENCODING = 'utf-8'
$sk = "./video-slides-to-deck/scripts"

# 0. calibrate the scene threshold for your deck (sweeps and reports the usable range)
& $py "$sk\selftest.py"

# 1. run the mechanical pipeline
& $py "$sk\pipeline.py" "C:\path\video.mp4" --out "C:\path\out"

# 2. author the titles / summaries / core points  <- the judgement step
# 3. render
& $py "$sk\render_storyboard.py" "C:\path\out\storyboard.json"
```

### Read this before using it

This pipeline is **not** general-purpose video summarising. It assumes the video
is a slide deck held on screen while someone narrates over it. Full applicability
matrix, parameter reference and troubleshooting:

**[video-slides-to-deck/references/README.md](video-slides-to-deck/references/README.md)**

Short version — **do not use** it for talking-head footage, screen recordings,
fast-cut montage, animation/motion-graphics, anything silent, or anything where
the speech does not match the picture.

### Why there is a selftest

ffmpeg's scene score is normalised over the whole frame, so a slide deck with a
fixed title bar and caption band (roughly a third of the image never changes)
pushes real cut scores far lower than a full-bleed change does. Set the threshold
too high and you get **zero** cuts — and the pipeline then silently falls back to
even time splitting, which looks like it worked. `selftest.py` measures the
usable range instead of trusting a constant.
