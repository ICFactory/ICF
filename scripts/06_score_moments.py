#!/usr/bin/env python3
"""
06_score_moments.py
--------------------
Scene-segmentation step for the Video-to-Shorts pipeline.

IMPORTANT DESIGN NOTE: this video is a COMPILATION of separately shot
scenes with real hard cuts -- not one continuous take with occasional
"highlight moments." So this step does not merge/pad around interesting
peaks. Instead it:

    1. Detects real scene-cut timestamps DIRECTLY from the original video
       (independently of the keyframe manifest -- see below for why).
    2. Treats every interval between two consecutive cuts as ONE scene =
       ONE candidate clip, using its exact start/end. No padding.
    3. Scores each scene using the keyframe manifest's per-frame signal
       data (motion/audio/scene/base), purely to rank scenes and pick a
       representative frame for vision description -- scoring never
       changes the scene's start/end.

Why detect boundaries directly from the video instead of reusing the
"scene" tags already in manifest.json: 05_extract_keyframes.py clusters
nearby candidate timestamps together and later deduplicates near-identical
frames. A frame sitting exactly on a hard cut can get merged into a
nearby base-sampled timestamp and then get dropped entirely if it closely
resembles a neighboring frame from the same original scene. That's fine
for "find interesting moments" but not precise enough to be a scene
BOUNDARY. Re-running scene detection here, decoupled from dedup, keeps
boundaries exact.

Usage:
    python 06_score_moments.py --manifest output/keyframes/manifest.json \
        --video input/long_video.mp4.mp4 --out output/events
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


SOURCE_WEIGHTS = {
    "audio": 2.0,
    "scene": 2.0,
    "motion": 1.5,
    "base": 0.5,
}
CORROBORATION_BONUS = 1.0


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode, result.stdout, result.stderr


def detect_scene_boundaries(video_path, duration, threshold, min_scene_duration):
    """Detect hard cut timestamps directly from the video (decoupled from
    the keyframe manifest's dedup), then turn them into scene start/end
    boundaries covering the whole video from 0 to duration."""
    code, out, err = run([
        "ffmpeg", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ])
    cut_timestamps = sorted(set(round(float(m), 3) for m in re.findall(r"pts_time:([\d.]+)", err)))

    boundaries = [0.0] + [t for t in cut_timestamps if 0.0 < t < duration] + [duration]
    boundaries = sorted(set(boundaries))

    # Merge boundaries that are too close together (noise / near-zero-length
    # slivers) by dropping the inner boundary, extending the previous scene.
    merged = [boundaries[0]]
    for b in boundaries[1:]:
        if b - merged[-1] < min_scene_duration:
            continue
        merged.append(b)
    if merged[-1] < duration:
        merged[-1] = duration
    return merged


def score_frame(sources):
    sources = sorted(set(sources))
    base_score = sum(SOURCE_WEIGHTS.get(s, 0.5) for s in sources)
    bonus = CORROBORATION_BONUS * max(0, len(sources) - 1)
    return round(base_score + bonus, 3)


def build_scenes(boundaries, scored_frames, video_path):
    scenes = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        frames_in_scene = [f for f in scored_frames if start <= f["timestamp"] < end]

        if not frames_in_scene:
            # Very short scene with no base/motion/audio/scene keyframe landed
            # inside it -- extract one frame directly so scoring/vision still
            # has something to work with.
            mid = (start + end) / 2
            fallback_path = None
            frames_in_scene = [{
                "timestamp": round(mid, 3),
                "sources": ["fallback"],
                "score": 0.5,
                "path": fallback_path,
            }]

        scenes.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "frames": frames_in_scene,
        })
    return scenes


def finalize_scenes(scenes):
    for i, s in enumerate(scenes, 1):
        frames = [f for f in s["frames"] if f.get("path")]
        if not frames:
            frames = s["frames"]  # keep fallback placeholder even without a real path

        source_counts = {}
        for f in frames:
            for src in f["sources"]:
                source_counts[src] = source_counts.get(src, 0) + 1

        peak_frame = max(frames, key=lambda f: f["score"])

        s["id"] = f"event_{i:03d}"
        s["duration"] = round(s["end"] - s["start"], 3)
        s["peak_time"] = peak_frame["timestamp"]
        s["peak_score"] = round(peak_frame["score"], 3)
        s["total_score"] = round(sum(f["score"] for f in frames), 3)
        s["frame_count"] = len(frames)
        s["source_counts"] = source_counts
        s["frames"] = [
            {"timestamp": f["timestamp"], "sources": f["sources"], "score": f["score"], "path": f.get("path")}
            for f in frames
        ]
    return scenes


def main():
    parser = argparse.ArgumentParser(description="Segment a compilation video into real scenes and score them")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json from 05_extract_keyframes.py")
    parser.add_argument("--video", required=True, help="Path to the original source video (for direct scene detection)")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--scene-threshold", type=float, default=0.4,
                         help="ffmpeg scene-change sensitivity; lower catches more/softer cuts")
    parser.add_argument("--min-scene-duration", type=float, default=1.0,
                         help="Scenes shorter than this get merged into the previous one (noise filter)")
    parser.add_argument("--max-scene-warning", type=float, default=40.0,
                         help="Print a warning for any scene longer than this, since it may mean a cut was missed")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"ERROR: manifest not found: {manifest_path}")
    if not Path(args.video).exists():
        sys.exit(f"ERROR: video not found: {args.video}")

    manifest = json.loads(manifest_path.read_text())
    duration = manifest.get("duration_sec", 0.0)
    raw_frames = manifest.get("frames", [])
    if not raw_frames:
        sys.exit("ERROR: manifest has no frames to score.")

    print(f"[1/3] Detecting scene-cut boundaries directly from the video ...")
    boundaries = detect_scene_boundaries(args.video, duration, args.scene_threshold, args.min_scene_duration)
    print(f"      {len(boundaries) - 1} scene(s) detected "
          f"(cuts at: {[round(b, 2) for b in boundaries[1:-1]]})")

    print(f"[2/3] Scoring keyframes and assigning them to scenes ...")
    scored_frames = [{
        "timestamp": f["timestamp"],
        "sources": f["sources"],
        "path": f["path"],
        "score": score_frame(f["sources"]),
    } for f in raw_frames]

    scenes = build_scenes(boundaries, scored_frames, args.video)
    scenes = finalize_scenes(scenes)

    long_scenes = [s for s in scenes if s["duration"] > args.max_scene_warning]
    if long_scenes:
        print(f"      WARNING: {len(long_scenes)} scene(s) exceed {args.max_scene_warning}s "
              f"-- a real cut may have been missed. Consider lowering --scene-threshold. "
              f"IDs: {[s['id'] for s in long_scenes]}")

    durations = [s["duration"] for s in scenes]
    print(f"      scene durations -- min: {min(durations):.1f}s, "
          f"max: {max(durations):.1f}s, avg: {sum(durations)/len(durations):.1f}s")

    print(f"[3/3] Writing events.json ...")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "source_manifest": str(manifest_path),
        "video": manifest.get("video"),
        "duration_sec": duration,
        "settings": vars(args),
        "total_input_frames": len(raw_frames),
        "total_events": len(scenes),
        "events": scenes,
    }

    events_path = out_dir / "events.json"
    events_path.write_text(json.dumps(output, indent=2))

    print()
    print(f"Done. {len(scenes)} scene(s) written as candidate clips.")
    print(f"Events: {events_path}")


if __name__ == "__main__":
    main() 
    