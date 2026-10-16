"""Build subtitles from verbatim semantic groups and a frozen acoustic time axis.

Usage:
    python scripts/build_semantic_captions.py --language zh-CN --lesson lesson.json \
      --alignment alignment.json --plan plan.json --audio master.wav --fps 24 \
      --font NotoSansSC.ttf --out captions

Dependencies: pillow, soundfile. No ASR, LLM calls, audio edits, or fallback splitting.
"""

import argparse
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

import soundfile as sf
from PIL import ImageFont


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    return "".join(c for c in text.casefold() if unicodedata.category(c)[0] in "LN")


def substitute(text, replacements):
    if not replacements:
        return text
    pattern = "|".join(re.escape(x) for x in sorted(replacements, key=len, reverse=True))
    return re.sub(pattern, lambda match: replacements[match[0]], text)


def literal(text):
    return re.sub(r"\s+", "", text)


def display_projection(lesson, aliases):
    """Project ordered pronunciation spans without guessing a many-to-one inverse."""
    displayed, mapping, by_slide = "", [], {}
    offset = 0
    for slide in lesson["slides"]:
        source = slide["spoken_text"]
        segments = slide.get("display_segments")
        if segments is not None:
            if aliases:
                raise ValueError("Explicit display segments cannot be mixed with global aliases")
            if "".join(s["spoken"] for s in segments) != source:
                raise ValueError("Display segments do not exactly cover the spoken scene")
        else:
            segments, cursor = [], 0
            pattern = "|".join(re.escape(x) for x in sorted(aliases, key=len, reverse=True))
            for match in re.finditer(pattern or r"(?!)", source):
                segments.append({"spoken": source[cursor:match.start()],
                                 "display": source[cursor:match.start()]})
                segments.append({"spoken": match[0], "display": aliases[match[0]]})
                cursor = match.end()
            segments.append({"spoken": source[cursor:], "display": source[cursor:]})
        scene_display = ""
        cursor = offset
        for segment in segments:
            spoken, shown = segment["spoken"], segment["display"]
            if not spoken and shown:
                raise ValueError("Display text cannot be inserted without a spoken span")
            if spoken and not shown:
                raise ValueError("Display text cannot silently omit a spoken span")
            scene_display += shown
            if spoken == shown:
                mapping.extend((cursor + i, cursor + i + 1) for i in range(len(spoken)))
            else:
                mapping.extend([(cursor, cursor + len(spoken))] * len(shown))
            cursor += len(spoken)
        by_slide[slide["id"]] = scene_display
        displayed += scene_display
        offset += len(source)
    return displayed, mapping, by_slide


