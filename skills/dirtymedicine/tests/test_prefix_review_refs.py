"""Reference-location tests use synthetic text, not private course material."""

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prefix_review_refs import (
    REVIEW_CONTRACT,
    RefContractError,
    build_ref_index,
    build_ref_review_schema,
    decode_ref_review,
)


def input_value(text="物质A被送入装置，装置因此启动。", *, task_kind="causal_understanding"):
    return {
        "case_id": "synthetic-reference-case",
        "language": "zh-CN",
        "task_kind": task_kind,
        "prefix": [
            {"id": "p1", "spoken_text": "物质A是一种输入。"},
            {"id": "p2", "spoken_text": text},
        ],
        "focus_quote": text,
        "question": "请复述材料中的动作。",
    }


def valid_review(index):
    prior = next(ref for ref in index["refs"] if ref["paragraph_id"] == "p1")
    current = [ref for ref in index["refs"] if ref["paragraph_id"] == "p2"]
    return {
        "contract_version": REVIEW_CONTRACT,
        "case_id": index["input"]["case_id"],
        "ref_index_sha256": index["ref_index_sha256"],
        "verdict": "pass",
        "dependencies": [
            {
                "fact": "物质A是输入",
                "use_ref": current[0]["ref_id"],
                "status": "established_before",
                "source_ref": prior["ref_id"],
                "reason": "前段已说明物质A。",
                "learner_question": None,
            }
        ],
        "teach_back_claims": [
            {
                "claim_id": "c1",
                "kind": "inference",
                "text": "材料依次讲述输入与启动。",
                "source_refs": [ref["ref_id"] for ref in current],
            }
        ],
        "negative_control": None,
        "required_edits": [],
        "optional_notes": [],
        "limits": ["仅定位引句。"],
    }


def decode(index, review):
    return decode_ref_review(
        index, review, original_result_bytes=json.dumps(review, ensure_ascii=False).encode()
    )


