"""Export course unit timings and pause/quiet-edit candidates; never modify audio.

Usage:
    python scripts/build_text_audio_map.py --language zh --audio narration.wav \
        --alignment qwen.units.json --lesson lesson.json --policy pause-policy.json --out map
    python scripts/build_text_audio_map.py --language en --audio narration.wav \
        --alignment narration.ctc.json --spoken-text spoken.txt --out map

Chinese uses native Qwen character units; English retains global CTC word timings.
Unknown scores stay null. Zero/repaired timings are exported but block nearby edits.
"""

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

DEFAULT_POLICY = {
    "id": "candidate-screen-v1",
    "quiet_window_seconds": 0.02,
    "quiet_hop_seconds": 0.01,
    "phonetic_guard_seconds": 0.04,
    "quiet_edge_guard_seconds": 0.02,
    "quiet_rms_dbfs": -54,
    "quiet_peak_dbfs": -44,
    "minimum_quiet_run_seconds": 0.06,
    "minimum_confidence": 0.65,
    "join_max_pcm_units": 8,
    "minimum_added_seconds": 0.08,
    "boundaries": [],
    "protected_phrases": [],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    return "".join(c for c in text.casefold() if unicodedata.category(c)[0] in "LN")


def spoken_only(text):
    """Strip known nonspoken pause controls, preserving pronunciation expansions."""
    result = re.sub(r"\[pause\s+[0-9.]+s\]", "", text, flags=re.IGNORECASE)
    if re.search(r"\[pause\b", result, re.IGNORECASE):
        raise ValueError("Unrecognized pause control; provide the exact spoken-only transcript")
    return result.strip()


def read_spoken(lesson=None, spoken_text=None, alignment=None):
    if lesson:
        slides = json.loads(lesson.read_text())["slides"]
        sections = [spoken_only(s["tts_input"]) for s in slides]
    elif spoken_text:
        sections = [spoken_only(spoken_text.read_text())]
    else:
        sections = [s["text"] for s in alignment.get("segments", [])]
    if not sections or any(not normalized(s) for s in sections):
        raise ValueError("Supply spoken text or lesson with nonempty tts_input sections")
    return "\n\n".join(sections), sections


def clock(seconds):
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes):02d}:{remainder:05.2f}"


