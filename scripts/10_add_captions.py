#!/usr/bin/env python3
"""
10_add_captions.py
---------------------
Burns synced captions onto cut clips. Pure FFmpeg for rendering; the only
"intelligence" is re-timing transcript segments to each clip's local
timeline (clip time = original time - clip start).

Usage:
    python 10_add_captions.py --manifest output/final_clips/final_clips_manifest.json \
        --transcript output/transcript.json --out output/captioned_clips
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode, result.stdout, result.stderr


def load_segments(path):
    data = json.loads(Path(path).read_text())
    segments = data.get("segments", data) if isinstance(data, dict) else data
    return [s for s in segments if "start" in s and "end" in s and "text" in s]


def srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments, clip_start, clip_end):
    lines = []
    idx = 1
    for seg in segments:
        if seg["end"] <= clip_start or seg["start"] >= clip_end:
            continue
        local_start = max(0.0, seg["start"] - clip_start)
        local_end = min(clip_end - clip_start, seg["end"] - clip_start)
        if local_end - local_start < 0.05:
            continue
        text = seg["text"].strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{srt_timestamp(local_start)} --> {srt_timestamp(local_end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    return "\n".join(lines)


def burn_subtitles(video_path, srt_path, out_path, font_size=22):
    style = f"FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2"
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{srt_escaped}':force_style='{style}'"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        str(out_path),
    ]
    code, _, err = run(cmd)
    return code == 0, err


def main():
    parser = argparse.ArgumentParser(description="Burn synced captions onto cut clips")
    parser.add_argument("--manifest", required=True, help="Path to final_clips_manifest.json")
    parser.add_argument("--transcript", required=True, help="Path to the full-video transcript.json")
    parser.add_argument("--out", required=True, help="Output directory for captioned clips")
    parser.add_argument("--font-size", type=int, default=22)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"ERROR: manifest not found: {manifest_path}")
    if not Path(args.transcript).exists():
        sys.exit(f"ERROR: transcript not found: {args.transcript}")

    manifest = json.loads(manifest_path.read_text())
    clips = manifest.get("clips", [])
    if not clips:
        sys.exit("ERROR: no clips in manifest.")

    segments = load_segments(args.transcript)
    print(f"Loaded {len(segments)} transcript segments.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for clip in clips:
        clip_path = Path(clip["file"])
        if not clip_path.exists():
            print(f"  [{clip['id']}] skipped -- file missing: {clip_path}")
            continue

        srt_text = build_srt(segments, clip["start"], clip["end"])
        if not srt_text.strip():
            print(f"  [{clip['id']}] no overlapping speech -- copying clip without captions")
            out_path = out_dir / clip_path.name
            code, _, err = run(["ffmpeg", "-y", "-i", str(clip_path), "-c", "copy", str(out_path)])
            results.append({"id": clip["id"], "file": str(out_path), "captioned": False})
            continue

        srt_path = out_dir / f"{clip_path.stem}.srt"
        srt_path.write_text(srt_text)

        out_path = out_dir / f"{clip_path.stem}_captioned.mp4"
        print(f"  [{clip['id']}] burning captions ...")
        ok, err = burn_subtitles(clip_path, srt_path, out_path, args.font_size)

        if ok:
            results.append({"id": clip["id"], "file": str(out_path), "captioned": True})
        else:
            print(f"      FAILED: {err[-300:]}")
            results.append({"id": clip["id"], "file": None, "captioned": False, "error": err[-300:]})

    out_manifest = out_dir / "captioned_clips_manifest.json"
    out_manifest.write_text(json.dumps({"clips": results}, indent=2))

    ok_count = sum(1 for r in results if r.get("captioned"))
    print()
    print(f"Done. {ok_count}/{len(results)} clips captioned successfully.")
    print(f"Manifest: {out_manifest}")


if __name__ == "__main__":
    main()
    