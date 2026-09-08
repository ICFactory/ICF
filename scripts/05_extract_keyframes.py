#!/usr/bin/env python3
"""
05_extract_keyframes.py
------------------------
Smart, local, content-agnostic keyframe extractor for the Video-to-Shorts pipeline.

Combines four local, free signals to decide WHICH moments in a long video are
worth sending to a vision model later:

    1. Base sampling      - fixed interval, guarantees no long gap is missed
    2. Motion spikes      - frame-differencing (OpenCV), catches sudden action
    3. Audio energy spikes- RMS loudness peaks (screams, laughs, impacts)
    4. Scene changes      - ffmpeg's built-in scene-detection filter

Then it:
    - merges/deduplicates candidate timestamps that are too close together
    - extracts one JPEG per surviving timestamp via ffmpeg
    - removes visually near-duplicate frames using a cheap perceptual hash
    - writes a manifest.json describing every kept frame and why it was picked

No cloud calls happen in this script. It only prepares the candidate frames
that a later stage may send to a vision model.

Usage:
    python 05_extract_keyframes.py --video input.mp4 --out output/keyframes

Dependencies: ffmpeg + ffprobe on PATH, opencv-python, numpy, scipy, pillow.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import cv2
from PIL import Image
from scipy.io import wavfile


# --------------------------------------------------------------------------- #
# Helpers: shell / ffprobe
# --------------------------------------------------------------------------- #

def run(cmd, capture=True):
    """Run a subprocess command, return (stdout, stderr) as text."""
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    return result.stdout or "", result.stderr or ""


def get_duration(video_path: str) -> float:
    out, _ = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ])
    try:
        return float(out.strip())
    except ValueError:
        raise RuntimeError(f"Could not read duration for {video_path}")


# --------------------------------------------------------------------------- #
# Signal 1: base sampling
# --------------------------------------------------------------------------- #

def base_sampling(duration: float, interval: float):
    """Fixed-interval timestamps so no stretch of video is ever skipped."""
    ts = np.arange(0, duration, interval)
    return [(float(t), "base") for t in ts]


# --------------------------------------------------------------------------- #
# Signal 2: motion spikes (OpenCV, downsampled + frame-skipped for speed)
# --------------------------------------------------------------------------- #

def motion_spikes(video_path: str, analysis_fps: float = 5.0,
                   z_thresh: float = 2.0, min_gap: float = 1.0,
                   resize_width: int = 160):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_skip = max(1, round(native_fps / analysis_fps))

    prev_gray = None
    diffs = []          # (timestamp, diff_score)
    frame_idx = 0

    while True:
        if frame_idx % frame_skip != 0:
            # cheap: grab without decoding
            if not cap.grab():
                break
            frame_idx += 1
            continue

        ok, frame = cap.read()
        if not ok:
            break

        h, w = frame.shape[:2]
        scale = resize_width / w
        small = cv2.resize(frame, (resize_width, max(1, int(h * scale))))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if prev_gray is not None:
            diff = float(np.mean(cv2.absdiff(gray, prev_gray)))
            timestamp = frame_idx / native_fps
            diffs.append((timestamp, diff))

        prev_gray = gray
        frame_idx += 1

    cap.release()

    if len(diffs) < 5:
        return []

    scores = np.array([d for _, d in diffs])
    mean, std = float(scores.mean()), float(scores.std() or 1e-6)
    threshold = mean + z_thresh * std

    spikes = []
    last_kept = -min_gap
    for ts, score in diffs:
        if score > threshold and (ts - last_kept) >= min_gap:
            spikes.append((ts, "motion"))
            last_kept = ts
    return spikes


# --------------------------------------------------------------------------- #
# Signal 3: audio energy spikes (RMS loudness)
# --------------------------------------------------------------------------- #

def audio_energy_spikes(video_path: str, work_dir: Path,
                         window: float = 0.5, z_thresh: float = 2.0,
                         min_gap: float = 1.0):
    wav_path = work_dir / "_audio_tmp.wav"
    run([
        "ffmpeg", "-y", "-i", video_path, "-vn",
        "-ac", "1", "-ar", "16000", "-f", "wav", str(wav_path),
    ])
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        return []  # e.g. video has no audio track

    sr, data = wavfile.read(str(wav_path))
    wav_path.unlink(missing_ok=True)

    data = data.astype(np.float32)
    win_samples = max(1, int(window * sr))
    n_windows = len(data) // win_samples
    if n_windows < 5:
        return []

    rms = np.array([
        np.sqrt(np.mean(data[i * win_samples:(i + 1) * win_samples] ** 2) + 1e-9)
        for i in range(n_windows)
    ])
    mean, std = float(rms.mean()), float(rms.std() or 1e-6)
    threshold = mean + z_thresh * std

    spikes = []
    last_kept = -min_gap
    for i, val in enumerate(rms):
        ts = i * window
        if val > threshold and (ts - last_kept) >= min_gap:
            spikes.append((float(ts), "audio"))
            last_kept = ts
    return spikes


# --------------------------------------------------------------------------- #
# Signal 4: scene changes (ffmpeg native filter)
# --------------------------------------------------------------------------- #

def scene_changes(video_path: str, threshold: float = 0.4):
    _, err = run([
        "ffmpeg", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ])
    timestamps = [float(m) for m in re.findall(r"pts_time:([\d.]+)", err)]
    return [(t, "scene") for t in timestamps]


# --------------------------------------------------------------------------- #
# Merge candidates from all signals
# --------------------------------------------------------------------------- #

def merge_candidates(all_candidates, min_gap: float, max_frames: int):
    """
    Sort all (timestamp, source) pairs, cluster anything within min_gap into
    a single candidate carrying the union of source tags, then cap the total
    count (prioritizing frames flagged by more than one signal).
    """
    all_candidates.sort(key=lambda x: x[0])

    clustered = []
    for ts, source in all_candidates:
        if clustered and (ts - clustered[-1]["timestamp"]) < min_gap:
            clustered[-1]["sources"].add(source)
        else:
            clustered.append({"timestamp": ts, "sources": {source}})

    if len(clustered) > max_frames:
        # Keep multi-signal frames first, then fill remaining slots by
        # spreading evenly through the rest so no region is fully skipped.
        multi = [c for c in clustered if len(c["sources"]) > 1]
        single = [c for c in clustered if len(c["sources"]) == 1]
        remaining_slots = max_frames - len(multi)
        if remaining_slots > 0 and single:
            step = max(1, len(single) // remaining_slots)
            single = single[::step][:remaining_slots]
        else:
            single = []
        clustered = sorted(multi + single, key=lambda c: c["timestamp"])

    return clustered


# --------------------------------------------------------------------------- #
# Frame extraction (fast + reasonably accurate two-step ffmpeg seek)
# --------------------------------------------------------------------------- #

def extract_frame(video_path: str, timestamp: float, out_path: Path):
    coarse = max(0.0, timestamp - 1.0)
    fine = timestamp - coarse
    run([
        "ffmpeg", "-y",
        "-ss", f"{coarse:.3f}", "-i", video_path,
        "-ss", f"{fine:.3f}",
        "-frames:v", "1", "-q:v", "2",
        str(out_path),
    ])


# --------------------------------------------------------------------------- #
# Deduplication via cheap average-hash (no extra dependency needed)
# --------------------------------------------------------------------------- #

def average_hash(image_path: Path, hash_size: int = 8) -> np.ndarray:
    img = Image.open(image_path).convert("L").resize(
        (hash_size, hash_size), Image.LANCZOS
    )
    arr = np.asarray(img, dtype=np.float32)
    return (arr > arr.mean()).flatten()


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def deduplicate(frames, hash_threshold: int = 4):
    """frames: list of dicts sorted by timestamp, each with a 'path' key."""
    kept = []
    prev_hash = None
    for f in frames:
        h = average_hash(Path(f["path"]))
        if prev_hash is not None and hamming(h, prev_hash) <= hash_threshold:
            f["dropped_as_duplicate"] = True
            continue
        f["dropped_as_duplicate"] = False
        prev_hash = h
        kept.append(f)
    return kept


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Smart local keyframe extractor")
    parser.add_argument("--video", required=True, help="Path to input video")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--base-interval", type=float, default=1.3)
    parser.add_argument("--scene-threshold", type=float, default=0.4)
    parser.add_argument("--motion-fps", type=float, default=5.0)
    parser.add_argument("--motion-zscore", type=float, default=2.0)
    parser.add_argument("--audio-window", type=float, default=0.5)
    parser.add_argument("--audio-zscore", type=float, default=2.0)
    parser.add_argument("--min-gap", type=float, default=0.6,
                         help="Minimum seconds between kept candidate timestamps")
    parser.add_argument("--hash-threshold", type=int, default=4,
                         help="Max hamming distance to treat frames as duplicates (0-64)")
    parser.add_argument("--max-frames", type=int, default=500,
                         help="Hard cap on candidate frames before extraction")
    args = parser.parse_args()

    video_path = args.video
    out_dir = Path(args.out)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    if not Path(video_path).exists():
        print(f"ERROR: video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/6] Reading video info ...")
    duration = get_duration(video_path)
    print(f"      duration = {duration:.1f}s")

    print(f"[2/6] Base sampling every {args.base_interval}s ...")
    candidates = base_sampling(duration, args.base_interval)

    print(f"[3/6] Detecting motion spikes ...")
    candidates += motion_spikes(
        video_path, analysis_fps=args.motion_fps,
        z_thresh=args.motion_zscore, min_gap=args.min_gap,
    )

    print(f"[4/6] Detecting audio energy spikes ...")
    candidates += audio_energy_spikes(
        video_path, out_dir, window=args.audio_window,
        z_thresh=args.audio_zscore, min_gap=args.min_gap,
    )

    print(f"[5/6] Detecting scene changes ...")
    candidates += scene_changes(video_path, threshold=args.scene_threshold)

    print(f"      total raw candidates: {len(candidates)}")
    clustered = merge_candidates(candidates, args.min_gap, args.max_frames)
    print(f"      merged/capped candidates: {len(clustered)}")

    print(f"[6/6] Extracting frames + removing near-duplicates ...")
    frames = []
    for i, c in enumerate(clustered):
        fname = f"frame_{i:05d}_{c['timestamp']:.2f}s.jpg"
        fpath = frames_dir / fname
        extract_frame(video_path, c["timestamp"], fpath)
        if fpath.exists() and fpath.stat().st_size > 0:
            frames.append({
                "timestamp": round(c["timestamp"], 3),
                "sources": sorted(c["sources"]),
                "path": str(fpath),
            })

    frames.sort(key=lambda f: f["timestamp"])
    kept = deduplicate(frames, hash_threshold=args.hash_threshold)

    # remove dropped-duplicate files from disk to save space
    dropped = [f for f in frames if f.get("dropped_as_duplicate")]
    for f in dropped:
        Path(f["path"]).unlink(missing_ok=True)

    manifest = {
        "video": video_path,
        "duration_sec": duration,
        "settings": vars(args),
        "total_candidates_before_dedup": len(frames),
        "total_kept_after_dedup": len(kept),
        "total_dropped_as_duplicate": len(dropped),
        "frames": [
            {"timestamp": f["timestamp"], "sources": f["sources"], "path": f["path"]}
            for f in kept
        ],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print()
    print(f"Done. {len(kept)} keyframes kept (of {len(frames)} extracted, "
          f"{len(dropped)} dropped as near-duplicates).")
    print(f"Manifest: {manifest_path}")
    print(f"Frames:   {frames_dir}")


if __name__ == "__main__":
    main() 
    