def load_units(alignment, language, duration):
    qwen = "units" in alignment
    if language == "zh" and (not qwen or "Qwen" not in alignment.get("model", "")):
        raise ValueError("Chinese workflow requires native Qwen unit alignment")
    if language == "en" and (qwen or "CTC" not in alignment.get("alignment_source", "")):
        raise ValueError("English workflow retains global CTC, not Qwen or independent ASR")
    raw = alignment["units"] if qwen else [w for s in alignment["segments"] for w in s["words"]]
    units = []
    for i, row in enumerate(raw):
        start, end = float(row["start"]), float(row["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= duration):
            raise ValueError(f"Invalid timestamp at unit {i}")
        text = row.get("text", row.get("word", "")).strip()
        if not normalized(text):
            raise ValueError(f"Empty normalized unit {i}")
        score = row.get("alignment_score") if qwen else row.get("probability")
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError(f"Invalid alignment score at unit {i}")
        flags = []
        if start == end:
            flags.append("zero_duration")
        if row.get("repaired_timestamp"):
            flags.append("model_repaired_timestamp")
        if row.get("unstable_timestamp"):
            flags.append("unstable_timestamp")
        units.append(
            {
                "index": i,
                "text": text,
                "start": start,
                "end": end,
                "alignment_score": score,
                "flags": flags,
            }
        )
    if not units:
        raise ValueError("Empty alignment")
    for i in range(len(units) - 1):
        if units[i]["end"] > units[i + 1]["start"]:
            units[i]["flags"].append("overlap_or_nonmonotonic")
            units[i + 1]["flags"].append("overlap_or_nonmonotonic")
    return units, qwen


def inspect_join(samples, rate, before, after, policy):
    """Physical quiet screening only; null Qwen score is never turned into a score."""
    if before["flags"] or after["flags"]:
        return {
            "state": "review_flagged_alignment",
            "flags": sorted(set(before["flags"] + after["flags"])),
        }
    scores = [w["alignment_score"] for w in (before, after)]
    known = [v for v in scores if v is not None]
    score = min(known) if known else None
    evidence = {"alignment_min_score": score, "alignment_scores_available": len(known) == 2}
    if known and score < policy["minimum_confidence"]:
        return {"state": "review_low_alignment_score", **evidence}
    left = math.ceil((before["end"] + policy["phonetic_guard_seconds"]) * rate)
    right = math.floor((after["start"] - policy["phonetic_guard_seconds"]) * rate)
    frame = max(1, round(policy["quiet_window_seconds"] * rate))
    hop = max(1, round(policy["quiet_hop_seconds"] * rate))
    starts = np.arange(max(1, left), min(len(samples), right) - frame + 1, hop, dtype=int)
    if not len(starts):
        return {"state": "no_guarded_window", **evidence}
    windows = np.stack([samples[s : s + frame].astype(float) / 32768 for s in starts])
    rms = np.sqrt(np.mean(windows * windows, axis=1))
    peaks = np.max(np.abs(windows), axis=1)
    quiet = (rms <= 10 ** (policy["quiet_rms_dbfs"] / 20)) & (
        peaks <= 10 ** (policy["quiet_peak_dbfs"] / 20)
    )
    changes = np.diff(np.r_[False, quiet, False].astype(np.int8))
    runs = [
        (a, b)
        for a, b in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))
        if ((b - a - 1) * hop + frame) / rate >= policy["minimum_quiet_run_seconds"]
    ]
    if not runs:
        return {"state": "no_confirmed_quiet_run", **evidence}
    begin, finish = max(runs, key=lambda r: r[1] - r[0])
    quiet_left, quiet_right = int(starts[begin]), int(starts[finish - 1] + frame)
    margin = round(policy["quiet_edge_guard_seconds"] * rate)
    positions = np.arange(quiet_left + margin, quiet_right - margin)
    pcm = samples.astype(np.int32)
    positions = positions[
        (np.abs(pcm[positions]) <= policy["join_max_pcm_units"])
        & (np.abs(pcm[positions - 1]) <= policy["join_max_pcm_units"])
    ]
    if not len(positions):
        return {"state": "no_near_zero_join", **evidence}
    join = int(positions[np.argmin(np.abs(positions - (quiet_left + quiet_right) / 2))])
    return {
        "state": "quiet_join_candidate_requires_listening",
        **evidence,
        "quiet_interval": [quiet_left / rate, quiet_right / rate],
        "quiet_run_seconds": (quiet_right - quiet_left) / rate,
        "source_sample": join,
        "source_seconds": join / rate,
        "join_left_pcm": int(samples[join - 1]),
        "join_right_pcm": int(samples[join]),
    }


def literal_matches(haystack, needle):
    if not needle:
        return []
    return [m.start() for m in re.finditer(f"(?={re.escape(needle)})", haystack)]


