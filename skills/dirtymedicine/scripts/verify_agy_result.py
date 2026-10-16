"""Validate the current final agy JSON before using it downstream.

Usage:
    python scripts/verify_agy_result.py --response response.json --schema schema.json \
      --previous previous.json --require-change --out selected

Dependencies: jsonschema. Preserve raw responses privately; no model calls.
"""

import argparse
import hashlib
import json
from pathlib import Path

import jsonschema
from agy_result import canonical_hash, select_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--require-change", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.require_change and not args.previous:
        parser.error("--require-change requires --previous")
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"state": "blocked", "model_called": False,
              "raw_response_sha256": hashlib.sha256(args.response.read_bytes()).hexdigest()}
    try:
        outer = json.loads(args.response.read_text())
        schema = json.loads(args.schema.read_text()) if args.schema else None
        result, evidence = select_result(outer, schema)
        report.update(evidence)
        if args.previous:
            before = canonical_hash(json.loads(args.previous.read_text()))
            report.update(previous_result_sha256=before,
                          requested_change_observed=before != canonical_hash(result))
            if args.require_change and not report["requested_change_observed"]:
                raise ValueError("Requested revision returned the unchanged prior result")
        (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        report["state"] = "passed"
    except (ValueError, TypeError, jsonschema.ValidationError, jsonschema.SchemaError) as error:
        report.update(error_type=type(error).__name__, error=str(error))
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("AGY_FINAL_RESULT", report["state"])
    if report["state"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
