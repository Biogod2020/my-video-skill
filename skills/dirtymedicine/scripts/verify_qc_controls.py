"""Validate assisted-review safeguards while retaining the model's failed blind score.

Usage: python scripts/verify_qc_controls.py --score heldout/score.json \
    --historical-control historical-source-audit.json --out calibration-controls.json
PASS applies to the assisted-use controls, never changes raw holdout_passed:false.
"""
import argparse
import hashlib
import json
import sys
import unittest
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ["score", "historical-control", "out"]:
        p.add_argument("--" + key, type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    names = ["test_source_adjudication", "test_course_qc_release"]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    score = json.loads(a.score.read_text())
    control = json.loads(a.historical_control.read_text())
    errors = []
    if score["state"] != "blocked" or score["holdout_passed"] is not False:
        errors.append("Expected the unmodified failed historical holdout record")
    if score.get("labels_provided_to_model") is not False:
        errors.append("Historical labels were not blinded")
    if (control["state"] != "blocked" or control.get("audit_scope") != "calibration_control"
            or not control["independent_audit_completed"]
            or not control["all_items_audited"] or not control["unresolved"]):
        errors.append("Independent control did not completely audit and block the actual historical gap")
    if not result.wasSuccessful() or result.skipped or result.testsRun < 37:
        errors.append("Required release/source-adjudication negative controls failed")
    report = {"state": "passed" if not errors else "blocked", "unresolved": errors,
              "scope": "limited_assisted_use", "labels_provided_to_model": False,
              "raw_model_failures_retained": True, "source_adjudication_required": True,
              "known_failure_controls_verified": not errors,
              "raw_model_holdout_passed": score["holdout_passed"],
              "raw_model_classification": score["classification"],
              "raw_model_core_source_fidelity": score["core_source_fidelity"],
              "reviewer_protocol_sha256": score["reviewer_protocol_sha256"],
              "checker_sha256": sha(Path(__file__)),
              "inputs": {"raw_score": {"path": str(a.score.resolve()), "sha256": sha(a.score)},
                         "historical_control": {"path": str(a.historical_control.resolve()),
                                                "sha256": sha(a.historical_control)}},
              "actual_test_count": result.testsRun,
              "test_failures": len(result.failures), "test_errors": len(result.errors),
              "test_sources": {name: sha(root / "tests" / (name + ".py")) for name in names},
              "controlled_tools": {name: sha(root / "scripts" / name) for name in
                                   ["course_qc.py", "course_qc.policy.json", "check_source_adjudication.py"]},
              "limits": ["Model blind audit still failed; this is not a model reliability certificate.",
                         "Independent complete source adjudication and actual full media review remain mandatory for every current course."]}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report["state"], report["scope"], errors)
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
