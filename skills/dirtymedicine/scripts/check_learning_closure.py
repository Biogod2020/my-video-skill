"""Check coverage and sources for material-grounded learning questions.

Usage: python scripts/check_learning_closure.py --draft draft.json --language zh-CN \
    --plan plan.json --review review.json --out closure-check.json

This validates a model's evidence contract, not causal entailment or human learning.
An independent reviewer must still check whether the cited text supports the answer.
"""

import argparse
import hashlib
import json
from pathlib import Path

import jsonschema
from check_learner_review import language_hash, paragraph_rows

SCHEMA_PATH = Path(__file__).with_name("learning_closure.schema.json")


def read(path):
    return json.loads(Path(path).read_text())


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(draft, language, plan, review):
    """Fail closed on missing goals, ungrounded answers, or unresolved findings."""
    schema = read(SCHEMA_PATH)
    errors, unresolved = [], []
    for kind, value in (("plan", plan), ("review", review)):
        validator = jsonschema.Draft202012Validator(
            {"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]}
        )
        errors.extend(
            f"{kind}/{'.'.join(map(str, e.absolute_path))}: {e.message}"
            for e in validator.iter_errors(value)
        )
    digest = language_hash(draft["languages"][language])
    if not errors:
        rows = paragraph_rows(draft, language)
        paragraphs = {r["id"]: r["spoken_text"] for r in rows}
        order = {r["id"]: i for i, r in enumerate(rows)}
        goals = {g["id"]: g for g in plan["goals"]}
        answers = {r["goal_id"]: r for r in review["answers"]}
        if len(paragraphs) != len(rows):
            errors.append("duplicate paragraph IDs")
        if len(goals) != len(plan["goals"]) or len(answers) != len(review["answers"]):
            errors.append("duplicate goal or answer IDs")
        if set(goals) != set(answers):
            errors.append("missing or extraneous learning-question answers")
        if not any(g["kind"] != "out_of_scope" for g in goals.values()):
            errors.append("plan has no core learning question")
        if plan["language"] != language or review["language"] != language:
            errors.append("language mismatch")
        if review["draft_language_sha256"] != digest:
            errors.append("review describes another draft version")
        if review["plan_sha256"] != language_hash(plan):
            errors.append("review describes another learning plan")
        for unit in plan["paired_units"]:
            ids = unit["paragraph_ids"]
            if len(set(ids)) != len(ids) or any(pid not in paragraphs for pid in ids):
                errors.append("paired unit contains missing or duplicate paragraphs")
        for gid, goal in goals.items():
            first, last = goal["introduced_at"], goal["resolution_by"]
            if first not in order or last not in order or order[first] > order[last]:
                errors.append(f"{gid}: invalid teaching interval")
                continue
            answer = answers.get(gid)
            if answer is None:
                continue
            status = answer["status"]
            if goal["kind"] == "out_of_scope":
                if (
                    status != "out_of_scope"
                    or answer["answer"] is not None
                    or answer["source_refs"]
                    or answer["missing_link"] is not None
                ):
                    errors.append(f"{gid}: outside-scope control answered or treated as a gap")
            elif status != "answered":
                unresolved.append({"goal_id": gid, "finding": answer})
                if status not in {"missing", "unclear"} or not answer["missing_link"]:
                    errors.append(f"{gid}: core question needs a concrete gap disposition")
                if answer["answer"] is not None:
                    errors.append(f"{gid}: missing answer must not be filled from outside knowledge")
            elif (
                not answer["answer"]
                or not answer["answer"].strip()
                or not answer["source_refs"]
                or answer["missing_link"] is not None
            ):
                errors.append(f"{gid}: answered question lacks complete evidence")
            for ref in answer["source_refs"]:
                pid, quote = ref["paragraph_id"], ref["quote"]
                if pid not in paragraphs or not quote.strip() or quote not in paragraphs[pid]:
                    errors.append(f"{gid}: cited words are not the actual spoken paragraph")
                elif order[pid] > order[last]:
                    errors.append(f"{gid}: explanation borrowed from after its required use")
        for gap in review["unplanned_gaps"]:
            if gap["paragraph_id"] not in paragraphs:
                errors.append("unplanned gap cites a missing paragraph")
            unresolved.append({"unplanned_gap": gap})
        unresolved.extend({"required_edit": x} for x in review["required_edits"])
        if review["verdict"] != "pass":
            unresolved.append({"review_verdict": review["verdict"]})

    ready = not errors and not unresolved
    return {
        "contract_version": "learning-closure-check/1",
        "language": language,
        "draft_language_sha256": digest,
        "plan_sha256": language_hash(plan),
        "review_sha256": language_hash(review),
        "checker_sha256": file_hash(__file__),
        "schema_sha256": file_hash(SCHEMA_PATH),
        "state": "passed" if ready else "blocked",
        "checked": True,
        "evidence_contract_valid": not errors,
        "ready_for_script_review": ready,
        "errors": errors,
        "unresolved": unresolved,
        "semantic_entailment_checked_by_script": False,
        "user_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("draft", "plan", "review", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--language", choices=("zh-CN", "en-US"), required=True)
    args = parser.parse_args()
    report = check(read(args.draft), args.language, read(args.plan), read(args.review))
    report["plan_file_sha256"] = file_hash(args.plan)
    report["review_file_sha256"] = file_hash(args.review)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("LEARNING_CLOSURE", args.language, report["state"])
    raise SystemExit(0 if report["ready_for_script_review"] else 1)


if __name__ == "__main__":
    main()
