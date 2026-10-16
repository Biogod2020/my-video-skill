"""Reconstruct a bounded author patch and its pronunciation-only TTS derivatives.

Usage: python scripts/check_course_author_chain.py --project COURSE --author RUN \
    --schema author.schema.json --language en-US --out check.json
Does not edit manuscripts or promote a cached application receipt to approval.
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from agy_result import select_result
from check_learner_review import language_hash


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alias_collisions(text, table, language):
    """Catch 'full name, or abbreviation' becoming the same spoken name twice."""
    def spoken_key(value):
        digits = (list("零一二三四五六七八九") if language == "zh-CN" else
                  ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])
        for digit, word in enumerate(digits):
            value = value.replace(str(digit), word)
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold().replace("+", "plus"))

    pattern = "|".join(re.escape(k) for k in sorted(table, key=len, reverse=True))
    convert = lambda value: re.sub(pattern, lambda m: table[m[0]], value)
    found = []
    for alias, rendered in table.items():
        if len(alias) < 2 or not re.search(r"[A-Za-z]", alias):
            continue
        for match in re.finditer(r"(?:\bor\s+|也叫\s*|简称\s*|或者\s*)" + re.escape(alias)
                                 + r"(?![A-Za-z0-9])", text):
            left = spoken_key(convert(text[max(0, match.start()-200):match.start()]))
            right = spoken_key(rendered)
            if len(right) >= 4 and left.endswith(right):
                found.append({"alias": alias, "rendered": rendered,
                              "source_offset": match.start(), "reason": "expanded alias duplicates preceding full name"})
    return found


def check(project, author, schema, language):
    selected, selection = select_result(read(author / "response.json"), read(schema))
    errors = []
    if selected != read(author / "result.json"):
        errors.append("Saved selection differs from the current final response")
    manifest = read(author / "manifest.json")
    if manifest.get("state") != "complete" or not manifest.get("current_final_response_selected"):
        errors.append("Author transport/selection incomplete")
    expected = read(project / "before/draft.v5.json")
    previous = copy.deepcopy(expected)
    for lang, value in selected["languages"].items():
        rows = {r["id"]: r for s in expected["languages"][lang]["sections"]
                for r in s["paragraphs"]}
        seen = set()
        for patch in value["patches"]:
            pid = patch["paragraph_id"]
            if pid not in rows or pid in seen:
                raise ValueError("Unknown or duplicate author patch ID")
            seen.add(pid)
            if rows[pid]["teaching_function"] == "question":
                raise ValueError("Frozen exercise paragraph was changed")
            for field in ["spoken_text", "teaching_function", "visual_intent"]:
                rows[pid][field] = patch[field]
    expected["teaching_plan"] = {
        "revision_plan": selected["plan"],
        "hook_decision": previous["teaching_plan"]["hook_decision"],
        "prior_knowledge": previous["teaching_plan"]["prior_knowledge"]}
    expected["teacher_notes"] = selected["teacher_notes"]
    expected["revision_invariants"] = selected["invariants"]
    actual = read(project / "draft.json")
    if actual != expected:
        errors.append("Current manuscript is not the exact bounded author reconstruction")
    folder = project / "private/voice-inputs"
    lesson = read(folder / f"B03.lesson.{language}-safe.json")
    maps = read(folder / f"pronunciation.{language}.json")
    table = {r["from"]: r["to"] for r in maps["reused_agy_authored_map"]
             if r["from"] != r["to"]}
    extra = maps.get("additional_agy_authored_map", [])
    if extra:
        extra_run = project / "pronunciation-author"
        extra_result, _ = select_result(read(extra_run / "response.json"),
                                       read(project / "pronunciation-author.schema.json"))
        accepted = [{k: row[k] for k in ["from", "to"]} for row in extra_result["maps"]]
        if accepted != extra or maps["additional_map_source_sha256"] != sha(extra_run / "result.json"):
            errors.append("Additional pronunciation rules differ from their current agy source")
        table.update({row["from"]: row["to"] for row in extra})
    table.update(maps["orthographic_variants"])
    pattern = "|".join(re.escape(k) for k in sorted(table, key=len, reverse=True))
    rows = [r for s in actual["languages"][language]["sections"] for r in s["paragraphs"]]
    for row, slide in zip(rows, lesson["slides"], strict=True):
        if alias_collisions(row["spoken_text"], table, language):
            errors.append("A pronunciation alias duplicates its just-spoken full name: " + row["id"])
        spoken = re.sub(pattern, lambda m: table[m[0]], row["spoken_text"])
        if slide["paragraph_id"] != row["id"] or slide["source_spoken_text"] != row["spoken_text"]:
            errors.append("Pronunciation derivative does not identify its original paragraph")
        if slide["tts_input"] != spoken or slide["spoken_text"] != spoken:
            errors.append("TTS derivative contains unauthorized prose changes")
        segments = slide["display_segments"]
        if "".join(s["spoken"] for s in segments) != spoken:
            errors.append("Display mapping misses spoken bytes")
        if "".join(s["display"] for s in segments) != row["spoken_text"]:
            errors.append("Display mapping alters the canonical manuscript")
    text = folder / f"B03-spoken-{language}-refined.txt"
    if text.read_text() != "\n\n".join(s["spoken_text"] for s in lesson["slides"]) + "\n":
        errors.append("Whole-course input file differs from the reviewed derivative")
    return {"state": "passed" if not errors else "blocked", "unresolved": errors,
            "language": language, "draft_language_sha256": language_hash(actual["languages"][language]),
            "tts_input_sha256": sha(text), "checker_sha256": sha(Path(__file__)),
            "source_final_sha256": sha(author / "result.json"),
            "source_envelope_sha256": sha(author / "response.json"),
            "source_schema_sha256": sha(schema), "selection": selection,
            "exact_bounded_reconstruction": not errors,
            "question_paragraphs_preserved": True, "paragraph_count": len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["project", "author", "schema", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--language", choices=["zh-CN", "en-US"], required=True)
    a = parser.parse_args()
    report = check(a.project, a.author, a.schema, a.language)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report["state"], report["unresolved"])
    raise SystemExit(0 if report["state"] == "passed" else 1)


if __name__ == "__main__":
    main()
