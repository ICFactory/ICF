#!/usr/bin/env python3
"""
09_cut_clips.py
-----------------
Final clip-cutting step for the Video-to-Shorts pipeline.

Pure FFmpeg -- no AI calls happen here. Takes selected_clips.json (from
08_select_moments.py) and the original source video, and for each chosen
clip:

    1. Optionally clamps clip duration to a max length, centered on the
       event's peak moment (so an overly long merged event still becomes
       a reasonably-sized Short rather than a multi-minute cut).
    2. Crops/pads the frame to a 9:16 vertical target resolution.
    3. Encodes a final standalone .mp4 for that clip.

By default only clips marked "recommended": true in selected_clips.json
are cut; pass --all to cut every non-excluded clip instead.

Usage:
    python 09_cut_clips.py --clips output/clips/selected_clips.json \
        --video input/long_video.mp4.mp4 --out output/final_clips
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode, result.stdout, result.stderr


def probe_dimensions(video_path: str):
    code, out, err = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", video_path,
    ])
    if code != 0 or "x" not in out:
        raise RuntimeError(f"Could not read video dimensions: {err}")
    w, h = out.strip().split("x")
    return int(w), int(h)


def build_vertical_filter(src_w, src_h, target_w, target_h):
    """
    If the source is wider than the target aspect ratio (typical 16:9
    footage going to 9:16), center-crop horizontally then scale down.
    Otherwise (source already narrow/tall), scale to fit width and pad
    top/bottom with black bars instead of cropping out content.
    """
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        crop_w = int(src_h * target_ratio)
        crop_w -= crop_w % 2  # keep even for encoder compatibility
        return (
            f"crop={crop_w}:{src_h}:(iw-{crop_w})/2:0,"
            f"scale={target_w}:{target_h}"
        )
    else:
        return (
            f"scale={target_w}:-2,"
            f"pad={target_w}:{target_h}:0:(oh-ih)/2:color=black"
        )


def cut_clip(video_path, start, end, out_path, vf_filter, crf=20, preset="veryfast"):
    duration = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-i", video_path,
        "-t", f"{duration:.3f}",
        "-vf", vf_filter,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    code, _, err = run(cmd)
    return code == 0, err


def clamp_clip_range(start, end, peak_time, max_duration, video_duration):
    duration = end - start
    if duration <= max_duration:
        return start, end
    half = max_duration / 2
    new_start = max(0.0, peak_time - half)
    new_end = min(video_duration, new_start + max_duration)
    new_start = max(0.0, new_end - max_duration)  # re-clamp if end hit video boundary
    return new_start, new_end


def main():
    parser = argparse.ArgumentParser(description="Cut, crop-to-9:16, and encode final Shorts clips")
    parser.add_argument("--clips", required=True, help="Path to selected_clips.json")
    parser.add_argument("--video", required=True, help="Path to the original source video")
    parser.add_argument("--out", required=True, help="Output directory for final clip files")
    parser.add_argument("--all", action="store_true",
                         help="Cut every non-excluded clip, not just recommended ones")
    parser.add_argument("--target-width", type=int, default=1080)
    parser.add_argument("--target-height", type=int, default=1920)
    parser.add_argument("--max-duration", type=float, default=60.0,
                         help="Clips longer than this are trimmed, centered on the peak moment")
    parser.add_argument("--min-duration", type=float, default=1.5,
                         help="Clips shorter than this are skipped as unusable")
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--preset", default="veryfast",
                         help="x264 preset -- veryfast recommended for CPU-only machines")
    args = parser.parse_args()

    clips_path = Path(args.clips)
    if not clips_path.exists():
        sys.exit(f"ERROR: clips file not found: {clips_path}")
    if not Path(args.video).exists():
        sys.exit(f"ERROR: video not found: {args.video}")

    data = json.loads(clips_path.read_text())
    all_clips = data.get("clips", [])
    if not all_clips:
        sys.exit("ERROR: no clips found in selected_clips.json")

    targets = all_clips if args.all else [c for c in all_clips if c.get("recommended")]
    if not targets:
        sys.exit("Nothing to cut -- no clips matched the selection (try --all).")

    print(f"[1/3] Probing source video dimensions ...")
    src_w, src_h = probe_dimensions(args.video)
    print(f"      source: {src_w}x{src_h}")

    code, out, _ = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", args.video,
    ])
    video_duration = float(out.strip()) if code == 0 and out.strip() else float("inf")

    vf_filter = build_vertical_filter(src_w, src_h, args.target_width, args.target_height)
    print(f"      filter: {vf_filter}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[2/3] Cutting {len(targets)} clip(s) ...")
    manifest = []
    for i, clip in enumerate(targets, 1):
        start, end = clip["start"], clip["end"]
        peak_time = clip.get("peak_time", (start + end) / 2)
        start, end = clamp_clip_range(start, end, peak_time, args.max_duration, video_duration)

        if (end - start) < args.min_duration:
            print(f"  [{i}] {clip.get('id')} skipped -- too short after clamping ({end - start:.2f}s)")
            continue

        fname = f"clip_{i:02d}_{clip.get('id', 'unknown')}_{start:.1f}-{end:.1f}s.mp4"
        out_path = out_dir / fname

        print(f"  [{i}] {clip.get('id')}: {start:.2f}s -> {end:.2f}s ...")
        ok, err = cut_clip(args.video, start, end, out_path, vf_filter, args.crf, args.preset)

        if ok:
            manifest.append({
                "rank": i,
                "id": clip.get("id"),
                "file": str(out_path),
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "final_score": clip.get("final_score"),
                "vision_description": clip.get("vision_description"),
                "transcript_text": clip.get("transcript_text"),
            })
        else:
            print(f"      FAILED: {err[-300:]}")

    print(f"[3/3] Writing clips manifest ...")
    manifest_path = out_dir / "final_clips_manifest.json"
    manifest_path.write_text(json.dumps({
        "source_video": args.video,
        "target_resolution": f"{args.target_width}x{args.target_height}",
        "clip_count": len(manifest),
        "clips": manifest,
    }, indent=2))

    print()
    print(f"Done. {len(manifest)}/{len(targets)} clips cut successfully.")
    print(f"Output: {out_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
    