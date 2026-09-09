# ICF — Local AI Automated Video-to-Shorts System

A local-first, automated pipeline that takes one long-form video and produces
multiple polished short-form videos (YouTube Shorts style) — with minimal
recurring AI/API costs for the core pipeline.

## Objective

Build a local, automated AI video-processing system that:

- Analyzes a long video
- Transcribes its speech
- Identifies the strongest/most interesting moments (audio, visual, or both)
- Extracts multiple clips
- Converts them to vertical (9:16) format
- Automatically edits them (captions, commentary, effects)
- Generates titles/descriptions/hashtags
- Eventually publishes to YouTube

The system is **content-agnostic** — no hardcoded logic for "baby", "funny",
"football", etc. The intelligence layer determines the event type dynamically,
so the same pipeline works across bloopers, accidents, car stunts, football,
wildlife, sports, interviews, reactions, fails, and similar long-form content.

## What is NOT in scope yet (Phase 2/3)

- Automatically monitoring/downloading from YouTube channels at scale
- TikTok / Facebook / Instagram / Snapchat publishing
- Multiple accounts, analytics, automatic scheduling
- Cloud deployment, Android app, multi-machine processing

## Architecture

- **OS / hardware**: Windows PC (via GitHub Codespaces for development),
  Intel i7, 8GB RAM, no dedicated GPU. CPU-only for now.
- **Video editing/rendering**: FFmpeg does 100% of the actual video work
  (cutting, resizing, 9:16 conversion, cropping, text, subtitles, audio
  mixing, encoding). The AI layer only **decides** what to do — FFmpeg
  **performs** it. No AI model ever touches pixels/encoding directly; this
  keeps rendering fast and avoids unnecessary AI compute.
- **Transcription**: faster-whisper, fully local, produces timestamped
  transcripts used to locate clip boundaries and optionally boost scoring
  for moments with speech.
- **Local signal detection**: OpenCV + FFmpeg detect motion, scene changes,
  and audio energy spikes, entirely locally and for free, before anything
  is sent to a cloud model.
- **Vision description**: only the surviving, deduplicated keyframes (a
  handful per video) are sent to **Gemini 3.6 Flash** (free tier) for a
  short neutral description of what's visible. Cloud usage is deliberately
  minimal — this is the only step that leaves the machine.
- **Moment selection**: combines the local signal score, vision description,
  and (optionally) overlapping transcript text into a final ranked list of
  candidate clips. A generic keyword filter excludes non-content frames
  (title cards, outros, "subscribe" overlays) before ranking. An optional
  local LLM via **Ollama** can further judge each moment's shareability;
  the pipeline works fine without Ollama running (heuristic score only).
- **Commentary** (planned): local LLM generates a commentary script for a
  selected clip → local TTS renders voice audio → FFmpeg mixes it into the
  final video, so the system never just reposts raw clips.

## Pipeline (current scripts, in order)

The repo has **9 script files total in `scripts/`**, but only 4 are the
active pipeline today (table below). The rest — including a same-numbered
`05_smart_video_analysis.py` — are legacy/reference only; see the note
under the table.

| Step | Script | Purpose |
|---|---|---|
| 1 | `scripts/05_extract_keyframes.py` | Extract candidate keyframes locally (base sampling + motion + audio energy + scene-change), dedup near-identical frames. Output: `manifest.json` |
| 2 | `scripts/06_score_moments.py` | Score keyframes by which local signals fired, merge nearby frames into candidate time-range **events**. Output: `events.json` |
| 3 | `scripts/07_describe_moments.py` | Send each event's peak frame to Gemini 3.6 Flash for a neutral visual description. Checkpointed/cached to survive small free-tier quotas. Output: `events_described.json` |
| 4 | `scripts/08_select_moments.py` | Filter out non-content events, optionally blend in transcript overlap + local Ollama judgment, rank final candidate clips. Output: `selected_clips.json` |
| 5 | `scripts/09_cut_clips.py` | Cut, crop to 9:16, and encode the selected clips — pure FFmpeg, no AI calls |
| 6 | `scripts/10_add_captions.py` | Re-time transcript segments to each clip's local timeline and burn synced captions — pure FFmpeg |
| 7 | `scripts/11_add_commentary.py` | Generate a short voiceover line (local Ollama, or vision description as fallback), render with local TTS (pyttsx3), mix into clip audio |
| 8 | `scripts/12_generate_metadata.py` | Generate title/description/hashtags per clip (local Ollama, or templated fallback) |

