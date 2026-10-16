"""Compare a declared voice recipe with the actual generation receipt and model defaults.

Usage:
    uv run python scripts/audit_voice_recipe.py --profile voice-profile.json \
        --receipt take.json --model-source modeling_moss_tts.py --out audit.json

Read-only audit. Does not alter historical receipts, model weights, text, or audio.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def generation_defaults(path):
    tree = ast.parse(path.read_text())
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "generate"
    )
    arguments = [argument.arg for argument in method.args.args]
    return dict(
        zip(
            arguments[-len(method.args.defaults) :],
            [ast.literal_eval(node) for node in method.args.defaults],
        )
    )


def audit(profile, receipt, defaults):
    errors = []
    warnings = []
    actual_loaded = receipt["adapter_loaded"]
    declared = profile.get("adapter")
    if isinstance(profile.get("adapter_loaded"), bool):
        declared_loaded = profile["adapter_loaded"]
        declared_hash = declared.get("sha256") if declared else None
        if declared and "enabled" in declared and bool(declared["enabled"]) != declared_loaded:
            errors.append("Recipe adapter_loaded and adapter.enabled contradict each other.")
    elif declared is None:
        declared_loaded = False
        declared_hash = None
    elif declared.get("enabled_by_job_variant"):
        declared_loaded = receipt["job"]["variant"] == "adapted"
        declared_hash = declared.get("sha256")
    else:
        declared_loaded = bool(declared.get("enabled", True))
        declared_hash = declared.get("sha256")
    if declared_loaded != actual_loaded:
        errors.append("Declared adapter selection contradicts the actual loaded model.")
    if actual_loaded and declared_hash != receipt.get("adapter_sha256"):
        errors.append("Loaded adapter identity is absent or differs from the declared SHA256.")
    expected = {key: value for key, value in defaults.items() if key != "attention_mask"}
    expected.update(profile["generation"])
    expected.update(receipt.get("job", {}).get("settings", {}))
    recorded = receipt["settings"]
    for key, value in recorded.items():
        if key not in defaults:
            errors.append(f"Unsupported generation argument: {key}")
        elif expected[key] != value:
            errors.append(f"Recorded generation argument contradicts its recipe: {key}")
    implicit = {key: value for key, value in expected.items() if key not in recorded}
    if implicit:
        warnings.append("Effective generation defaults were omitted from the runtime receipt.")
    for key in ["model", "codec"]:
        if profile[key]["revision"] != receipt[key + "_revision"]:
            errors.append(f"Actual {key} revision differs from the declared immutable revision.")
    if profile["reference_sha256"] != receipt["reference_sha256"]:
        errors.append("Actual reference audio differs from the recipe.")
    if receipt.get("hit_length_limit"):
        warnings.append("Generation exhausted its budget; completeness needs actual audio review.")
    return {
        "configuration_consistent": not errors,
        "errors": errors,
        "warnings": warnings,
        "effective_generation_settings": expected,
        "unrecorded_effective_settings": implicit,
        "declared_adapter_loaded": declared_loaded,
        "actual_adapter_loaded": actual_loaded,
        "scope": "Configuration consistency only; this is not a voice naturalness approval.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--tts-input", type=Path,
                        help="Also verify the actual normalized text receipt against this file")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(load(args.profile), load(args.receipt), generation_defaults(args.model_source))
    receipt = load(args.receipt)
    profile_sha = hashlib.sha256(args.profile.read_bytes()).hexdigest()
    report["profile_sha256"] = profile_sha
    if receipt.get("input_profile_sha256") != profile_sha:
        report["errors"].append(
            "Recipe file hash differs from the actual generation input profile."
        )
        report["configuration_consistent"] = False
    report["source_sha256"] = hashlib.sha256(args.model_source.read_bytes()).hexdigest()
    if args.tts_input:
        data = args.tts_input.read_bytes()
        report["tts_input_sha256"] = hashlib.sha256(data).hexdigest()
        normalized_sha = hashlib.sha256(args.tts_input.read_text().strip().encode()).hexdigest()
        if normalized_sha != receipt.get("text_sha256"):
            report["errors"].append("Actual synthesis receipt belongs to a different text input.")
            report["configuration_consistent"] = False
    report["checker_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["state"] = "passed" if report["configuration_consistent"] else "blocked"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "consistent": report["configuration_consistent"],
                "errors": report["errors"],
                "warnings": report["warnings"],
            }
        )
    )
    raise SystemExit(0 if report["configuration_consistent"] else 1)


if __name__ == "__main__":
    main()