class PrefixReferenceTests(unittest.TestCase):
    def setUp(self):
        self.index = build_ref_index(input_value())
        self.review = valid_review(self.index)

    def test_lossless_punctuation_decimals_quotes_and_whitespace(self):
        text = "他说“开始！”然后量取 2.5 mg，重复；再看 1,000 个。\n 最后停下。  "
        index = build_ref_index(input_value(text))
        refs = [ref for ref in index["refs"] if ref["paragraph_id"] == "p2"]
        self.assertEqual("".join(ref["text"] for ref in refs), text)
        offset = 0
        for ref in refs:
            self.assertEqual(ref["start"], offset)
            self.assertEqual(text[ref["start"] : ref["end"]], ref["text"])
            offset = ref["end"]
        self.assertEqual(offset, len(text))
        self.assertTrue(any("2.5" in ref["text"] for ref in refs))
        self.assertTrue(any("1,000" in ref["text"] for ref in refs))
        self.assertEqual(refs[0]["text"], "他说“开始！”")

    def test_sentence_and_clause_modes_preserve_same_original(self):
        inp = input_value("甲，乙；丙。丁？")
        sentence = build_ref_index(inp, granularity="sentence")
        clause = build_ref_index(inp, granularity="clause")
        get = lambda index: [r["text"] for r in index["refs"] if r["paragraph_id"] == "p2"]
        self.assertEqual(get(sentence), ["甲，乙；丙。", "丁？"])
        self.assertEqual(get(clause), ["甲，", "乙；", "丙。", "丁？"])

    def test_repeated_words_have_distinct_stable_positions(self):
        inp = input_value("重复，重复，重复。")
        first, second = build_ref_index(inp), build_ref_index(copy.deepcopy(inp))
        self.assertEqual(first, second)
        refs = [ref for ref in first["refs"] if ref["paragraph_id"] == "p2"]
        self.assertEqual([r["start"] for r in refs], [0, 3, 6])
        self.assertEqual(len({r["ref_id"] for r in refs}), 3)

    def test_unchanged_prior_paragraph_keeps_ids_in_longer_prefix(self):
        short = input_value()
        short["prefix"] = short["prefix"][:1]
        short["focus_quote"] = short["prefix"][-1]["spoken_text"]
        first = build_ref_index(short)
        extended = build_ref_index(input_value())
        self.assertEqual(first["refs"], [r for r in extended["refs"] if r["paragraph_id"] == "p1"])

    def test_unicode_offsets_are_code_points(self):
        index = build_ref_index(input_value("α😀，α😀。"))
        refs = [r for r in index["refs"] if r["paragraph_id"] == "p2"]
        self.assertEqual([(r["start"], r["end"]) for r in refs], [(0, 3), (3, 6)])

    def test_cutoff_cannot_include_text_after_focus(self):
        inp = input_value("当前句。未来句。")
        inp["focus_quote"] = "当前句。"
        with self.assertRaisesRegex(RefContractError, "beyond focus"):
            build_ref_index(inp)

    def test_duplicate_paragraph_ids_and_hidden_fields_rejected(self):
        for mutation in ("duplicate", "extra"):
            inp = input_value()
            if mutation == "duplicate":
                inp["prefix"][1]["id"] = "p1"
            else:
                inp["teacher_notes"] = "不应进入引用表。"
            with self.assertRaises(RefContractError):
                build_ref_index(inp)

    def test_index_cannot_be_edited_to_extend_a_span(self):
        index = copy.deepcopy(self.index)
        index["refs"][-1]["end"] += 1
        index["refs"][-1]["text"] += "未来"
        with self.assertRaisesRegex(RefContractError, "changed or malformed"):
            decode(index, self.review)

    def test_schema_enumerates_real_ids_and_typed_arrays(self):
        schema = build_ref_review_schema(self.index)
        jsonschema.Draft202012Validator.check_schema(schema)
        dependency = schema["properties"]["dependencies"]["items"]
        current_ids = [r["ref_id"] for r in self.index["refs"] if r["paragraph_id"] == "p2"]
        self.assertEqual(dependency["properties"]["use_ref"]["enum"], current_ids)
        claim_items = schema["properties"]["teach_back_claims"]["items"]
        self.assertEqual(claim_items["properties"]["source_refs"]["items"]["type"], "string")

    def test_decoder_restores_only_index_text_and_keeps_original_hash(self):
        raw = (json.dumps(self.review, ensure_ascii=False, indent=3) + "\n").encode()
        result = decode_ref_review(self.index, self.review, original_result_bytes=raw)
        dependency = result["result"]["dependencies"][0]
        self.assertEqual(dependency["source_quote"], "物质A是一种输入。")
        self.assertEqual(dependency["use_quote"], "物质A被送入装置，")
        self.assertEqual(dependency["source_chunk_id"], "p1")
        self.assertEqual(
            result["evidence"]["original_result_sha256"], hashlib.sha256(raw).hexdigest()
        )
        binding = result["reference_bindings"]["dependencies"][0]
        self.assertEqual(binding["use_ref"], self.review["dependencies"][0]["use_ref"])
        self.assertEqual(binding["source_span"]["start"], 0)
        self.assertFalse(result["semantic_entailment_checked"])

    def test_wrong_use_source_or_claim_id_fails_closed(self):
        for field in ("use_ref", "source_ref", "claim"):
            review = copy.deepcopy(self.review)
            if field == "claim":
                review["teach_back_claims"][0]["source_refs"] = ["unknown-id"]
            else:
                review["dependencies"][0][field] = "unknown-id"
            with self.subTest(field=field), self.assertRaises(RefContractError):
                decode(self.index, review)

    def test_prior_paragraph_cannot_be_selected_as_current_use(self):
        self.review["dependencies"][0]["use_ref"] = self.review["dependencies"][0]["source_ref"]
        with self.assertRaises(RefContractError):
            decode(self.index, self.review)

    def test_generated_quotes_are_forbidden_in_model_schema(self):
        self.review["dependencies"][0]["source_quote"] = "自由生成的引句。"
        with self.assertRaises(RefContractError):
            decode(self.index, self.review)

    def test_same_ref_first_definition_decodes(self):
        index = build_ref_index(input_value("把A变成B的动作叫作转换。"))
        review = valid_review(index)
        dependency = review["dependencies"][0]
        dependency.update(status="introduced_here", source_ref=dependency["use_ref"])
        decoded = decode(index, review)
        dependency = decoded["result"]["dependencies"][0]
        self.assertEqual(dependency["use_quote"], "把A变成B的动作叫作转换。")
        self.assertEqual(dependency["source_quote"], dependency["use_quote"])

    def test_same_ref_derivation_decodes(self):
        self.review["dependencies"][0].update(
            status="derived_here", source_ref=self.review["dependencies"][0]["use_ref"]
        )
        self.assertEqual(decode(self.index, self.review)["result"]["verdict"], "pass")

    def test_later_local_source_and_same_established_source_fail(self):
        current = [r for r in self.index["refs"] if r["paragraph_id"] == "p2"]
        for status, source in (
            ("introduced_here", current[1]),
            ("derived_here", current[1]),
            ("established_before", current[0]),
        ):
            review = copy.deepcopy(self.review)
            review["dependencies"][0].update(status=status, source_ref=source["ref_id"])
            with self.subTest(status=status), self.assertRaises(RefContractError):
                decode(self.index, review)

    def test_local_introduction_cannot_cite_another_paragraph(self):
        self.review["dependencies"][0]["status"] = "introduced_here"
        with self.assertRaises(RefContractError):
            decode(self.index, self.review)

    def test_missing_and_unclear_decode_only_with_null_source_and_question(self):
        for status in ("missing", "unclear"):
            review = copy.deepcopy(self.review)
            review["verdict"] = "revise" if status == "missing" else "uncertain"
            review["dependencies"][0].update(
                status=status, source_ref=None, learner_question="前提在哪里？"
            )
            result = decode(self.index, review)["result"]["dependencies"][0]
            self.assertIsNone(result["source_quote"])
            self.assertEqual(result["status"], status)
            review["dependencies"][0]["source_ref"] = self.index["refs"][0]["ref_id"]
            with self.assertRaises(RefContractError):
                decode(self.index, review)

    def test_pass_cannot_hide_missing_dependency_or_required_edit(self):
        self.review["required_edits"] = ["必须补充。"]
        with self.assertRaises(RefContractError):
            decode(self.index, self.review)
        self.review["required_edits"] = []
        self.review["dependencies"][0].update(
            status="missing", source_ref=None, learner_question="前提在哪里？"
        )
        with self.assertRaises(RefContractError):
            decode(self.index, self.review)

    def test_patient_observation_needs_quote_but_code_does_not_guess_meaning(self):
        claim = self.review["teach_back_claims"][0]
        claim.update(kind="patient_observation", source_refs=[])
        with self.assertRaises(RefContractError):
            decode(self.index, self.review)
        claim["source_refs"] = [self.index["refs"][0]["ref_id"]]
        result = decode(self.index, self.review)
        self.assertTrue(result["teach_back_claims"][0]["sources"])
        self.assertFalse(result["semantic_entailment_checked"])

    def test_missing_information_claim_can_be_uncited_and_claim_ids_unique(self):
        claim = self.review["teach_back_claims"][0]
        claim.update(kind="missing_information", source_refs=[], text="材料未提供另一项检查。")
        self.assertTrue(decode(self.index, self.review)["teach_back_claims"])
        self.review["teach_back_claims"].append(copy.deepcopy(claim))
        with self.assertRaisesRegex(RefContractError, "claim ID"):
            decode(self.index, self.review)

    def test_negative_control_abstention_and_cited_answer_shapes(self):
        index = build_ref_index(input_value(task_kind="negative_control"))
        review = valid_review(index)
        review["negative_control"] = {
            "answerable_from_material": False,
            "answer": None,
            "source_ref": None,
        }
        self.assertIsNone(decode(index, review)["result"]["negative_control"]["source_quote"])
        review["negative_control"] = {
            "answerable_from_material": True,
            "answer": "给定输入。",
            "source_ref": index["refs"][0]["ref_id"],
        }
        self.assertEqual(
            decode(index, review)["result"]["negative_control"]["source_quote"], "物质A是一种输入。"
        )
        review["negative_control"]["source_ref"] = None
        with self.assertRaises(RefContractError):
            decode(index, review)

    def test_raw_bytes_must_match_and_duplicate_json_keys_fail(self):
        other = copy.deepcopy(self.review)
        other["verdict"] = "uncertain"
        with self.assertRaisesRegex(RefContractError, "raw result"):
            decode_ref_review(
                self.index, self.review, original_result_bytes=json.dumps(other).encode()
            )
        raw = json.dumps(self.review)
        duplicate = ('{"case_id":"duplicate",' + raw[1:]).encode()
        with self.assertRaises(RefContractError):
            decode_ref_review(self.index, self.review, original_result_bytes=duplicate)

    def test_old_index_hash_or_wrong_case_fails(self):
        for key in ("ref_index_sha256", "case_id"):
            review = copy.deepcopy(self.review)
            review[key] = "other"
            with self.subTest(key=key), self.assertRaises(RefContractError):
                decode(self.index, review)


if __name__ == "__main__":
    unittest.main()
