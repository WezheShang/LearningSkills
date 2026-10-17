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
  Do NOT use for: talking-head or vlog footage, fast-cut montage, animation or
  motion-graphics videos, anything with no narration, or any video where the
  speech does not correspond to what is on screen -- see references/README.md
  for the full applicability matrix, and confirm the fit BEFORE running.
  Exception: two non-slide categories still have supported paths here.
  (1) Progressive-annotation screen recordings -- someone drawing on a live
  chart or diagram while narrating -- are neither static slides nor montage;
  split them by topic, not by scene, and pick frames with
  `scripts/pick_annotated_frame.py`. (2) Recordings whose frames carry no
  information at all still have a text-first branch
  (`scripts/srt_segmap.py` + `scripts/build_notes.py`) that skips screenshots
  entirely. Both branches reuse the same renderer.
---

# Video (slide lecture) -> illustrated HTML deck

## Inputs to collect

Confirm these before running anything; a wrong assumption here invalidates the whole run.

1. **The video file** (or a URL you can download with `yt-dlp`).
2. **Is it a static-slide lecture?** Look at 3–4 frames spread across the video.
   The test: does the frame hold a slide-like layout (title, bullets, diagram,
   chart) while the narration moves on? Read the applicability matrix in
   `references/README.md`; if it is a talking head or fast-cut footage, stop and
   tell the user this pipeline does not fit. If it is a screen recording, do not
   conclude either way from three or four frames — go to step 2a first.
2a. **Screen recordings need a cheap full-runtime look, not a few frames.**
   Three or four hand-picked timestamps can all land on the same app state and
   make a visibly-changing video look frozen. When a platform offers a storyboard
   sprite, fetch it: bilibili's
   `https://api.bilibili.com/x/player/videoshot?aid=<aid>&cid=<cid>&index=1`
   returns one JPEG holding 45–100 keyframes spread across the whole runtime. A
   single `read` of that image decides whether the frames carry information, and
   it costs nothing. Getting this wrong in the dangerous direction is worse than
   being slow: it silently justifies shipping a text-only page for a video whose
   screenshots would have taught the lesson.
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

   **Then check that noise floor against the 0.005 assumption.** Large burned-in
   captions break it: when a subtitle line spans most of the frame width, every
   new caption scores ~0.065 on its own, which sits *right on* the 0.06 default —
   so each real slide gets sliced into fragments whose frames are identical.
   Symptom: stage 1's `strengths` line shows a crowd of scores evenly spread over
   0.05–0.08. Fix: pass `--scene-mask-bottom` equal to `--sub-band` (e.g. `0.20`).
   It crops the bottom before *scoring* only; keyframes still come from the full
   frame. Measured on a 5:43 lecture: floor 0.0395 → 0.0078, cuts 65 → 15 for 14
   real changes, distribution turning bimodal with a 3× gap underneath.

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

## Branch B — topic-split notes (screen recordings and other non-slide video)

Branch A above is the default. Use this branch when the frame check said "not a
slide deck" **but** the video has real subtitles worth reading. Two sub-cases,
and which one you are in decides whether screenshots appear:

- **Progressive annotation** — someone drawing on a live chart/diagram while
  narrating. The picture *is* the lesson. Go to `pick_annotated_frame.py` below.
- **Uninformative frames** — a static app window, a mostly-dark demo, talking
  head over screen. Skip screenshots entirely; the page is prose.

**Do not run `pipeline.py` on either.** Scene detection is wrong in both
directions: on an annotated screen recording every frame differs (a pen stroke
was just added) so the noise floor swamps the real boundaries, and on a static
window it finds nothing useful (a floating app window opening scores a perfect
1.0). Split by topic instead — that is what the speaker is actually doing.

The gate between the two sub-cases is step 2a above. Decide it with the storyboard
sprite, not with a handful of hand-picked frames.

1. **Get the subtitles.** Official CC tracks beat burned-in OCR. On bilibili,
   `yt-dlp --list-subs` returns `subtitles: []` when logged out — that is a login
   wall, not proof of absence. Re-check with a cookie file containing
   `SESSDATA`, or call `https://api.bilibili.com/x/player/wbi/v2?aid=<aid>&cid=<cid>`
   with the same cookie. Full method and both cookie-extraction failure modes:
   `references/README.md`.

