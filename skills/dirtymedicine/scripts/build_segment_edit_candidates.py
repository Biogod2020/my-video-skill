"""Screen ASR segment gaps for quiet splice candidates without inventing word times.

Usage:
    python scripts/build_segment_edit_candidates.py --audio narration.wav \
        --segments transcription.json --out segment-candidates.json

Input: source_sha256 and segments[{start,end,text}] in SOURCE seconds. Adapt native
model keys/units explicitly before calling; text cleanup never changes clocks.
Output remains a review list. It does not remove gaps, breaths, words or audio.
"""

import argparse
import json
import math
from pathlib import Path

import soundfile as sf
from build_text_audio_map import DEFAULT_POLICY, inspect_join, sha


def build(audio, source, policy=None):
    digest = sha(audio)
    data = json.loads(source.read_text())
    if digest != data["source_sha256"]:
        raise ValueError("ASR segment clocks belong to another audio version")
    if sf.info(audio).subtype != "PCM_16":
        raise ValueError("Use PCM16 mono mother")
    samples, rate = sf.read(audio, dtype="int16")
    if samples.ndim != 1:
        raise ValueError("Use mono mother")
    rows = data["segments"]
    duration = len(samples) / rate
    units = []
    for row in rows:
        start, end = row["start"], row["end"]
        if not all(math.isfinite(x) for x in [start, end]) or not 0 <= start < end <= duration:
            raise ValueError(
                "ASR segment timestamp invalid; explicitly convert ms to source seconds"
            )
        units.append({"start": start, "end": end, "flags": [], "alignment_score": None})
    candidates = []
    for i in range(len(units) - 1):
        before, after = units[i : i + 2]
        if before["end"] > after["start"]:
            waveform = {"state": "review_overlapping_segment_times"}
        else:
            waveform = inspect_join(
                samples, rate, before, after, {**DEFAULT_POLICY, **(policy or {})}
            )
        candidates.append(
            {
                "after_segment": i,
                "before_text": rows[i]["text"],
                "after_text": rows[i + 1]["text"],
                "estimated_gap_seconds": after["start"] - before["end"],
                "waveform": waveform,
                "requires_semantic_and_context_review": True,
                "edit_approved": False,
            }
        )
    if sha(audio) != digest:
        raise ValueError("Mother changed during analysis")
    return {
        "source_audio_sha256": digest,
        "source_asr_sha256": sha(source),
        "source_sample_rate": rate,
        "source_model": data.get("model", data.get("asr_model")),
        "source_time_unit": "seconds",
        "granularity": "asr_segments",
        "word_timestamps_fabricated": False,
        "llm_timing_calls": 0,
        "audio_modified": False,
        "edit_approved": False,
        "candidates": candidates,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--segments", type=Path, required=True)
    p.add_argument("--policy", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = build(
        args.audio, args.segments, json.loads(args.policy.read_text()) if args.policy else None
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2))
    print("SEGMENT_EDIT_SCREEN_READY", len(result["candidates"]), "boundaries; no audio edits")


if __name__ == "__main__":
    main()
