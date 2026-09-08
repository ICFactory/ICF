#!/usr/bin/env python3

"""
ICF - Smart Local Video Analysis

Purpose:
    Analyze a long video locally before sending anything to Vision AI.

The analyzer looks for:
    - scene changes
    - visual motion
    - frame-to-frame visual differences
    - audio energy
    - representative frames
    - near-duplicate frames

It does NOT attempt to decide whether something is funny.
That is the job of the later multimodal Vision + reasoning stage.

Output:
    output/analysis/
        analysis.json
        frames/
            ...
"""

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

BASE_SAMPLE_SECONDS = 1.5

# Frames around strong local events
EVENT_WINDOW_BEFORE = 2.0
EVENT_WINDOW_AFTER = 3.0

# Minimum distance between independent events
MIN_EVENT_GAP = 2.5

# Visual thresholds
MOTION_THRESHOLD = 0.08
SCENE_CHANGE_THRESHOLD = 0.35

# Audio threshold
AUDIO_SPIKE_MULTIPLIER = 2.0

# Number of representative frames per event
MAX_FRAMES_PER_EVENT = 8


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def run_command(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed:\n{' '.join(cmd)}\n\n{result.stderr}"
        )

    return result.stdout


def get_video_info(video):
    output = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video
    ])

    duration = float(output.strip())

    return {
        "duration": duration
    }


def frame_difference(a, b):
    """
    Compare two grayscale frames.

    Returns a normalized 0-1 difference score.
    """

    a = cv2.resize(a, (320, 180))
    b = cv2.resize(b, (320, 180))

    diff = cv2.absdiff(a, b)

    return float(np.mean(diff) / 255.0)


def calculate_motion(prev_gray, gray):
    """
    Estimate motion using frame difference.
    """

    return frame_difference(prev_gray, gray)


def calculate_scene_change(prev_gray, gray):
    """
    Strong frame difference is treated as a possible scene change.
    """

    return frame_difference(prev_gray, gray)


def extract_frame(cap, timestamp):
    """
    Seek to a timestamp and return a frame.
    """

    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)

    ok, frame = cap.read()

    if not ok:
        return None

    return frame


def save_frame(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)

    # JPEG keeps the candidate set relatively small.
    cv2.imwrite(
        str(path),
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, 85]
    )


# ------------------------------------------------------------
# Audio analysis
# ------------------------------------------------------------

def analyze_audio(video, duration, bucket=0.5):
    """
    Generate local audio RMS measurements using FFmpeg.

    This does not send audio anywhere.
    """

    print("Analyzing audio energy...")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", video,
        "-vn",
        "-af",
        "astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f", "null",
        "-"
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    values = []

    # astats metadata is normally emitted to stderr.
    for line in result.stderr.splitlines():
        if "lavfi.astats.Overall.RMS_level" in line:
            try:
                value = float(line.split("=")[-1])
                if math.isfinite(value):
                    values.append(value)
            except ValueError:
                pass

    if not values:
        return []

    median = float(np.median(values))

    spikes = []

    for i, value in enumerate(values):
        if value > median * AUDIO_SPIKE_MULTIPLIER:
            timestamp = i * bucket

            if timestamp < duration:
                spikes.append({
                    "time": round(timestamp, 3),
                    "rms": round(value, 3)
                })

    return spikes


# ------------------------------------------------------------
# Video analysis
# ------------------------------------------------------------

