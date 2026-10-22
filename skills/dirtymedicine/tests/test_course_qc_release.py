"""Synthetic release-state tests; these fixtures are not actual media reviews."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from course_qc import CHECK_CONTRACT, CONTRACT, digest, evaluate, file_digest, read

POLICY = Path(__file__).resolve().parents[1] / "scripts/course_qc.policy.json"


def put(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))
    return {"path": str(path), "sha256": file_digest(path)}


def set_pointer(value, pointer, content):
    parts = pointer[1:].split("/")
    for part in parts[:-1]:
        value = value.setdefault(part, {})
    value[parts[-1]] = content


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Path(self.temp.name)
        self.policy = read(POLICY)
        self.m = {
            "schema_version": CONTRACT,
            "candidate_id": "synthetic-zh-v1",
            "language": "zh-CN",
            "target": "private-video-review",
            "release_policy": str(POLICY),
            "artifacts": {},
            "checks": {},
            "issues": [],
            "policy_files": {},
        }
        artifact_ids = {
            a
            for key in self.policy["targets"][self.m["target"]]
            for a in self.policy["checks"][key]["required_artifacts"]
        }
        for key in artifact_ids:
            body = (
                {"languages": {"zh-CN": {"sections": []}}} if key == "draft" else {"fixture": key}
            )
            self.m["artifacts"][key] = put(self.p / f"{key}.json", body)
        for key, parents in self.policy["artifact_dependencies"].items():
            if key in self.m["artifacts"]:
                self.m["artifacts"][key]["built_from"] = {
                    a: self.m["artifacts"][a]["sha256"] for a in parents
                }
        families = {
            f
            for key in self.policy["targets"][self.m["target"]]
            for f in self.policy["checks"][key]["required_policies"]
        }
        for name in families:
            self.m["policy_files"][name] = put(self.p / f"policy-{name}.json", {"rule": name})
        self.tool = put(self.p / "validator.py", "synthetic tool identity")
        for key in self.policy["targets"][self.m["target"]]:
            rule = self.policy["checks"][key]
            results = {}
            for condition in rule["conditions"]:
                body = results.setdefault(condition["evidence"], {})
                set_pointer(body, condition["pointer"], condition["equals"])
            for identity in rule["result_identity"]:
                expected = self.m["artifacts"][identity["artifact"]]["sha256"]
                if identity.get("mode") == "draft_language":
                    expected = digest({"sections": []})
                body = results.setdefault(identity["evidence"], {})
                set_pointer(body, identity["pointer"].replace("{language}", "zh-CN"), expected)
            for identity in rule.get("literal_identity", []):
                set_pointer(
                    results[identity["evidence"]],
                    identity["pointer"],
                    self.m[identity["manifest_key"]],
                )
            for identity in rule.get("result_tool_identity", []):
                set_pointer(results[identity["evidence"]], identity["pointer"], self.tool["sha256"])
            if rule.get("full_media_artifact"):
                artifact = self.m["artifacts"][rule["full_media_artifact"]]
                results["transport"] = {
                    "state": "complete",
                    "actual_media": [artifact],
                    "complete_unchanged_media_file": True,
                    "audio_not_trimmed": True,
                    "finish_reasons": ["STOP"],
                }
            prompt = put(self.p / f"{key}-prompt.txt", "synthetic prompt")
            if rule["reviewer_kind"] == "model":
                results.setdefault("transport", {}).update(
                    state="complete", prompt_sha256=prompt["sha256"], stateless=True
                )
            evidence = {
                name: put(self.p / f"{key}-{name}.json", body) for name, body in results.items()
            }
            if rule["reviewer_kind"] == "model":
                evidence["prompt"] = prompt
            receipt = {
                "schema_version": CHECK_CONTRACT,
                "check_id": key,
                "candidate_id": self.m["candidate_id"],
                "language": "zh-CN",
                "status": "PASS",
                "rule_sha256": digest(rule),
                "bindings": {
                    "artifacts": {
                        a: self.m["artifacts"][a]["sha256"] for a in rule["required_artifacts"]
                    },
                    "tools": {"validator": self.tool},
                    "policies": {f: self.m["policy_files"][f] for f in rule["required_policies"]},
                },
                "evidence": evidence,
                "reviewer_kind": rule["reviewer_kind"],
                "prompt_sha256": prompt["sha256"],
                "independence": "stateless fixture",
                "open_blocking_issues": [],
            }
            self.m["checks"][key] = put(self.p / f"{key}-receipt.json", receipt)

    def run_release(self):
        path = self.p / "current-release.json"
        put(path, self.m)
        return evaluate(path)

    def alter_receipt(self, key, fn):
        path = Path(self.m["checks"][key]["path"])
        body = read(path)
        fn(body)
        self.m["checks"][key] = put(path, body)

    def test_missing_learning_closure_blocks_release(self):
        def remove_closure(receipt):
            receipt["evidence"].pop("closure")

        self.alter_receipt("learner", remove_closure)
        report = self.run_release()
        self.assertNotEqual(report["checks"]["learner"]["status"], "PASS")
        self.assertNotEqual(report["status"], "REVIEW_READY")

    def test_changed_learning_plan_invalidates_learner_evidence(self):
        path = Path(self.m["artifacts"]["learning_plan"]["path"])
        path.write_text('{"changed": true}')
        report = self.run_release()
        self.assertEqual(report["checks"]["learner"]["status"], "STALE")
        self.assertNotEqual(report["status"], "REVIEW_READY")

    def test_review_ready_does_not_require_or_create_user_acceptance(self):
        r = self.run_release()
        self.assertTrue(r["ready_for_target"])
        self.assertFalse(r["user_accepted"])
        self.assertFalse(r["published"])

    def test_missing_receipt_blocks_despite_cached_ready(self):
        self.m["cached_ready"] = True
        self.m["checks"].pop("prefix")
        r = self.run_release()
        self.assertFalse(r["ready_for_target"])
        self.assertEqual(r["checks"]["prefix"]["status"], "NOT_RUN")

    def test_model_pass_cannot_replace_source_adjudication(self):
        self.m["checks"].pop("source_audit")
        r = self.run_release()
        self.assertFalse(r["ready_for_target"])
        self.assertEqual(r["checks"]["source_audit"]["status"], "NOT_RUN")

    def test_unresolved_source_gap_blocks_even_if_model_and_calibration_pass(self):
        receipt = read(Path(self.m["checks"]["source_audit"]["path"]))
        path = Path(receipt["evidence"]["result"]["path"])
        body = read(path)
        body["unresolved"] = ["Unreported patient finding used as evidence"]
        receipt["evidence"]["result"] = put(path, body)
        self.m["checks"]["source_audit"] = put(Path(self.m["checks"]["source_audit"]["path"]), receipt)
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_model_independence_claim_without_transport_blocks(self):
        self.alter_receipt("medical", lambda r: r["evidence"].pop("transport"))
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_model_prompt_hash_must_match_actual_request(self):
        self.alter_receipt("medical", lambda r: r.update(prompt_sha256="wrong"))
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_old_inner_checker_cannot_be_rebound_to_new_tool(self):
        path = Path(self.m["checks"]["learner"]["path"])
        receipt = read(path)
        result_path = Path(receipt["evidence"]["result"]["path"])
        body = read(result_path)
        body["checker_sha256"] = "old checker"
        receipt["evidence"]["result"] = put(result_path, body)
        self.m["checks"]["learner"] = put(path, receipt)
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_changed_draft_invalidates_bound_checks(self):
        Path(self.m["artifacts"]["draft"]["path"]).write_text("changed")
        r = self.run_release()
        self.assertFalse(r["ready_for_target"])
        self.assertEqual(r["checks"]["learner"]["status"], "STALE")

    def test_changed_upstream_invalidates_derived_artifact(self):
        self.m["artifacts"]["audio"]["built_from"] = {"tts_input": "0" * 64}
        r = self.run_release()
        self.assertFalse(r["ready_for_target"])
        self.assertTrue(r["artifact_dependency_errors"]["audio"])

    def test_old_rule_receipt_is_stale(self):
        self.alter_receipt("prefix", lambda r: r.update(rule_sha256="old"))
        r = self.run_release()
        self.assertEqual(r["checks"]["prefix"]["status"], "STALE")

    def test_changed_checker_invalidates_receipts(self):
        Path(self.tool["path"]).write_text("new tool")
        r = self.run_release()
        self.assertFalse(r["ready_for_target"])

    def test_failure_cannot_be_overridden_by_receipt_pass(self):
        path = Path(self.m["checks"]["medical"]["path"])
        receipt = read(path)
        result_path = Path(receipt["evidence"]["result"]["path"])
        body = read(result_path)
        body["verdict"] = "revise"
        receipt["evidence"]["result"] = put(result_path, body)
        self.m["checks"]["medical"] = put(path, receipt)
        r = self.run_release()
        self.assertEqual(r["checks"]["medical"]["status"], "FAIL")

    def test_full_media_hash_must_match(self):
        path = Path(self.m["checks"]["video_review"]["path"])
        receipt = read(path)
        transport_path = Path(receipt["evidence"]["transport"]["path"])
        body = read(transport_path)
        body["actual_media"][0]["sha256"] = "old"
        receipt["evidence"]["transport"] = put(transport_path, body)
        self.m["checks"]["video_review"] = put(path, receipt)
        r = self.run_release()
        self.assertEqual(r["checks"]["video_review"]["status"], "FAIL")

    def test_uncertain_is_not_pass(self):
        self.alter_receipt("prefix", lambda r: r.update(status="UNCERTAIN"))
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_open_issue_blocks_and_optional_cannot_hide_it(self):
        for status in ("OPEN", "OPTIONAL"):
            self.m["issues"] = [{"id": "i1", "original_severity": "BLOCKING", "status": status}]
            self.assertFalse(self.run_release()["ready_for_target"])

    def test_evidence_based_rejection_can_close_false_positive(self):
        evidence = put(
            self.p / "frame-evidence.json",
            {
                "actual": "synthetic frame record",
                "issue_id": "i1",
                "resolved": True,
                "disposition": "REJECTED_WITH_EVIDENCE",
            },
        )
        proof = {
            "issue_id": "i1",
            "status": "REJECTED_WITH_EVIDENCE",
            "artifact_bindings": {"video": self.m["artifacts"]["video"]["sha256"]},
            "evidence": {"decision": evidence},
        }
        self.m["issues"] = [
            {
                "id": "i1",
                "original_severity": "BLOCKING",
                "status": "REJECTED_WITH_EVIDENCE",
                "required_checks": ["video_review"],
                "closure": put(self.p / "closure.json", proof),
            }
        ]
        self.assertTrue(self.run_release()["ready_for_target"])

    def test_model_check_cannot_claim_engineering_kind(self):
        self.alter_receipt("video_review", lambda r: r.update(reviewer_kind="engineering"))
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_inner_learner_language_must_match(self):
        path = Path(self.m["checks"]["learner"]["path"])
        r = read(path)
        result_path = Path(r["evidence"]["result"]["path"])
        data = read(result_path)
        data["language"] = "en-US"
        r["evidence"]["result"] = put(result_path, data)
        self.m["checks"]["learner"] = put(path, r)
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_required_policy_cannot_be_omitted(self):
        self.alter_receipt("prefix", lambda r: r["bindings"].update(policies={}))
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_required_provenance_edge_cannot_be_omitted(self):
        self.m["artifacts"]["audio"].pop("built_from")
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_unresolved_closure_decision_cannot_be_wrapped_as_fixed(self):
        evidence = put(
            self.p / "unresolved.json",
            {"issue_id": "i1", "resolved": False, "disposition": "VERIFIED_FIXED"},
        )
        proof = {
            "issue_id": "i1",
            "status": "VERIFIED_FIXED",
            "artifact_bindings": {"video": self.m["artifacts"]["video"]["sha256"]},
            "evidence": {"decision": evidence},
        }
        self.m["issues"] = [
            {
                "id": "i1",
                "original_severity": "BLOCKING",
                "status": "VERIFIED_FIXED",
                "required_checks": ["video_review"],
                "closure": put(self.p / "bad-closure.json", proof),
            }
        ]
        self.assertFalse(self.run_release()["ready_for_target"])

    def test_author_cannot_review_same_session(self):
        self.m["author_session"] = "same-session"

        def change(r):
            r.update(
                reviewer_kind="model",
                reviewer_session="same-session",
                prompt_sha256="prompt",
                independence="new_session",
            )

        self.alter_receipt("medical", change)
        self.assertEqual(self.run_release()["checks"]["medical"]["status"], "FAIL")

    def test_script_review_does_not_require_audio_or_user_acceptance(self):
        self.m["target"] = "script-review"
        self.m["checks"] = {
            k: v
            for k, v in self.m["checks"].items()
            if k in self.policy["targets"]["script-review"]
        }
        self.assertTrue(self.run_release()["ready_for_target"])


if __name__ == "__main__":
    unittest.main()