def build_boundaries(text, sections, units, policy):
    """Match punctuation/annotation by text offsets, never interpolate inside a unit."""
    offsets, cursor = [], 0
    for w in units:
        cursor += len(normalized(w["text"]))
        offsets.append(cursor)
    supplied = normalized(text)
    aligned = "".join(normalized(w["text"]) for w in units)
    if supplied != aligned:
        raise ValueError("Spoken transcript and alignment token stream differ; verify inputs first")
    ends = {end: i for i, end in enumerate(offsets)}
    starts = {0, *offsets[:-1]}
    hints, unresolved = {}, []
    at = 0
    for i, char in enumerate(text):
        at += len(normalized(char))
        kind = None
        if char in ".?!。？！" and at in ends:
            kind = "sentence_end"
        if char == "\n" and i and text[i - 1] == "\n":
            kind = "paragraph_end"
        if kind and at in ends:
            hints.setdefault(ends[at], set()).add(kind)
    at = 0
    for section in sections[:-1]:
        at += len(normalized(section))
        if at in ends:
            hints.setdefault(ends[at], set()).add("section_end")
    protected = []
    for phrase in policy.get("protected_phrases", []):
        token = normalized(phrase)
        protected.extend((i, i + len(token), phrase) for i in literal_matches(supplied, token))
    semantic = {}
    for request in policy["boundaries"]:
        quote = normalized(request["after_quote"])
        matches = [
            i for i in literal_matches(supplied, quote) if i in starts and i + len(quote) in ends
        ]
        occurrence = request.get("occurrence")
        if occurrence is not None:
            matches = matches[occurrence - 1 : occurrence] if occurrence > 0 else []
        if len(matches) != 1:
            unresolved.append(
                {
                    **request,
                    "state": "review_ambiguous_or_missing_anchor",
                    "matching_occurrences": len(matches),
                }
            )
            continue
        index = ends[matches[0] + len(quote)]
        if index in semantic:
            raise ValueError("Multiple teaching requests point to the same boundary")
        target = request.get("target_gap_seconds")
        if target is not None and (not math.isfinite(target) or target < 0):
            raise ValueError("Invalid target gap")
        addition_limit = request.get("maximum_added_seconds")
        if addition_limit is not None and (
            not math.isfinite(addition_limit) or addition_limit <= 0
        ):
            raise ValueError("Invalid boundary-specific addition limit")
        semantic[index] = request
    return hints, semantic, protected, offsets, unresolved


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_map(
    audio, alignment_path, out, language=None, lesson=None, spoken_text=None, policy=None
):
    alignment = json.loads(alignment_path.read_text())
    digest = sha(audio)
    if digest != alignment["source_sha256"]:
        raise ValueError("Alignment belongs to another audio version")
    if sf.info(audio).subtype != "PCM_16":
        raise ValueError("Quiet thresholds require PCM16 analysis source")
    samples, rate = sf.read(audio, dtype="int16")
    if samples.ndim != 1:
        raise ValueError("Use the mono analysis mother")
    duration = len(samples) / rate
    units, qwen = load_units(alignment, language, duration)
    text, sections = read_spoken(lesson, spoken_text, alignment)
    policy = {**DEFAULT_POLICY, **(policy or {})}
    hints, semantic, protected, offsets, unresolved = build_boundaries(
        text, sections, units, policy
    )
    word_rows, boundaries = [], []
    for i, unit in enumerate(units):
        after = units[i + 1] if i + 1 < len(units) else None
        gap = after["start"] - unit["end"] if after else None
        word_rows.append(
            {
                "index": i,
                "text": unit["text"],
                "start_s": unit["start"],
                "end_s": unit["end"],
                "start_clock": clock(unit["start"]),
                "end_clock": clock(unit["end"]),
                "next_word_gap_s": gap,
                "alignment_score": unit["alignment_score"],
                "flags": "|".join(unit["flags"]),
            }
        )
        request = semantic.get(i)
        if after and (i in hints or request):
            blocked = [phrase for a, b, phrase in protected if a < offsets[i] < b]
            join = (
                {"state": "review_protected_phrase", "phrases": blocked}
                if blocked
                else inspect_join(samples, rate, unit, after, policy)
            )
            target = request.get("target_gap_seconds") if request else None
            deficit = max(0, target - gap) if target is not None else None
            physical = join["state"] == "quiet_join_candidate_requires_listening"
            if not request:
                pause_state = "semantic_review_required"
            elif target is None:
                pause_state = "teaching_target_not_set"
            elif deficit < policy["minimum_added_seconds"]:
                pause_state = "already_sufficient"
            elif physical:
                pause_state = "pause_insert_candidate_requires_listening"
            else:
                pause_state = "review_no_eligible_quiet_join"
            boundaries.append(
                {
                    "word_index": i,
                    "before_text": " ".join(w["text"] for w in units[max(0, i - 9) : i + 1]),
                    "after_text": " ".join(w["text"] for w in units[i + 1 : i + 11]),
                    "left_end_s": unit["end"],
                    "right_start_s": after["start"],
                    "word_gap_s": gap,
                    "hints": sorted(hints.get(i, [])),
                    "semantic_role": "existing_teaching_annotation"
                    if request
                    else "punctuation_hint_only",
                    "purpose": request.get("purpose", "") if request else "",
                    "necessary_edit": request.get("necessary_edit") is True if request else False,
                    "necessity_reason": request.get("necessity_reason", "") if request else "",
                    "existing_target_gap_s": target,
                    "additional_gap_budget_s": deficit,
                    "maximum_added_seconds": request.get("maximum_added_seconds")
                    if request
                    else None,
                    "pause_state": pause_state,
                    "needs_semantic_review_before_edit": request is None,
                    "waveform": join,
                    "edit_approved": False,
                }
            )
    manifest = {
        "schema_version": 2,
        "audio_sha256": digest,
        "alignment_sha256": sha(alignment_path),
        "audio": str(audio.resolve()),
        "audio_duration_seconds": duration,
        "sample_rate": rate,
        "language": language,
        "word_count": len(units),
        "granularity": "qwen_cjk_characters_and_latin_groups" if qwen else "ctc_words",
        "alignment_source": alignment.get("alignment_source", alignment.get("model")),
        "alignment_scores_exposed": not qwen,
        "flagged_unit_count": sum(bool(w["flags"]) for w in units),
        "multi_character_chinese_tokens_not_interpolated": sum(
            len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", w["text"])) > 1 for w in units
        ),
        "alignment_is_estimate_not_sample_exact_phonetic_truth": True,
        "content_coverage_proof": False,
        "llm_timing_calls": 0,
        "audio_modified": False,
        "quiet_checks_are_candidates_not_final_edit_approval": True,
        "canonical_spoken_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "policy": policy,
        "script_sha256": sha(Path(__file__)),
        "word_rows": word_rows,
        "boundaries": boundaries,
        "unresolved_annotations": unresolved,
    }
    out.mkdir(parents=True, exist_ok=False)
    (out / "text-audio-map.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    write_csv(out / "word-seconds.csv", word_rows, list(word_rows[0]))
    summary = [
        {
            "word_index": b["word_index"],
            "before_text": b["before_text"],
            "after_text": b["after_text"],
            "left_end": clock(b["left_end_s"]),
            "right_start": clock(b["right_start_s"]),
            "gap_s": b["word_gap_s"],
            "role": b["semantic_role"],
            "purpose": b["purpose"],
            "additional_gap_budget_s": b["additional_gap_budget_s"],
            "pause_state": b["pause_state"],
            "quiet_candidate": b["waveform"]["state"],
            "candidate_cut_s": b["waveform"].get("source_seconds"),
            "candidate_cut_sample": b["waveform"].get("source_sample"),
        }
        for b in boundaries
    ]
    fields = [
        "word_index",
        "before_text",
        "after_text",
        "left_end",
        "right_start",
        "gap_s",
        "role",
        "purpose",
        "additional_gap_budget_s",
        "pause_state",
        "quiet_candidate",
        "candidate_cut_s",
        "candidate_cut_sample",
    ]
    write_csv(out / "boundary-candidates.csv", summary, fields)
    cuts = [
        {
            **b,
            "source_audio_sha256": digest,
            "source_sample_rate": rate,
            "operation": "quiet_splice_point_only_no_trim_range",
            "requires_context_listening": True,
        }
        for b in boundaries
        if b["waveform"]["state"] == "quiet_join_candidate_requires_listening"
    ]
    pauses = [b for b in cuts if b["pause_state"] == "pause_insert_candidate_requires_listening"]
    for name, candidates in [
        ("safe-edit-candidates.json", cuts),
        ("pause-candidates.json", pauses),
    ]:
        (out / name).write_text(
            json.dumps(
                {
                    "audio_modified": False,
                    "edit_approved": False,
                    "source_audio_sha256": digest,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    lines = ["# Course transcript timing", "", "Estimated source clocks; candidates only.", ""]
    at = 0
    for paragraph in re.split(r"\n\s*\n", text):
        length = len(normalized(paragraph))
        if length:
            first = bisect.bisect_right(offsets, at)
            last = bisect.bisect_left(offsets, at + length)
            lines.extend(
                [f"[{clock(units[first]['start'])}–{clock(units[last]['end'])}] " + paragraph, ""]
            )
            at += length
    (out / "timestamped-script.md").write_text("\n".join(lines))
    if sha(audio) != digest:
        raise ValueError("Source audio changed during analysis")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--language", choices=["zh", "en"])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--lesson", type=Path)
    source.add_argument("--spoken-text", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_map(
        args.audio,
        args.alignment,
        args.out,
        args.language,
        args.lesson,
        args.spoken_text,
        json.loads(args.policy.read_text()) if args.policy else None,
    )
    print(
        json.dumps(
            {
                "units": result["word_count"],
                "boundaries": len(result["boundaries"]),
                "flagged_units": result["flagged_unit_count"],
                "unresolved_annotations": len(result["unresolved_annotations"]),
                "audio_modified": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
