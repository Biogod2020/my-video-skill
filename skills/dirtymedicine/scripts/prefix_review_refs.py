"""Locate prefix-review evidence through immutable text references, without judging meaning.

The caller supplies an already truncated prefix. This module preserves its Unicode
code points and punctuation, assigns deterministic paragraph/range IDs, builds a
reference-selection JSON Schema, and decodes selected IDs into exact source text.
It cannot establish that a claim follows from a citation or that a model chose the
right claim kind. In particular, a cited general mechanism is not proof of a
patient observation. No role instructions or model calls are included.

Python API:
    index = build_ref_index(prefix_input, granularity="clause")
    schema = build_ref_review_schema(index)
    decoded = decode_ref_review(index, parsed_review, original_result_bytes=raw_bytes)

CLI:
    uv run python scripts/prefix_review_refs.py index --input input.json \
        --out refs.json --schema-out review.schema.json
    uv run python scripts/prefix_review_refs.py decode --index refs.json \
        --result review.json --out decoded.json

Ranges use zero-based Python Unicode code-point offsets, with an exclusive end.
Reference IDs remain stable for an unchanged paragraph ID, range, and source text.
All examples and tests use synthetic text; this module embeds no private courses.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import jsonschema

INDEX_CONTRACT = "prefix-ref-index/1"
REVIEW_CONTRACT = "prefix-review-refs/1"
DECODED_CONTRACT = "decoded-prefix-review-refs/1"
STATUSES = ["established_before", "introduced_here", "derived_here", "missing", "unclear"]
CLAIM_KINDS = ["patient_observation", "general_mechanism", "inference", "missing_information"]
TASK_KINDS = {
    "spoken_context",
    "visual_context",
    "causal_understanding",
    "novice_load",
    "negative_control",
}
INPUT_KEYS = {"case_id", "language", "task_kind", "prefix", "focus_quote", "question"}
CLOSING_MARKS = "\"'”’」』）》】"


class RefContractError(ValueError):
    """The input, index, or selected references violate the locating contract."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise RefContractError(message)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_input(inp):
    _require(isinstance(inp, dict) and set(inp) == INPUT_KEYS, "unexpected/missing input fields")
    for field in ("case_id", "focus_quote", "question"):
        _require(_nonempty(inp[field]), f"input {field} must be nonempty text")
    _require(
        isinstance(inp["language"], str) and inp["language"] in {"zh-CN", "en-US"},
        "unsupported language",
    )
    _require(
        isinstance(inp["task_kind"], str) and inp["task_kind"] in TASK_KINDS,
        "unsupported task kind",
    )
    _require(isinstance(inp["prefix"], list) and inp["prefix"], "prefix must be nonempty")
    seen = set()
    for paragraph in inp["prefix"]:
        _require(
            isinstance(paragraph, dict) and set(paragraph) == {"id", "spoken_text"},
            "paragraph fields must be id and spoken_text",
        )
        _require(_nonempty(paragraph["id"]), "paragraph ID must be nonempty text")
        _require(paragraph["id"] not in seen, "duplicate paragraph ID")
        seen.add(paragraph["id"])
        _require(_nonempty(paragraph["spoken_text"]), "spoken text must be nonempty")
    current = inp["prefix"][-1]["spoken_text"]
    _require(current.endswith(inp["focus_quote"]), "current paragraph extends beyond focus")


def _spans(text, granularity):
    separators = set("。！？!?\n\r.")
    if granularity == "clause":
        separators.update("，,；;：:")
    spans, start, offset = [], 0, 0
    while offset < len(text):
        mark = text[offset]
        numeric_mark = (
            mark in ".,"
            and 0 < offset < len(text) - 1
            and text[offset - 1].isdigit()
            and text[offset + 1].isdigit()
        )
        if mark not in separators or numeric_mark:
            offset += 1
            continue
        end = offset + 1
        while end < len(text) and (text[end] in separators or text[end] in CLOSING_MARKS):
            end += 1
        if text[start:end].strip():
            spans.append((start, end))
            start = end
        offset = end
    if start < len(text):
        if text[start:].strip():
            spans.append((start, len(text)))
        elif spans:
            spans[-1] = (spans[-1][0], len(text))
    return spans


