#!/usr/bin/env python3
"""
08_select_moments.py
----------------------
Final moment-selection step for the Video-to-Shorts pipeline.

Reads events_described.json (from 07_describe_moments.py) and, if available,
a transcript.json (word/segment-level, e.g. from faster-whisper), then:

    1. Attaches any transcript text that overlaps each event's time range.
    2. Filters out events that are clearly NOT usable content -- title
       cards, outros, watermarks, "subscribe" overlays -- using a generic
       keyword heuristic over the vision description. This is a content-
       TYPE filter (is this footage vs. a UI/text screen), not a judgment
       about what the footage is *about*, so it stays content-agnostic.
    3. Computes a final_score per remaining event by combining:
         - the local signal score already computed in 06_score_moments.py
         - a bonus if speech overlaps the event (people are usually
           talking/reacting during a real moment)
    4. If a local Ollama server is reachable, asks it to rate each
       remaining event 0-10 on "would this make a compelling short-form
       clip" using ONLY the vision description + transcript text (never
       hardcoded categories), and blends that into final_score. If Ollama
       isn't running, this step is skipped gracefully -- the heuristic
       score alone still produces a usable ranking.
    5. Writes selected_clips.json: the full ranked list (excluded events
       included but marked), so nothing is silently thrown away.

Usage:
    python 08_select_moments.py --events output/events/events_described.json \
        --out output/clips/selected_clips.json \
        [--transcript output/transcript.json] \
        [--ollama-url http://localhost:11434] [--ollama-model llama3.1] \
        [--top-n 10]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError


# --------------------------------------------------------------------------- #
# Generic "is this even usable footage" filter -- catches title/outro/UI
# screens regardless of what the video's subject matter is.
# --------------------------------------------------------------------------- #

NON_CONTENT_PATTERNS = [
    r"\btitle screen\b", r"\btitle card\b", r"\bintro screen\b",
    r"\boutro\b", r"\bwatermark\b", r"\blogo\b", r"\bavatar\b",
    r"\bsubscribe\b", r"\blike (and|,)? ?comment\b",
    r"\bon[- ]screen text\b", r"\btext (overlay|reads|displayed)\b",
    r"\bthumbnail\b", r"\bend card\b", r"\bblank (screen|frame)\b",
]
NON_CONTENT_RE = re.compile("|".join(NON_CONTENT_PATTERNS), re.IGNORECASE)


def is_non_content(vision_description: str) -> bool:
    if not vision_description:
        return False
    return bool(NON_CONTENT_RE.search(vision_description))


# --------------------------------------------------------------------------- #
# Transcript overlap
# --------------------------------------------------------------------------- #

def load_transcript_segments(path: str):
    """
    Accepts a faster-whisper-style transcript.json: either
    {"segments": [{"start":.., "end":.., "text":..}, ...]} or a bare list
    of the same segment dicts.
    """
    data = json.loads(Path(path).read_text())
    segments = data.get("segments", data) if isinstance(data, dict) else data
    return [s for s in segments if "start" in s and "end" in s and "text" in s]


def overlapping_text(segments, start, end):
    matched = [s["text"].strip() for s in segments if s["end"] > start and s["start"] < end]
    return " ".join(matched).strip()


# --------------------------------------------------------------------------- #
# Optional local Ollama scoring
# --------------------------------------------------------------------------- #

def ollama_score(ollama_url, model, vision_description, transcript_text, timeout=20):
    prompt = (
        "You are helping select moments from a long video to turn into a "
        "short-form clip (like a YouTube Short). You are NOT told what "
        "category of video this is -- judge purely on what is described.\n\n"
        f"Visual description: {vision_description}\n"
        f"Spoken words during this moment: {transcript_text or '(none / no speech)'}\n\n"
        "On a scale of 0 to 10, how likely is this moment to make a "
        "compelling, shareable short-form clip on its own? "
        "Reply with ONLY a JSON object: {\"score\": <0-10 integer>, \"reason\": \"<one short sentence>\"}"
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
    return {
        "score": float(parsed.get("score", 0)),
        "reason": str(parsed.get("reason", "")).strip(),
    }


def check_ollama_available(ollama_url, timeout=3):
    try:
        req = urlrequest.Request(f"{ollama_url.rstrip('/')}/api/tags")
        with urlrequest.urlopen(req, timeout=timeout):
            return True
    except (URLError, HTTPError, OSError):
        return False


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

SPEECH_OVERLAP_BONUS = 3.0


def compute_heuristic_score(event, transcript_text):
    score = event.get("peak_score", 0.0)
    if transcript_text:
        score += SPEECH_OVERLAP_BONUS
    return round(score, 3)


def main():
    parser = argparse.ArgumentParser(description="Select and rank final candidate clips")
    parser.add_argument("--events", required=True, help="Path to events_described.json")
    parser.add_argument("--out", required=True, help="Path to write selected_clips.json")
    parser.add_argument("--transcript", default=None, help="Optional path to transcript.json")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--ollama-model", default="llama3.1")
    parser.add_argument("--top-n", type=int, default=10, help="How many top clips to mark as recommended")
    args = parser.parse_args()

    events_path = Path(args.events)
    if not events_path.exists():
        sys.exit(f"ERROR: events file not found: {events_path}")

    data = json.loads(events_path.read_text())
    events = data.get("events", [])
    if not events:
        sys.exit("ERROR: no events found.")

    segments = []
    if args.transcript:
        tpath = Path(args.transcript)
        if tpath.exists():
            segments = load_transcript_segments(str(tpath))
            print(f"Loaded transcript with {len(segments)} segments.")
        else:
            print(f"WARNING: transcript path given but not found: {tpath} -- continuing without it.")
    else:
        print("No transcript provided -- scoring on visual/audio signals only.")

    ollama_available = check_ollama_available(args.ollama_url)
    print(f"Local Ollama reachable: {ollama_available}"
          + ("" if ollama_available else " -- skipping LLM scoring, using heuristic score only."))

    results = []
    for event in events:
        vision_desc = event.get("vision_description", "")
        text = overlapping_text(segments, event["start"], event["end"]) if segments else ""
        excluded = is_non_content(vision_desc)

        entry = dict(event)
        entry["transcript_text"] = text
        entry["excluded"] = excluded
        entry["exclude_reason"] = "non-content (title/UI/text screen)" if excluded else None

        if excluded:
            entry["final_score"] = 0.0
            results.append(entry)
            continue

        heuristic = compute_heuristic_score(event, text)
        entry["heuristic_score"] = heuristic
        entry["final_score"] = heuristic

        if ollama_available:
            try:
                llm = ollama_score(args.ollama_url, args.ollama_model, vision_desc, text)
                if llm:
                    entry["llm_score"] = llm["score"]
                    entry["llm_reason"] = llm["reason"]
                    # Blend: local signal grounds it, LLM judgment adjusts it.
                    entry["final_score"] = round((heuristic + llm["score"]) / 2, 3)
            except Exception as e:
                entry["llm_error"] = str(e)

        results.append(entry)

    kept = [r for r in results if not r["excluded"]]
    kept.sort(key=lambda r: r["final_score"], reverse=True)
    for i, r in enumerate(kept):
        r["recommended"] = i < args.top_n

    excluded_events = [r for r in results if r["excluded"]]

    out_data = {
        "source_events": str(events_path),
        "transcript_used": bool(segments),
        "ollama_used": ollama_available,
        "total_events": len(events),
        "excluded_count": len(excluded_events),
        "kept_count": len(kept),
        "recommended_count": min(args.top_n, len(kept)),
        "clips": kept,
        "excluded": excluded_events,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_data, indent=2))

    print()
    print(f"Done. {len(kept)} usable clips, {len(excluded_events)} excluded as non-content.")
    print(f"Top {out_data['recommended_count']} marked as recommended.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
    