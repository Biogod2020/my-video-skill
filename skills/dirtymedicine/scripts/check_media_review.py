"""Verify full-media delivery and locate a review's quotes on the real audio clock.

Usage: python scripts/check_media_review.py --media course.mp4 --audio narration.wav \
    --alignment alignment.json --review RUN/result.json --transport RUN/manifest.json \
    --language en-US --kind video --out proof.json
Quote matching and corrected clock locations are engineering evidence, not proof
of human viewing or a semantic quality decision. Original model times are retained.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import soundfile as sf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    # Spoken letters remain letters; case, punctuation and whitespace are typographic.
    return "".join(c for c in text.casefold() if unicodedata.category(c)[0] in "LN")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ["media", "audio", "alignment", "review", "transport", "out"]:
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--language", choices=["zh-CN", "en-US"], required=True)
    p.add_argument("--kind", choices=["audio", "video"], required=True)
    a = p.parse_args()
    read = lambda path: json.loads(path.read_text())
    review, transport, clock = read(a.review), read(a.transport), read(a.alignment)
    digest = sha(a.media)
    duration = sf.info(a.audio).duration
    errors, located = [], []
    attached = [m for m in transport.get("actual_media", []) if m["sha256"] == digest]
    if (transport.get("state") != "complete" or not transport.get("complete_unchanged_media_file")
            or not transport.get("audio_not_trimmed") or len(attached) != 1
            or attached[0]["bytes"] != a.media.stat().st_size):
        errors.append("Complete unchanged current media delivery is not proven")
    if not review.get("actual_media_received") or "audio" not in review.get("observed_modalities", []):
        errors.append("Reviewer did not confirm actual audio access")
    if a.kind == "video" and "video" not in review.get("observed_modalities", []):
        errors.append("Reviewer did not confirm actual video access")
    if review.get("input_media_sha256") != digest:
        errors.append("Review identifies a different media file")
    if clock.get("source_sha256") != sha(a.audio):
        errors.append("Acoustic clock belongs to another audio master")
    units = (clock["units"] if a.language == "zh-CN" else
             [w for s in clock["segments"] for w in s["words"]])
    text, owners = "", []
    for unit in units:
        key = normalize(unit.get("text", unit.get("word", "")))
        text += key
        owners.extend([(unit["start"], unit["end"])] * len(key))
    for row in review.get("evidence", []):
        quote = normalize(row["spoken_quote"])
        if not quote:
            errors.append("Empty spoken evidence")
            continue
        matches = list(re.finditer(re.escape(quote), text))
        if matches:
            at = min(matches, key=lambda m: abs(owners[m.start()][0] - row["time_s"]))
            start, end, fraction = owners[at.start()][0], owners[at.end() - 1][1], 1.0
        else:
            block = SequenceMatcher(None, quote, text, autojunk=False).find_longest_match()
            offset = max(0, block.b - block.a)
            candidate = text[max(0, offset - 3):offset + len(quote) + 3]
            fraction = sum(b.size for b in SequenceMatcher(None, quote, candidate,
                                                         autojunk=False).get_matching_blocks()) / len(quote)
            if not block.size:
                errors.append("Spoken evidence not found on acoustic axis")
                continue
            start, end = owners[block.b][0], owners[block.b + block.size - 1][1]
        if fraction < .72 or len(quote) < 8:
            errors.append("Quote requires actual-media verification: " + row["spoken_quote"])
        if not 0 <= row["time_s"] <= duration:
            errors.append("Reviewer time exceeds actual media duration")
        located.append({**row, "clock_start_s": start, "clock_end_s": end,
                        "quote_matching_fraction": fraction,
                        "model_time_delta_s": max(start-row["time_s"], row["time_s"]-end, 0),
                        "clock_source": "actual acoustic alignment; model approximate time retained"})
    if len(located) < 4 or not any(r["clock_start_s"] < duration * .2 for r in located):
        errors.append("Missing opening spoken evidence")
    if not any(duration * .2 <= r["clock_start_s"] <= duration * .8 for r in located):
        errors.append("Missing middle spoken evidence")
    if not any(r["clock_start_s"] >= duration * .85 for r in located):
        errors.append("Missing ending spoken evidence")
    if review["verdict"] == "PASS" and review.get("required_fixes"):
        errors.append("PASS contradicts required fixes")
    output = {"state": "passed" if not errors else "blocked", "unresolved": errors,
              "checker_sha256": sha(Path(__file__)), "input_media_sha256": digest,
              "audio_sha256": sha(a.audio), "duration_s": duration,
              "review_sha256": sha(a.review), "transport_sha256": sha(a.transport),
              "located_evidence": located, "calls_to_llm": 0,
              "scope": "Delivery identity and spoken anchors only; semantic/visual findings need separate adjudication."}
    a.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(output["state"], errors)
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
