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

import jsonschema

CONTRACT_VERSION = "learner-review/1"
SCHEMA_PATH = Path(__file__).with_name("learner_review.schema.json")


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


def review_shape_errors(review, kind):
    """Validate the consumer contract, not the truth of a model's judgement."""
    schema = read(SCHEMA_PATH)
    target = {"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]}
    validator = jsonschema.Draft202012Validator(target)
    return [
        f"{kind}/{'.'.join(map(str, error.absolute_path))}: {error.message}"
        for error in sorted(validator.iter_errors(review), key=lambda e: str(e.absolute_path))
    ]


def check_context(row, key, paragraphs, errors, unresolved):
    """Verify cited spoken setup, without pretending to infer semantic entailment."""
    label = f"novice/{key}/context"
    context = row.get("context_check")
    if not isinstance(context, dict) or context.get("checked") is not True:
        errors.append(f"{label}: missing explicit context review")
        return
    if not {"checked", "dependencies", "no_dependencies_reason"} <= context.keys():
        errors.append(f"{label}: incomplete context review fields")
    dependencies = context.get("dependencies")
    if not isinstance(dependencies, list):
        errors.append(f"{label}: dependencies must be a list")
        return
    reason = context.get("no_dependencies_reason")
    if not dependencies and (not isinstance(reason, str) or not reason.strip()):
        errors.append(f"{label}: empty dependency list needs an explicit reason")
    order = list(paragraphs)
    current = paragraphs[key]["spoken_text"]
    for index, dependency in enumerate(dependencies):
        item = f"{label}/{index}"
        if not isinstance(dependency, dict):
            errors.append(f"{item}: invalid dependency record")
            continue
        required = {
            "fact",
            "use_quote",
            "status",
            "source_chunk_id",
            "source_quote",
            "learner_question",
        }
        if not required <= dependency.keys():
            errors.append(f"{item}: incomplete dependency evidence fields")
        if not isinstance(dependency.get("fact"), str) or not dependency["fact"].strip():
            errors.append(f"{item}: missing assumed fact/referent")
        use = dependency.get("use_quote")
        if not exact_quote(use, current):
            errors.append(f"{item}: use quote is not current spoken text")
        status = dependency.get("status")
        if not isinstance(status, str):
            errors.append(f"{item}: dependency status must be text")
            continue
        if status in {"missing", "unclear"}:
            question = dependency.get("learner_question")
            if not isinstance(question, str) or not question.strip():
                errors.append(f"{item}: missing concrete learner question")
            unresolved.append({"review": "context", "chunk_id": key, "finding": dependency})
            continue
        if status not in {"established_before", "introduced_here", "derived_here"}:
            errors.append(f"{item}: unknown dependency status")
            continue
        source_id, quote = dependency.get("source_chunk_id"), dependency.get("source_quote")
        if not isinstance(source_id, str) or source_id not in paragraphs:
            errors.append(f"{item}: source is not a supplied spoken paragraph")
            continue
        source = paragraphs[source_id]["spoken_text"]
        if not exact_quote(quote, source):
            errors.append(f"{item}: setup quote is not actual spoken text")
            continue
        if order.index(source_id) > order.index(key):
            errors.append(f"{item}: setup borrowed from later paragraph")
        elif status == "introduced_here" and source_id != key:
            errors.append(f"{item}: local introduction must be in the current paragraph")
        elif source_id == key and exact_quote(use, current):
            if current.count(quote) != 1 or current.count(use) != 1:
                errors.append(f"{item}: local setup/use quotes need unique positions")
            elif status == "established_before":
                if current.index(quote) + len(quote) > current.index(use):
                    errors.append(f"{item}: earlier local setup must precede its use")
            elif current.index(quote) > current.index(use) or (
                current.index(quote) + len(quote) > current.index(use) and use not in quote
            ):
                errors.append(f"{item}: local definition/derivation borrows later text")


def check(draft, language, corpus, novice, comparison):
    paragraphs = unique_index(paragraph_rows(draft, language), "id")
    digest = language_hash(draft["languages"][language])
    references = unique_index([r for r in corpus if r["language"] == language], "key")
    if not paragraphs or not references:
        raise ValueError("Require full current draft and registered same-language references")
    errors, unresolved = [], []
    shape_errors = [
        error
        for kind, review in (("novice", novice), ("comparison", comparison))
        for error in review_shape_errors(review, kind)
    ]
    if shape_errors:
        return make_report(
            language, digest, paragraphs, references, shape_errors, [], novice, comparison
        )
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
        before_findings = len(unresolved)
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
                check_context(row, key, paragraphs, errors, unresolved)
                for field, finding in row["naturalness_check"].items():
                    if finding.strip():
                        unresolved.append(
                            {
                                "review": kind,
                                "chunk_id": key,
                                "category": "naturalness",
                                "field": field,
                                "finding": finding,
                            }
                        )
                if not row.get("novice_paraphrase") or not isinstance(
                    row.get("causal_chain"), list
                ):
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
                        errors.append(
                            f"novice/{key}: prerequisite borrowed from later/missing text"
                        )
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
                        if not block or not exact_quote(
                            match.get("reference_quote"), block["text"]
                        ):
                            errors.append(
                                f"comparison/{key}/{ref_key}: reference quote is ungrounded"
                            )
                    elif match.get("comparable") is not False or not match.get("limitation"):
                        errors.append(f"comparison/{key}/{ref_key}: missing match or limitation")
                    if not match.get("observation"):
                        errors.append(f"comparison/{key}/{ref_key}: missing concrete observation")
                    if match.get("required_change"):
                        unresolved.append({"review": kind, "chunk_id": key, "finding": match})
                if row.get("paragraph_acceptable") is not True:
                    unresolved.append({"review": kind, "chunk_id": key, "finding": row})
        findings_present = len(unresolved) > before_findings
        if review["verdict"] != "pass":
            unresolved.append(
                {"review": kind, "category": "overall_verdict", "finding": review["verdict"]}
            )
            if review["verdict"] == "revise" and not findings_present:
                errors.append(f"{kind}: revise verdict has no concrete required finding")
        elif findings_present:
            errors.append(f"{kind}: pass verdict contradicts unresolved required findings")
    return make_report(
        language, digest, paragraphs, references, errors, unresolved, novice, comparison
    )


def make_report(language, digest, paragraphs, references, errors, unresolved, novice, comparison):
    """Keep evidence validity, reported semantics and user acceptance separate."""
    return {
        "contract_version": CONTRACT_VERSION,
        "language": language,
        "draft_language_sha256": digest,
        "paragraph_count": len(paragraphs),
        "registered_references": list(references),
        "expected_comparison_cells": len(paragraphs) * len(references),
        "evidence_checks_passed": not errors,
        "evidence_contract_valid": not errors,
        "errors": errors,
        "unresolved_model_findings": unresolved,
        "text_gate_ready": not errors and not unresolved,
        "gate_scope": "paragraph review evidence and reported findings only; not course release",
        "review_verdicts": {
            "novice": novice.get("verdict"),
            "comparison": comparison.get("verdict"),
        },
        "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
        "context_review_required": True,
        "context_semantic_entailment_checked_by_script": False,
        "actual_visible_slide_context_review_required_separately": True,
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
    report["input_files"] = {
        name: {
            "path": str(getattr(args, name).resolve()),
            "sha256": hashlib.sha256(getattr(args, name).read_bytes()).hexdigest(),
        }
        for name in ("draft", "corpus", "novice", "comparison")
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "language",
                    "paragraph_count",
                    "expected_comparison_cells",
                    "text_gate_ready",
                )
            }
        )
    )
    if not report["text_gate_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
