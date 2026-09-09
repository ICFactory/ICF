#!/usr/bin/env python3
"""
12_generate_metadata.py
--------------------------
Generates a title, description, and hashtags for each final clip.

Uses local Ollama if available for genuinely good, content-agnostic
copywriting. Falls back to a simple templated generator (built only from
the vision description / transcript text already on hand) if Ollama isn't
running, so this step never blocks the pipeline.

Usage:
    python 12_generate_metadata.py --manifest output/final_clips/final_clips_manifest.json \
        --out output/metadata.json \
        [--ollama-url http://localhost:11434] [--ollama-model llama3.1]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

STOPWORDS = {
    "the", "and", "with", "that", "this", "from", "into", "onto", "while",
    "sits", "features", "shows", "displayed", "appears", "their", "them",
    "than", "have", "has", "for", "are", "was", "were",
}


def check_ollama_available(ollama_url, timeout=3):
    try:
        req = urlrequest.Request(f"{ollama_url.rstrip('/')}/api/tags")
        with urlrequest.urlopen(req, timeout=timeout):
            return True
    except (URLError, HTTPError, OSError):
        return False


def ollama_metadata(ollama_url, model, vision_description, transcript_text, timeout=30):
    prompt = (
        "Based only on the description below, generate metadata for a short-form "
        "video clip (YouTube Shorts style). Do not assume a category or theme "
        "beyond what's described.\n\n"
        f"Visual description: {vision_description}\n"
        f"Spoken words: {transcript_text or '(none)'}\n\n"
        "Reply with ONLY a JSON object in this exact shape:\n"
        '{"title": "<under 60 chars, catchy>", '
        '"description": "<1-2 sentences>", '
        '"hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]}'
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
    raw = data.get("response", "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    parsed = json.loads(match.group(0))
    if not all(k in parsed for k in ("title", "description", "hashtags")):
        return None
    return parsed


def fallback_metadata(vision_description, transcript_text):
    """Simple templated fallback -- no invented facts, built only from what's on hand."""
    text = (vision_description or "").strip()
    words = text.split()
    title = " ".join(words[:8]).rstrip(".,") or "Untitled Clip"
    if len(title) > 60:
        title = title[:57].rstrip() + "..."

    description_parts = [p for p in [text, transcript_text.strip() if transcript_text else ""] if p]
    description = " ".join(description_parts).strip() or "Short clip."

    keywords = []
    for w in re.findall(r"[A-Za-z]{4,}", text.lower()):
        if w not in STOPWORDS and w not in keywords:
            keywords.append(w)
        if len(keywords) >= 4:
            break
    hashtags = ["#shorts"] + [f"#{w}" for w in keywords]

    return {"title": title, "description": description, "hashtags": hashtags}


def main():
    parser = argparse.ArgumentParser(description="Generate title/description/hashtags per clip")
    parser.add_argument("--manifest", required=True, help="Path to final_clips_manifest.json")
    parser.add_argument("--out", required=True, help="Path to write metadata.json")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--ollama-model", default="llama3.1")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"ERROR: manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    clips = manifest.get("clips", [])
    if not clips:
        sys.exit("ERROR: no clips in manifest.")

    ollama_available = check_ollama_available(args.ollama_url)
    print(f"Local Ollama reachable: {ollama_available}"
          + ("" if ollama_available else " -- using templated fallback metadata."))

    results = []
    for clip in clips:
        clip_id = clip["id"]
        vision_desc = clip.get("vision_description", "") or ""
        transcript_text = clip.get("transcript_text", "") or ""

        meta = None
        source = "fallback"
        if ollama_available:
            try:
                meta = ollama_metadata(args.ollama_url, args.ollama_model, vision_desc, transcript_text)
                if meta:
                    source = "ollama"
            except Exception as e:
                print(f"  [{clip_id}] Ollama call failed ({e}); using fallback")

        if not meta:
            meta = fallback_metadata(vision_desc, transcript_text)

        print(f"  [{clip_id}] ({source}) {meta['title']}")
        results.append({
            "id": clip_id,
            "file": clip.get("file"),
            "source": source,
            **meta,
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"clips": results}, indent=2))

    print()
    print(f"Done. Metadata generated for {len(results)} clips.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
    