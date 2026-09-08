#!/usr/bin/env python3
"""
Phase 1 - Multi Clip Generator
------------------------------
Create several vertical Shorts from one long video using a simple list of timestamps.
"""

import argparse
import subprocess
import sys
from pathlib import Path


# ============================================================
#  EDIT THIS LIST – add as many clips as you want
#  Format: (start, end, output_name)
# ============================================================
CLIPS = [
    ("00:00:05", "00:00:11", "short_01.mp4"),
    # ("00:00:25.500", "00:00:38", "short_02.mp4"),
    # ("00:01:10", "00:01:28.200", "short_03.mp4"),
]
# ============================================================


def find_ffmpeg() -> str:
    for cand in ["ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
        try:
            subprocess.run([cand, "-version"], capture_output=True, check=True)
            return cand
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print("ERROR: ffmpeg not found")
    sys.exit(1)


def create_clip(ffmpeg: str, input_path: str, start: str, end: str, output_path: str):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    vf = "crop=ih*9/16:ih,scale=1080:1920"

    cmd = [
        ffmpeg, "-y",
        "-ss", start,
        "-to", end,
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "medium",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    print(f"\n→ {start} to {end}  =>  {output_path}")
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        print("  ✓ Success")
    else:
        print("  ✗ Failed")
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True, help="Long video path")
    parser.add_argument("--output-dir", default="output", help="Folder for Shorts")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"ERROR: {args.input} not found")
        sys.exit(1)

    ffmpeg = find_ffmpeg()
    print(f"Input video : {args.input}")
    print(f"Creating {len(CLIPS)} Shorts...\n")

    success = 0
    for start, end, name in CLIPS:
        out = str(Path(args.output_dir) / name)
        if create_clip(ffmpeg, args.input, start, end, out):
            success += 1

    print(f"\nFinished: {success}/{len(CLIPS)} Shorts created in '{args.output_dir}/'")


if __name__ == "__main__":
    main()
