#!/usr/bin/env python3
"""
Phase 1 - Basic Clip Extractor + Vertical Converter
--------------------------------------------------
Takes a long video, extracts a time range, converts it to 9:16 (1080x1920)
with center crop, and saves a clean Short-ready MP4.

Works with pure FFmpeg. No AI yet.
Compatible with Python 3.8+ (and the old Windows 7 machine if needed).
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


def find_ffmpeg(ffmpeg_path: str = "") -> str:
    """Return the ffmpeg executable path."""
    if ffmpeg_path and Path(ffmpeg_path).exists():
        return ffmpeg_path

    # Try common locations
    candidates = [
        "ffmpeg",
        "ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for cand in candidates:
        try:
            subprocess.run([cand, "-version"], capture_output=True, check=True)
            return cand
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    print("ERROR: ffmpeg not found.")
    print("Please install portable FFmpeg and either:")
    print("  1. Add it to PATH, or")
    print("  2. Pass --ffmpeg C:/path/to/ffmpeg.exe")
    sys.exit(1)


def run_ffmpeg(cmd: list) -> None:
    """Run an FFmpeg command and stream output."""
    print("\nRunning FFmpeg command:")
    print(" ".join(cmd))
    print("-" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nFFmpeg failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    print("-" * 60)
    print("Done.")


def create_vertical_clip(
    input_path: str,
    output_path: str,
    start: str,
    end: str,
    ffmpeg_exe: str,
    width: int = 1080,
    height: int = 1920,
    crf: int = 20,
    preset: str = "medium",
):
    """
    Extract a segment and convert it to vertical 9:16 with center crop.
    Simple & reliable version (Phase 1).
    """
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Center crop to 9:16 then scale to exact 1080x1920
    # This is the classic reliable method.
    vf = (
        f"crop=ih*9/16:ih,"          # crop width to match 9:16 based on height
        f"scale={width}:{height}"    # final resolution
    )

    cmd = [
        ffmpeg_exe,
        "-y",                       # overwrite
        "-ss", start,               # start time (fast seek)
        "-to", end,                 # end time
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",  # better for web/Shorts
        output_path,
    ]

    run_ffmpeg(cmd)
    print(f"\n✓ Vertical clip saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1: Extract a clip and convert it to vertical Short (9:16)"
    )
    parser.add_argument("--input", "-i", required=True, help="Path to long video")
    parser.add_argument("--output", "-o", required=True, help="Output Short path (e.g. output/short_01.mp4)")
    parser.add_argument("--start", "-s", required=True, help="Start time (HH:MM:SS or MM:SS or seconds)")
    parser.add_argument("--end", "-e", required=True, help="End time (HH:MM:SS or MM:SS or seconds)")
    parser.add_argument("--ffmpeg", default="", help="Full path to ffmpeg.exe (optional)")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--crf", type=int, default=20, help="Quality (18-23 is good, lower = better)")
    parser.add_argument("--preset", default="medium", help="FFmpeg preset (ultrafast → veryslow)")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    ffmpeg_exe = find_ffmpeg(args.ffmpeg)

    create_vertical_clip(
        input_path=args.input,
        output_path=args.output,
        start=args.start,
        end=args.end,
        ffmpeg_exe=ffmpeg_exe,
        width=args.width,
        height=args.height,
        crf=args.crf,
        preset=args.preset,
    )


if __name__ == "__main__":
    main()