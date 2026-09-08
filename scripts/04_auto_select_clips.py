#!/usr/bin/env python3
"""
Phase 3 - Automatic Clip Selector (Rule-based + Energy)
Analyzes transcript and automatically creates multiple vertical Shorts
from the most interesting moments.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict


def load_transcript(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def score_segment(segment: Dict) -> float:
    """Simple scoring based on energy indicators"""
    text = segment["text"].lower().strip()
    duration = segment["end"] - segment["start"]
    score = 0.0

    # High energy words / reactions
    energy_words = ["oh my gosh", "ready", "go", "no!", "wow", "what", "holy", 
                    "insane", "crazy", "wait", "look", "dude", "bro", "lol", "haha"]
    
    for word in energy_words:
        if word in text:
            score += 2.5

    # Short intense reactions are often good for Shorts
    if duration < 3.0 and ("!" in text or "?" in text):
        score += 1.5

    # Very short "No!" type reactions
    if text in ["no!", "no", "yes!", "what?", "wow!", "oh!"]:
        score += 2.0

    # Penalize very long segments
    if duration > 12:
        score -= 1.0

    return score


def find_best_moments(transcript: Dict, max_clips: int = 5, min_duration: float = 4.0, max_duration: float = 15.0) -> List[Dict]:
    segments = transcript["segments"]
    candidates = []

    # Score individual segments
    for i, seg in enumerate(segments):
        score = score_segment(seg)
        duration = seg["end"] - seg["start"]

        # Try to expand short segments into better clip lengths
        start = seg["start"]
        end = seg["end"]

        # Grow the clip a bit for better context
        if duration < min_duration:
            # Look ahead
            j = i
            while j + 1 < len(segments) and (segments[j+1]["end"] - start) <= max_duration:
                j += 1
                end = segments[j]["end"]
                score += score_segment(segments[j]) * 0.5

        final_duration = end - start
        if min_duration <= final_duration <= max_duration:
            candidates.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(final_duration, 2),
                "score": round(score, 2),
                "text": " ".join([s["text"] for s in segments[i:j+1] if i <= segments.index(s) <= j][:3])
            })

    # Sort by score and remove heavy overlaps
    candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)

    selected = []
    for cand in candidates:
        overlap = False
        for sel in selected:
            # Check overlap
            if not (cand["end"] <= sel["start"] or cand["start"] >= sel["end"]):
                overlap = True
                break
        if not overlap:
            selected.append(cand)
        if len(selected) >= max_clips:
            break

    return selected


def create_clip(ffmpeg: str, input_video: str, start: float, end: float, output_path: str):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    vf = "crop=ih*9/16:ih,scale=1080:1920"
    cmd = [
        ffmpeg, "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "medium",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Original long video")
    parser.add_argument("--transcript", default="output/transcript.json")
    parser.add_argument("--output-dir", default="output/auto_shorts")
    parser.add_argument("--max-clips", type=int, default=5)
    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"Video not found: {args.video}")
        sys.exit(1)
    if not Path(args.transcript).exists():
        print(f"Transcript not found: {args.transcript}")
        sys.exit(1)

    transcript = load_transcript(args.transcript)
    moments = find_best_moments(transcript, max_clips=args.max_clips)

    print(f"\nFound {len(moments)} interesting moments:\n")
    for i, m in enumerate(moments, 1):
        print(f"{i}. {m['start']}s → {m['end']}s  (score: {m['score']})  |  {m['text'][:60]}...")

    print("\nCreating vertical Shorts...\n")

    success = 0
    for i, m in enumerate(moments, 1):
        out_name = f"auto_short_{i:02d}.mp4"
        out_path = str(Path(args.output_dir) / out_name)
        print(f"Creating {out_name} ({m['start']}s → {m['end']}s)...")
        if create_clip("ffmpeg", args.video, m["start"], m["end"], out_path):
            print("  ✓ Success")
            success += 1
        else:
            print("  ✗ Failed")

    print(f"\nDone! {success} Shorts saved in: {args.output_dir}/")


if __name__ == "__main__":
    main()

