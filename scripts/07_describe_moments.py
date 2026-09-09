#!/usr/bin/env python3
"""
07_describe_moments.py
------------------------
Vision description step for the Video-to-Shorts pipeline.

Reads events.json (from 06_score_moments.py), sends ONE representative
frame per event (the peak frame) to Gemini 2.5 Flash for a short, factual
visual description, and writes the results back into an enriched
events_described.json.

Content-agnostic: the prompt asks for a neutral description of what is
happening -- it never asks the model to judge whether something is
"funny", "cute", etc. That judgment is made later by the reasoning stage
that combines this description with the transcript.

Designed for a small/uncertain free-tier daily quota:
    - Sends at most --max-requests calls per run (default 90, safely under
      a 100 RPD budget).
    - Checkpoints after every single call to a local cache file, so a
      run that gets interrupted (or hits a 429) can simply be re-run and
      will skip everything already described.
    - Backs off and stops cleanly on a quota/rate-limit error instead of
      crashing or burning further quota.

Usage:
    export GEMINI_API_KEY=your_key_here
    python 07_describe_moments.py --events output/events/events.json \
        --out output/events/events_described.json
"""

import argparse
import json
import os
import sys
import time
import base64
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

MODEL = "gemini-3.6-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

PROMPT = (
    "Describe, in one or two neutral factual sentences, exactly what is "
    "visibly happening in this video frame: the subjects, their action, "
    "and the setting. Do not judge whether it is interesting, funny, or "
    "significant -- just describe what is shown."
)


def load_cache(cache_path: Path):
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    return {}


def save_cache(cache_path: Path, cache: dict):
    cache_path.write_text(json.dumps(cache, indent=2))


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def describe_frame(image_path: str, api_key: str, timeout: int = 30):
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": encode_image(image_path)}},
            ]
        }]
    }
    req = urlrequest.Request(
        f"{API_URL}?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Describe candidate-event peak frames with Gemini vision")
    parser.add_argument("--events", required=True, help="Path to events.json from 06_score_moments.py")
    parser.add_argument("--out", required=True, help="Path to write the enriched events_described.json")
    parser.add_argument("--cache", default=None,
                         help="Path to a description cache (default: <out-dir>/vision_cache.json)")
    parser.add_argument("--max-requests", type=int, default=None,
                         help="Hard cap on API calls this run. Default: no extra cap beyond RPM pacing.")
    parser.add_argument("--sleep-between", type=float, default=13.0,
                         help="Seconds to wait between calls. Default 13s keeps you under a 5 RPM quota.")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("ERROR: set the GEMINI_API_KEY environment variable first.")

    events_path = Path(args.events)
    if not events_path.exists():
        sys.exit(f"ERROR: events file not found: {events_path}")

    data = json.loads(events_path.read_text())
    events = data.get("events", [])
    if not events:
        sys.exit("ERROR: no events found in events.json")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path = Path(args.cache) if args.cache else out_path.parent / "vision_cache.json"
    cache = load_cache(cache_path)

    print(f"Loaded {len(events)} events. {len(cache)} already described (cached).")

    requests_made = 0
    stopped_early = False

    for event in events:
        eid = event["id"]

        if eid in cache:
            event["vision_description"] = cache[eid]
            continue

        if args.max_requests is not None and requests_made >= args.max_requests:
            stopped_early = True
            continue

        # Use the peak frame -- the frame with the highest local score --
        # as the single representative image for this event.
        peak_frame = max(event["frames"], key=lambda f: f["score"])
        image_path = peak_frame["path"]

        if not Path(image_path).exists():
            print(f"  [{eid}] skipped -- frame file missing: {image_path}")
            continue

        try:
            print(f"  [{eid}] describing frame at {peak_frame['timestamp']}s ...")
            description = describe_frame(image_path, api_key)
            requests_made += 1

            if description:
                cache[eid] = description
                event["vision_description"] = description
                save_cache(cache_path, cache)  # checkpoint immediately
            else:
                print(f"  [{eid}] empty response, will retry next run")

            time.sleep(args.sleep_between)

        except HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 or "RESOURCE_EXHAUSTED" in body:
                print("  Quota/rate limit hit. Stopping this run -- "
                      "already-described events are saved, re-run later to continue.")
                stopped_early = True
                break
            print(f"  [{eid}] HTTP error {e.code}: {body[:200]}")
        except URLError as e:
            print(f"  [{eid}] network error: {e}. Stopping this run.")
            stopped_early = True
            break

    described_count = sum(1 for e in events if "vision_description" in e)
    data["vision_model"] = MODEL
    data["events"] = events
    out_path.write_text(json.dumps(data, indent=2))

    print()
    print(f"Done. {described_count}/{len(events)} events have a vision description.")
    print(f"Requests made this run: {requests_made}")
    if stopped_early:
        print("Stopped early (quota cap or API limit). Re-run the same command "
              "later to describe the remaining events -- cached results are kept.")
    print(f"Output: {out_path}")
    print(f"Cache:  {cache_path}")


if __name__ == "__main__":
    main()
    