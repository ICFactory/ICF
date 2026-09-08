# Intelligent Content Factory (ICF)

ICF is an AI-powered video-to-Shorts system that takes a long-form video, finds the best moments, and turns them into polished vertical Shorts.

The goal is to automate the process from **long video → intelligent moment selection → editing → finished Shorts → metadata**.

## Current Approach

ICF uses a **hybrid architecture**:

* **Local/open-source tools** where they are practical and efficient
* **Cloud AI** where stronger vision, reasoning, or other AI capabilities are useful
* **FFmpeg** for reliable video/audio processing and rendering
* **GitHub Codespaces** as the primary development environment

The system is designed so individual AI components can be replaced without rebuilding the entire pipeline.

## What We Have Achieved

### Phase 1 — Video Engine

* GitHub repository and Codespaces development environment
* FFmpeg installed and working in Codespaces
* Basic video clipping
* Precise timestamp support, including milliseconds
* 9:16 vertical conversion
* 1080×1920 output
* Original audio preservation
* Single-clip generation working
* Multi-clip generation script added
* Batch generation from multiple timestamp ranges working

### Phase 2 — Transcription

* `faster-whisper` installed in Codespaces
* Local transcription pipeline implemented
* Timestamped transcript generation
* Audio extraction through FFmpeg
* Language detection

## What Remains

The main intelligent part of ICF is still being built.

* Multimodal video analysis
* Visual/keyframe analysis
* Hybrid Vision AI
* Intelligent moment detection
* AI-based clip scoring and ranking
* Accurate automatic clip boundaries
* Duplicate/overlap control
* Smart vertical framing
* Automatic captions
* AI-generated original commentary
* Text-to-speech
* Automatic video enhancements
* Final Short assembly
* Title, description and hashtag generation
* End-to-end automated pipeline
* YouTube publishing

## Project Structure

```text
ICF/
├── README.md
├── config.example.yaml
├── .gitignore
├── scripts/
│   ├── 01_basic_clip.py
│   ├── 01_basic_clip.bat
│   └── 02_multi_clips.py
├── input/
│   └── .gitkeep
├── output/
│   └── .gitkeep
├── temp/
├── models/
└── docs/
```

The `input/`, `output/`, `temp/`, and `models/` directories are intended to support the processing pipeline as it grows.

## Development Environment

Development is primarily done in **GitHub Codespaces**.

The Windows 7 machine is kept lightweight. Heavy development and AI processing are not tied to the local machine.

Current development stack includes:

* Python
* FFmpeg
* faster-whisper
* GitHub Codespaces
* Pluggable AI/LLM services
* Hybrid local/cloud Vision AI

## Roadmap

### Phase 1 — Video Engine ✓

Basic clipping, vertical conversion and batch clip generation.

### Phase 2 — Transcription ✓

Timestamped speech transcription using faster-whisper.

### Phase 3 — Multimodal Analysis

Combine transcript, audio and visual information to understand what is happening in the video.

### Phase 4 — Intelligent Selection

Find, score and rank the strongest moments automatically.

### Phase 5 — Smart Clip Boundaries

Determine where each Short should actually start and end.

### Phase 6 — Short Editor

Automatically handle framing, captions, effects, audio and other enhancements.

### Phase 7 — AI Commentary

Generate original commentary and voice narration.

### Phase 8 — Metadata

Generate titles, descriptions and hashtags.

### Phase 9 — Complete Pipeline

One long video → multiple finished Shorts + metadata.

### Phase 10 — Publishing & Expansion

YouTube API, monitoring, scheduling and eventually additional platforms.

## First Major Goal

The first major milestone is simple:

**One long video → AI understands it → selects the best moments → creates several polished Shorts automatically.**

Everything else comes after that.
