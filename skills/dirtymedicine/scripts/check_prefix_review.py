"""Validate exact evidence and physical-prefix isolation, without semantic adjudication."""

import json
from pathlib import Path

import jsonschema


def check_prefix(inp, result, schema):
    jsonschema.validate(result, schema)
    errors = []
    order = {x["id"]: i for i, x in enumerate(inp["prefix"])}
    chunks = {x["id"]: x["spoken_text"] for x in inp["prefix"]}
    current = inp["prefix"][-1]
    text = current["spoken_text"]
    if result["case_id"] != inp["case_id"]:
        errors.append("case identity mismatch")
    if not text.endswith(inp["focus_quote"]):
        errors.append("future text beyond focus")
    for d in result["dependencies"]:
        use = d["use_quote"]
        source = d["source_quote"]
        sid = d["source_chunk_id"]
        status = d["status"]
        if not use or use not in text:
            errors.append("use quote is not actual current text")
            continue
        if status in ["missing", "unclear"]:
            if not d["learner_question"]:
                errors.append("missing/unclear requires actual question")
            continue
        if sid not in chunks or not source or source not in chunks[sid]:
            errors.append("unsupported source quote")
            continue
        if sid == current["id"]:
            # A first definition/announced new fact or derivation may include its own
            # conclusion; evidence must stop by that conclusion, never borrow later text.
            if status == "established_before" and text.index(source) + len(source) > text.index(
                use
            ):
                errors.append("earlier-source claim overlaps use")
            elif status in ["introduced_here", "derived_here"] and (
                text.index(source) > text.index(use)
                or (text.index(source) + len(source) > text.index(use) and use not in source)
            ):
                errors.append("local source extends after use")
        elif order[sid] >= order[current["id"]]:
            errors.append("borrowed future source")
    if result["verdict"] == "pass" and (
        result["required_edits"]
        or any(d["status"] in ["missing", "unclear"] for d in result["dependencies"])
    ):
        errors.append("pass contradicts blocking finding")
    if inp["task_kind"] == "negative_control":
        nc = result["negative_control"]
        if (
            not nc
            or nc["answerable_from_material"] is not False
            or nc["answer"] is not None
            or nc["source_quote"] is not None
        ):
            errors.append("negative-control source leakage")
    return errors


