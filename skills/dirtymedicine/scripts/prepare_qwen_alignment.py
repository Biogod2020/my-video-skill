"""Package a Chinese mother and spoken lesson into bounded Qwen alignment jobs.

Usage:
    python scripts/prepare_qwen_alignment.py --audio narration.wav --lesson lesson.json \
        --coarse-alignment narration.asr.json --out private/alignment-kit

Coarse ASR times only plan overlapping inference windows. No fine timestamp is copied.
Alignment-window splitting does not split or regenerate the TTS mother.
"""

import argparse
import difflib
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf
from build_text_audio_map import read_spoken, sha

PINS = {
    "model_id": "Qwen/Qwen3-ForcedAligner-0.6B",
    "model_revision": "c7cbfc2048c462b0d63a45797104fc9db3ad62b7",
    "repo_commit": "7c6daf77a2421100f5fb066495372c00129d39ff",
    "qwen_asr_version": "0.0.6",
    "transformers_version": "4.57.6",
}


def clean(text):
    return "".join(c for c in text if c == "'" or unicodedata.category(c)[0] in "LN")


def tokens(text):
    result = []
    for segment in text.split():
        result.extend(
            re.findall(
                r"[\u3400-\u4dbf\u4e00-\u9fff]|[^\u3400-\u4dbf\u4e00-\u9fff]+", clean(segment)
            )
        )
    return result


def prepare(audio, lesson, coarse_path, out, context_units=20, padding=1.0):
    if context_units < 0 or padding < 0:
        raise ValueError("Negative context")
    text, sections = read_spoken(lesson=lesson)
    source_sha = sha(audio)
    coarse = json.loads(coarse_path.read_text())
    if coarse["source_sha256"] != source_sha:
        raise ValueError("Coarse alignment belongs to another mother")
    if sf.info(audio).subtype != "PCM_16":
        raise ValueError("Use a PCM16 mother")
    samples, rate = sf.read(audio, dtype="int16")
    if samples.ndim != 1:
        raise ValueError("Use mono mother")
    words = [w for s in coarse["segments"] for w in s["words"]]
    duration = len(samples) / rate
    if not words or any(not 0 <= w["start"] <= w["end"] <= duration for w in words):
        raise ValueError("Invalid coarse times")
    units, ranges = [], []
    for i, section in enumerate(sections):
        a = len(units)
        units.extend(tokens(section))
        ranges.append((f"zh-{i + 1:02d}", a, len(units)))
    canonical = "".join(units).lower()
    owners, old = [], ""
    for i, word in enumerate(words):
        value = clean(word["word"]).lower()
        owners.extend([i] * len(value))
        old += value
    mapping = {}
    for block in difflib.SequenceMatcher(
        None, canonical, old, autojunk=False
    ).get_matching_blocks():
        mapping.update({block.a + i: owners[block.b + i] for i in range(block.size)})
    fraction = len(mapping) / len(canonical)
    if fraction < 0.75:
        raise ValueError("Coarse ASR mismatches spoken text; inspect or supply corrected anchors")
    offsets, at = [], 0
    for unit in units:
        offsets.append((at, at + len(unit)))
        at += len(unit)

    def approximate(index, last=False):
        a, b = offsets[index]
        candidates = [mapping[c] for c in range(a, b) if c in mapping]
        if not candidates:
            nearest = min(mapping, key=lambda c: abs(c - (b - 1 if last else a)))
            candidates = [mapping[nearest]]
        word = words[max(candidates) if last else min(candidates)]
        return word["end"] if last else word["start"]

    jobs = []

    def add_job(name, a, b):
        lo, hi = max(0, a - context_units), min(len(units), b + context_units)
        left = int(max(0, approximate(lo) - padding) * rate)
        right = min(len(samples), round((approximate(hi - 1, True) + padding) * rate))
        if right <= left:
            raise ValueError("Coarse anchors produce an empty/reversed window")
        if (right - left) / rate >= 180:
            if b - a <= 1:
                raise ValueError("Context exceeds 180s; inspect coarse anchors or reduce context")
            middle = (a + b) // 2
            add_job(name + "a", a, middle)
            add_job(name + "b", middle, b)
            return
        jobs.append(
            {
                "id": name,
                "language": "Chinese",
                "start_frame": left,
                "end_frame": right,
                "offset_seconds": left / rate,
                "duration_seconds": (right - left) / rate,
                "unit_start": lo,
                "unit_end": hi,
                "core_unit_start": a,
                "core_unit_end": b,
                "text": " ".join(units[lo:hi]),
                "coarse_planning_used_old_alignment": True,
                "output_word_times_copied_from_old_alignment": False,
            }
        )

    for name, a, b in ranges:
        add_job(name, a, b)
    out.mkdir(parents=True, exist_ok=False)
    lossless = out / "course.flac"
    sf.write(lossless, samples, rate, format="FLAC", subtype="PCM_16")
    check, check_rate = sf.read(lossless, dtype="int16")
    if check_rate != rate or not np.array_equal(check, samples):
        raise ValueError("Lossless package verification failed")
    manifest = {
        "language": "Chinese",
        "sample_rate": rate,
        "duration_seconds": duration,
        "source_sha256": source_sha,
        "lossless_sha256": sha(lossless),
        "lesson_sha256": sha(lesson),
        "coarse_alignment_sha256": sha(coarse_path),
        "coarse_equal_character_fraction": fraction,
        "model_pins": PINS,
        "units": units,
        "jobs": jobs,
        "audio_modified": False,
    }
    (out / "alignment-plan.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (out / "spoken.txt").write_text(text)
    if sha(audio) != source_sha:
        raise ValueError("Mother changed during packaging")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--lesson", type=Path, required=True)
    p.add_argument("--coarse-alignment", type=Path, required=True)
    p.add_argument("--context-units", type=int, default=20)
    p.add_argument("--padding-seconds", type=float, default=1.0)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    plan = prepare(
        args.audio,
        args.lesson,
        args.coarse_alignment,
        args.out,
        args.context_units,
        args.padding_seconds,
    )
    print(
        json.dumps(
            {
                "jobs": len(plan["jobs"]),
                "units": len(plan["units"]),
                "max_window_seconds": max(j["duration_seconds"] for j in plan["jobs"]),
                "audio_modified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
