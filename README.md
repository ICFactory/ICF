# ICF — Local AI Automated Video-to-Shorts System

A local-first, automated pipeline that takes one long-form video and produces
multiple polished short-form videos (YouTube Shorts style) — with no recurring
AI/API costs for the core pipeline.

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

## Architecture decisions

- **OS / hardware**: Windows PC, Intel i7, 8GB RAM, no dedicated GPU. CPU-only
  for now; benchmark before buying hardware. Recommended eventual RAM: 16GB
  minimum, 32GB preferred.
- **Video editing/rendering**: FFmpeg does all the actual video work (cutting,
  resizing, 9:16 conversion, cropping, text, subtitles, audio mixing,
  encoding). The AI layer only *decides* what to do — FFmpeg *performs* it.
  This keeps processing fast and avoids unnecessary AI compute.
- **Transcription**: faster-whisper, fully local, produces timestamped
  transcripts used to locate clip boundaries.
- **Moment selection (text)**: local LLM via Ollama — analyzes transcripts,
  scores potential clips, generates hooks/commentary/titles/descriptions/
  hashtags. No external API required for these text operations.
- **Moment selection (visual)** — for content where transcript alone isn't
  enough (animal fails, physical comedy, accidents, sports, reactions):
  a **hybrid, mostly-local** approach was chosen over pure local or pure
  cloud vision:
  1. Extract candidate keyframes **locally and for free** using FFmpeg/OpenCV,
     combining four signals: fixed-interval base sampling, motion spikes
     (frame differencing), audio energy spikes (RMS loudness), and
     ffmpeg's native scene-change detection.
  2. Deduplicate near-identical frames locally (cheap average-hash comparison)
     before anything leaves the machine.
  3. Only the surviving, meaningful keyframes are sent to a vision model
     (Gemini Flash free tier) for description — kept far under typical daily
     free-tier limits.
  4. Combine vision descriptions + transcript + audio energy locally to make
     the final moment-selection decision.
  5. A fully local vision model can replace the cloud step later as
     open-source vision models improve.
  - Result: ~80–90% of the work stays local; cloud is used only where it adds
    real value.
- **Commentary**: local LLM generates an original commentary script for a
  selected clip → local TTS renders voice audio → FFmpeg mixes it into the
  final video, so the system never just reposts raw clips.

## Current status

### Done

- Project brief and architecture finalized (this document).
- **Smart local keyframe extractor** (`scripts/05_extract_keyframes.py`)
  — implemented and tested against a real ~3-minute video:
  - Combines base sampling + motion detection + audio energy + scene-change
    detection.
  - Merges/caps candidates and removes near-duplicate frames via perceptual
    hashing.
  - Outputs a `manifest.json` per run listing every kept frame's timestamp
    and which signal(s) triggered it.
  - Verified end-to-end run: 189s video → 212 raw candidates → 150 after
    merge/cap → 106 kept after dedup.
- Initial `app/` package scaffolding created (`app/core`, `app/media`,
  `app/ai/providers`, `app/pipeline`, `app/cli.py`, `run_icf.py`) as the
  foundation for the content-agnostic core architecture, alongside legacy
  reference scripts (`scripts/02_multi_clips.py`, `03_transcribe.py`,
  `04_auto_select_clips.py`, `05_smart_video_analysis.py`).

### Remaining

- Reconcile `scripts/05_smart_video_analysis.py` (legacy) with the new
  `scripts/05_extract_keyframes.py` — confirm no duplicated responsibility.
- Build the **vision description step**: send surviving keyframes to Gemini
  Flash free tier (or a local vision model later) and capture per-keyframe
  descriptions.
- Build **moment scoring/selection**: combine vision descriptions +
  transcript (faster-whisper) + audio energy into a ranked list of best
  moments with timestamp, reason, and hook.
- Integrate the keyframe extractor and upcoming vision/scoring steps into the
  `app/pipeline/` architecture (currently only scaffolding exists).
- Automatic editing engine (smart crop, 9:16 conversion, subject positioning,
  zoom/pan, animated captions, hook/ending text) via FFmpeg.
- AI commentary generation (local LLM script → local TTS → FFmpeg mix).
- Title/description/hashtag generation per Short.
- Manual-inspection step before any YouTube upload; YouTube API integration
  deferred until the generation pipeline is reliable.

## Working rules

- Ask before writing code; get approval; then deliver a full implementation
  chunk rather than incremental baby steps.
- Keep the core content-agnostic — no per-category hardcoding.
- No unnecessary documentation or long planning essays — update this README
  when status changes instead.