def build_prefix_prompt(inp, protocol):
    """Canonical request using only exact prefix references and the generic protocol."""
    from prefix_review_refs import build_api_review_schema, build_ref_index

    index = build_ref_index(inp, granularity="sentence")
    payload = {
        key: inp[key] for key in ["case_id", "language", "task_kind", "focus_quote", "question"]
    }
    payload.update(
        ref_index_sha256=index["ref_index_sha256"],
        current_paragraph_id=index["current_paragraph_id"],
        reference_table=index["refs"],
    )
    return (
        protocol + "\n只输出引用选择结果，不自由生成use_quote/source_quote。"
        "从下列真实原文表选择use_ref/source_ref；首次定义可同一ref，"
        "established_before必须选更早的ref。每个复述claim标明kind及支持它的source_refs。"
        "一般机制不等于患者已测结果。没有报告的患者数据必须明说缺失。"
        "只裁决当前focus及当前段前提，前缀其他问题不代替此点判断。"
        "不调用工具，不添加$schema或Markdown。\n输出形状："
        + json.dumps(build_api_review_schema(index), ensure_ascii=False, sort_keys=True)
        + "\n实际前缀引用表：\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def main():
    import argparse
    import hashlib

    from check_learner_review import language_hash, paragraph_rows
    from prefix_review_refs import build_ref_index, decode_ref_review

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["draft", "manifest", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--language", choices=["zh-CN", "en-US"], required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(Path(path).read_text())
    sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    draft, manifest = read(args.draft), read(args.manifest)
    rows = paragraph_rows(draft, args.language)
    indices = {row["id"]: i for i, row in enumerate(rows)}
    digest = language_hash(draft["languages"][args.language])
    errors, reports, covered, negative_controls, seen, supplied_focuses = (
        [],
        [],
        set(),
        0,
        set(),
        set(),
    )
    if manifest["draft_language_sha256"] != digest or manifest["language"] != args.language:
        errors.append("manifest version/language mismatch")
    protocol_ref = manifest["reviewer_protocol"]
    protocol = Path(protocol_ref["path"]).read_text()
    if sha(protocol_ref["path"]) != protocol_ref["sha256"]:
        errors.append("reviewer protocol changed")
    if not isinstance(manifest.get("risk_inventory"), list):
        errors.append("missing explicit first-dependency risk inventory")
    if manifest.get("evidence_mode") != "selected_refs/1":
        errors.append("current reference-selection evidence contract required")
    for number, case in enumerate(manifest["cases"]):
        bad, result, inp = [], {}, {}
        try:
            for key in [
                "input",
                "prompt",
                "result",
                "transport",
                "raw_result",
                "ref_index",
                "decoded",
            ]:
                if sha(case[key]["path"]) != case[key]["sha256"]:
                    bad.append(key + " changed")
            inp, result, transport = (
                read(case["input"]["path"]),
                read(case["result"]["path"]),
                read(case["transport"]["path"]),
            )
            jsonschema.validate(
                inp, json.loads(Path(__file__).with_name("prefix_input.schema.json").read_text())
            )
            if inp["case_id"] in seen:
                bad.append("duplicate case identity")
            seen.add(inp["case_id"])
            actual_prompt = Path(case["prompt"]["path"]).read_text()
            if actual_prompt != build_prefix_prompt(inp, protocol):
                bad.append("actual model prompt is not canonical prefix-only request")
            index = build_ref_index(inp, granularity="sentence")
            if read(case["ref_index"]["path"]) != index:
                bad.append("reference index does not match exact prefix")
            raw = Path(case["raw_result"]["path"]).read_bytes()
            decoded = decode_ref_review(index, json.loads(raw), original_result_bytes=raw)
            if read(case["decoded"]["path"]) != decoded or decoded["result"] != result:
                bad.append("decoded evidence differs from actual selected references")
            last = inp["prefix"][-1]
            idx = indices.get(last["id"])
            if idx is None:
                bad.append("current id missing from draft")
            else:
                expected = [{"id": r["id"], "spoken_text": r["spoken_text"]} for r in rows[:idx]]
                if inp["prefix"][:-1] != expected:
                    bad.append("prior chunks do not match exact current draft prefix")
                original = rows[idx]["spoken_text"]
                if not original.startswith(last["spoken_text"]) or not last["spoken_text"].endswith(
                    inp["focus_quote"]
                ):
                    bad.append("not physically truncated at current focus")
                if last["spoken_text"] == original and inp["task_kind"] != "negative_control":
                    covered.add(last["id"])
                supplied_focuses.add((last["id"], inp["focus_quote"]))
            if inp["task_kind"] == "negative_control":
                negative_controls += 1
            if inp["language"] != args.language:
                bad.append("case language mismatch")
            if not (
                transport["state"] == "complete"
                and transport.get("stateless") is True
                and transport["prompt_sha256"] == case["prompt"]["sha256"]
                and transport["finish_reasons"][-1] == "STOP"
            ):
                bad.append("incomplete or non-independent transport")
            bad.extend(
                check_prefix(
                    inp, result, read(Path(__file__).with_name("prefix_review.schema.json"))
                )
            )
            if result["verdict"] != "pass" or result["required_edits"]:
                bad.append("reviewer has unresolved findings")
        except (
            KeyError,
            TypeError,
            ValueError,
            OSError,
            IndexError,
            jsonschema.ValidationError,
        ) as error:
            bad.append("invalid case contract: " + type(error).__name__)
        reports.append(
            {
                "case_id": inp.get("case_id", f"invalid-{number}"),
                "verdict": result.get("verdict", "error"),
                "passed": not bad,
                "errors": bad,
                "required_edits": result.get("required_edits", []),
            }
        )
    if len(reports) != len(manifest["cases"]) or not reports:
        errors.append("missing case results")
    if covered != set(indices):
        errors.append(
            "whole-course prefix coverage missing: " + ",".join(sorted(set(indices) - covered))
        )
    if not negative_controls:
        errors.append("no source-abstention negative control")
    for risk in manifest.get("risk_inventory", []):
        if (risk["paragraph_id"], risk["focus_quote"]) not in supplied_focuses:
            errors.append("required first-dependency focus missing: " + risk["paragraph_id"])
    unresolved = [r for r in reports if not r["passed"]]
    output = {
        "state": "passed" if not errors and not unresolved else "blocked",
        "language": args.language,
        "draft_language_sha256": digest,
        "future_content_in_probe_inputs": False if not errors and not unresolved else None,
        "unresolved": unresolved + errors,
        "cases": reports,
        "paragraphs_covered": sorted(covered),
        "negative_controls": negative_controls,
        "scope": "Exact canonical prefix requests, whole-paragraph views, declared risk focuses and recorded model judgement; no semantic proof by string match",
        "checker_sha256": sha(__file__),
        "manifest_sha256": sha(args.manifest),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(output["state"], len(reports))
    raise SystemExit(0 if output["state"] == "passed" else 1)


if __name__ == "__main__":
    main()
