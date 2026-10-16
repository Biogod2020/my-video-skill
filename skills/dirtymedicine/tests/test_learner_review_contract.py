"""Regression checks for contradictory verdicts and valid optional suggestions."""

import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_learner_review import CONTRACT_VERSION, check, language_hash


def fixture():
    value = {
        "sections": [{"paragraphs": [{"id": "p1", "spoken_text": "先说明对象。再解释动作。"}]}]
    }
    corpus = [
        {
            "key": "ref",
            "language": "zh-CN",
            "status": "COMPLETE",
            "reference_role": "accepted_course_prose",
            "acceptance_basis": "synthetic",
            "full_script_sha256": hashlib.sha256("参考动作。".encode()).hexdigest(),
            "blocks": [{"id": "r1", "text": "参考动作。"}],
        }
    ]
    common = {
        "contract_version": CONTRACT_VERSION,
        "language": "zh-CN",
        "draft_language_sha256": language_hash(value),
        "required_edits": [],
        "optional_notes": [],
        "verdict": "pass",
    }
    novice = {
        **copy.deepcopy(common),
        "records": [
            {
                "chunk_id": "p1",
                "original_quote": "先说明对象。",
                "novice_paraphrase": "先认识对象。",
                "causal_chain": [],
                "cognitive_obstacles": [],
                "chunk_goal_understood": True,
                "context_check": {
                    "checked": True,
                    "dependencies": [],
                    "no_dependencies_reason": "初始说明，无回指。",
                },
                "naturalness_check": {"spoken_aloud_problem": "", "ordinary_word_difficulty": ""},
            }
        ],
    }
    comparison = {
        **copy.deepcopy(common),
        "records": [
            {
                "chunk_id": "p1",
                "original_quote": "先说明对象。",
                "paragraph_acceptable": True,
                "comparisons": [
                    {
                        "reference_key": "ref",
                        "comparable": True,
                        "reference_block_id": "r1",
                        "reference_quote": "参考动作。",
                        "observation": "均先建立对象再解释动作。",
                        "required_change": "",
                    }
                ],
            }
        ],
    }
    return {"languages": {"zh-CN": value}}, corpus, novice, comparison


class LearnerContractTests(unittest.TestCase):
    def run_check(self, change=None):
        draft, corpus, novice, comparison = fixture()
        if change:
            change(draft, corpus, novice, comparison)
        return check(draft, "zh-CN", corpus, novice, comparison)

    def test_valid_evidence_does_not_grant_user_acceptance(self):
        report = self.run_check()
        self.assertTrue(report["text_gate_ready"])
        self.assertFalse(report["user_accepted"])
        self.assertFalse(report["context_semantic_entailment_checked_by_script"])

    def test_revise_cannot_pass_with_empty_required_edits(self):
        r = self.run_check(lambda d, c, n, x: n.update(verdict="revise"))
        self.assertFalse(r["text_gate_ready"])

    def test_comparison_revise_cannot_pass(self):
        r = self.run_check(lambda d, c, n, x: x.update(verdict="revise"))
        self.assertFalse(r["text_gate_ready"])

    def test_naturalness_issue_cannot_hide_behind_pass(self):
        def change(d, c, n, x):
            n["records"][0]["naturalness_check"]["spoken_aloud_problem"] = "这里确有口语障碍。"

        r = self.run_check(change)
        self.assertFalse(r["text_gate_ready"])
        self.assertTrue(any("contradicts" in e for e in r["errors"]))

    def test_optional_note_is_not_a_blocker(self):
        r = self.run_check(lambda d, c, n, x: n["optional_notes"].append("可选换一个比喻。"))
        self.assertTrue(r["text_gate_ready"])

    def test_missing_naturalness_field_fails_closed(self):
        r = self.run_check(lambda d, c, n, x: n["records"][0].pop("naturalness_check"))
        self.assertFalse(r["text_gate_ready"])

    def test_missing_contract_version_is_not_current_evidence(self):
        r = self.run_check(lambda d, c, n, x: n.pop("contract_version"))
        self.assertFalse(r["text_gate_ready"])

    def test_string_boolean_is_not_accepted(self):
        r = self.run_check(lambda d, c, n, x: n["records"][0].update(chunk_goal_understood="true"))
        self.assertFalse(r["text_gate_ready"])

    def test_draft_identity_change_invalidates_review(self):
        r = self.run_check(lambda d, c, n, x: n.update(draft_language_sha256="0" * 64))
        self.assertFalse(r["text_gate_ready"])

    def test_local_setup_before_use_passes(self):
        def change(d, c, n, x):
            n["records"][0]["context_check"] = {
                "checked": True,
                "no_dependencies_reason": None,
                "dependencies": [
                    {
                        "fact": "对象已介绍",
                        "use_quote": "再解释动作。",
                        "status": "introduced_here",
                        "source_chunk_id": "p1",
                        "source_quote": "先说明对象。",
                        "learner_question": None,
                    }
                ],
            }

        self.assertTrue(self.run_check(change)["text_gate_ready"])

    def test_local_setup_after_use_fails(self):
        def change(d, c, n, x):
            n["records"][0]["context_check"] = {
                "checked": True,
                "no_dependencies_reason": None,
                "dependencies": [
                    {
                        "fact": "倒置来源",
                        "use_quote": "先说明对象。",
                        "status": "introduced_here",
                        "source_chunk_id": "p1",
                        "source_quote": "再解释动作。",
                        "learner_question": None,
                    }
                ],
            }

        self.assertFalse(self.run_check(change)["text_gate_ready"])

    def test_first_definition_and_derivation_can_be_the_current_assertion(self):
        for status in ("introduced_here", "derived_here"):

            def change(d, c, n, x, status=status):
                n["records"][0]["context_check"] = {
                    "checked": True,
                    "no_dependencies_reason": None,
                    "dependencies": [
                        {
                            "fact": "当前新介绍",
                            "use_quote": "先说明对象。",
                            "status": status,
                            "source_chunk_id": "p1",
                            "source_quote": "先说明对象。",
                            "learner_question": None,
                        }
                    ],
                }

            self.assertTrue(self.run_check(change)["text_gate_ready"])


if __name__ == "__main__":
    unittest.main()
