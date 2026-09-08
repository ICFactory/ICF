#!/usr/bin/env python3
"""
Phase 2 - Transcription
Transcribes a video using faster-whisper and saves timestamped transcript.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from faster_whisper import WhisperModel


def extract_audio(video_path: str, audio_path: str):
    """Extract audio from video using FFmpeg"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path
    ]
    print("Extracting audio...")
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        print("Failed to extract audio")
        sys.exit(1)
    print("Audio extracted.")


def transcribe(audio_path: str, model_size: str = "base"):
    """Transcribe audio with faster-whisper"""
    print(f"Loading Whisper model ({model_size})...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print("Transcribing... (this can take a few minutes)")
    segments, info = model.transcribe(audio_path, beam_size=5)

    print(f"Detected language: {info.language} (probability {info.language_probability:.2f})")

    result = {
        "language": info.language,
        "segments": []
    }

    for segment in segments:
        result["segments"].append({
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip()
        })
        print(f"[{segment.start:.2f}s → {segment.end:.2f}s] {segment.text.strip()}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Transcribe video to timestamped JSON")
    parser.add_argument("--input", "-i", required=True, help="Input video file")
    parser.add_argument("--output", "-o", default="output/transcript.json", help="Output JSON path")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium"], help="Whisper model size")
    args = parser.parse_args()

    video_path = Path(args.input)
    if not video_path.exists():
        print(f"ERROR: {video_path} not found")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Temporary audio file
    audio_path = Path("temp") / "audio.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract audio
    extract_audio(str(video_path), str(audio_path))

    # Step 2: Transcribe
    transcript = transcribe(str(audio_path), model_size=args.model)

    # Step 3: Save JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Transcript saved to: {output_path}")
    print(f"Total segments: {len(transcript['segments'])}")


if __name__ == "__main__":
    main()
