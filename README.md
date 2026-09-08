# Local AI Video-to-Shorts System

**Goal**: Turn one long video into multiple polished vertical Shorts (9:16) with captions, original AI commentary, effects, titles, descriptions and hashtags — completely local and free after the initial setup.

## Current Status (Phase 0 → Phase 1)

We are building this **incrementally**.  
Right now we only have the basic **FFmpeg video engine**.

### Hardware Reality (Your Machine)
- Windows 7 Ultimate SP1
- Intel i7-3632QM (2012)
- 8 GB RAM

Because of these limits:
- Full local LLM (Ollama) and modern Whisper are **not practical** on this PC.
- We develop and test almost everything **remotely** (this environment + GitHub).
- On your Windows 7 machine you only need **portable FFmpeg**.

## Project Structure

```
video-to-shorts/
├── README.md
├── .gitignore
├── config.example.yaml
├── scripts/
│   ├── 01_basic_clip.py          # Extract + convert one clip to vertical
│   ├── 01_basic_clip.bat         # Easy Windows launcher
│   └── utils/
├── input/                        # Put your long videos here
├── output/                       # Finished Shorts appear here
├── temp/                         # Temporary files (auto-cleaned later)
├── models/                       # Future: local models
└── docs/
```

## What You Need on Windows 7 (Minimal)

### 1. Portable FFmpeg (Required)

1. Go to: https://www.gyan.dev/ffmpeg/builds/
2. Download the **essentials** build (Windows 7 compatible).
3. Extract it to `C:\ffmpeg` (or any folder you like).
4. Test:
   ```bat
   C:\ffmpeg\bin\ffmpeg.exe -version
   ```

### 2. (Optional) Old Git for Windows
Only if you want `git` commands locally.  
Latest version that still supports Windows 7 is **2.46.2**.

You can also just download ZIP files from GitHub — no Git needed.

## How to Use the Current Phase 1 Script

### Easy way (Windows)

1. Put a long video in the `input` folder (example: `input/long_video.mp4`).
2. Edit `scripts/01_basic_clip.bat` and change the times if you want.
3. Double-click `scripts/01_basic_clip.bat`  
   or run it from Command Prompt.

### Advanced (Python – only if you have Python 3.8)

```bash
python scripts/01_basic_clip.py --input input/long_video.mp4 --start 00:04:30 --end 00:04:55 --output output/short_01.mp4
```

The script will:
- Cut the selected part
- Convert to 1080×1920 (9:16) with center crop
- Keep original audio
- Output a clean vertical MP4

## Development Workflow (Recommended)

1. All real development happens in this GitHub repository + remote environment.
2. You only download the latest code when you want to test on your machine.
3. Heavy AI steps (transcription, moment selection, commentary) will be designed so they can run:
   - Remotely / on free cloud (Colab, Codespaces)
   - Or later on a better computer

## Roadmap (from original brief)

- [x] Phase 0 – Environment understanding
- [ ] Phase 1 – Basic FFmpeg video engine   ← **we are here**
- [ ] Phase 2 – Transcription (standalone Faster-Whisper or remote)
- [ ] Phase 3 – Local / remote LLM clip selector
- [ ] Phase 4 – Automated clipping
- [ ] Phase 5 – Captions
- [ ] Phase 6 – AI Commentary + TTS
- [ ] Phase 7 – Full Short editor
- [ ] Phase 8 – Metadata (title / description / hashtags)
- [ ] Phase 9 – YouTube upload
- [ ] Phase 10 – Full content factory

## Next Steps

After you confirm FFmpeg works on your machine, we will:
1. Improve the vertical conversion (better smart crop later)
2. Add batch processing
3. Start the transcription stage

---

**Created for the Local AI Automated Video-to-Shorts project**  
Keep it simple. Keep it local where possible. Keep it free.