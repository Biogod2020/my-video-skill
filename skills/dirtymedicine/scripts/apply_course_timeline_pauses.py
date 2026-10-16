"""Apply sparse semantic quiet inserts and retain every original PCM sample.

Usage: python scripts/apply_course_timeline_pauses.py --language zh \
    --audio narration.wav --alignment qwen.units.json --lesson lesson.json \
    --policy pause-policy.json --out derived-master

English defaults to analysis only. Necessary English inserts require an explicit
mode and a contextual reason on each boundary; an old target is not edit approval.
"""

import argparse
import bisect
import copy
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from build_text_audio_map import build_map, sha


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def mapped_seconds(seconds, rate, edits):
    count = bisect.bisect_right([e["source_sample"] for e in edits], seconds * rate)
    return seconds + sum(e["added_samples"] for e in edits[:count]) / rate


def remap_alignment(source, rate, edits, digest, original_hash):
    value = copy.deepcopy(source)
    rows = value.get("units", []) + [
        row for segment in value.get("segments", []) for row in [segment, *segment.get("words", [])]
    ]
    for row in rows:
        for key in ("start", "end"):
            row["original_source_" + key] = row[key]
            row[key] = mapped_seconds(row[key], rate, edits)
    value.update(
        source_sha256=digest,
        original_source_sha256=original_hash,
        time_scale=1.0,
        silence_edit_mapping="sample-accurate sparse insertion offsets",
        new_model_inference=False,
        llm_timing_calls=0,
    )
    return value


def insert_and_verify(samples, edits):
    blocks, spans = [], []
    original, delivery = 0, 0
    for edit in edits:
        position, addition = edit["source_sample"], edit["added_samples"]
        if not original <= position <= len(samples) or addition <= 0:
            raise ValueError("Invalid or unsorted sample edit")
        blocks.extend([samples[original:position], np.zeros(addition, dtype=np.int16)])
        spans.append((original, position, delivery, delivery + position - original))
        delivery += position - original + addition
        original = position
    blocks.append(samples[original:])
    spans.append((original, len(samples), delivery, delivery + len(samples) - original))
    result = np.concatenate(blocks)
    for start, end, new_start, new_end in spans:
        if not np.array_equal(samples[start:end], result[new_start:new_end]):
            raise AssertionError("Original samples were altered")
    if len(result) != len(samples) + sum(e["added_samples"] for e in edits):
        raise AssertionError("Edit duration differs from exact sample budget")
    return result, spans