def analyze_video(video, duration):

    print("Analyzing video locally...")
    print(f"Duration: {duration:.2f}s")
    print(
        f"Base sampling: every {BASE_SAMPLE_SECONDS:.2f}s"
    )

    cap = cv2.VideoCapture(video)

    if not cap.isOpened():
        raise RuntimeError("Could not open video.")

    fps = cap.get(cv2.CAP_PROP_FPS)

    if not fps or fps <= 0:
        fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Resolution: {width}x{height}")
    print(f"FPS: {fps:.2f}")

    samples = []

    previous_gray = None

    timestamp = 0.0

    while timestamp < duration:

        frame = extract_frame(cap, timestamp)

        if frame is None:
            timestamp += BASE_SAMPLE_SECONDS
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        motion = 0.0
        scene_change = 0.0

        if previous_gray is not None:

            motion = calculate_motion(
                previous_gray,
                gray
            )

            scene_change = calculate_scene_change(
                previous_gray,
                gray
            )

        samples.append({
            "time": round(timestamp, 3),
            "motion": round(motion, 5),
            "scene_change": round(scene_change, 5)
        })

        previous_gray = gray

        timestamp += BASE_SAMPLE_SECONDS

    cap.release()

    return {
        "fps": fps,
        "width": width,
        "height": height,
        "samples": samples
    }


# ------------------------------------------------------------
# Candidate event detection
# ------------------------------------------------------------

def detect_events(video_data, audio_spikes, duration):

    samples = video_data["samples"]

    if not samples:
        return []

    motion_values = [
        x["motion"]
        for x in samples
    ]

    scene_values = [
        x["scene_change"]
        for x in samples
    ]

    motion_median = float(
        np.median(motion_values)
    )

    scene_median = float(
        np.median(scene_values)
    )

    candidates = []

    for sample in samples:

        motion = sample["motion"]
        scene = sample["scene_change"]

        motion_score = (
            motion / max(motion_median, 0.001)
        )

        scene_score = (
            scene / max(scene_median, 0.001)
        )

        score = 0.0

        if motion > MOTION_THRESHOLD:
            score += min(motion_score, 5.0)

        if scene > SCENE_CHANGE_THRESHOLD:
            score += min(scene_score, 5.0)

        candidates.append({
            "time": sample["time"],
            "motion": motion,
            "scene_change": scene,
            "local_score": round(score, 3)
        })

    # Add audio spikes as another independent signal.
    for spike in audio_spikes:

        nearest = min(
            candidates,
            key=lambda x:
                abs(x["time"] - spike["time"])
        )

        nearest["audio_spike"] = True
        nearest["audio_rms"] = spike["rms"]
        nearest["local_score"] += 2.0

    # Keep only meaningful candidates.
    candidates = [
        x for x in candidates
        if x["local_score"] > 0
    ]

    # Highest local signal first.
    candidates.sort(
        key=lambda x: x["local_score"],
        reverse=True
    )

    # Merge nearby detections into events.
    events = []

    for candidate in candidates:

        center = candidate["time"]

        overlapping = None

        for event in events:

            if (
                center >= event["start"] - MIN_EVENT_GAP
                and
                center <= event["end"] + MIN_EVENT_GAP
            ):
                overlapping = event
                break

        if overlapping:

            overlapping["signals"].append(candidate)

            overlapping["start"] = min(
                overlapping["start"],
                max(0.0, center - EVENT_WINDOW_BEFORE)
            )

            overlapping["end"] = max(
                overlapping["end"],
                min(duration, center + EVENT_WINDOW_AFTER)
            )

            overlapping["peak_score"] = max(
                overlapping["peak_score"],
                candidate["local_score"]
            )

        else:

            events.append({
                "start": max(
                    0.0,
                    center - EVENT_WINDOW_BEFORE
                ),
                "end": min(
                    duration,
                    center + EVENT_WINDOW_AFTER
                ),
                "peak_time": center,
                "peak_score": candidate["local_score"],
                "signals": [candidate]
            })

    # Sort chronologically.
    events.sort(
        key=lambda x: x["start"]
    )

    # Assign IDs and useful summaries.
    for index, event in enumerate(events, 1):

        signals = event["signals"]

        event["id"] = f"event_{index:03d}"

        event["duration"] = round(
            event["end"] - event["start"],
            3
        )

        event["peak_score"] = round(
            event["peak_score"],
            3
        )

        event["signal_count"] = len(signals)

        event["has_audio_spike"] = any(
            s.get("audio_spike", False)
            for s in signals
        )

        event["max_motion"] = round(
            max(s["motion"] for s in signals),
            5
        )

        event["max_scene_change"] = round(
            max(s["scene_change"] for s in signals),
            5
        )

    return events


