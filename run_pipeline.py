#!/usr/bin/env python3
"""
run_pipeline.py
------------------
One-command orchestrator for the full ICF pipeline: chains scripts
05 through 12 in order, using config.yaml for shared settings, so you
don't have to run 8 commands by hand every time.

    05 extract_keyframes -> 06 score_moments -> 07 describe_moments ->
    08 select_moments -> 09 cut_clips -> 10 add_captions ->
    11 add_commentary -> 12 generate_metadata

Design notes:
    - This is a standalone orchestrator (kept outside the app/ package)
      that calls each existing, already-tested script via subprocess.
      It does NOT duplicate their logic -- each script is still the
      single source of truth for its own stage.
    - Stage 07 (vision) is the one stage that costs real API quota.
      --start-from and --skip let you re-run later stages without
      burning it again on a day you've already described your events.
    - A transcript.json is optional. If it doesn't exist at the
      configured path, captions (10) are skipped with a clear message,
      and 08/11 simply run without transcript-based scoring/context --
      exactly like running those scripts standalone.

Usage:
    python run_pipeline.py --video input/long_video.mp4.mp4
    python run_pipeline.py --video input/long_video.mp4.mp4 --start-from 4
    python run_pipeline.py --video input/long_video.mp4.mp4 --only 9
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).parent / "scripts"

STAGES = [1, 2, 3, 4, 5, 6, 7, 8]
STAGE_NAMES = {
    1: "extract_keyframes",
    2: "score_moments",
    3: "describe_moments",
    4: "select_moments",
    5: "cut_clips",
    6: "add_captions",
    7: "add_commentary",
    8: "generate_metadata",
}


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def find_input_video(input_dir: Path, override: str = None) -> Path:
    if override:
        p = Path(override)
        if not p.exists():
            sys.exit(f"ERROR: --video path not found: {p}")
        return p

    videos = [p for p in input_dir.glob("*") if p.suffix.lower() in
              (".mp4", ".mov", ".mkv", ".avi") or p.name.lower().endswith(".mp4.mp4")]
    if not videos:
        sys.exit(f"ERROR: no video found in {input_dir}. Pass --video explicitly.")
    if len(videos) > 1:
        names = ", ".join(v.name for v in videos)
        sys.exit(f"ERROR: multiple videos found in {input_dir} ({names}). Pass --video to pick one.")
    return videos[0]


def run_stage(cmd, stage_num, name):
    print()
    print("=" * 70)
    print(f"STAGE {stage_num}: {name}")
    print("=" * 70)
    print(" ".join(cmd))
    print()
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"\nERROR: stage {stage_num} ({name}) failed (exit code {result.returncode}). "
                  f"Fix the issue above, then resume with: --start-from {stage_num}")


def main():
    parser = argparse.ArgumentParser(description="Run the full ICF pipeline end-to-end")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--video", default=None, help="Override input video path")
    parser.add_argument("--start-from", type=int, choices=STAGES, default=1,
                         help="Resume from this stage number (1-8), skipping earlier ones")
    parser.add_argument("--only", type=int, choices=STAGES, default=None,
                         help="Run only this single stage")
    parser.add_argument("--skip-captions", action="store_true", help="Skip stage 6 (captions)")
    parser.add_argument("--skip-commentary", action="store_true", help="Skip stage 7 (commentary)")
    args = parser.parse_args()

    if not Path(args.config).exists():
        sys.exit(f"ERROR: config file not found: {args.config}")
    cfg = load_config(args.config)

    input_dir = Path(cfg["paths"]["input_dir"])
    output_dir = Path(cfg["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    video = find_input_video(input_dir, args.video)
    print(f"Input video: {video}")

    # Fixed, predictable output layout for this run.
    keyframes_manifest = output_dir / "keyframes" / "manifest.json"
    events_json = output_dir / "events" / "events.json"
    events_described_json = output_dir / "events" / "events_described.json"
    selected_clips_json = output_dir / "clips" / "selected_clips.json"
    final_clips_dir = output_dir / "final_clips"
    final_clips_manifest = final_clips_dir / "final_clips_manifest.json"
    captioned_dir = output_dir / "captioned_clips"
    commentary_dir = output_dir / "commentary_clips"
    metadata_json = output_dir / "metadata.json"
    transcript_json = output_dir / "transcript.json"

    have_transcript = transcript_json.exists()
    if not have_transcript:
        print(f"NOTE: no transcript found at {transcript_json} -- "
              f"run scripts/03_transcribe.py first if you want captions "
              f"and transcript-aware scoring. Continuing without it.")

    stages_to_run = [args.only] if args.only else [s for s in STAGES if s >= args.start_from]

    if 1 in stages_to_run:
        run_stage([
            sys.executable, str(SCRIPTS_DIR / "05_extract_keyframes.py"),
            "--video", str(video),
            "--out", str(output_dir / "keyframes"),
            "--base-interval", str(cfg["analysis"]["sample_interval"]),
            "--max-frames", str(cfg["analysis"]["max_candidates"]),
        ], 1, STAGE_NAMES[1])

    if 2 in stages_to_run:
        run_stage([
            sys.executable, str(SCRIPTS_DIR / "06_score_moments.py"),
            "--manifest", str(keyframes_manifest),
            "--out", str(output_dir / "events"),
            "--window-before", str(cfg["analysis"]["event_padding_before"]),
            "--window-after", str(cfg["analysis"]["event_padding_after"]),
        ], 2, STAGE_NAMES[2])

    if 3 in stages_to_run:
        run_stage([
            sys.executable, str(SCRIPTS_DIR / "07_describe_moments.py"),
            "--events", str(events_json),
            "--out", str(events_described_json),
        ], 3, STAGE_NAMES[3])

    if 4 in stages_to_run:
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "08_select_moments.py"),
            "--events", str(events_described_json),
            "--out", str(selected_clips_json),
            "--top-n", str(cfg["shorts"]["target_count"]),
        ]
        if have_transcript:
            cmd += ["--transcript", str(transcript_json)]
        run_stage(cmd, 4, STAGE_NAMES[4])

    if 5 in stages_to_run:
        run_stage([
            sys.executable, str(SCRIPTS_DIR / "09_cut_clips.py"),
            "--clips", str(selected_clips_json),
            "--video", str(video),
            "--out", str(final_clips_dir),
            "--target-width", str(cfg["ffmpeg"]["width"]),
            "--target-height", str(cfg["ffmpeg"]["height"]),
            "--max-duration", str(cfg["shorts"]["max_duration"]),
            "--min-duration", str(cfg["shorts"]["min_duration"]),
            "--crf", str(cfg["ffmpeg"]["crf"]),
            "--preset", str(cfg["ffmpeg"]["preset"]),
        ], 5, STAGE_NAMES[5])

    if 6 in stages_to_run and not args.skip_captions:
        if have_transcript:
            run_stage([
                sys.executable, str(SCRIPTS_DIR / "10_add_captions.py"),
                "--manifest", str(final_clips_manifest),
                "--transcript", str(transcript_json),
                "--out", str(captioned_dir),
            ], 6, STAGE_NAMES[6])
        else:
            print("\nSTAGE 6 (add_captions): skipped -- no transcript.json available.")

    if 7 in stages_to_run and not args.skip_commentary:
        run_stage([
            sys.executable, str(SCRIPTS_DIR / "11_add_commentary.py"),
            "--manifest", str(final_clips_manifest),
            "--out", str(commentary_dir),
        ], 7, STAGE_NAMES[7])

    if 8 in stages_to_run:
        run_stage([
            sys.executable, str(SCRIPTS_DIR / "12_generate_metadata.py"),
            "--manifest", str(final_clips_manifest),
            "--out", str(metadata_json),
        ], 8, STAGE_NAMES[8])

    print()
    print("=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"Final clips:   {final_clips_dir}")
    print(f"Captioned:     {captioned_dir}")
    print(f"Commentary:    {commentary_dir}")
    print(f"Metadata:      {metadata_json}")


if __name__ == "__main__":
    main()
    