def apply(audio, alignment_path, lesson, policy_path, out, language):
    policy = json.loads(policy_path.read_text())
    default_mode = "candidates_only" if language == "en" else "annotated_boundaries"
    mode = policy.get("application_mode", policy.get("application_mode_by_language", {}).get(
        language, default_mode
    ))
    allowed = {"candidates_only", "necessary_only", "annotated_boundaries"}
    if mode not in allowed or (language == "en" and mode == "annotated_boundaries"):
        raise ValueError("English requires candidates_only or necessary_only application mode")
    limit = policy.get("maximum_added_seconds_per_point")
    if limit is None or not math.isfinite(limit) or limit <= 0:
        raise ValueError("Course policy must explicitly set a positive per-point addition limit")
    metadata = json.loads(audio.with_suffix(".json").read_text())
    original_hash = sha(audio)
    alignment = json.loads(alignment_path.read_text())
    if metadata["audio_sha256"] != original_hash or alignment["source_sha256"] != original_hash:
        raise ValueError("Source audio, provenance and alignment hashes differ")
    info = sf.info(audio)
    if info.channels != 1 or info.subtype != "PCM_16":
        raise ValueError("Require PCM16 mono; preserve the frozen source")
    samples, rate = sf.read(audio, dtype="int16")
    out.mkdir(parents=True, exist_ok=False)
    mapping = build_map(
        audio, alignment_path, out / "source-timeline", language, lesson=lesson, policy=policy
    )
    if mapping["unresolved_annotations"]:
        raise ValueError(f"Unresolved teaching anchors: {mapping['unresolved_annotations']}")
    edits, decisions = [], []
    for row in mapping["boundaries"]:
        if row["semantic_role"] != "existing_teaching_annotation":
            continue
        decision = copy.deepcopy(row)
        eligible = mode == "annotated_boundaries" or (
            mode == "necessary_only" and row.get("necessary_edit") is True
            and isinstance(row.get("necessity_reason"), str)
            and bool(row["necessity_reason"].strip())
        )
        decision["application_mode"] = mode
        if not eligible:
            decision["application_state"] = "analysis_only_native_gap_preserved"
            decisions.append(decision)
            continue
        if row["pause_state"] == "pause_insert_candidate_requires_listening":
            boundary_limit = row.get("maximum_added_seconds") or limit
            added = round(min(row["additional_gap_budget_s"], boundary_limit) * rate)
            if added / rate >= policy.get("minimum_added_seconds", 0.08):
                edits.append(
                    {
                        "source_sample": row["waveform"]["source_sample"],
                        "source_seconds": row["waveform"]["source_seconds"],
                        "added_samples": added,
                        "added_seconds": added / rate,
                        "purpose": row["purpose"],
                        "source_boundary": row,
                    }
                )
                decision["applied_in_authorized_default_workflow"] = True
                decision["application_state"] = "applied_with_contextual_necessity" if (
                    mode == "necessary_only"
                ) else "applied_annotated_boundary"
        decisions.append(decision)
    edits.sort(key=lambda e: e["source_sample"])
    if len({e["source_sample"] for e in edits}) != len(edits):
        raise ValueError("Duplicate teaching boundaries resolve to the same sample")
    delivery, spans = insert_and_verify(samples, edits)
    target = out / "narration.wav"
    sf.write(target, delivery, rate, subtype="PCM_16")
    reread, new_rate = sf.read(target, dtype="int16")
    if new_rate != rate or not np.array_equal(reread, delivery) or sha(audio) != original_hash:
        raise AssertionError("Output round-trip/source preservation failed")
    digest = sha(target)
    edl = {
        "source": str(audio.resolve()),
        "source_sha256": original_hash,
        "output_sha256": digest,
        "sample_rate": rate,
        "native_duration_seconds": len(samples) / rate,
        "delivery_duration_seconds": len(delivery) / rate,
        "total_added_seconds": (len(delivery) - len(samples)) / rate,
        "edits": edits,
        "application_mode": mode,
        "all_decisions": decisions,
        "retained_spans": spans,
        "source_spans_retained_bit_identical": True,
        "tempo_processing": False,
        "new_speech_generated": False,
        "llm_timing_calls": 0,
        "policy_sha256": sha(policy_path),
        "script_sha256": sha(Path(__file__)),
    }
    save(out / "pause-edl.json", edl)
    save(out / "alignment.json", remap_alignment(alignment, rate, edits, digest, original_hash))
    save(
        out / "remap.json",
        {
            "source_sha256": original_hash,
            "output_sha256": digest,
            "sample_rate": rate,
            "mapping_rule": "source t + inserts at or before t",
            "edits": [{k: e[k] for k in ("source_sample", "added_samples")} for e in edits],
        },
    )
    prior_processing = metadata.get("postprocessing", [])
    if isinstance(prior_processing, dict):
        prior_processing = [{"operation": "prior_processing_record", "details": prior_processing}]
    if not isinstance(prior_processing, list):
        raise TypeError("Unsupported source postprocessing provenance")
    metadata.update(
        audio_sha256=digest,
        original_source_sha256=original_hash,
        duration_seconds=len(delivery) / rate,
        silence_edit_derived_master=bool(edits),
        time_stretch=False,
        postprocessing=prior_processing
        + [
            {
                "operation": "sparse_verified_quiet_insertions" if edits
                else "timeline_analysis_identity",
                "edl": str((out / "pause-edl.json").resolve()),
                "seconds_added": edl["total_added_seconds"],
                "retained_pcm_bit_identical": True,
            }
        ],
    )
    save(out / "narration.json", metadata)
    print("TIMELINE_MASTER_READY", len(edits), round(edl["total_added_seconds"], 3), flush=True)
    return edl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=["zh", "en"], required=True)
    for name in ("audio", "alignment", "lesson", "policy", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    apply(args.audio, args.alignment, args.lesson, args.policy, args.out, args.language)


if __name__ == "__main__":
    main()
