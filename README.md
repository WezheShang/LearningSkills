# LearningSkills

Skills that make your learning more productive.

Each skill lives in its own folder and is self-contained: a `SKILL.md` that an AI
agent loads, plus whatever scripts and reference docs it needs.

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