def clock(milliseconds):
    hours, value = divmod(round(milliseconds), 3600000)
    minutes, value = divmod(value, 60000)
    seconds, value = divmod(value, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{value:03}"


def build(args):
    lesson, alignment, plan = read(args.lesson), read(args.alignment), read(args.plan)
    settings = {
        "font_size": 40, "max_line_width_px": 1440, "min_display_s": 1.2,
        "max_display_s": 7.0, "short_quiet_hold_s": 1.0, "long_quiet_hold_s": 0.35,
        "min_blank_s": 0.5, "max_reading_characters_per_s": 9 if args.language == "zh-CN" else 24,
        "minimum_group_characters": 7 if args.language == "zh-CN" else 8,
        "protected_phrases": [],
    }
    if args.config:
        settings.update(read(args.config))
    aliases = lesson.get("display_replacements", {})
    if args.aliases:
        aliases = {**aliases, **read(args.aliases)}
    if any(not a or not b for a, b in aliases.items()):
        raise ValueError("Empty pronunciation/display alias")
    duration = sf.info(args.audio).duration
    digest = sha(args.audio)
    if alignment.get("source_sha256") != digest:
        raise ValueError("Alignment does not identify this exact frozen audio hash")
    if args.language == "zh-CN":
        if "Qwen" not in alignment.get("model", "") or "units" not in alignment:
            raise ValueError("Chinese requires native Qwen character units")
        units = alignment["units"]
    else:
        if "CTC" not in alignment.get("alignment_source", ""):
            raise ValueError("English requires the existing global acoustic CTC axis")
        units = [word for seg in alignment["segments"] for word in seg["words"]]
    source = "".join(s["spoken_text"] for s in lesson["slides"])
    source_key = normalize(source)
    aligned, owners = "", []
    previous_start = -1
    for i, unit in enumerate(units):
        start, end = unit["start"], unit["end"]
        if not all(math.isfinite(x) for x in [start, end]) or not 0 <= start <= end <= duration:
            raise ValueError(f"Invalid unit clock at {i}")
        if start < previous_start - 1e-6:
            raise ValueError(f"Nonmonotonic alignment at {i}")
        previous_start = start
        key = normalize(unit.get("text", unit.get("word", "")))
        if not key:
            raise ValueError(f"Empty alignment unit at {i}")
        aligned += key
        owners.extend([i] * len(key))
    if aligned != source_key:
        raise ValueError("Acoustic units do not exactly cover the supplied spoken transcript")

    # Map authored display groups directly onto the full source, including aliases
    # spanning several native units. Sequential ownership permits repeated phrases.
    display_source, display_map, scene_display = display_projection(lesson, aliases)
    # Build exact matching from the source rather than reverse a potentially
    # many-to-one alias. A boundary inside an alias is prohibited.
    source_chars, source_owner = [], []
    key_index = 0
    for char in source:
        key = normalize(char)
        source_chars.append(key_index)
        source_owner.append(owners[key_index] if key else None)
        key_index += len(key)
    source_chars.append(key_index)
    assert len(display_map) == len(display_source)
    # Whitespace is typographic; punctuation and every spoken word are preserved.
    visible_source = "".join(c for c in display_source if not c.isspace())
    visible_map = [m for c, m in zip(display_source, display_map, strict=True)
                   if not c.isspace()]
    groups = plan["captions"]
    authored = "".join("".join(c["lines"]) for c in groups)
    if literal(authored) != visible_source:
        raise ValueError("Semantic plan changes, omits, repeats words or punctuation")
    for slide in lesson["slides"]:
        text = "".join("".join(c["lines"]) for c in groups if c["slide_id"] == slide["id"])
        if literal(text) != literal(scene_display[slide["id"]]):
            raise ValueError(f"Incorrect scene ownership for slide {slide['id']}")
    protected = [*settings["protected_phrases"],
                 *[v.get(k, "") for v in lesson.get("term_pairs", [])
                   for k in ["zh", "en", "abbr"]]]
    boundaries, offset = set(), 0
    for group in groups:
        if not 1 <= len(group["lines"]) <= 2:
            raise ValueError("Each caption requires one or two authored semantic lines")
        for line in group["lines"]:
            if not line.strip() or re.match(r"^[，。；：？！、,.!?;:）】]", line):
                raise ValueError("Empty line or stranded leading punctuation")
            offset += len(literal(line))
            boundaries.add(offset)
            if offset < len(visible_map):
                left, right = visible_map[offset - 1], visible_map[offset]
                if left == right:
                    raise ValueError("Line boundary splits an explicit pronunciation alias")
                gap = source[left[1]:right[0]]
                if (args.language == "en-US" and not gap
                        and re.fullmatch(r"[A-Za-z0-9'-]", visible_source[offset - 1])
                        and re.fullmatch(r"[A-Za-z0-9'-]", visible_source[offset])):
                    raise ValueError("English line/caption boundary splits a word")
    for term in protected:
        for match in re.finditer(re.escape(literal(term)), visible_source) if term else []:
            if any(match.start() < boundary < match.end() for boundary in boundaries):
                raise ValueError(f"Broken protected phrase: {term}")

    font = ImageFont.truetype(str(args.font), size=settings["font_size"])
    timed, details, cursor = [], [], 0
    for i, group in enumerate(groups):
        text = "\n".join(group["lines"])
        count = len(literal(text))
        first, last = visible_map[cursor][0], visible_map[cursor + count - 1][1]
        if cursor and visible_map[cursor - 1] == visible_map[cursor]:
            raise ValueError("Group boundary splits an explicit pronunciation alias")
        cursor += count
        a, b = source_chars[first], source_chars[last]
        if a == b:
            raise ValueError("Caption contains no spoken characters")
        first_unit, last_unit = owners[a], owners[b - 1]
        if a and owners[a - 1] == first_unit:
            raise ValueError("Caption boundary splits a native acoustic unit")
        start, end = units[first_unit]["start"], units[last_unit]["end"]
        widths = [font.getlength(line) for line in group["lines"]]
        if max(widths) > settings["max_line_width_px"]:
            raise ValueError(f"Caption {i + 1} exceeds configured line width")
        if len(normalize(text)) < settings["minimum_group_characters"]:
            raise ValueError(f"Caption {i + 1} is a fragment requiring semantic regrouping")
        timed.append({"text": text, "startMs": math.floor(start * args.fps + 1e-6)
                      * 1000 / args.fps, "endMs": None, "timestampMs": None, "confidence": None})
        details.append({"id": i + 1, "slide_id": group["slide_id"],
                        "speech_start_s": start, "speech_end_s": end,
                        "first_unit": first_unit, "last_unit": last_unit,
                        "line_widths_px": widths, "reading_characters": len(normalize(text))})
    for i, (caption, row) in enumerate(zip(timed, details, strict=True)):
        following = timed[i + 1]["startMs"] / 1000 if i + 1 < len(timed) else duration
        gap = following - row["speech_end_s"]
        end = following
        if gap > settings["short_quiet_hold_s"]:
            end = min(following - settings["min_blank_s"],
                      row["speech_end_s"] + settings["long_quiet_hold_s"])
        explicit_end = groups[i].get("display_until_s")
        if explicit_end is not None:
            end = min(end, explicit_end)
        end = min(math.ceil(end * args.fps - 1e-6) / args.fps, following, duration)
        # Reuse the identical stored frame timestamp at a shared boundary.
        caption["endMs"] = ((timed[i + 1]["startMs"] if i + 1 < len(timed)
                             else duration * 1000) if abs(end - following) < 1e-8
                            else end * 1000)
        shown = end - caption["startMs"] / 1000
        if end < row["speech_end_s"] - 1 / args.fps - 1e-6:
            raise ValueError(f"Caption {i + 1} disappears before its speech ends")
        if not settings["min_display_s"] <= shown <= settings["max_display_s"]:
            raise ValueError(f"Caption {i + 1} needs regrouping: display {shown:.3f}s")
        load = row["reading_characters"] / shown
        if load > settings["max_reading_characters_per_s"]:
            raise ValueError(f"Caption {i + 1} reading load exceeds configured threshold")
        row.update(display_duration_s=shown, reading_characters_per_s=load,
                   display_start_s=caption["startMs"] / 1000, display_end_s=end)
    save(args.out / "timed.json", timed)
    save(args.out / "timeline.json", details)
    (args.out / "captions.srt").write_text("\n\n".join(
        f"{i}\n{clock(c['startMs'])} --> {clock(c['endMs'])}\n{c['text']}"
        for i, c in enumerate(timed, 1)) + "\n")
    return {"state": "passed", "language": args.language, "audio_sha256": digest,
            "algorithm_sha256": sha(Path(__file__)),
            "inputs": {n: sha(getattr(args, n)) for n in ["lesson", "alignment", "plan", "font"]},
            "source_spoken_characters": len(source_key), "caption_count": len(timed),
            "duration_s": duration, "fps": args.fps, "settings": settings,
            "exact_ordered_transcript_and_punctuation_coverage": True,
            "stranded_punctuation": 0, "broken_protected_phrases": 0,
            "overlapping_captions": 0, "audio_modified": False, "llm_timing_calls": 0,
            "minimum_display_s": min(r["display_duration_s"] for r in details),
            "maximum_display_s": max(r["display_duration_s"] for r in details),
            "real_frame_visual_verification_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=["zh-CN", "en-US"])
    for name in ["lesson", "alignment", "plan", "audio", "font", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ["aliases", "config"]:
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--fps", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.fps) or args.fps <= 0:
        parser.error("fps must be finite and positive")
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        report = build(args)
    except (ValueError, KeyError, IndexError, TypeError, AssertionError) as error:
        save(args.out / "checks.json", {"state": "blocked", "error": str(error),
                                       "audio_modified": False, "llm_timing_calls": 0})
        raise SystemExit(f"SEMANTIC_CAPTIONS_BLOCKED: {error}") from None
    save(args.out / "checks.json", report)
    print("SEMANTIC_CAPTIONS_PASSED", report["caption_count"], args.language)


if __name__ == "__main__":
    main()
