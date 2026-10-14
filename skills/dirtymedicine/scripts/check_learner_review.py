"""Check full paragraph and reference coverage of independent teaching reviews.

Usage: python scripts/check_learner_review.py --draft draft.json --language zh-CN \
    --corpus accepted-corpus.json --novice novice.json --comparison comparison.json \
    --out review-check.json

This checks evidence and unresolved model findings, not actual human learning.
It never calls a model, edits prose, or grants user approval.
"""

import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def language_hash(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def paragraph_rows(draft, language):
    return [p for s in draft["languages"][language]["sections"] for p in s["paragraphs"]]


def unique_index(rows, key):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate {key}")
    return result


def exact_quote(quote, text):
    return isinstance(quote, str) and bool(quote.strip()) and quote in text


def check(draft, language, corpus, novice, comparison):
    paragraphs = unique_index(paragraph_rows(draft, language), "id")
    digest = language_hash(draft["languages"][language])
    references = unique_index(
        [r for r in corpus if r["language"] == language], "key"
    )
    if not paragraphs or not references:
        raise ValueError("Require full current draft and registered same-language references")
    errors, unresolved = [], []
    for key, ref in references.items():
        text = "\n\n".join(block["text"] for block in ref["blocks"])
        actual = hashlib.sha256(text.encode()).hexdigest()
        if (
            ref.get("status") != "COMPLETE"
            or ref.get("reference_role") != "accepted_course_prose"
            or not ref.get("acceptance_basis")
            or actual != ref["full_script_sha256"]
        ):
            errors.append(f"Unverified registered full reference: {key}")
    for kind, review in [("novice", novice), ("comparison", comparison)]:
        if review.get("language") != language or review.get("draft_language_sha256") != digest:
            errors.append(f"{kind}: wrong draft version/language")
        rows = unique_index(review["records"], "chunk_id")
        if set(rows) != set(paragraphs):
            errors.append(f"{kind}: incomplete/extraneous paragraph coverage")
        if review.get("required_edits"):
            unresolved.extend({"review": kind, "finding": r} for r in review["required_edits"])
        for key, row in rows.items():
            if key not in paragraphs:
                continue
            if not exact_quote(row.get("original_quote"), paragraphs[key]["spoken_text"]):
                errors.append(f"{kind}/{key}: quote is not current paragraph text")
            if kind == "novice":
                if not row.get("novice_paraphrase") or not isinstance(row.get("causal_chain"), list):
                    errors.append(f"novice/{key}: missing teach-back/causal evidence")
                if not isinstance(row.get("cognitive_obstacles"), list):
                    errors.append(f"novice/{key}: missing explicit obstacle disposition")
                if row.get("cognitive_obstacles") or row.get("chunk_goal_understood") is not True:
                    unresolved.append({"review": kind, "chunk_id": key, "finding": row})
                for prerequisite in row.get("prerequisites", []):
                    prior = prerequisite["chunk_id"]
                    order = list(paragraphs)
                    if (
                        prior not in paragraphs
                        or order.index(prior) >= order.index(key)
                        or not exact_quote(prerequisite["quote"], paragraphs[prior]["spoken_text"])
                    ):
                        errors.append(f"novice/{key}: prerequisite borrowed from later/missing text")
            else:
                matches = unique_index(row["comparisons"], "reference_key")
                if set(matches) != set(references):
                    errors.append(f"comparison/{key}: omitted/extraneous registered course")
                for ref_key, match in matches.items():
                    if ref_key not in references:
                        continue
                    if match.get("comparable") is True:
                        blocks = unique_index(references[ref_key]["blocks"], "id")
                        block = blocks.get(match.get("reference_block_id"))
                        if not block or not exact_quote(match.get("reference_quote"), block["text"]):
                            errors.append(f"comparison/{key}/{ref_key}: reference quote is ungrounded")
                    elif match.get("comparable") is not False or not match.get("limitation"):
                        errors.append(f"comparison/{key}/{ref_key}: missing match or limitation")
                    if not match.get("observation"):
                        errors.append(f"comparison/{key}/{ref_key}: missing concrete observation")
                    if match.get("required_change"):
                        unresolved.append({"review": kind, "chunk_id": key, "finding": match})
                if row.get("paragraph_acceptable") is not True:
                    unresolved.append({"review": kind, "chunk_id": key, "finding": row})
    return {
        "language": language,
        "draft_language_sha256": digest,
        "paragraph_count": len(paragraphs),
        "registered_references": list(references),
        "expected_comparison_cells": len(paragraphs) * len(references),
        "evidence_checks_passed": not errors,
        "errors": errors,
        "unresolved_model_findings": unresolved,
        "text_gate_ready": not errors and not unresolved,
        "calls_to_llm": 0,
        "human_student_experiment": False,
        "medical_fact_review_required_separately": True,
        "user_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("draft", "corpus", "novice", "comparison", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--language", choices=["zh-CN", "en-US"], required=True)
    args = parser.parse_args()
    report = check(
        read(args.draft), args.language, read(args.corpus), read(args.novice), read(args.comparison)
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in (
        "language", "paragraph_count", "expected_comparison_cells", "text_gate_ready"
    )}))
    if not report["text_gate_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