def build_ref_index(inp, *, granularity="clause"):
    """Return a lossless reference table for exactly the supplied prefix.

    ``granularity`` is ``clause`` or ``sentence``. All spaces and punctuation are
    retained; decimal points and numeric thousands commas are not cut points.
    This validates the supplied cutoff, not its identity against a larger draft.
    """
    _validate_input(inp)
    _require(
        isinstance(granularity, str) and granularity in {"sentence", "clause"},
        "unknown reference granularity",
    )
    refs = []
    for order, paragraph in enumerate(inp["prefix"]):
        text = paragraph["spoken_text"]
        for start, end in _spans(text, granularity):
            identity = {
                "paragraph_id": paragraph["id"],
                "start": start,
                "end": end,
                "text": text[start:end],
            }
            refs.append(
                {"ref_id": "r_" + _digest(identity)[:24], "paragraph_order": order, **identity}
            )
    _require(len({ref["ref_id"] for ref in refs}) == len(refs), "reference ID collision")
    index = {
        "schema_version": INDEX_CONTRACT,
        "granularity": granularity,
        "offset_unit": "unicode_code_points",
        "end_exclusive": True,
        "input": copy.deepcopy(inp),
        "input_sha256": _digest(inp),
        "current_paragraph_id": inp["prefix"][-1]["id"],
        "focus_range": {
            "paragraph_id": inp["prefix"][-1]["id"],
            "start": len(inp["prefix"][-1]["spoken_text"]) - len(inp["focus_quote"]),
            "end": len(inp["prefix"][-1]["spoken_text"]),
        },
        "refs": refs,
    }
    index["ref_index_sha256"] = _digest(index)
    return index


def _validated_refs(index):
    _require(isinstance(index, dict), "reference index must be an object")
    try:
        rebuilt = build_ref_index(index["input"], granularity=index["granularity"])
    except (KeyError, TypeError) as error:
        raise RefContractError("malformed reference index") from error
    _require(_canonical(index) == _canonical(rebuilt), "reference index was changed or malformed")
    return {ref["ref_id"]: ref for ref in index["refs"]}


def build_ref_review_schema(index):
    """Build a typed JSON Schema whose citation fields can select only this index.

    The model supplies reference IDs, never free-form ``use_quote`` or
    ``source_quote`` fields. Patient observations require at least one citation;
    the model remains responsible for their kind and semantic support.
    """
    refs = _validated_refs(index)
    ids = list(refs)
    current_ids = [
        key for key, ref in refs.items() if ref["paragraph_id"] == index["current_paragraph_id"]
    ]
    selected_ref = {"type": "string", "enum": ids}
    nullable_ref = {"anyOf": [selected_ref, {"type": "null"}]}
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    text_array = {"type": "array", "items": text}
    dependency = {
        "type": "object",
        "additionalProperties": False,
        "required": ["fact", "use_ref", "status", "source_ref", "reason", "learner_question"],
        "properties": {
            "fact": text,
            "use_ref": {"type": "string", "enum": current_ids},
            "status": {"type": "string", "enum": STATUSES},
            "source_ref": nullable_ref,
            "reason": text,
            "learner_question": {"type": ["string", "null"]},
        },
        "allOf": [
            {
                "if": {"properties": {"status": {"enum": ["missing", "unclear"]}}},
                "then": {"properties": {"source_ref": {"type": "null"}, "learner_question": text}},
                "else": {
                    "properties": {"source_ref": selected_ref, "learner_question": {"type": "null"}}
                },
            }
        ],
    }
    claim = {
        "type": "object",
        "additionalProperties": False,
        "required": ["claim_id", "kind", "text", "source_refs"],
        "properties": {
            "claim_id": text,
            "kind": {"type": "string", "enum": CLAIM_KINDS},
            "text": text,
            "source_refs": {"type": "array", "uniqueItems": True, "items": selected_ref},
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "kind": {"enum": ["patient_observation", "general_mechanism", "inference"]}
                    }
                },
                "then": {"properties": {"source_refs": {"minItems": 1}}},
            }
        ],
    }
    negative_control = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answerable_from_material", "answer", "source_ref"],
        "properties": {
            "answerable_from_material": {"type": "boolean"},
            "answer": {"type": ["string", "null"]},
            "source_ref": nullable_ref,
        },
        "allOf": [
            {
                "if": {"properties": {"answerable_from_material": {"const": False}}},
                "then": {
                    "properties": {"answer": {"type": "null"}, "source_ref": {"type": "null"}}
                },
                "else": {"properties": {"answer": text, "source_ref": selected_ref}},
            }
        ],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PrefixReviewWithSelectedReferences",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "case_id",
            "ref_index_sha256",
            "verdict",
            "dependencies",
            "teach_back_claims",
            "negative_control",
            "required_edits",
            "optional_notes",
            "limits",
        ],
        "properties": {
            "contract_version": {"const": REVIEW_CONTRACT},
            "case_id": {"const": index["input"]["case_id"]},
            "ref_index_sha256": {"const": index["ref_index_sha256"]},
            "verdict": {"type": "string", "enum": ["pass", "revise", "uncertain"]},
            "dependencies": {"type": "array", "items": dependency},
            "teach_back_claims": {"type": "array", "minItems": 1, "items": claim},
            "negative_control": negative_control
            if index["input"]["task_kind"] == "negative_control"
            else {"type": "null"},
            "required_edits": text_array,
            "optional_notes": text_array,
            "limits": text_array,
        },
    }


