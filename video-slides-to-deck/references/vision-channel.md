# Worker vision channel: looking at frames without eyes

How a worker (or the main agent) inspects picked keyframes through the
`mcode-tools` multimodal CLI when the current model cannot read images
directly. Battle-tested across a 43-episode screen-recording course run
(one vision call per frame, ~340 frames, every caption grounded in what
the vision model actually reported seeing).

## The channel

1. **Load the skill first.** `mcode-tools-master` (in
   `~/.minimax/.builtin-skills/`). If the skill tool is not available in
   the current session, `read` its `SKILL.md` directly — the CLI usage is
   all there.
2. **Upload each frame** for a temporary URL:

   ```
   mcode-tools upload_temp_url <frame.png>
   ```

3. **Call the vision model, one image per call.** The subcommand is
   `call` (not `invoke`):

   ```
   mcode-tools connector call connector__matrix__describe_images --args-file args_s1.json
   ```

   `args.json` layout — the array field is `image_info`, and the file must
   be UTF-8 **without BOM**:

   ```json
   {"image_info":[{"url":"<temp url>","prompt":"..."}]}
   ```

   Write the prompt with fullwidth quotes （「」） so no `"` needs JSON
   escaping inside a hand-written file.

## Prompt shape (anti-hallucination)

Ask for an objective inventory, not an interpretation:

> 描述这张帧画面：左侧是什么窗口、板书/导图的层级结构、手绘图形元素
> （折线、方框、圈、叉）及颜色、可见的文字标注。只描述确实可见的内容，
> 不要猜测没有的东西，不要解读含义。

Failure mode seen in the wild: the model replies in role-play prose and
clearly never looked at the image. Fix: switch to a more templated,
checklist-style prompt and retry — not re-uploading first, re-prompting.

## Known flakiness (all intermittent, all retry-once-and-move-on)

- **Temp-URL download failure** on the vision side → re-run
  `upload_temp_url` for that frame and call again.
- **Two descriptions disagree** on structure (typically mind-map
  parent/child hierarchy) → make a follow-up call quoting the two
  versions and asking which is right. Do not average them.
- **Unreadable handwriting** with contradictory guesses across calls →
  caption writes 「字迹潦草、不可辨认」. Never adopt a guess.
- **Watermarks** (contact info printed in a frame corner) → identify
  once, then exclude from every caption; also grep the authored
  `notes.json` for the literal string as a gate. base64 payloads will
  produce false-positive substring hits — the authored-JSON grep is the
  real check.

## ffmpeg probe (replace a bad frame)

When the auto-picked frame misses the teaching moment (board not yet
drawn, canvas scrolled elsewhere, or a pure mind-map frame where a
hand-drawn one exists later in the segment), probe nearby timestamps:

```
ffmpeg -ss <t> -i video.mp4 -frames:v 1 -vf scale=1280:-1 -update 1 probe_s3_114.png
```

- **ffmpeg 8.x needs `-update 1`** to write a single still PNG; without
  it the command "succeeds" and writes nothing.
- Path candidates on this machine: `~/miniconda3/Scripts/ffmpeg.exe`
  first, else `~/AppData/Microsoft/WinGet/Links/ffmpeg.exe`.
- In PowerShell, ffmpeg's progress banner on stderr is *not* an error —
  verify the probe landed by listing the directory (`cmd /c dir /b`),
  never by trusting the console output.
- After replacing `frames/sN.png` (keep the filename), update the
  timestamp for that entry in `frames/frames.json` if the picker wrote
  one, so the metadata still matches the image.

Probe rule of thumb: the teaching drawing for a segment usually appears
in the **middle to late** part of the segment, after the narrator
finishes talking and starts drawing. Probe 2–4 points there before
giving up and keeping the auto frame.

## Batch pipeline notes (multi-worker runs)

- Cap workers at 4 concurrent; queue the 5th and dispatch on the first
  completion. Material prep (subtitles, video downloads) for the *next*
  batch can run while current workers are still going — downloads are
  shell tasks and don't consume worker slots.
- Each worker brief carries: input paths, duration + suggested section
  count, the three script commands, this vision-channel recipe, a
  `notes.json` schema reference, content hard rules, the accumulated
  homophone correction table, and a fixed report format.
- Section-count heuristics that produced sane cuts: ~90–130s → 2–3,
  ~220s → 3, ~450s → 5–6, ~620s → 6–7, 720–800s → 7–8, ~900–1000s →
  8–9, 1050–1200s → 9–10, 2000s+ → 12–14. Always "cut at topic turns,
  never pad to reach the count".
- **Homophone correction table** (AI `ai-zh` tracks mis-hear domain
  terms): maintain per-project, append every newly observed variant each
  batch, and attach context guards to risky entries (e.g. 300→三买 only
  in buy-point context, never 沪深300; 上周→上冲 only in the specific
  mis-heard phrase; 盘子→盘整 except when it means float size). The
  table is an aid for human-in-the-loop transcription repair — never a
  mechanical find/replace.
- **Acceptance suite** per batch: structural check (sections/imgs/caps/
  subs counts per page), occlusion scan on chart frames, terminology
  trace + guaranteed-return-claim scan, and an unmatched-term
  classifier (variant / cross-segment / caption-only / *unexplained*).
  Only the *unexplained* class blocks delivery; each item is resolved by
  re-checking the subtitle source and, when it is a paraphrase of a
  mis-heard word, fixing one word in `notes.json` and re-rendering.
- Script hygiene: scripts that span batches should locate pages through
  a root-list + `root_for(page)` lookup (newest batch first), and grep
  for stale hardcoded variables after every refactor — one `ROOT` left
  behind crashed the traceability stage three batches later.