2. **Split by topic, not by scene.** Read the transcript and pick 6–12 cut
   times in seconds where the topic turns, then:

   ```powershell
   python scripts/srt_segmap.py sub.srt --out segmap.json --cuts 118,258,394,534
   ```

   It assigns every cue exactly once and prints a per-segment line count so you
   can see a bad cut immediately. Cuts are numbers, not anchor strings: AI
   subtitle tracks (`ai-zh`) contain homophone errors, so text matching misses
   silently and shifts boundaries.

2b. **Pick frames (annotated sub-case only).**

   ```powershell
   python scripts/pick_annotated_frame.py video.mp4 --segmap segmap.json --out frames
   ```

   It samples ~8 frames per segment and keeps the one carrying the most drawing.
   Scoring is two-tier on purpose: frames whose background is dark (a chart
   window) are ranked by bright-mark density, and only a segment that is *entirely*
   a light mind-map panel falls back to red-ink density. Sharing one score across
   both window types saturates — a white panel reads as ~50% "ink" no matter how
   little is drawn on it, which silently ranks every panel frame equal. Measured
   on a real 16-minute series: 7 of 8 segments resolve to chart frames, and the
   intro legitimately stays on the panel.

   It also drops **modal-dialog candidates** (a settings popup covering the
   chart), which otherwise win: a dialog is bright, so it inflates the very
   score meant to reward pen strokes. Detection is "share of the frame that is
   bright *and* grey" — measured 0.001–0.018 on annotated charts versus 0.070
   on a dialog. Two things this taught: measure a heuristic's distribution on
   known-good and known-bad frames before trusting a threshold (a first attempt
   using centre-concentration of bright pixels looked reasonable and had *no*
   separating power — good frames scored 0.50–0.89, the dialog only 0.92), and
   apply the test only to chart-type frames, because a white mind-map panel is
   itself bright and grey and would be rejected wholesale.

   Then **look at every frame you picked** before writing its caption.

3. **Write `notes.json`** — titles, self-sufficient summaries (same standard as
   step 3 above), core points, meta, and `note_paragraphs` telling the reader how
   the page was made. For the annotated sub-case give each section an `image` and
   a `caption` describing what is actually visible in that frame (how many marks,
   where the polyline connects, what number is written beside it). For the
   uninformative sub-case omit `image` everywhere and keep only any one genuinely
   useful picture (a course map, a worked example) in `assets`.

4. **Render and verify.**

   ```powershell
   python scripts/build_notes.py --segmap segmap.json --notes notes.json --out notes.html --root .
   ```

   It exits non-zero and writes nothing if any segment lacks a section, a
   section has no subtitle lines, an asset is missing, or segments overlap —
   so a batch run cannot silently ship a half-written page. It warns (not
   fails) on a summary under `--min-summary` (default 80 chars), because that is
   the "restates the title" failure mode rather than a structural error. Load
   the result and read two sections before calling it done.

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
- **Far more segments than visible slides, and neighbouring segments show the
  same slide** → the noise floor is above the threshold, almost always because
  the caption band is large. Add `--scene-mask-bottom 0.20` (match it to
  `--sub-band`) rather than raising the threshold, which would also lose real cuts.
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
- **`srt_segmap.py` reports `assigned N/M` with N < M** → a cue started before
  the first cut or landed exactly on a boundary. Re-check the cut list; the
  first cut must be > 0 and below the last cue's end time.
- **`srt_segmap.py` warns that a segment has 0 lines** → two cuts sit too close
  together, or one falls outside the speech. Widen that boundary.
- **`build_notes.py` exits 1 with `segment sNN has no entry`** → you wrote fewer
  sections than the segment map has segments. Add the missing one; a blank
  section is worse than merging two adjacent segments in `notes.json` (drop the
  cut and re-run `srt_segmap.py`).
- **`build_notes.py` warns about a short summary** → treat it as a real defect.
  The page is only worth reading if each section stands alone; rewrite the
  summary instead of lowering `--min-summary`.

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
