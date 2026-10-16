"""Calibrate course articulation rate and pause bands without an LLM.

Usage: python scripts/standardize_course_pacing.py --audio narration.wav \
    --asr narration.asr.json --lesson lesson.json --policy pacing-policy.json \
    --out renders/pacing-preview --render-from production-report.json

Uses existing word timestamps and authored punctuation. Ambiguous boundaries
remain unchanged and are reported; passing numeric checks is not a listening review.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

PAUSE = re.compile(r"\[pause\s+([\d.]+)s\]")


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", PAUSE.sub("", text).lower())


def load_pcm(path):
    with wave.open(str(path)) as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("Expected mono PCM16 WAV")
        return audio.getframerate(), np.frombuffer(
            audio.readframes(audio.getnframes()), dtype="<i2"
        ).copy()


def write_pcm(path, rate, samples):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, rate, len(samples), "NONE", "not compressed"))
        audio.writeframes(samples.astype("<i2").tobytes())


def quiet_intervals(samples, rate, policy):
    hop = round(rate * policy["rms_window_seconds"])
    frames = samples[: len(samples) // hop * hop].astype(float).reshape(-1, hop)
    rms = np.sqrt(np.mean((frames / 32768) ** 2, axis=1))
    quiet = rms < 10 ** (policy["quiet_threshold_dbfs"] / 20)
    edges = np.diff(np.r_[False, quiet, False].astype(int))
    return [
        (int(a * hop), int(b * hop))
        for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0])
        if (b - a) * hop / rate >= policy["minimum_measured_pause_seconds"]
    ]


def count_units(text, language):
    # A reproducible mixed-language proxy, not an exact Chinese syllable count.
    expression = r"[A-Za-z]+(?:['-][A-Za-z]+)*|\d+(?:\.\d+)?"
    if language == "zh-CN":
        expression = r"[\u4e00-\u9fff]|" + expression
    return len(re.findall(expression, PAUSE.sub("", text)))


def metrics(samples, rate, units, policy):
    quiet = quiet_intervals(samples, rate, policy)
    duration = len(samples) / rate
    quiet_seconds = sum(b - a for a, b in quiet) / rate
    speech = duration - quiet_seconds
    return {
        "units": units,
        "duration_seconds": duration,
        "articulation_seconds": speech,
        "articulation_units_per_minute": units * 60 / speech,
        "gross_units_per_minute": units * 60 / duration,
        "quiet_seconds": quiet_seconds,
        "quiet_gaps": len(quiet),
    }


def authored_boundaries(lesson):
    """Use existing content; never invent cognitive intent from raw punctuation."""
    rows = {}
    offset = 0

    def add(position, kind, before, after, minimum=0):
        priority = {"sentence": 1, "question": 2, "authored": 3, "scene": 4, "quiz": 5}
        row = {"position": position, "class": kind, "before": before[-60:],
               "after": after[:60], "explicit_minimum_seconds": minimum}
        if position not in rows or priority[kind] > priority[rows[position]["class"]]:
            rows[position] = row

    for index, slide in enumerate(lesson["slides"]):
        text = slide["spoken_text"]
        for match in re.finditer(r"[。！？!?]|(?<!\d)\.(?!\d)", text):
            # Avoid acronym dots, decimals and abbreviation fragments.
            if match[0] == "." and match.end() < len(text) and text[match.end()].isalpha():
                continue
            prefix = text[:match.end()]
            add(offset + len(normalize(prefix)),
                "question" if match[0] in "？?" else "sentence", prefix, text[match.end():])
        for match in PAUSE.finditer(text):
            seconds = float(match[1])
            if seconds < 1.5:
                add(offset + len(normalize(text[:match.start()])), "authored",
                    text[:match.start()], text[match.end():])
        offset += len(normalize(text))
        if index + 1 < len(lesson["slides"]):
            kind = "quiz" if slide.get("kind") == "quiz" else "scene"
            # A spoken promise of five seconds must remain at least five seconds.
            literal = 0
            if kind == "quiz":
                tail = PAUSE.sub("", text)[-160:].lower()
                if re.search(r"五秒|five seconds", tail):
                    literal = 5.0
                for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:秒|seconds)", tail):
                    literal = max(literal, float(match[1]))
            add(offset, kind, text, lesson["slides"][index + 1]["spoken_text"], literal)
    final = len(normalize("".join(s["spoken_text"] for s in lesson["slides"])))
    return [row for p, row in sorted(rows.items()) if 0 < p < final]


def locate_boundaries(lesson, asr, speed, quiet, rate):
    expected = "".join(normalize(s["spoken_text"]) for s in lesson["slides"])
    heard, ranges = "", []
    for segment in asr["segments"]:
        for word in segment.get("words", []):
            part = normalize(word["word"])
            heard += part
            ranges += [(word["start"] / speed, word["end"] / speed)] * len(part)
    matcher = SequenceMatcher(None, expected, heard, autojunk=False)
    indices = {}
    for block in matcher.get_matching_blocks():
        for i in range(block.size):
            indices[block.a + i] = block.b + i
    if matcher.ratio() < 0.8:
        raise ValueError(f"Text/ASR alignment too weak: {matcher.ratio():.3f}")
    claimed, rows = set(), []
    # Longer semantic boundaries take precedence over nearby sentence punctuation.
    pending = sorted(authored_boundaries(lesson), key=lambda r: r["class"] != "quiz")
    for row in pending:
        p = row["position"]
        neighbourhood = range(max(0, p - 5), min(len(expected), p + 5))
        if any(i not in indices for i in neighbourhood):
            rows.append({**row, "status": "unresolved", "reason": "local ASR mismatch"})
            continue
        left, right = ranges[indices[p - 1]], ranges[indices[p]]
        if left == right:
            rows.append({**row, "status": "unresolved", "reason": "inside one ASR word"})
            continue
        # Ordinary phoneme closures are not extended. A real quiet interval must
        # lie between the lexical endpoint estimates, with limited timestamp jitter.
        boundary_time = (left[1] + right[0]) / 2
        candidates = [
            (i, a, b) for i, (a, b) in enumerate(quiet)
            if i not in claimed and a / rate >= left[0] + 0.05
            and b / rate <= right[1] - 0.05
            and a / rate - 0.08 <= boundary_time <= b / rate + 0.08
        ]
        if len(candidates) != 1:
            reason = "no unique measured inter-word quiet interval"
            rows.append({**row, "status": "unresolved", "reason": reason})
            continue
        i, a, b = candidates[0]
        claimed.add(i)
        rows.append({**row, "status": "located", "start_frame": a, "end_frame": b})
    return matcher.ratio(), sorted(rows, key=lambda r: r["position"])


def edit_quiet(samples, rate, rows, policy):
    edits = []
    for row in rows:
        if row["status"] != "located":
            continue
        a, b = row["start_frame"], row["end_frame"]
        band = policy["pause_classes"][row["class"]]
        minimum = max(band["minimum_seconds"], row["explicit_minimum_seconds"])
        maximum = max(band["maximum_seconds"], minimum)
        target = max(band["target_seconds"], minimum)
        seconds = (b - a) / rate
        row["measured_seconds"] = seconds
        row["allowed_band_seconds"] = [minimum, maximum]
        if minimum <= seconds <= maximum:
            row["status"] = "within_band"
            row["final_seconds"] = seconds
            continue
        delta = round(target * rate) - (b - a)
        center = (a + b) // 2
        begin = finish = center
        if delta > 0:
            # Insert at a near-zero sample boundary, avoiding a discontinuity
            # from the low-level codec/background floor to digital silence.
            radius = round(0.02 * rate)
            lo, hi = max(a + 1, center - radius), min(b - 1, center + radius)
            amplitudes = np.abs(samples[lo - 1:hi + 1].astype(np.int32))
            allowed = np.where((amplitudes[:-1] <= policy["cut_max_pcm_amplitude"])
                               & (amplitudes[1:] <= policy["cut_max_pcm_amplitude"]))[0] + lo
            if not len(allowed):
                row["status"] = "unresolved"
                row["reason"] = "no near-zero insertion boundary; preserved"
                continue
            begin = finish = int(min(allowed, key=lambda frame: abs(frame - center)))
        else:
            # Only remove an acoustically near-digital-zero center. RMS silence
            # alone cannot distinguish a quiet breath from dispensable silence.
            mask = np.abs(samples[a:b].astype(np.int32)) <= policy["cut_max_pcm_amplitude"]
            edges = np.diff(np.r_[False, mask, False].astype(int))
            eligible = []
            guard = round(policy["cut_edge_guard_seconds"] * rate)
            for x, y in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
                if y - x >= -delta + 2 * guard:
                    eligible.append((int(a + x + guard), int(a + y - guard)))
            if not eligible:
                row["status"] = "unresolved"
                row["reason"] = "long gap contains breath or nonzero audio; preserved"
                continue
            x, y = max(eligible, key=lambda r: r[1] - r[0])
            center = (x + y) // 2
            begin = center - (-delta) // 2
            finish = begin - delta
        edits.append({"start_frame": a, "end_frame": b, "delta_frames": delta,
                      "edit_begin_frame": begin, "edit_end_frame": finish,
                      "class": row["class"], "position": row["position"]})
        row["status"] = "extended" if delta > 0 else "shortened_digital_quiet"
        row["final_seconds"] = (b - a + delta) / rate
    parts, retained, cursor = [], [], 0
    for edit in sorted(edits, key=lambda e: e["edit_begin_frame"]):
        a, b = edit["edit_begin_frame"], edit["edit_end_frame"]
        parts.append(samples[cursor:a])
        retained.append((cursor, a))
        if edit["delta_frames"] > 0:
            parts.append(np.zeros(edit["delta_frames"], dtype="<i2"))
        cursor = b
    parts.append(samples[cursor:])
    retained.append((cursor, len(samples)))
    final = np.concatenate(parts)
    # Every original nonremoved sample is copied exactly, and all removals meet
    # the strict amplitude bound. No new voice chunks are synthesized or joined.
    recovered, output_cursor, input_cursor = [], 0, 0
    for edit in sorted(edits, key=lambda e: e["edit_begin_frame"]):
        a, b = edit["edit_begin_frame"], edit["edit_end_frame"]
        length = a - input_cursor
        recovered.append(final[output_cursor:output_cursor + length])
        output_cursor += length + max(0, edit["delta_frames"])
        input_cursor = b
    recovered.append(final[output_cursor:])
    expected = np.concatenate([samples[a:b] for a, b in retained])
    if not np.array_equal(np.concatenate(recovered), expected):
        raise ValueError("Retained PCM preservation check failed")
    return final, edits


def mapped_time(seconds, speed, edits, rate):
    t = seconds / speed
    shift = 0.0
    for edit in edits:
        a, b = edit["start_frame"] / rate, edit["end_frame"] / rate
        delta = edit["delta_frames"] / rate
        if t >= b:
            shift += delta
        elif t > a:
            shift += delta * (t - a) / (b - a)
    return t + shift


def transform_asr(asr, output, speed, edits, rate):
    def at(t):
        return mapped_time(t, speed, edits, rate)
    result = {**asr, "source_sha256": sha(output), "segments": []}
    for segment in asr["segments"]:
        result["segments"].append({**segment, "start": at(segment["start"]),
            "end": at(segment["end"]), "words": [
                {**w, "start": at(w["start"]), "end": at(w["end"])}
                for w in segment.get("words", [])]})
    # Original scans/scales do not describe the new piecewise timeline.
    for key in ["quiet_intervals", "quiet_fraction", "quiet_over_one_second",
                "time_scale", "speed_derivative"]:
        result.pop(key, None)
    output_rate, output_samples = load_pcm(output)
    result["duration_seconds"] = len(output_samples) / output_rate
    result["mapping_method"] = "tempo scale; piecewise-linear visual mapping within edited quiet"
    return result


def standardize(args):
    policy, lesson, asr = read(args.policy), read(args.lesson), read(args.asr)
    if sha(args.audio) != asr["source_sha256"]:
        raise ValueError("ASR belongs to a different audio file")
    declared = {"en": "en-US", "English": "en-US", "zh": "zh-CN", "Chinese": "zh-CN"}.get(
        lesson.get("language"), lesson.get("language"))
    language = args.language or declared
    if language not in policy["languages"]:
        raise ValueError("Specify a supported language; legacy lessons may omit it")
    if declared and language != declared:
        raise ValueError("CLI language conflicts with the lesson")
    units = count_units("\n".join(s["spoken_text"] for s in lesson["slides"]), language)
    rate, original = load_pcm(args.audio)
    baseline = metrics(original, rate, units, policy)
    target = policy["languages"][language]["articulation_target"]
    speed = target / baseline["articulation_units_per_minute"]
    if not policy["tempo_factor_limits"][0] <= speed <= policy["tempo_factor_limits"][1]:
        raise ValueError("Required tempo change exceeds the configured quality guard")
    args.out.mkdir(parents=True, exist_ok=False)
    tempo_path = args.out / "tempo-only.wav"
    attempts = []
    for attempt in range(3):
        subprocess.run([args.ffmpeg, "-v", "error", "-y", "-i", str(args.audio), "-af",
                        f"atempo={speed:.12f}", "-ac", "1", "-c:a", "pcm_s16le",
                        str(tempo_path)], check=True)
        _, tempo_samples = load_pcm(tempo_path)
        measured = metrics(tempo_samples, rate, units, policy)
        attempts.append({"factor": speed, "metrics": measured})
        ratio = measured["articulation_units_per_minute"] / target
        if abs(ratio - 1) <= policy["rate_tolerance_fraction"] or attempt == 2:
            break
        speed /= ratio
        if not policy["tempo_factor_limits"][0] <= speed <= policy["tempo_factor_limits"][1]:
            raise ValueError("Iterated tempo change exceeds the quality guard")
    similarity, rows = locate_boundaries(
        lesson, asr, speed, quiet_intervals(tempo_samples, rate, policy), rate)
    final, edits = edit_quiet(tempo_samples, rate, rows, policy)
    output = args.out / "narration.wav"
    write_pcm(output, rate, final)
    final_metrics = metrics(final, rate, units, policy)
    rate_pass = abs(final_metrics["articulation_units_per_minute"] / target - 1) <= \
        policy["rate_tolerance_fraction"]
    report = {
        "policy_id": policy["id"], "policy_sha256": sha(args.policy),
        "engine_sha256": sha(__file__), "numpy_version": np.__version__,
        "ffmpeg_version": subprocess.check_output(
            [args.ffmpeg, "-version"], text=True).splitlines()[0],
        "language": language, "unit_definition": policy["languages"][language]["unit"],
        "source_audio": str(args.audio.resolve()), "source_audio_sha256": sha(args.audio),
        "source_asr_sha256": sha(args.asr), "source_lesson_sha256": sha(args.lesson),
        "output_audio_sha256": sha(output), "tempo_only_sha256": sha(tempo_path),
        "tempo_factor": speed, "tempo_attempts": attempts, "target": target,
        "baseline": baseline, "final": final_metrics, "rate_within_tolerance": rate_pass,
        "alignment_similarity": similarity, "boundaries": rows, "quiet_edits": edits,
        "sample_rate": rate, "retained_post_tempo_pcm_bit_identical": True,
        "removed_samples_max_amplitude": policy["cut_max_pcm_amplitude"],
        "llm_calls": 0, "original_preserved": True, "listening_review": "not performed",
        "publication_ready": False, "unresolved_boundaries": sum(
            r["status"] == "unresolved" for r in rows),
        "time_mapping": "t/source_tempo + linear quiet-interval deltas; shared by all cues",
    }
    save(args.out / "pacing-report.json", report)
    save(output.with_suffix(".asr.json"), transform_asr(asr, output, speed, edits, rate))
    source_meta_path = args.audio.with_suffix(".json")
    source_meta = read(source_meta_path) if source_meta_path.exists() else {}
    save(output.with_suffix(".json"), {**source_meta, "audio_sha256": sha(output),
        "duration_seconds": len(final) / rate, "time_stretch": True,
        "raw_source": str(args.audio.resolve()), "raw_audio_sha256": sha(args.audio),
        "independent_speech_segment_stitching": False, "pacing_policy_sha256": sha(args.policy),
        "pacing_report": str((args.out / "pacing-report.json").resolve()),
        "actual_complete_audio_review": "pending for this exact derivative"})
    if not rate_pass:
        raise ValueError("Output rate missed target; preserved output is a failed candidate")
    if args.render_from:
        render_from_events(args, report)
    print(json.dumps({"out": str(args.out), "factor": speed, "final_rate":
                      final_metrics["articulation_units_per_minute"],
                      "edits": len(edits), "unresolved": report["unresolved_boundaries"]}))


def stamp(seconds, ass=False):
    scale = 100 if ass else 1000
    value = round(seconds * scale)
    hours, value = divmod(value, 3600 * scale)
    minutes, value = divmod(value, 60 * scale)
    seconds, value = divmod(value, scale)
    return f"{hours}:{minutes:02}:{seconds:02}.{value:02}" if ass else \
        f"{hours:02}:{minutes:02}:{seconds:02},{value:03}"


def render_from_events(args, pacing):
    """Reuse original clean PNG states; retime every cue through one mapping."""
    source = read(args.render_from)
    if source.get("audio_sha256", source.get("delivery_master_sha256")) != sha(args.audio):
        raise ValueError("Video event report belongs to a different delivered audio")
    rate, edits, speed = pacing["sample_rate"], pacing["quiet_edits"], pacing["tempo_factor"]

    def at(t):
        return mapped_time(t, speed, edits, rate)

    events = [{**e, "start": at(e["start"]), "end": at(e["end"])}
              for e in source["events"]]
    for event in events:
        if not Path(event["path"]).is_file() or "'" in event["path"]:
            raise ValueError("Missing or unsupported source frame path")
    events[-1]["end"] = pacing["final"]["duration_seconds"]
    chapters = [{**c, "start": at(c["start"]), "end": at(c["end"])}
                for c in source["chapters"]]
    chapters[-1]["end"] = events[-1]["end"]
    captions = read(args.render_from.parent / "captions.json")
    captions = [{**c, "start": at(c["start"]), "end": at(c["end"])} for c in captions]
    save(args.out / "captions.json", captions)
    save(args.out / "chapters.json", chapters)
    (args.out / "captions.srt").write_text("\n\n".join(
        f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}"
        for i, c in enumerate(captions, 1)) + "\n")
    ass = (args.render_from.parent / "captions.ass").read_text()
    header = ass[:ass.index("Dialogue:")]
    (args.out / "captions.ass").write_text(header + "".join(
        f"Dialogue: 0,{stamp(c['start'], True)},{stamp(c['end'], True)},"
        f"Default,,0,0,0,,{c['text']}\n" for c in captions))
    (args.out / "progressive.txt").write_text("".join(
        f"file '{e['path']}'\nduration {e['end'] - e['start']:.9f}\n" for e in events)
        + f"file '{events[-1]['path']}'\n")
    (args.out / "chapters.ffmetadata").write_text(";FFMETADATA1\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(c['start'] * 1000)}\n"
        f"END={round(c['end'] * 1000)}\ntitle={c['title']}\n" for c in chapters))
    subprocess.run([args.ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(args.out / "progressive.txt"), "-i", str(args.out / "narration.wav"),
        "-i", str(args.out / "chapters.ffmetadata"), "-map", "0:v", "-map", "1:a",
        "-map_metadata", "2", "-map_chapters", "2", "-vf",
        f"fps=24,ass='{args.out / 'captions.ass'}':fontsdir='/System/Library/Fonts/Supplemental'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-t",
        str(events[-1]["end"]), "-movflags", "+faststart", str(args.out / "course.mp4")],
        check=True)
    shutil.copy2(args.lesson, args.out / "lesson.json")
    save(args.out / "production-report.json", {"source_report_sha256": sha(args.render_from),
        "duration_seconds": events[-1]["end"], "events": events, "chapters": chapters,
        "slides": [{**s, "start": at(s["start"]), "end": at(s["end"])}
                   for s in source["slides"]], "video_sha256": sha(args.out / "course.mp4"),
        "audio_sha256": sha(args.out / "narration.wav"),
        "shared_piecewise_timing_map": True, "actual_complete_media_review": "pending",
        "publication_ready": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "asr", "lesson", "policy", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--language", choices=["zh-CN", "en-US"])
    parser.add_argument("--render-from", type=Path)
    standardize(parser.parse_args())


if __name__ == "__main__":
    main()