**Note on `05_*`:** there are two scripts starting with `05` in `scripts/`.
Only `05_extract_keyframes.py` is active. `05_smart_video_analysis.py` is
the pre-restructure legacy version it replaced — its event-grouping idea
was carried forward into `06_score_moments.py`, but the script itself is
not called by anything and should not be run.

Legacy/reference only (superseded, not run in the active pipeline):
`scripts/01_basic_clip.py` / `.bat`, `02_multi_clips.py`, `03_transcribe.py`
(faster-whisper — still the intended transcription source, just not yet
wired into the pipeline as a script call), `04_auto_select_clips.py`,
`05_smart_video_analysis.py`.

## Current status

### Done

- Project brief and architecture finalized.
- Steps 1–4 above implemented and **verified end-to-end on a real ~3-minute
  video**: 189s video → 212 raw signal candidates → 150 after merge/cap →
  106 keyframes kept after dedup → grouped into events → 4 events described
  by Gemini 3.6 Flash → 3 usable clips ranked after filtering out 1 title
  card.
- Vision descriptions confirmed accurate on real footage, including
  correctly identifying and excluding a title/outro card as non-content.
- **Full pipeline (steps 1–5) run end-to-end on the real ~189s test video**,
  producing 3 final, playable, correctly-cropped 9:16 clips (no distortion,
  confirmed visually) with no manual intervention beyond running each
  script in order.
- **Steps 6–8 (captions, commentary, metadata) run end-to-end on the same
  3 real clips**: synced captions burned in correctly, a local-LLM-or-fallback
  voiceover line generated and mixed into each clip's audio via local TTS
  (pyttsx3 + espeak-ng), and title/description/hashtags generated for all 3
  (currently via the templated fallback, since Ollama isn't running yet in
  that environment — output is still usable, just less creative than an
  LLM pass would produce).
  - Known harmless issue: pyttsx3's espeak driver prints a
    `ReferenceError` traceback per synthesized line on this Python
    version; it does not affect output — each `.wav` file is still
    written correctly. Cosmetic only, safe to ignore for now.
- Initial `app/` package scaffolding created (`app/core`, `app/media`,
  `app/ai/providers`, `app/pipeline`, `app/cli.py`, `run_icf.py`) as the
  foundation for wiring the scripts above into a single application later.

### Remaining

- Set up local Ollama (with a model pulled) so steps 4, 7, and 8 use real
  LLM reasoning instead of their heuristic/templated fallbacks — everything
  already works without it, this is a quality upgrade, not a blocker.
- Wire `03_transcribe.py`'s output into `08_select_moments.py`'s
  `--transcript` option for the scoring bonus (it's already used
  successfully by steps 6–7, just not yet passed into step 4's scoring).
- **Disk-space housekeeping.** Every run writes real files into
  `output/keyframes/frames/`, `output/events/`, `output/final_clips/`, plus
  any transcript/temp folders — these grow every run and are never cleaned
  up automatically. Needed:
  - A `.gitignore` entry for `output/`, `input/`, and any `temp*/` /
    `*_tmp*` paths so raw video/image/JSON test artifacts never get
    committed to the repo (they don't belong in git history).
  - A cleanup script/flag (e.g. `--clean-intermediate`) that removes
    per-run keyframe/event frame folders once `final_clips/` has been
    produced successfully, so only the final output and its manifest are
    kept long-term.
- Automatic editing engine (smart crop/subject positioning, zoom/pan,
  animated captions, hook/ending text) via FFmpeg.
- AI commentary generation (local LLM script → local TTS → FFmpeg mix).
- Title/description/hashtag generation per Short.
- Integrate all steps into the `app/pipeline/` architecture (currently only
  scaffolding exists; scripts are run manually and separately today).
- Manual-inspection step before any YouTube upload; YouTube API integration
  deferred until the generation pipeline is reliable.

## Working rules

- Ask before writing code; get approval; then deliver a full implementation
  chunk rather than incremental baby steps.
- Keep the core content-agnostic — no per-category hardcoding.
- No unnecessary documentation or long planning essays — update this README
  when status changes instead.