# ------------------------------------------------------------
# Representative frames
# ------------------------------------------------------------

def select_representative_times(event):

    start = event["start"]
    end = event["end"]

    duration = end - start

    count = min(
        MAX_FRAMES_PER_EVENT,
        max(3, int(duration / 1.0) + 1)
    )

    if count <= 1:
        return [event["peak_time"]]

    times = np.linspace(
        start,
        end,
        count
    )

    # Always include the local peak.
    times = list(times)
    times.append(event["peak_time"])

    times = sorted(set(
        round(float(x), 3)
        for x in times
    ))

    return times


def extract_event_frames(video, events, output_dir):

    frames_dir = output_dir / "frames"

    if frames_dir.exists():
        shutil.rmtree(frames_dir)

    frames_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    cap = cv2.VideoCapture(video)

    if not cap.isOpened():
        raise RuntimeError("Could not open video.")

    total_frames = 0

    for event in events:

        event_dir = frames_dir / event["id"]
        event_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        frame_records = []

        times = select_representative_times(event)

        for index, timestamp in enumerate(times):

            frame = extract_frame(
                cap,
                timestamp
            )

            if frame is None:
                continue

            filename = (
                f"{event['id']}_"
                f"{index:02d}_"
                f"{timestamp:.3f}.jpg"
            )

            path = event_dir / filename

            save_frame(frame, path)

            frame_records.append({
                "time": timestamp,
                "file": str(path)
            })

            total_frames += 1

        event["frames"] = frame_records

    cap.release()

    return total_frames


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="ICF smart local video analyzer"
    )

    parser.add_argument(
        "--input",
        "-i",
        required=True
    )

    parser.add_argument(
        "--output",
        "-o",
        default="output/analysis"
    )

    args = parser.parse_args()

    video = Path(args.input)

    if not video.exists():
        raise SystemExit(
            f"Video not found: {video}"
        )

    output_dir = Path(args.output)
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    print()
    print("=" * 60)
    print("ICF SMART VIDEO ANALYZER")
    print("=" * 60)
    print()

    info = get_video_info(
        str(video)
    )

    duration = info["duration"]

    video_data = analyze_video(
        str(video),
        duration
    )

    audio_spikes = analyze_audio(
        str(video),
        duration
    )

    events = detect_events(
        video_data,
        audio_spikes,
        duration
    )

    # Avoid an enormous candidate set.
    # The Vision stage will receive only the strongest local events.
    events.sort(
        key=lambda x: x["peak_score"],
        reverse=True
    )

    events = events[:50]

    # Return events to chronological order.
    events.sort(
        key=lambda x: x["start"]
    )

    frame_count = extract_event_frames(
        str(video),
        events,
        output_dir
    )

    analysis = {
        "video": {
            "path": str(video),
            "duration": round(duration, 3),
            "width": video_data["width"],
            "height": video_data["height"],
            "fps": round(video_data["fps"], 3)
        },

        "sampling": {
            "base_interval_seconds":
                BASE_SAMPLE_SECONDS,
            "method":
                "motion + scene change + audio energy + event grouping + representative frames"
        },

        "statistics": {
            "base_samples":
                len(video_data["samples"]),
            "audio_spikes":
                len(audio_spikes),
            "candidate_events":
                len(events),
            "representative_frames":
                frame_count
        },

        "events": events
    }

    analysis_path = (
        output_dir / "analysis.json"
    )

    with open(
        analysis_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            analysis,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(
        f"Base samples       : "
        f"{len(video_data['samples'])}"
    )
    print(
        f"Audio spikes       : "
        f"{len(audio_spikes)}"
    )
    print(
        f"Candidate events   : "
        f"{len(events)}"
    )
    print(
        f"Representative JPG : "
        f"{frame_count}"
    )
    print()
    print(
        f"Analysis JSON      : "
        f"{analysis_path}"
    )
    print(
        f"Frames             : "
        f"{output_dir / 'frames'}"
    )
    print()


if __name__ == "__main__":
    main()
