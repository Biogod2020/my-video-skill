"""Validate independently authored source adjudications for one current language batch.

Usage: uv run python scripts/check_source_adjudication.py --batch results.json \
    --draft draft.json --language zh-CN --adjudications adjudication.jsonl --out audit.json

The adjacent requests.json freezes the required checkpoint set; --requests can
select it explicitly. Every checkpoint_context, claim/<id>, dependency/<index>,
required_edit/<index>, and negative_control item needs one independent judgement.
checkpoint_context records a fresh first-dependency search, even if the candidate
reported no dependencies. REVIEWER_ERROR needs counterevidence and a correction;
COURSE_GAP and UNCERTAIN never become PASS through a closure/override flag.

This verifies structure, current hashes, exact reference ranges, order and coverage.
It does not infer medical meaning, guarantee that a search was exhaustive, or
prove the declared reviewer's independence. Trusted independent semantic review
remains necessary. Corrections are separate evidence; no source/model file changes.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import jsonschema
from check_prefix_review import build_prefix_prompt
from prefix_review_refs import (
    CLAIM_KINDS,
    STATUSES,
    build_api_review_schema,
    build_ref_index,
    decode_ref_review,
)

CONTRACT = "source-adjudication/1"
OUTPUT_CONTRACT = "source-audit/1"
DISPOSITIONS = {"SUPPORTED", "REVIEWER_ERROR", "COURSE_GAP", "UNCERTAIN"}
BINDING_KEYS = {
    "raw_manifest_sha256",
    "requests_manifest_sha256",
    "draft_sha256",
    "draft_language_sha256",
    "input_sha256",
    "ref_index_file_sha256",
    "ref_index_sha256",
    "raw_result_sha256",
    "decoded_sha256",
    "result_sha256",
    "prompt_sha256",
    "transport_sha256",
    "protocol_sha256",
    "formatter_sha256",
    "decoder_sha256",
    "language",
    "api_schema_sha256",
    "transport_schema_sha256",
}
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
SCOPE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "condition", "quantifier"],
    "properties": {key: TEXT for key in ("subject", "condition", "quantifier")},
}
CITATION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ref_id", "paragraph_id", "start", "end", "text_sha256"],
    "properties": {
        "ref_id": TEXT,
        "paragraph_id": TEXT,
        "start": {"type": "integer", "minimum": 0},
        "end": {"type": "integer", "minimum": 1},
        "text_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    },
}
ROW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "case_id",
        "item_id",
        "disposition",
        "reviewer",
        "bindings",
        "rationale",
        "scope_check",
        "citations",
        "counterevidence",
        "correction",
        "checkpoint_context",
    ],
    "properties": {
        "schema_version": {"const": CONTRACT},
        "case_id": TEXT,
        "item_id": TEXT,
        "disposition": {"enum": sorted(DISPOSITIONS)},
        "reviewer": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "session_id", "independent_of_candidate"],
            "properties": {
                "id": TEXT,
                "session_id": TEXT,
                "independent_of_candidate": {"const": True},
            },
        },
        "bindings": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(BINDING_KEYS),
            "properties": {key: TEXT for key in BINDING_KEYS},
        },
        "rationale": TEXT,
        "scope_check": SCOPE,
        "citations": {"type": "array", "items": CITATION, "uniqueItems": True},
        "counterevidence": {"type": "array", "items": CITATION, "uniqueItems": True},
        "correction": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["text", "claim_kind", "source_refs", "scope_check"],
            "properties": {
                "text": TEXT,
                "claim_kind": {"enum": CLAIM_KINDS},
                "source_refs": {"type": "array", "items": CITATION, "uniqueItems": True},
                "scope_check": SCOPE,
                "negative_control": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["answerable_from_material", "answer", "source_quote"],
                    "properties": {
                        "answerable_from_material": {"const": False},
                        "answer": {"type": "null"},
                        "source_quote": {"type": "null"},
                    },
                },
            },
        },
        "checkpoint_context": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [
                "prefix_read_independently",
                "first_use_checked",
                "no_dependencies_reason",
                "first_dependencies",
            ],
            "properties": {
                "prefix_read_independently": {"const": True},
                "first_use_checked": {"const": True},
                "no_dependencies_reason": {"type": ["string", "null"]},
                "first_dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "fact",
                            "use_ref",
                            "status",
                            "source_refs",
                            "learner_question",
                            "blocks_current_focus",
                            "rationale",
                        ],
                        "properties": {
                            "fact": TEXT,
                            "use_ref": TEXT,
                            "status": {"enum": STATUSES},
                            "source_refs": {"type": "array", "items": TEXT, "uniqueItems": True},
                            "learner_question": {"type": ["string", "null"]},
                            "blocks_current_focus": {"type": "boolean"},
                            "rationale": TEXT,
                        },
                    },
                },
            },
        },
    },
}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def citation(ref):
    """Build the exact, content-bound citation object; no semantic decision is made."""
    return {key: ref[key] for key in ("ref_id", "paragraph_id", "start", "end")} | {
        "text_sha256": hashlib.sha256(ref["text"].encode()).hexdigest()
    }


def expected_item_ids(case_context):
    """Enumerate all mandatory independent decisions for one decoded candidate."""
    decoded = case_context["decoded"]
    return (
        {"checkpoint_context", "negative_control"}
        | {"claim/" + claim["claim_id"] for claim in decoded["teach_back_claims"]}
        | {f"dependency/{i}" for i in range(len(decoded["result"]["dependencies"]))}
        | {f"required_edit/{i}" for i in range(len(decoded["result"]["required_edits"]))}
    )


def load_batch_context(
    batch_path, draft_path, language, requests_path=None, calibration_control=False
):
    """Read/verify current artifacts and expose bindings for an independently written ledger.

    Errors are returned, never hidden by a candidate PASS or a subset of cases.
    The public helper only supplies identities/item IDs, not adjudication language.
    """
    batch_path, draft_path = Path(batch_path).resolve(), Path(draft_path).resolve()
    requests_path = (
        Path(requests_path).resolve() if requests_path else batch_path.with_name("requests.json")
    )
    context = {
        "cases": {},
        "errors": [],
        "language": language,
        "raw_manifest_sha256": sha(batch_path),
        "requests_manifest_sha256": sha(requests_path),
        "batch_path": str(batch_path),
        "draft_path": str(draft_path),
        "requests_path": str(requests_path),
        "audit_scope": "calibration_control" if calibration_control else "production",
    }
    errors = context["errors"]
    batch, requests, draft = read(batch_path), read(requests_path), read(draft_path)
    lang = draft["languages"][language]
    context["draft_language_sha256"] = digest(lang)
    rows = [p for section in lang["sections"] for p in section["paragraphs"]]
    order = {p["id"]: i for i, p in enumerate(rows)}
    if not rows or len(order) != len(rows):
        errors.append("empty draft or duplicate paragraph IDs")
    for obj, label in ((batch, "batch"), (requests, "requests")):
        if obj.get("language") != language or obj.get("draft_language_sha256") != digest(lang):
            errors.append(label + " language/draft binding mismatch")
        if obj.get("evidence_mode") != "selected_refs/1":
            errors.append(label + " is not selected_refs/1")
    if batch.get("state") != "complete":
        errors.append("batch is not complete")
    required = {c["case_id"]: c for c in requests["cases"]}
    actual = {c["case_id"]: c for c in batch["cases"]}
    control_scope_valid = False
    if calibration_control:
        try:
            if not (
                requests.get("audit_scope") == batch.get("audit_scope") == "calibration_control"
                and requests.get("calibration_control") == batch.get("calibration_control")
            ):
                raise ValueError("calibration flag needs matching frozen calibration scope")
            control = requests["calibration_control"]
            historical_ref = control["historical_batch"]
            historical_path = Path(historical_ref["path"])
            if sha(historical_path) != historical_ref["sha256"]:
                raise ValueError("historical calibration manifest changed")
            historical = read(historical_path)
            historical_case = next(
                c for c in historical["cases"] if c["case_id"] == control["case_id"]
            )
            if not (
                historical.get("state") == "complete"
                and len(required) == len(actual) == 1
                and set(required) == {control["case_id"]}
                and actual[control["case_id"]] == historical_case
            ):
                raise ValueError("calibration case differs from the one frozen historical result")
            control_scope_valid = True
        except (KeyError, TypeError, ValueError, OSError, StopIteration) as error:
            errors.append("invalid calibration scope: " + str(error))
    elif any(obj.get("audit_scope", "production") != "production" for obj in (requests, batch)):
        errors.append("calibration scope requires explicit --calibration-control")
    if (
        not required
        or len(required) != len(requests["cases"])
        or len(actual) != len(batch["cases"])
        or set(actual) != set(required)
    ):
        errors.append("batch does not exactly cover frozen request cases")
    context["required_case_ids"] = sorted(required)
    protocol_ref = requests["reviewer_protocol"]
    protocol_path = Path(protocol_ref["path"])
    protocol = protocol_path.read_text()
    if (
        sha(protocol_path) != protocol_ref["sha256"]
        or batch.get("reviewer_protocol") != protocol_ref
    ):
        errors.append("protocol binding changed")
    formatter = Path(__file__).with_name("check_prefix_review.py")
    decoder = Path(__file__).with_name("prefix_review_refs.py")
    if batch.get("formatter_sha256") != sha(formatter) or requests.get("formatter_sha256") != sha(
        formatter
    ):
        errors.append("prefix formatter identity changed")
    covered, focuses, controls = set(), set(), 0
    for case_id in sorted(required):
        if case_id not in actual:
            continue
        case = actual[case_id]
        try:
            if case.get("state") != "decoded":
                raise ValueError("case is not decoded")
            for field in (
                "input",
                "prompt",
                "ref_index",
                "api_schema",
                "raw_result",
                "decoded",
                "result",
                "transport",
            ):
                if sha(case[field]["path"]) != case[field]["sha256"]:
                    raise ValueError(field + " file hash changed")
            for field in ("input", "prompt", "ref_index", "api_schema"):
                if case[field] != required[case_id][field]:
                    raise ValueError(field + " differs from frozen request")
            inp, index = read(case["input"]["path"]), read(case["ref_index"]["path"])
            if inp["language"] != language or inp["case_id"] != case_id:
                raise ValueError("input language/case identity differs")
            if index != build_ref_index(inp, granularity="sentence"):
                raise ValueError("reference index differs from current prefix")
            if read(case["api_schema"]["path"]) != build_api_review_schema(index):
                raise ValueError("API schema differs from current reference index")
            if Path(case["prompt"]["path"]).read_text() != build_prefix_prompt(inp, protocol):
                raise ValueError("prompt is not current canonical prefix request")
            raw = Path(case["raw_result"]["path"]).read_bytes()
            decoded = decode_ref_review(index, json.loads(raw), original_result_bytes=raw)
            if decoded != read(case["decoded"]["path"]) or decoded["result"] != read(
                case["result"]["path"]
            ):
                raise ValueError("decoded/result differs from actual raw selections")
            transport = read(case["transport"]["path"])
            transport_schema = case.get("transport_schema", case["api_schema"])
            if (
                sha(transport_schema["path"]) != transport_schema["sha256"]
                or transport.get("schema_sha256") != transport_schema["sha256"]
            ):
                raise ValueError("actual transport schema hash differs from its explicit binding")
            if not (
                transport.get("state") == "complete"
                and transport.get("stateless") is True
                and transport.get("finish_reasons", [])[-1:] == ["STOP"]
                and transport.get("prompt_sha256") == case["prompt"]["sha256"]
            ):
                raise ValueError("incomplete/non-independent prompt transport")
            last = inp["prefix"][-1]
            current_i = order[last["id"]]
            expected_prior = [
                {"id": p["id"], "spoken_text": p["spoken_text"]} for p in rows[:current_i]
            ]
            if inp["prefix"][:-1] != expected_prior or not rows[current_i][
                "spoken_text"
            ].startswith(last["spoken_text"]):
                raise ValueError("prefix differs from current draft")
            if (
                last["spoken_text"] == rows[current_i]["spoken_text"]
                and inp["task_kind"] != "negative_control"
            ):
                covered.add(last["id"])
            focuses.add((last["id"], inp["focus_quote"]))
            controls += inp["task_kind"] == "negative_control"
            bindings = {
                "raw_manifest_sha256": context["raw_manifest_sha256"],
                "requests_manifest_sha256": context["requests_manifest_sha256"],
                "draft_sha256": sha(draft_path),
                "draft_language_sha256": digest(lang),
                "input_sha256": case["input"]["sha256"],
                "ref_index_file_sha256": case["ref_index"]["sha256"],
                "ref_index_sha256": index["ref_index_sha256"],
                "raw_result_sha256": case["raw_result"]["sha256"],
                "decoded_sha256": case["decoded"]["sha256"],
                "result_sha256": case["result"]["sha256"],
                "prompt_sha256": case["prompt"]["sha256"],
                "transport_sha256": case["transport"]["sha256"],
                "protocol_sha256": protocol_ref["sha256"],
                "formatter_sha256": sha(formatter),
                "decoder_sha256": sha(decoder),
                "language": language,
                "api_schema_sha256": case["api_schema"]["sha256"],
                "transport_schema_sha256": transport_schema["sha256"],
            }
            context["cases"][case_id] = {
                "input": inp,
                "index": index,
                "decoded": decoded,
                "raw": json.loads(raw),
                "bindings": bindings,
                "refs": {r["ref_id"]: r for r in index["refs"]},
            }
        except (
            KeyError,
            TypeError,
            ValueError,
            OSError,
            IndexError,
            jsonschema.ValidationError,
        ) as error:
            errors.append(case_id + ": " + type(error).__name__ + ": " + str(error))
    if not control_scope_valid and covered != set(order):
        errors.append("current full-paragraph coverage incomplete")
    if not control_scope_valid and not controls:
        errors.append("source-abstention negative control missing")
    risks = requests.get("risk_inventory")
    if not isinstance(risks, list):
        errors.append("explicit risk inventory missing")
    else:
        for risk in risks:
            if (risk["paragraph_id"], risk["focus_quote"]) not in focuses:
                errors.append("required first-dependency focus unexecuted")
    return context


def _check_citations(items, refs):
    for item in items:
        ref = refs.get(item["ref_id"])
        if ref is None or item != citation(ref):
            raise ValueError("citation ID/range/text identity differs from actual prefix")


def _check_context(value, refs):
    dependencies = value["first_dependencies"]
    if not dependencies and not (
        isinstance(value["no_dependencies_reason"], str) and value["no_dependencies_reason"].strip()
    ):
        raise ValueError("independent empty dependency search needs an explicit reason")
    unresolved = []
    for item in dependencies:
        use = refs.get(item["use_ref"])
        if use is None:
            raise ValueError("first-dependency use ID is absent")
        sources = [refs[key] for key in item["source_refs"]]
        if item["status"] in {"missing", "unclear"}:
            if (
                sources
                or not isinstance(item["learner_question"], str)
                or not item["learner_question"].strip()
            ):
                raise ValueError(
                    "missing/unclear independent dependency needs no source and an actual question"
                )
            if item["blocks_current_focus"]:
                unresolved.append("independent search found blocking " + item["status"])
        else:
            if not sources or item["learner_question"] is not None or item["blocks_current_focus"]:
                raise ValueError(
                    "established/introduced/derived dependency needs sources and no blocking question"
                )
            for source in sources:
                if source["paragraph_order"] > use["paragraph_order"]:
                    raise ValueError("independent source follows first use")
                if (
                    item["status"] == "introduced_here"
                    and source["paragraph_id"] != use["paragraph_id"]
                ):
                    raise ValueError("independent local introduction cites another paragraph")
                if source["paragraph_id"] == use["paragraph_id"]:
                    same = source["ref_id"] == use["ref_id"]
                    if source["end"] > use["start"] and not (
                        same and item["status"] in {"introduced_here", "derived_here"}
                    ):
                        raise ValueError("independent local source overlaps/follows use")
    return unresolved


def _read_rows(path):
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key in adjudication")
            value[key] = item
        return value

    rows = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line, object_pairs_hook=unique_object)
        rows.append((number, value))
    return rows


def evaluate(
    batch_path,
    draft_path,
    adjudications_path,
    language,
    requests_path=None,
    calibration_control=False,
):
    context = load_batch_context(
        batch_path, draft_path, language, requests_path, calibration_control
    )
    unresolved = [{"type": "evidence_contract", "reason": error} for error in context["errors"]]
    expected = {
        (cid, item_id)
        for cid, case in context["cases"].items()
        for item_id in expected_item_ids(case)
    }
    seen, valid, disposition_counts, corrections = set(), set(), Counter(), []
    row_errors = []
    for number, row in _read_rows(adjudications_path):
        try:
            jsonschema.validate(row, ROW_SCHEMA)
            key = (row["case_id"], row["item_id"])
            if key in seen:
                raise ValueError("duplicate adjudication item")
            seen.add(key)
            if key not in expected:
                raise ValueError("unknown case/item, or candidate case evidence is invalid")
            case = context["cases"][row["case_id"]]
            if row["bindings"] != case["bindings"]:
                raise ValueError("stale adjudication binding")
            if row["reviewer"]["session_id"] == read(batch_path).get("author_session"):
                raise ValueError("adjudication reused candidate author session")
            for field in ("citations", "counterevidence"):
                _check_citations(row[field], case["refs"])
            if row["item_id"] == "checkpoint_context":
                if row["checkpoint_context"] is None:
                    raise ValueError("checkpoint needs independent first-dependency search")
                for reason in _check_context(row["checkpoint_context"], case["refs"]):
                    unresolved.append(
                        {
                            "case_id": key[0],
                            "item_id": key[1],
                            "type": "independent_context_gap",
                            "reason": reason,
                        }
                    )
            elif row["checkpoint_context"] is not None:
                raise ValueError("context search belongs to checkpoint_context item")
            disposition = row["disposition"]
            if disposition == "REVIEWER_ERROR":
                correction = row["correction"]
                if not row["counterevidence"] or correction is None:
                    raise ValueError("reviewer error needs counterevidence and a correction")
                _check_citations(correction["source_refs"], case["refs"])
                if (
                    correction["claim_kind"] != "missing_information"
                    and not correction["source_refs"]
                ):
                    raise ValueError(
                        "non-absence correction needs exact supporting source references"
                    )
                if (
                    row["item_id"] == "negative_control"
                    and case["input"]["task_kind"] == "negative_control"
                    and correction.get("negative_control")
                    != {"answerable_from_material": False, "answer": None, "source_quote": None}
                ):
                    raise ValueError("corrected negative control must explicitly abstain")
                corrections.append({"case_id": key[0], "item_id": key[1], "correction": correction})
            elif row["correction"] is not None or row["counterevidence"]:
                raise ValueError("correction/counterevidence requires REVIEWER_ERROR")
            if disposition in {"COURSE_GAP", "UNCERTAIN"}:
                unresolved.append(
                    {
                        "case_id": key[0],
                        "item_id": key[1],
                        "type": disposition,
                        "reason": row["rationale"],
                    }
                )
            if disposition == "SUPPORTED":
                if row["item_id"].startswith("claim/"):
                    claim_id = row["item_id"][6:]
                    claim = next(
                        c for c in case["decoded"]["teach_back_claims"] if c["claim_id"] == claim_id
                    )
                    if {c["ref_id"] for c in row["citations"]} != set(claim["source_refs"]):
                        raise ValueError(
                            "SUPPORTED claim must audit its actual selected references; use REVIEWER_ERROR for a citation repair"
                        )
                if row["item_id"].startswith("required_edit/"):
                    unresolved.append(
                        {
                            "case_id": key[0],
                            "item_id": key[1],
                            "type": "confirmed_required_edit",
                            "reason": "independent audit confirms an unresolved necessary edit",
                        }
                    )
                if row["item_id"].startswith("dependency/"):
                    dependency = case["decoded"]["result"]["dependencies"][
                        int(row["item_id"].split("/")[1])
                    ]
                    if dependency["status"] in {"missing", "unclear"}:
                        unresolved.append(
                            {
                                "case_id": key[0],
                                "item_id": key[1],
                                "type": "confirmed_dependency_gap",
                                "reason": "independent audit confirms missing/unclear prerequisite",
                            }
                        )
                if (
                    row["item_id"] == "negative_control"
                    and case["input"]["task_kind"] == "negative_control"
                    and case["decoded"]["result"]["negative_control"]
                    != {
                        "answerable_from_material": False,
                        "answer": None,
                        "source_quote": None,
                    }
                ):
                    raise ValueError("supported source-abstention control did not abstain")
            disposition_counts[disposition] += 1
            valid.add(key)
        except (KeyError, TypeError, ValueError, IndexError, jsonschema.ValidationError) as error:
            row_errors.append({"line": number, "type": type(error).__name__, "reason": str(error)})
    missing = sorted(expected - valid)
    unresolved.extend(
        {"type": "missing_adjudication", "case_id": cid, "item_id": item_id}
        for cid, item_id in missing
    )
    unresolved.extend({"type": "invalid_adjudication", **error} for error in row_errors)
    complete = (
        not context["errors"]
        and not row_errors
        and not missing
        and valid == expected
        and bool(expected)
    )
    return {
        "schema_version": OUTPUT_CONTRACT,
        "audit_scope": context["audit_scope"],
        "state": "passed" if complete and not unresolved else "blocked",
        "independent_audit_completed": complete,
        "all_items_audited": complete,
        "unresolved": unresolved,
        "language": language,
        "draft_language_sha256": context["draft_language_sha256"],
        "checker_sha256": sha(__file__),
        "raw_manifest_sha256": context["raw_manifest_sha256"],
        "requests_manifest_sha256": context["requests_manifest_sha256"],
        "adjudications_sha256": sha(adjudications_path),
        "required_case_count": len(context["required_case_ids"]),
        "valid_case_count": len(context["cases"]),
        "expected_item_count": len(expected),
        "audited_item_count": len(valid),
        "disposition_counts": dict(disposition_counts),
        "corrected_reviewer_errors": corrections,
        "semantic_entailment_checked_by_code": False,
        "independent_reviewer_identity_is_declared_not_cryptographically_proven": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("batch", "draft", "adjudications", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--requests", type=Path)
    parser.add_argument("--language", choices=["zh-CN", "en-US"], required=True)
    parser.add_argument(
        "--calibration-control",
        action="store_true",
        help="Only one byte-identical historical case, with matching frozen calibration scope",
    )
    args = parser.parse_args()
    try:
        result = evaluate(
            args.batch,
            args.draft,
            args.adjudications,
            args.language,
            args.requests,
            args.calibration_control,
        )
    except (KeyError, TypeError, ValueError, OSError, IndexError) as error:
        result = {
            "schema_version": OUTPUT_CONTRACT,
            "audit_scope": "calibration_control" if args.calibration_control else "production",
            "state": "blocked",
            "independent_audit_completed": False,
            "all_items_audited": False,
            "language": args.language,
            "draft_language_sha256": None,
            "raw_manifest_sha256": sha(args.batch) if args.batch.is_file() else None,
            "unresolved": [{"type": type(error).__name__, "reason": str(error)}],
            "checker_sha256": sha(__file__),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("state", "independent_audit_completed", "all_items_audited")
            }
        )
    )
    raise SystemExit(0 if result["state"] == "passed" else 1)


if __name__ == "__main__":
    main()
