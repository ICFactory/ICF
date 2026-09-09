#!/usr/bin/env python3
"""
11_add_commentary.py
-----------------------
Generates a short, content-agnostic AI commentary line per clip (local
Ollama LLM), renders it to speech with a fully local/offline TTS engine
(pyttsx3), and mixes it into the clip's audio with FFmpeg.

Every stage degrades gracefully:
    - No Ollama running -> falls back to using the vision description
      itself as the commentary line (no LLM rewrite).
    - No TTS engine available -> clip is left as-is (video/audio
      untouched), reported as skipped, pipeline keeps going.

Usage:
    python 11_add_commentary.py --manifest output/final_clips/final_clips_manifest.json \
        --out output/commentary_clips \
        [--ollama-url http://localhost:11434] [--ollama-model llama3.1]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode, result.stdout, result.stderr


def check_ollama_available(ollama_url, timeout=3):
    try:
        req = urlrequest.Request(f"{ollama_url.rstrip('/')}/api/tags")
        with urlrequest.urlopen(req, timeout=timeout):
            return True
    except (URLError, HTTPError, OSError):
        return False


def generate_commentary_line(ollama_url, model, vision_description, transcript_text, timeout=30):
    prompt = (
        "Write ONE short, punchy voiceover line (max 15 words) for a short-form "
        "video clip, based only on what is described below. Do not mention that "
        "this is AI-generated. Do not use hashtags or emojis. Just the spoken line.\n\n"
        f"Visual description: {vision_description}\n"
        f"Spoken words in the clip: {transcript_text or '(none)'}\n\n"
        "Voiceover line:"
    )
    payload = {"model": model, "prompt": prompt, "stream": False}
    req = urlrequest.Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    line = data.get("response", "").strip().strip('"')
    return line or None


def synthesize_tts(text, out_wav_path, rate=175):
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)
    engine.save_to_file(text, str(out_wav_path))
    engine.runAndWait()


def mix_commentary(video_path, voice_wav, out_path, original_volume=0.35, voice_volume=1.3):
    filter_complex = (
        f"[0:a]volume={original_volume}[a0];"
        f"[1:a]volume={voice_volume}[a1];"
        f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path), "-i", str(voice_wav),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]
    code, _, err = run(cmd)
    return code == 0, err


def main():
    parser = argparse.ArgumentParser(description="Add AI voiceover commentary to clips")
    parser.add_argument("--manifest", required=True, help="Path to final_clips_manifest.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--ollama-model", default="llama3.1")
    parser.add_argument("--tts-rate", type=int, default=175, help="Words-per-minute for the TTS voice")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"ERROR: manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    clips = manifest.get("clips", [])
    if not clips:
        sys.exit("ERROR: no clips in manifest.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ollama_available = check_ollama_available(args.ollama_url)
    print(f"Local Ollama reachable: {ollama_available}")
    print(f"Local TTS (pyttsx3) available: {TTS_AVAILABLE}")
    if not TTS_AVAILABLE:
        print("  -> pyttsx3 not installed. Install with: pip install pyttsx3"
              " (Linux also needs: sudo apt-get install espeak-ng)")

    results = []
    for clip in clips:
        clip_id = clip["id"]
        clip_path = Path(clip["file"])
        if not clip_path.exists():
            print(f"  [{clip_id}] skipped -- file missing: {clip_path}")
            continue

        vision_desc = clip.get("vision_description", "") or ""
        transcript_text = clip.get("transcript_text", "") or ""

        # 1. Get a commentary line (LLM if available, else the raw description).
        line = None
        if ollama_available:
            try:
                line = generate_commentary_line(args.ollama_url, args.ollama_model, vision_desc, transcript_text)
            except Exception as e:
                print(f"  [{clip_id}] Ollama call failed ({e}); falling back to vision description")
        if not line:
            line = vision_desc

        if not line:
            print(f"  [{clip_id}] no usable text for commentary -- skipping")
            results.append({"id": clip_id, "file": str(clip_path), "commentary_added": False,
                             "reason": "no text available"})
            continue

        if not TTS_AVAILABLE:
            results.append({"id": clip_id, "file": str(clip_path), "commentary_added": False,
                             "reason": "pyttsx3 not installed", "commentary_line": line})
            continue

        print(f"  [{clip_id}] commentary: \"{line}\"")
        wav_path = out_dir / f"{clip_path.stem}_voice.wav"
        try:
            synthesize_tts(line, wav_path, rate=args.tts_rate)
        except Exception as e:
            print(f"  [{clip_id}] TTS synthesis failed: {e}")
            results.append({"id": clip_id, "file": str(clip_path), "commentary_added": False,
                             "reason": f"TTS error: {e}", "commentary_line": line})
            continue

        out_path = out_dir / f"{clip_path.stem}_commentary.mp4"
        ok, err = mix_commentary(clip_path, wav_path, out_path)
        if ok:
            results.append({"id": clip_id, "file": str(out_path), "commentary_added": True,
                             "commentary_line": line})
        else:
            print(f"  [{clip_id}] audio mix failed: {err[-300:]}")
            results.append({"id": clip_id, "file": str(clip_path), "commentary_added": False,
                             "reason": "ffmpeg mix failed", "commentary_line": line})

    out_manifest = out_dir / "commentary_clips_manifest.json"
    out_manifest.write_text(json.dumps({"clips": results}, indent=2))

    added = sum(1 for r in results if r.get("commentary_added"))
    print()
    print(f"Done. {added}/{len(results)} clips got voiceover commentary.")
    print(f"Manifest: {out_manifest}")


if __name__ == "__main__":
    main()
    