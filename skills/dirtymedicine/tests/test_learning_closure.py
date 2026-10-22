"""Synthetic evidence-contract regressions; actual lesson tests stay private."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_learning_closure import check, language_hash


def fixture():
    language = {"sections": [{"paragraphs": [
        {"id": "p1", "spoken_text": "旧储备拆不开。新生产线仍在工作。"},
        {"id": "p2", "spoken_text": "新生产补不齐消耗时，总供应仍然不足。"},
    ]}]}
    plan = {
        "contract_version": "learning-closure-plan/1", "language": "zh-CN",
        "goals": [
            {"id": "supply", "question": "仍在生产为什么供应不足？", "kind": "preserved_function",
             "introduced_at": "p1", "resolution_by": "p2", "importance_reason": "本段核心矛盾"},
            {"id": "outside", "question": "生产线编号是多少？", "kind": "out_of_scope",
             "introduced_at": "p1", "resolution_by": "p2", "importance_reason": "材料外负控"},
        ],
        "paired_units": [{"paragraph_ids": ["p1", "p2"], "reason": "提出矛盾后解释"}],
    }
    review = {
        "contract_version": "learning-closure-review/1", "language": "zh-CN",
        "draft_language_sha256": language_hash(language), "plan_sha256": language_hash(plan),
        "answers": [
            {"goal_id": "supply", "status": "answered", "answer": "新生产仍可能补不齐消耗。",
             "source_refs": [{"paragraph_id": "p1", "quote": "新生产线仍在工作。"},
                             {"paragraph_id": "p2", "quote": "新生产补不齐消耗时，总供应仍然不足。"}],
             "missing_link": None, "reason": "两段共同给出完整解释"},
            {"goal_id": "outside", "status": "out_of_scope", "answer": None,
             "source_refs": [], "missing_link": None, "reason": "材料未给编号且不属教学目标"},
        ],
        "unplanned_gaps": [], "required_edits": [], "optional_notes": [], "verdict": "pass",
    }
    return {"languages": {"zh-CN": language}}, plan, review


class ClosureTests(unittest.TestCase):
    def run_check(self, change=None):
        draft, plan, review = copy.deepcopy(fixture())
        if change:
            change(draft, plan, review)
        return check(draft, "zh-CN", plan, review)

    def test_multi_paragraph_explanation_is_valid_without_claiming_learning_proof(self):
        report = self.run_check()
        self.assertTrue(report["ready_for_script_review"])
        self.assertFalse(report["semantic_entailment_checked_by_script"])
        self.assertFalse(report["user_accepted"])

    def test_missing_core_answer_cannot_hide_behind_pass(self):
        def change(d, p, r):
            r["answers"][0].update(status="missing", answer=None, source_refs=[],
                                    missing_link="没有说明为何代偿不够")
        self.assertFalse(self.run_check(change)["ready_for_script_review"])

    def test_omitted_goal_is_rejected(self):
        self.assertFalse(self.run_check(lambda d, p, r: r["answers"].pop())["evidence_contract_valid"])

    def test_core_question_cannot_be_dismissed_as_outside_scope(self):
        def change(d, p, r):
            r["answers"][0].update(status="out_of_scope", answer=None, source_refs=[])
        self.assertFalse(self.run_check(change)["evidence_contract_valid"])

    def test_external_knowledge_cannot_answer_control(self):
        def change(d, p, r):
            r["answers"][1].update(status="answered", answer="七号生产线")
        self.assertFalse(self.run_check(change)["evidence_contract_valid"])

    def test_invented_quote_is_rejected(self):
        def change(d, p, r):
            r["answers"][0]["source_refs"][0]["quote"] = "稿子没有这一句"
        self.assertFalse(self.run_check(change)["evidence_contract_valid"])

    def test_future_resolution_cannot_supply_an_earlier_question(self):
        def change(d, p, r):
            p["goals"][0]["resolution_by"] = "p1"
            r["plan_sha256"] = language_hash(p)
        self.assertFalse(self.run_check(change)["evidence_contract_valid"])

    def test_changed_draft_invalidates_review(self):
        def change(d, p, r):
            d["languages"]["zh-CN"]["sections"][0]["paragraphs"][0]["spoken_text"] += "新增条件。"
        self.assertFalse(self.run_check(change)["evidence_contract_valid"])

    def test_unplanned_core_gap_blocks_release(self):
        def change(d, p, r):
            r["unplanned_gaps"] = [{"paragraph_id": "p1", "question": "旧储备为何拆不开？",
                                      "missing_link": "没有说明受阻动作"}]
        self.assertFalse(self.run_check(change)["ready_for_script_review"])


if __name__ == "__main__":
    unittest.main()
