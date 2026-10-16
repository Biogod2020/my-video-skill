"""Meaningful fail-closed contracts using synthetic source and review evidence only."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_prefix_review import build_prefix_prompt
from check_source_adjudication import (
    CONTRACT,
    citation,
    digest,
    evaluate,
    expected_item_ids,
    load_batch_context,
    sha,
)
from prefix_review_refs import (
    REVIEW_CONTRACT,
    build_api_review_schema,
    build_ref_index,
    decode_ref_review,
)

ROOT = Path(__file__).resolve().parents[1]
SCOPE = {"subject": "合成装置", "condition": "只按所给前缀", "quantifier": "不扩大程度"}


def put(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return {"path": str(path), "sha256": sha(path)}


class SourceAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Path(self.temp.name)
        self.draft = self.p / "draft.json"
        self.paragraph = {"id": "p1", "spoken_text": "定义物质A。物质A触发装置。"}
        put(self.draft, {"languages": {"zh-CN": {"sections": [{"paragraphs": [self.paragraph]}]}}})
        self.protocol = self.p / "protocol.txt"
        self.protocol.write_text("合成定位协议。")
        self.requests, self.batch, self.ledger = (
            self.p / "requests.json",
            self.p / "results.json",
            self.p / "audit.jsonl",
        )
        self.make_batch()
        self.rows = self.make_rows()

    def make_batch(self, required_edit=False, bad_control=False):
        self.prepared, cases = [], []
        for number in range(2):
            control = number == 1
            inp = {
                "case_id": f"c{number}",
                "language": "zh-CN",
                "task_kind": "negative_control" if control else "spoken_context",
                "prefix": [self.paragraph],
                "focus_quote": self.paragraph["spoken_text"],
                "question": "编号是什么？" if control else "当前动作是什么？",
            }
            index = build_ref_index(inp, granularity="sentence")
            first = index["refs"][0]["ref_id"]
            review = {
                "contract_version": REVIEW_CONTRACT,
                "case_id": inp["case_id"],
                "ref_index_sha256": index["ref_index_sha256"],
                "verdict": "revise" if required_edit and not control else "pass",
                "dependencies": [],
                "teach_back_claims": [
                    {
                        "claim_id": "cl1",
                        "kind": "missing_information" if control else "general_mechanism",
                        "text": "未给编号。" if control else "定义输入物质。",
                        "source_refs": [] if control else [first],
                    }
                ],
                "negative_control": (
                    {
                        "answerable_from_material": bad_control,
                        "answer": "物质A" if bad_control else None,
                        "source_ref": first if bad_control else None,
                    }
                    if control
                    else None
                ),
                "required_edits": ["必须补充。"] if required_edit and not control else [],
                "optional_notes": [],
                "limits": ["合成。"],
            }
            if not control:
                review["dependencies"] = [
                    {
                        "fact": "定义A",
                        "use_ref": first,
                        "status": "introduced_here",
                        "source_ref": first,
                        "reason": "当句定义。",
                        "learner_question": None,
                    }
                ]
            raw = json.dumps(review, ensure_ascii=False).encode()
            decoded = decode_ref_review(index, review, original_result_bytes=raw)
            pre = {
                "case_id": inp["case_id"],
                "input": put(self.p / f"{number}-input.json", inp),
                "ref_index": put(self.p / f"{number}-index.json", index),
                "api_schema": put(self.p / f"{number}-schema.json", build_api_review_schema(index)),
            }
            prompt = self.p / f"{number}-prompt.txt"
            prompt.write_text(build_prefix_prompt(inp, self.protocol.read_text()))
            pre["prompt"] = {"path": str(prompt), "sha256": sha(prompt)}
            self.prepared.append(copy.deepcopy(pre))
            rp = self.p / f"{number}-raw.json"
            rp.write_bytes(raw)
            case = {
                **pre,
                "state": "decoded",
                "raw_result": {"path": str(rp), "sha256": sha(rp)},
                "decoded": put(self.p / f"{number}-decoded.json", decoded),
                "result": put(self.p / f"{number}-result.json", decoded["result"]),
                "transport": put(
                    self.p / f"{number}-transport.json",
                    {
                        "state": "complete",
                        "stateless": True,
                        "finish_reasons": ["STOP"],
                        "prompt_sha256": pre["prompt"]["sha256"],
                        "schema_sha256": pre["api_schema"]["sha256"],
                    },
                ),
            }
            cases.append(case)
        lang = json.loads(self.draft.read_text())["languages"]["zh-CN"]
        meta = {
            "language": "zh-CN",
            "draft_language_sha256": digest(lang),
            "evidence_mode": "selected_refs/1",
            "formatter_sha256": sha(ROOT / "scripts/check_prefix_review.py"),
            "risk_inventory": [],
            "reviewer_protocol": {"path": str(self.protocol), "sha256": sha(self.protocol)},
        }
        put(self.requests, {**meta, "cases": self.prepared})
        put(self.batch, {**meta, "state": "complete", "cases": cases})

    def make_rows(self):
        context = load_batch_context(self.batch, self.draft, "zh-CN")
        self.assertFalse(context["errors"])
        self.context = context
        rows = []
        for cid, case in context["cases"].items():
            first = case["index"]["refs"][0]
            for item in sorted(expected_item_ids(case)):
                selected = []
                if item.startswith("claim/"):
                    claim = case["decoded"]["teach_back_claims"][0]
                    selected = [citation(case["refs"][key]) for key in claim["source_refs"]]
                row = {
                    "schema_version": CONTRACT,
                    "case_id": cid,
                    "item_id": item,
                    "disposition": "SUPPORTED",
                    "reviewer": {
                        "id": "synthetic-auditor",
                        "session_id": "independent-session",
                        "independent_of_candidate": True,
                    },
                    "bindings": copy.deepcopy(case["bindings"]),
                    "rationale": "逐项核对合成来源。",
                    "scope_check": SCOPE,
                    "citations": selected,
                    "counterevidence": [],
                    "correction": None,
                    "checkpoint_context": None,
                }
                if item == "checkpoint_context":
                    row["checkpoint_context"] = {
                        "prefix_read_independently": True,
                        "first_use_checked": True,
                        "no_dependencies_reason": None,
                        "first_dependencies": [
                            {
                                "fact": "独立识别定义A",
                                "use_ref": first["ref_id"],
                                "status": "introduced_here",
                                "source_refs": [first["ref_id"]],
                                "learner_question": None,
                                "blocks_current_focus": False,
                                "rationale": "不是复制raw依赖枚举来当覆盖。",
                            }
                        ],
                    }
                rows.append(row)
        return rows

    def run_audit(self):
        self.ledger.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in self.rows) + "\n"
        )
        return evaluate(self.batch, self.draft, self.ledger, "zh-CN")

    def row(self, item, cid="c0"):
        return next(r for r in self.rows if r["case_id"] == cid and r["item_id"] == item)

    def reviewer_error(self, row):
        ref = citation(self.context["cases"][row["case_id"]]["index"]["refs"][0])
        row.update(
            disposition="REVIEWER_ERROR",
            counterevidence=[ref],
            correction={
                "text": "独立纠正其范围。",
                "claim_kind": "general_mechanism",
                "source_refs": [ref],
                "scope_check": SCOPE,
            },
        )

    def test_complete_current_independent_audit_passes(self):
        result = self.run_audit()
        self.assertEqual(result["state"], "passed")
        self.assertTrue(result["all_items_audited"])
        self.assertFalse(result["semantic_entailment_checked_by_code"])
        self.assertEqual(result["audit_scope"], "production")

    def freeze_single_calibration(self):
        historical = self.p / "historical-results.json"
        historical.write_bytes(self.batch.read_bytes())
        batch = json.loads(self.batch.read_text())
        requests = json.loads(self.requests.read_text())
        scope = {
            "case_id": "c0",
            "historical_batch": {"path": str(historical), "sha256": sha(historical)},
        }
        for obj in (batch, requests):
            obj["cases"] = [c for c in obj["cases"] if c["case_id"] == "c0"]
            obj["audit_scope"] = "calibration_control"
            obj["calibration_control"] = scope
        put(self.batch, batch)
        put(self.requests, requests)
        context = load_batch_context(self.batch, self.draft, "zh-CN", calibration_control=True)
        self.assertFalse(context["errors"])
        self.rows = [r for r in self.rows if r["case_id"] == "c0"]
        for row in self.rows:
            row["bindings"] = context["cases"]["c0"]["bindings"]
        self.ledger.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n")

    def test_calibration_requires_both_flag_and_frozen_scope(self):
        self.freeze_single_calibration()
        self.assertEqual(evaluate(self.batch, self.draft, self.ledger, "zh-CN")["state"], "blocked")
        result = evaluate(self.batch, self.draft, self.ledger, "zh-CN", calibration_control=True)
        self.assertEqual(result["state"], "passed")
        self.assertEqual(result["audit_scope"], "calibration_control")
        self.assertTrue(result["all_items_audited"])
        requests = json.loads(self.requests.read_text())
        requests["audit_scope"] = "production"
        put(self.requests, requests)
        self.assertEqual(
            evaluate(self.batch, self.draft, self.ledger, "zh-CN", calibration_control=True)[
                "state"
            ],
            "blocked",
        )

    def test_calibration_cannot_change_historical_case(self):
        self.freeze_single_calibration()
        batch = json.loads(self.batch.read_text())
        batch["cases"][0]["invented_metadata"] = "changed"
        put(self.batch, batch)
        result = evaluate(self.batch, self.draft, self.ledger, "zh-CN", calibration_control=True)
        self.assertEqual(result["state"], "blocked")
        self.assertFalse(result["independent_audit_completed"])

    def test_each_mandatory_item_type_cannot_be_omitted(self):
        original = copy.deepcopy(self.rows)
        for item in ("checkpoint_context", "claim/cl1", "dependency/0", "negative_control"):
            self.rows = [
                r
                for r in copy.deepcopy(original)
                if not (r["case_id"] == "c0" and r["item_id"] == item)
            ]
            with self.subTest(item=item):
                self.assertEqual(self.run_audit()["state"], "blocked")

    def test_stale_raw_or_protocol_binding_blocks(self):
        for key in (
            "raw_result_sha256",
            "protocol_sha256",
            "draft_language_sha256",
            "decoder_sha256",
        ):
            original = self.row("claim/cl1")["bindings"][key]
            self.row("claim/cl1")["bindings"][key] = "0" * 64
            with self.subTest(key=key):
                self.assertEqual(self.run_audit()["state"], "blocked")
            self.row("claim/cl1")["bindings"][key] = original

    def test_wrong_source_range_or_id_cannot_pass(self):
        row = self.row("claim/cl1")
        row["citations"][0]["end"] += 1
        self.assertEqual(self.run_audit()["state"], "blocked")
        row["citations"][0]["ref_id"] = "unknown"
        self.assertEqual(self.run_audit()["state"], "blocked")

    def test_course_gap_is_complete_but_never_ready(self):
        self.row("checkpoint_context")["disposition"] = "COURSE_GAP"
        result = self.run_audit()
        self.assertTrue(result["independent_audit_completed"])
        self.assertEqual(result["state"], "blocked")
        self.row("checkpoint_context")["resolved"] = True
        self.assertEqual(self.run_audit()["state"], "blocked")

    def test_independent_search_gap_blocks_even_with_supported_stamp(self):
        dep = self.row("checkpoint_context")["checkpoint_context"]["first_dependencies"][0]
        dep.update(
            status="missing",
            source_refs=[],
            learner_question="依据在哪？",
            blocks_current_focus=True,
        )
        result = self.run_audit()
        self.assertEqual(result["state"], "blocked")
        self.assertTrue(any(u["type"] == "independent_context_gap" for u in result["unresolved"]))

    def test_reviewer_error_needs_counterevidence_and_correction(self):
        row = self.row("claim/cl1")
        row["disposition"] = "REVIEWER_ERROR"
        self.assertEqual(self.run_audit()["state"], "blocked")
        self.reviewer_error(row)
        self.assertEqual(self.run_audit()["state"], "passed")
        row["correction"]["source_refs"][0]["start"] += 1
        self.assertEqual(self.run_audit()["state"], "blocked")

    def test_uncertain_blocks(self):
        self.row("claim/cl1")["disposition"] = "UNCERTAIN"
        self.assertEqual(self.run_audit()["state"], "blocked")

    def test_duplicate_or_unknown_items_block(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        self.assertEqual(self.run_audit()["state"], "blocked")
        self.rows[-1]["item_id"] = "claim/not-present"
        self.assertEqual(self.run_audit()["state"], "blocked")

    def test_unexecuted_or_removed_checkpoint_cannot_be_hidden(self):
        batch = json.loads(self.batch.read_text())
        batch["cases"].pop()
        put(self.batch, batch)
        result = self.run_audit()
        self.assertEqual(result["state"], "blocked")
        self.assertTrue(
            any("frozen request cases" in u.get("reason", "") for u in result["unresolved"])
        )

    def test_required_edit_is_covered_and_confirmed_edit_blocks(self):
        self.make_batch(required_edit=True)
        self.rows = self.make_rows()
        result = self.run_audit()
        self.assertEqual(result["state"], "blocked")
        self.assertTrue(any(u["type"] == "confirmed_required_edit" for u in result["unresolved"]))
        self.reviewer_error(self.row("required_edit/0"))
        self.assertEqual(self.run_audit()["state"], "passed")

    def test_wrong_negative_control_cannot_hide_behind_supported(self):
        self.make_batch(bad_control=True)
        self.rows = self.make_rows()
        self.assertEqual(self.run_audit()["state"], "blocked")
        row = self.row("negative_control", "c1")
        self.reviewer_error(row)
        row["correction"].update(
            claim_kind="missing_information",
            source_refs=[],
            negative_control={
                "answerable_from_material": False,
                "answer": None,
                "source_quote": None,
            },
        )
        self.assertEqual(self.run_audit()["state"], "passed")

    def test_explicit_backend_schema_is_bound_without_weakening_local_decoder(self):
        batch = json.loads(self.batch.read_text())
        case = batch["cases"][0]
        alternate = put(self.p / "backend-schema.json", {"type": "object"})
        case["transport_schema"] = alternate
        transport = json.loads(Path(case["transport"]["path"]).read_text())
        transport["schema_sha256"] = alternate["sha256"]
        case["transport"] = put(Path(case["transport"]["path"]), transport)
        put(self.batch, batch)
        self.rows = self.make_rows()
        self.assertEqual(self.run_audit()["state"], "passed")
        alternate_path = Path(alternate["path"])
        alternate_path.write_text("{}")
        self.assertEqual(self.run_audit()["state"], "blocked")

    def test_independent_first_use_cannot_borrow_later_source(self):
        case = self.context["cases"]["c0"]
        first, later = case["index"]["refs"]
        dep = self.row("checkpoint_context")["checkpoint_context"]["first_dependencies"][0]
        dep.update(
            use_ref=first["ref_id"], status="established_before", source_refs=[later["ref_id"]]
        )
        self.assertEqual(self.run_audit()["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
