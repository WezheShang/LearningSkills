---
name: video-slides-to-deck
description: |
  Turn a static-slide lecture video (one slide deck held on screen while someone
  narrates over it) into a self-contained illustrated HTML deck: a top overview
  with the source link and core points, then one page per slide showing the best
  key screenshot, a substantive written summary, and a toggle to reveal the
  burned-in subtitles for that time span. Use when the user wants to read a
  slide-lecture video as notes ("把这个视频转成图文/PPT/要点", "video to deck",
  "summarise this lecture video", "turn this course video into notes").
  Do NOT use for: talking-head or vlog footage, screen recordings, fast-cut
  montage, animation or motion-graphics videos, anything with no narration, or
  any video where the speech does not correspond to what is on screen -- see
  references/README.md for the full applicability matrix, and confirm the fit
  BEFORE running.
---

# Video (slide lecture) -> illustrated HTML deck

## Inputs to collect

Confirm these before running anything; a wrong assumption here invalidates the whole run.

1. **The video file** (or a URL you can download with `yt-dlp`).
2. **Is it a static-slide lecture?** Look at 3–4 frames spread across the video.
   The test: does the frame hold a slide-like layout (title, bullets, diagram,
   chart) while the narration moves on? Read the applicability matrix in
   `references/README.md`; if it is a talking head, a screen recording, or
   fast-cut footage, stop and tell the user this pipeline does not fit.
3. **Is there burned-in narration?** The whole point of the subtitle band is to
   recover what was said. If the video is silent, or the captions are absent and
   unobtainable, stop — you cannot write the summaries without the speech.
4. **Language** of the subtitles (default `zh`).

If a video URL is given but the user has not confirmed fit, sample frames first
(`ffmpeg -ss <t> -i <video> -frames:v 1 out.png` at several timestamps) and read
them before committing to a full run.

## Procedure

1. **Self-check the segmentation before trusting it.** Run
   `python scripts/selftest.py`. It builds a synthetic slide video with known cut
   points and sweeps the threshold, reporting the usable range. Reason: the
   scene-score threshold is not a documented constant — it is normalised over the
   whole frame, so a deck with a fixed title bar and caption band (~1/3 of the
   image never changes) pushes real cuts far lower than a full-bleed change
   does. A threshold set above every real cut yields **zero** cuts, and the
   pipeline then silently falls back to even time splitting, which *looks* like
   it worked. Measured: full-bleed cuts 0.15–0.29, chrome-heavy cuts as low as
   0.076, intra-shot noise below 0.005. Default 0.06 passes both.

2. **Run the mechanical pipeline.**
   `python scripts/pipeline.py <video> --out <dir>`
   This does scene-split → contact sheets → vision keyframe pick → per-segment
   subtitle transcription, then scrubs the subtitle output and prints a table.
   Run it with an absolute `--out` path: the storyboard stores absolute frame
   paths, and the last stage is the slow one (one vision call per segment), so
   budget roughly 20–40 s per segment.

3. **Read the subtitle table and write the content yourself.** For every segment
   write `title` and `summary`, and write `meta` (title / author / url /
   core_points). This is the step that determines whether the deck is useful.

   A summary must be **self-sufficient**. The reader should be able to learn the
   definition, mechanism or rule from the summary alone, without the video and
   without the slide. Bad: *"买点的选择，关键在于要看不同级别之间是怎么配合的"* —
   that restates the title and answers nothing. Good: *"买点不是单一级别上的孤立形态，
   而是来自不同级别之间的配合——大级别定方向、中级别定区域、小级别定精确入场点。"*
   Reason: the deck's whole value is that a reader can skim it and still get the
   substance.

4. **Render.** `python scripts/render_storyboard.py <out>/storyboard.json`
   Produces one self-contained HTML file (images inlined as base64, so it works
   offline and can be printed to a 16:9 PDF).

5. **Verify in a browser before claiming it works.** Load the HTML, scroll to the
   overview, then to two different segments, and click a 字幕 toggle. Screenshots
   taken immediately after load often capture un-decoded inline images as black —
   scroll a little and re-shoot before concluding anything is wrong.

## Output contract

- `<out>/storyboard.html` — the deliverable. One file, images inlined, overview
  on top (clickable source link, core points, jumpable TOC), then one page per
  segment with keyframe + summary, plus a 总结/字幕 toggle per page.
- `<out>/storyboard.json` — the structured record: segment bounds, keyframe
  paths, `on_screen_text` (retained even though it is not rendered), subtitle
  lines, titles, summaries, meta. Keep it; it is the input for any re-render or
  for feeding another tool.

Do not produce a .pptx. The HTML is the deliverable.

## Failure handling

- **`selftest.py` reports `cut_recall 0.00`** → the threshold is above every real
  cut. Re-run `selftest.py` to get the usable range for that deck and pass the
  low end of it (`--scene-threshold 0.06` is the calibrated default; 0.12 and
  above can drop real cuts on slides with a title bar and caption band).
- **`selftest.py` passes but the real video splits badly** → the deck is
  unusual. Low cut scores mean raise nothing, lower `--scene-threshold`; a count
  far above the visible slide count means the slides animate, so raise it to
  0.20–0.25 to skip the build steps.
- **Segments much longer than the slide count suggests** → raise
  `--scene-threshold` (0.20–0.25) to ignore animated builds, or lower
  `--min-segment` if genuine short slides are being merged.
- **No subtitles detected** → the band is wrong. Measure it: crop candidates and
  look, or adjust `--sub-band` (default `0.20`, measured as 0.198–0.202 across
  three frames of a real lecture). If the video truly has no captions, the deck
  cannot carry per-segment summaries — report that to the user rather than
  inventing content.
- **`subtitle_needs_review` flagged** → the vision model returned prose about the
  task instead of transcribing. Re-run `subtitle_scan.py --force` for those
  segments, or transcribe them by reading the strip image in
  `<out>/substrips/subNNN.png` directly.
- **A segment's subtitle list is empty while others are fine** → that time span
  had no caption on screen. Accept it, or merge it into the neighbour.

## Windows (win32) platform notes

- Run Python as `"$env:USERPROFILE\miniconda3\python.exe"`. The default `python` on
  PATH is the hermes venv and is missing `faster_whisper` / `PIL`.
- Set `$env:PYTHONIOENCODING='utf-8'` and
  `[Console]::OutputEncoding=[System.Text.Encoding]::UTF8` or Chinese output
  crashes the console codec.
- `mcode-tools` resolves through `~/.minimax/bin/mcode-tools.cmd`; the bundled
  `vlm_pick.py` locates it itself and invokes it via `cmd /c`, so no PATH setup
  is needed.
- PowerShell `>` redirection writes UTF-16. Redirect through Python or use
  `Out-File -Encoding UTF8` when capturing JSON.
