"""Align a prepared Chinese course kit on CUDA, retaining native timestamp repair flags.

Usage:
    python scripts/run_qwen_alignment.py --kit private/alignment-kit --out aligned
    python scripts/run_qwen_alignment.py --kit private/alignment-kit --out replay \
        --assemble-only --results prior-native-outputs

Assembly validates original audio, job text/sample ranges and pinned model provenance.
It keeps one core owner per unit and never copies old ASR fine timestamps.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

import soundfile as sf
from build_text_audio_map import sha


def assemble(plan, results, destination):
    units = []
    for job in plan["jobs"]:
        record = json.loads((results / f"{job['id']}.json").read_text())
        if record["source_audio_sha256"] != plan["source_sha256"]:
            raise ValueError("Native result belongs to another mother")
        for key in [
            "start_frame",
            "end_frame",
            "unit_start",
            "unit_end",
            "core_unit_start",
            "core_unit_end",
            "text",
            "language",
            "offset_seconds",
        ]:
            if record["job"][key] != job[key]:
                raise ValueError(f"Native job input changed: {job['id']} {key}")
        pins = plan["model_pins"]
        if record["model"]["model_revision"] != pins["model_revision"] or (
            record["model"]["code_commit"] != pins["repo_commit"]
        ):
            raise ValueError("Native result model pins mismatch")
        rows = record["units"]
        if [u["text"] for u in rows] != plan["units"][job["unit_start"] : job["unit_end"]]:
            raise ValueError("Native output transcript mismatch")
        for i, unit in enumerate(rows, job["unit_start"]):
            if unit["global_unit_index"] != i:
                raise ValueError("Native index mismatch")
            if not job["core_unit_start"] <= i < job["core_unit_end"]:
                continue
            if any(not math.isfinite(unit[k]) for k in ["start", "end"]) or not (
                0 <= unit["start"] <= unit["end"] <= plan["duration_seconds"]
            ):
                raise ValueError("Invalid native global time")
            units.append({**unit, "job": job["id"], "alignment_score": None})
    if [u["global_unit_index"] for u in units] != list(range(len(plan["units"]))):
        raise ValueError("Core ownership is incomplete or duplicated")
    result = {
        "source_sha256": plan["source_sha256"],
        "model": "Qwen3-ForcedAligner-0.6B",
        "model_pins": plan["model_pins"],
        "units": units,
        "scores_exposed": False,
        "content_coverage_proof": False,
        "audio_modified": False,
        "coarse_times_copied_to_output": False,
    }
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def infer(plan, samples, rate, results):
    # Optional GPU dependencies are imported only for inference, not candidate export or replay.
    import numpy as np
    import torch
    from huggingface_hub import snapshot_download
    from qwen_asr import Qwen3ForcedAligner

    pins = plan["model_pins"]
    for package, version in [
        ("qwen-asr", pins["qwen_asr_version"]),
        ("transformers", pins["transformers_version"]),
    ]:
        if importlib.metadata.version(package) != version:
            raise ValueError(f"Install the pinned alignment GPU environment: {package}=={version}")
    package_meta = importlib.metadata.distribution("qwen-asr")
    direct_url = json.loads(package_meta.read_text("direct_url.json") or "{}")
    code_commit = direct_url.get("vcs_info", {}).get("commit_id")
    if code_commit != pins["repo_commit"]:
        raise ValueError("Install qwen-asr from the pinned Git commit, not an unverified wheel")
    if not torch.cuda.is_available():
        raise ValueError("Use the project's owned Colab/CUDA runtime for Qwen inference")
    torch.manual_seed(42)
    model = Qwen3ForcedAligner.from_pretrained(
        snapshot_download(pins["model_id"], revision=pins["model_revision"]),
        dtype=torch.bfloat16,
        device_map="cuda:0",
        attn_implementation="sdpa",
    )
    model.model.eval()
    original = model.aligner_processor.parse_timestamp
    audit = []

    def audited_parse(word_list, timestamps):
        rows = original(word_list, timestamps)
        raw = timestamps.tolist()
        fixed = [v for row in rows for v in [row["start_time"], row["end_time"]]]
        audit.append(
            {
                "raw_timestamp_ms": raw,
                "fixed_timestamp_ms": fixed,
                "repair_indices": [i for i, (a, b) in enumerate(zip(raw, fixed)) if a != b],
            }
        )
        return rows

    model.aligner_processor.parse_timestamp = audited_parse
    environment = {
        "model_id": pins["model_id"],
        "model_revision": pins["model_revision"],
        "code_commit": code_commit,
        "qwen_asr_version": importlib.metadata.version("qwen-asr"),
        "torch_version": torch.__version__,
        "gpu": torch.cuda.get_device_name(),
        "dtype": "bfloat16",
        "attention": "sdpa",
        "timestamp_segment_time_ms": model.timestamp_segment_time,
        "scores_exposed_by_official_output": False,
    }
    for job in plan["jobs"]:
        if not 0 < (job["end_frame"] - job["start_frame"]) / rate < 180:
            raise ValueError("Inference window must be shorter than 180 seconds")
        audit.clear()
        expected = plan["units"][job["unit_start"] : job["unit_end"]]
        input_tokens, _ = model.aligner_processor.encode_timestamp(job["text"], "Chinese")
        if input_tokens != expected:
            raise ValueError("Official tokenizer differs from prepared input")
        clip = samples[job["start_frame"] : job["end_frame"]]
        result = model.align(audio=(clip, rate), text=job["text"], language="Chinese")[0]
        if len(result) != len(expected) or len(audit) != 1:
            raise ValueError("Unexpected official aligner result")
        repaired = set(audit[0]["repair_indices"])
        rows = []
        for i, (token, item) in enumerate(zip(expected, result)):
            if token != item.text:
                raise ValueError("Unexpected native token")
            rows.append(
                {
                    "global_unit_index": job["unit_start"] + i,
                    "text": item.text,
                    "start": item.start_time + job["offset_seconds"],
                    "end": item.end_time + job["offset_seconds"],
                    "local_start": item.start_time,
                    "local_end": item.end_time,
                    "repaired_timestamp": bool({2 * i, 2 * i + 1} & repaired),
                    "alignment_score": None,
                    "native_output_unit": "cjk_character_or_word",
                }
            )
        record = {
            "job": job,
            "units": rows,
            "timestamp_audit": audit[0],
            "model": environment,
            "source_audio_sha256": plan["source_sha256"],
            "lossless_audio_sha256": plan["lossless_sha256"],
            "input_pcm_sha256": hashlib.sha256(np.asarray(clip).tobytes()).hexdigest(),
        }
        (results / f"{job['id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        print("ALIGNED", job["id"], len(rows), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kit", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--assemble-only", action="store_true")
    p.add_argument("--results", type=Path)
    args = p.parse_args()
    plan = json.loads((args.kit / "alignment-plan.json").read_text())
    audio = args.kit / "course.flac"
    if sha(audio) != plan["lossless_sha256"]:
        raise ValueError("Alignment kit audio hash mismatch")
    samples, rate = sf.read(audio, dtype="float32")
    if rate != plan["sample_rate"] or samples.ndim != 1:
        raise ValueError("Invalid kit audio")
    if args.assemble_only and not args.results:
        raise ValueError("--assemble-only requires --results")
    args.out.mkdir(parents=True, exist_ok=False)
    results = args.results if args.assemble_only else args.out / "native"
    if not args.assemble_only:
        results.mkdir()
        infer(plan, samples, rate, results)
    assembled = assemble(plan, results, args.out / "qwen.units.json")
    print("QWEN_TIMELINE_READY", len(assembled["units"]), "native units; audio unmodified")


if __name__ == "__main__":
    main()