def build_api_review_schema(index):
    """Send reference enums to Gemini; retain conditional checks in the local decoder.

    The backend supports a JSON Schema subset. This shape deliberately omits
    conditional keywords; decode_ref_review still validates the full schema.
    """

    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {
                key: visit(item)
                for key, item in value.items()
                if key not in {"$schema", "title", "allOf", "if", "then", "else"}
            }
        return value

    return visit(build_ref_review_schema(index))


def _strict_json(raw):
    def object_hook(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise RefContractError(f"invalid JSON constant: {value}")

    try:
        return json.loads(raw, object_pairs_hook=object_hook, parse_constant=invalid_constant)
    except (TypeError, ValueError, UnicodeError) as error:
        raise RefContractError("original result is not valid unambiguous JSON") from error


def _check_source_order(dependency, refs, current_id):
    use = refs[dependency["use_ref"]]
    status = dependency["status"]
    if status in {"missing", "unclear"}:
        _require(_nonempty(dependency["learner_question"]), "missing/unclear needs a question")
        return
    source = refs[dependency["source_ref"]]
    if status == "introduced_here":
        _require(
            source["paragraph_id"] == current_id, "local introduction must cite current paragraph"
        )
    _require(source["paragraph_order"] <= use["paragraph_order"], "source is later than use")
    if source["paragraph_id"] == use["paragraph_id"]:
        same_ref = source["ref_id"] == use["ref_id"]
        if status == "established_before":
            _require(source["end"] <= use["start"], "established source must precede use")
        else:
            _require(same_ref or source["end"] <= use["start"], "local source extends after use")


def decode_ref_review(index, review, *, original_result_bytes):
    """Decode selected references and retain exact original-result byte identity.

    Returns an envelope with a legacy-shaped ``result`` and separate citation
    bindings/claim records. Only table entries generate quotation fields. The
    supplied raw bytes must parse to exactly the supplied review. Structural and
    temporal errors raise ``RefContractError``; no partial decoded PASS is emitted.
    """
    refs = _validated_refs(index)
    _require(isinstance(original_result_bytes, bytes), "original result bytes are required")
    parsed = _strict_json(original_result_bytes)
    _require(_canonical(parsed) == _canonical(review), "raw result and parsed review differ")
    try:
        jsonschema.validate(review, build_ref_review_schema(index))
    except jsonschema.ValidationError as error:
        raise RefContractError("reference review schema violation: " + error.message) from error
    if review["verdict"] == "pass":
        _require(not review["required_edits"], "pass contradicts required edits")
        _require(
            not any(d["status"] in {"missing", "unclear"} for d in review["dependencies"]),
            "pass contradicts missing/unclear dependencies",
        )
    current_id = index["current_paragraph_id"]
    dependencies, bindings = [], []
    for number, dependency in enumerate(review["dependencies"]):
        _check_source_order(dependency, refs, current_id)
        use = refs[dependency["use_ref"]]
        source = refs[dependency["source_ref"]] if dependency["source_ref"] else None
        dependencies.append(
            {
                "fact": dependency["fact"],
                "use_quote": use["text"],
                "status": dependency["status"],
                "source_chunk_id": source["paragraph_id"] if source else None,
                "source_quote": source["text"] if source else None,
                "reason": dependency["reason"],
                "learner_question": dependency["learner_question"],
            }
        )
        bindings.append(
            {
                "dependency_index": number,
                "use_ref": use["ref_id"],
                "source_ref": source["ref_id"] if source else None,
                "use_span": copy.deepcopy(use),
                "source_span": copy.deepcopy(source),
            }
        )
    claims, claim_ids = [], set()
    for claim in review["teach_back_claims"]:
        _require(
            _nonempty(claim["claim_id"]) and claim["claim_id"] not in claim_ids,
            "empty/duplicate claim ID",
        )
        _require(_nonempty(claim["text"]), "empty teach-back claim")
        claim_ids.add(claim["claim_id"])
        claims.append(
            {
                **copy.deepcopy(claim),
                "sources": [copy.deepcopy(refs[key]) for key in claim["source_refs"]],
            }
        )
    nc = review["negative_control"]
    nc_binding = None
    if nc is not None:
        source = refs[nc["source_ref"]] if nc["source_ref"] else None
        nc_binding = {"source_ref": nc["source_ref"], "source_span": copy.deepcopy(source)}
        nc = {
            "answerable_from_material": nc["answerable_from_material"],
            "answer": nc["answer"],
            "source_quote": source["text"] if source else None,
        }
    return {
        "schema_version": DECODED_CONTRACT,
        "result": {
            "case_id": review["case_id"],
            "verdict": review["verdict"],
            "dependencies": dependencies,
            "teach_back": "\n".join(claim["text"] for claim in claims),
            "negative_control": nc,
            "required_edits": copy.deepcopy(review["required_edits"]),
            "optional_notes": copy.deepcopy(review["optional_notes"]),
            "limits": copy.deepcopy(review["limits"]),
        },
        "teach_back_claims": claims,
        "reference_bindings": {"dependencies": bindings, "negative_control": nc_binding},
        "evidence": {
            "input_sha256": index["input_sha256"],
            "ref_index_sha256": index["ref_index_sha256"],
            "original_result_sha256": hashlib.sha256(original_result_bytes).hexdigest(),
            "original_result_hash_mode": "exact_bytes",
            "decoder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "semantic_entailment_checked": False,
        "claim_kinds_assigned_by_model": True,
    }


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    index_parser = commands.add_parser("index")
    index_parser.add_argument("--input", type=Path, required=True)
    index_parser.add_argument("--out", type=Path, required=True)
    index_parser.add_argument("--schema-out", type=Path)
    index_parser.add_argument("--granularity", choices=["sentence", "clause"], default="clause")
    decode_parser = commands.add_parser("decode")
    for name in ("index", "result", "out"):
        decode_parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "index":
        index = build_ref_index(_strict_json(args.input.read_bytes()), granularity=args.granularity)
        _write(args.out, index)
        if args.schema_out:
            _write(args.schema_out, build_ref_review_schema(index))
        print(json.dumps({"state": "indexed", "reference_count": len(index["refs"])}))
    else:
        raw = args.result.read_bytes()
        decoded = decode_ref_review(
            _strict_json(args.index.read_bytes()), _strict_json(raw), original_result_bytes=raw
        )
        _write(args.out, decoded)
        print(json.dumps({"state": "decoded", "verdict": decoded["result"]["verdict"]}))


if __name__ == "__main__":
    main()
