#!/usr/bin/env python3
"""
06_score_moments.py
--------------------
Local moment-scoring step for the Video-to-Shorts pipeline.

Reads the manifest.json produced by 05_extract_keyframes.py and turns the
flat list of scored keyframes into candidate EVENTS: merged time ranges
(start/end) with a peak score, ready to hand to the vision-description step
and, later, to transcript-based scoring.

This replaces the event-grouping logic that used to live inside
scripts/05_smart_video_analysis.py (legacy) -- but instead of recomputing
motion/scene/audio signals itself, it reuses the already-computed, already
-deduplicated frames and their source tags from the keyframe extractor.

Content-agnostic: scoring is based purely on which local signals fired
(motion / audio / scene / base), never on what the content "is".

Usage:
    python 06_score_moments.py --manifest output/keyframes/manifest.json \
        --out output/events
"""

import argparse
import json
from pathlib import Path


# --------------------------------------------------------------------------- #
# Signal weights -- how much each source contributes to a frame's score.
# A frame flagged by multiple signals is more likely to be a real moment.
# --------------------------------------------------------------------------- #

SOURCE_WEIGHTS = {
    "audio": 2.0,
    "scene": 2.0,
    "motion": 1.5,
    "base": 0.5,
}

# Bonus per additional corroborating signal beyond the first (rewards
# frames where multiple independent signals agree).
CORROBORATION_BONUS = 1.0


def score_frame(sources):
    sources = sorted(set(sources))
    base_score = sum(SOURCE_WEIGHTS.get(s, 0.5) for s in sources)
    bonus = CORROBORATION_BONUS * max(0, len(sources) - 1)
    return round(base_score + bonus, 3)


def group_into_events(frames, window_before, window_after, min_gap, duration):
    """
    Merge scored frames into events (time ranges), the same way nearby
    detections were merged in the legacy analyzer -- but operating on
    already-deduplicated keyframes instead of raw per-sample signals.
    """
    frames = sorted(frames, key=lambda f: f["timestamp"])
    events = []

    for f in frames:
        center = f["timestamp"]
        placed = False

        for event in events:
            if event["start"] - min_gap <= center <= event["end"] + min_gap:
                event["frames"].append(f)
                event["start"] = min(event["start"], max(0.0, center - window_before))
                event["end"] = min(duration, max(event["end"], center + window_after))
                if f["score"] > event["peak_score"]:
                    event["peak_score"] = f["score"]
                    event["peak_time"] = center
                placed = True
                break

        if not placed:
            events.append({
                "start": max(0.0, center - window_before),
                "end": min(duration, center + window_after),
                "peak_time": center,
                "peak_score": f["score"],
                "frames": [f],
            })

    events.sort(key=lambda e: e["start"])
    return events


def finalize_events(events):
    for i, e in enumerate(events, 1):
        frames = e["frames"]
        source_counts = {}
        for f in frames:
            for s in f["sources"]:
                source_counts[s] = source_counts.get(s, 0) + 1

        e["id"] = f"event_{i:03d}"
        e["duration"] = round(e["end"] - e["start"], 3)
        e["peak_score"] = round(e["peak_score"], 3)
        e["total_score"] = round(sum(f["score"] for f in frames), 3)
        e["frame_count"] = len(frames)
        e["source_counts"] = source_counts
        e["frames"] = [
            {"timestamp": f["timestamp"], "sources": f["sources"],
             "score": f["score"], "path": f["path"]}
            for f in frames
        ]
    return events


def main():
    parser = argparse.ArgumentParser(description="Score and group keyframes into candidate moments")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json from 05_extract_keyframes.py")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--window-before", type=float, default=2.0,
                         help="Seconds to pad before a peak when forming an event")
    parser.add_argument("--window-after", type=float, default=3.0,
                         help="Seconds to pad after a peak when forming an event")
    parser.add_argument("--min-gap", type=float, default=2.5,
                         help="Merge events whose padded ranges are within this many seconds of each other")
    parser.add_argument("--max-events", type=int, default=50,
                         help="Cap on number of events kept, ranked by peak score")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"ERROR: manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    duration = manifest.get("duration_sec", 0.0)
    raw_frames = manifest.get("frames", [])

    if not raw_frames:
        raise SystemExit("ERROR: manifest has no frames to score.")

    print(f"[1/3] Scoring {len(raw_frames)} keyframes ...")
    scored = []
    for f in raw_frames:
        scored.append({
            "timestamp": f["timestamp"],
            "sources": f["sources"],
            "path": f["path"],
            "score": score_frame(f["sources"]),
        })

    print(f"[2/3] Grouping into candidate events ...")
    events = group_into_events(
        scored, args.window_before, args.window_after, args.min_gap, duration
    )
    events = finalize_events(events)
    print(f"      {len(events)} raw events before capping")

    if len(events) > args.max_events:
        events.sort(key=lambda e: e["peak_score"], reverse=True)
        events = events[:args.max_events]
        events.sort(key=lambda e: e["start"])

    print(f"[3/3] Writing events.json ...")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "source_manifest": str(manifest_path),
        "video": manifest.get("video"),
        "duration_sec": duration,
        "settings": vars(args),
        "total_input_frames": len(raw_frames),
        "total_events": len(events),
        "events": events,
    }

    events_path = out_dir / "events.json"
    events_path.write_text(json.dumps(output, indent=2))

    print()
    print(f"Done. {len(events)} candidate events written.")
    print(f"Events: {events_path}")


if __name__ == "__main__":
    main() 
    