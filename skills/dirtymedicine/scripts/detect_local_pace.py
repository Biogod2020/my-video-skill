"""Screen English word timings for local pace jumps without an LLM or audio edits.

Usage:
    python scripts/detect_local_pace.py --audio narration.wav --asr narration.asr.json \
        --policy projects/course-pacing-standard-20261010/local-rate-policy.json \
        --out renders/local-pace-check

English vowel-group counts are syllable proxies, not phonetic measurements.
Candidates require elevated proxy rate and a contrast with nearby delivery.
Existing ASR is used as alignment; this tool never calls a model or edits sound.
"""

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
from itertools import pairwise
from pathlib import Path

import cmudict
import numpy as np
from standardize_course_pacing import load_pcm

PRONUNCIATIONS = cmudict.dict()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def syllable_proxy(text, overrides=None):
    """Use a pronunciation lexicon; expose estimates for out-of-vocabulary terms."""
    token = text.lower().strip(" .,;:!?\"'()[]")
    if overrides and token in overrides:
        return int(overrides[token]), "override"
    parts = re.findall(r"[a-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?", token)
    if not parts or any(part[0].isdigit() for part in parts):
        return 0, "unsupported_number_or_token"
    total = 0
    estimated = False
    for part in parts:
        pronunciations = PRONUNCIATIONS.get(part)
        if pronunciations:
            total += sum(phoneme[-1].isdigit() for phoneme in pronunciations[0])
            continue
        if len(part) == 1 and part != "a":
            return 0, "unsupported_letter"
        estimated = True
        part = part.replace("'", "")
        count = len(re.findall(r"[aeiouy]+", part))
        if count > 1 and part.endswith("e") and not part.endswith(("le", "ye")):
            count -= 1
        total += max(1, count)
    return total, "vowel_group_estimate" if estimated else "cmudict_first_pronunciation"


class Activity:
    """Gain-invariant quiet measurement on a bounded RMS frame grid."""

    def __init__(self, samples, rate, policy):
        self.duration = len(samples) / rate
        hop = max(1, round(rate * policy["rms_window_seconds"]))
        frames = samples[: len(samples) // hop * hop].astype(np.float64).reshape(-1, hop)
        if not len(frames):
            raise ValueError("Audio is shorter than one analysis window")
        rms = np.sqrt(np.mean((frames / 32768) ** 2, axis=1))
        full_rms = float(np.sqrt(np.mean(rms**2)))
        if full_rms < 1e-8:
            raise ValueError("No measurable audio activity")
        self.normalization_gain = 10 ** (policy["normalization_rms_dbfs"] / 20) / full_rms
        quiet = rms * self.normalization_gain < 10 ** (policy["quiet_threshold_dbfs"] / 20)
        edges = np.diff(np.r_[False, quiet, False].astype(np.int8))
        retained = np.zeros(len(quiet), dtype=bool)
        frame_seconds = hop / rate
        for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            if (b - a) * frame_seconds >= policy["minimum_quiet_seconds"]:
                retained[a:b] = True
        self.times = np.arange(len(rms) + 1) * frame_seconds
        self.cumulative_quiet = np.r_[0.0, np.cumsum(retained) * frame_seconds]

    def speech_seconds(self, start, end):
        quiet = np.diff(np.interp([start, end], self.times, self.cumulative_quiet))[0]
        return max(0.0, end - start - quiet)


def flatten_words(asr, duration, policy):
    words, diagnostics = [], []
    last_start = -1.0
    for segment in asr.get("segments", []):
        for raw in segment.get("words", []):
            try:
                start, end = float(raw["start"]), float(raw["end"])
            except (KeyError, ValueError, TypeError) as error:
                raise ValueError("Invalid word timing schema") from error
            if not all(math.isfinite(t) for t in [start, end]):
                raise ValueError("Non-finite word timestamps")
            if start < last_start or start < 0 or end > duration + 0.05:
                raise ValueError("Non-monotonic or out-of-range word timestamps")
            last_start = start
            text = str(raw.get("word", ""))
            count, method = syllable_proxy(text, policy.get("syllable_overrides"))
            confidence = raw.get("probability")
            confidence = float(confidence) if confidence is not None else None
            if confidence is not None and (
                not math.isfinite(confidence) or not 0 <= confidence <= 1
            ):
                raise ValueError("Invalid alignment probability")
            valid = end > start and count > 0
            if not valid:
                diagnostics.append(
                    {
                        "start": start,
                        "end": end,
                        "text": text,
                        "reason": "zero_duration" if end <= start else method,
                    }
                )
            words.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "units": count,
                    "unit_method": method,
                    "confidence": confidence,
                    "valid": valid,
                }
            )
    if not words:
        raise ValueError("No word timestamps; segment-only ASR cannot measure local pace")
    return words, diagnostics


def enumerate_windows(words, activity, policy):
    windows, uncertain = [], 0
    for count in policy["window_word_counts"]:
        for first in range(len(words) - count + 1):
            span = words[first : first + count]
            if any(not word["valid"] for word in span):
                continue
            if any(re.search(r"[.!?]$", word["text"].strip()) for word in span[:-1]):
                continue
            if any(
                b["start"] - a["end"] > policy["maximum_internal_word_gap_seconds"]
                for a, b in pairwise(span)
            ):
                continue
            known = [w["confidence"] for w in span if w["confidence"] is not None]
            minimum = min(known) if known else None
            if len(known) != len(span) or minimum < policy["minimum_word_confidence"]:
                uncertain += 1
                continue
            start, end = span[0]["start"], span[-1]["end"]
            elapsed = end - start
            if not policy["span_seconds"][0] <= elapsed <= policy["span_seconds"][1]:
                continue
            speech = activity.speech_seconds(start, end)
            if speech / elapsed < policy["minimum_active_fraction"]:
                uncertain += 1
                continue
            units = sum(w["units"] for w in span)
            windows.append(
                {
                    "word_start_index": first,
                    "word_count": count,
                    "start": start,
                    "end": end,
                    "center": (start + end) / 2,
                    "text": "".join(w["text"] for w in span).strip(),
                    "syllable_proxy_units": units,
                    "elapsed_seconds": elapsed,
                    "estimated_word_count": sum(
                        w["unit_method"] == "vowel_group_estimate" for w in span
                    ),
                    "speech_seconds": speech,
                    "proxy_units_per_speech_second": units / speech,
                    "words_per_elapsed_minute": count * 60 / elapsed,
                    "minimum_alignment_probability": minimum,
                    "sentence_onset": first == 0
                    or bool(re.search(r"[.!?]$", words[first - 1]["text"].strip())),
                }
            )
    return windows, uncertain


def screen(samples, rate, asr, policy):
    if policy["language"] != "en-US":
        raise ValueError("This detector's syllable proxy currently supports English only")
    activity = Activity(samples, rate, policy)
    words, invalid = flatten_words(asr, activity.duration, policy)
    windows, uncertain = enumerate_windows(words, activity, policy)
    if len(windows) < policy["minimum_reference_windows"]:
        raise ValueError("Too few reliable timing windows for a local reference")
    candidates = []
    for count in policy["window_word_counts"]:
        group = [w for w in windows if w["word_count"] == count]
        if not group:
            continue
        centers = np.array([w["center"] for w in group])
        rates = np.array([w["proxy_units_per_speech_second"] for w in group])
        course_median = float(np.median(rates))
        for row in group:
            start, end = row["start"], row["end"]
            margin = policy["reference_exclusion_seconds"]
            local = abs(centers - row["center"]) <= policy["context_seconds"]
            local &= (centers < start - margin) | (centers > end + margin)
            # No overlapping word windows in the baseline.
            local &= np.array([w["end"] <= start or w["start"] >= end for w in group])
            before, after = rates[local & (centers < start)], rates[local & (centers > end)]
            reference = rates[local]
            if len(reference) < policy["minimum_reference_windows"]:
                continue
            neighborhood = float(np.median(reference))
            comparisons = [
                float(np.median(side))
                for side in [before, after]
                if len(side) >= policy["minimum_side_reference_windows"]
            ]
            if not comparisons:
                continue
            local_rate = row["proxy_units_per_speech_second"]
            context_ratio = local_rate / neighborhood
            course_ratio = local_rate / course_median
            contrast_ratio = local_rate / min(comparisons)
            immediate_ratio = None
            if row["sentence_onset"]:
                previous = [
                    w
                    for w in group
                    if 0 <= start - w["end"] <= policy["maximum_onset_reference_gap_seconds"]
                ]
                if previous:
                    last = max(previous, key=lambda w: w["end"])
                    immediate_ratio = local_rate / last["proxy_units_per_speech_second"]
            row.update(
                context_median_proxy_rate=neighborhood,
                course_median_proxy_rate=course_median,
                ratio_to_context=context_ratio,
                ratio_to_course=course_ratio,
                maximum_side_contrast_ratio=contrast_ratio,
                sentence_onset_previous_window_ratio=immediate_ratio,
            )
            broad_jump = (
                context_ratio >= policy["minimum_context_ratio"]
                and contrast_ratio >= policy["minimum_side_contrast_ratio"]
            )
            onset_jump = (
                immediate_ratio is not None
                and immediate_ratio >= policy["minimum_onset_contrast_ratio"]
            )
            if course_ratio >= policy["minimum_course_ratio"] and (broad_jump or onset_jump):
                candidates.append(
                    {
                        **row,
                        "score": course_ratio * max(context_ratio, immediate_ratio or 0),
                        "triggers": [
                            kind
                            for kind, found in [
                                ("neighborhood_contrast", broad_jump),
                                ("sentence_onset_contrast", onset_jump),
                            ]
                            if found
                        ],
                        "status": "review_candidate_not_confirmed_defect",
                    }
                )
    # Collapse overlapping detections; report the strongest reproducible evidence
    # window, while preserving a slightly wider interval for listening in context.
    merged = []
    for row in sorted(candidates, key=lambda w: w["start"]):
        if merged and row["start"] <= merged[-1]["review_end"]:
            prior = merged[-1]
            review_start, review_end = prior["review_start"], max(prior["review_end"], row["end"])
            if row["score"] > prior["score"]:
                merged[-1] = {**row, "review_start": review_start, "review_end": review_end}
            else:
                prior["review_end"] = review_end
        else:
            merged.append({**row, "review_start": row["start"], "review_end": row["end"]})
    merged.sort(key=lambda w: w["score"], reverse=True)
    for rank, row in enumerate(merged, 1):
        row["rank"] = rank
    return {
        "status": "screening_complete",
        "llm_calls": 0,
        "audio_modified": False,
        "language": policy["language"],
        "duration_seconds": activity.duration,
        "normalization_gain_for_analysis_only": activity.normalization_gain,
        "valid_windows": len(windows),
        "alignment_uncertain_windows_skipped": uncertain,
        "invalid_or_unsupported_word_timings": invalid,
        "candidates": merged,
        "estimated_syllable_word_count": sum(
            w["unit_method"] == "vowel_group_estimate" for w in words
        ),
        "windows": windows,
        "limitations": [
            "Lexicon syllables describe a listed pronunciation, not actual phonemes.",
            "Out-of-vocabulary vowel-group counts are explicitly marked estimates.",
            "Word timestamps and their probabilities are not phonetic ground truth.",
            "Short function words can be naturally fast; a flag is a review candidate.",
            "Unsupported tokens, poor alignment and insufficient references are skipped.",
            "This measures pace contrasts, not natural stress or teaching correctness.",
        ],
    }


def write_html(path, report, audio):
    rows = []
    for row in report["candidates"]:
        minute, second = divmod(row["start"], 60)
        label = f"{int(minute):02d}:{second:05.2f}"
        a, b = (
            max(0, row["review_start"] - 4),
            min(report["duration_seconds"], row["review_end"] + 4),
        )
        rows.append(
            f"<tr><td>{row['rank']}</td><td>{label}</td>"
            f"<td>{html.escape(row['text'])}</td>"
            f"<td>{row['ratio_to_context']:.2f}×</td>"
            f'<td><button data-start="{a:.4f}" data-end="{b:.4f}">Listen</button>'
            "</td></tr>"
        )
    src = html.escape(os.path.relpath(audio.resolve(), path.parent.resolve()), quote=True)
    path.write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Local pace screening</title><style>
body{{font:16px system-ui;margin:32px;max-width:1200px;color:#163346;background:#f6fafb}}
table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;text-align:left;
border-bottom:1px solid #d6e2e7}}audio{{position:sticky;top:0;width:100%;background:white}}
button{{padding:8px 14px;cursor:pointer}}p{{line-height:1.6}}</style>
<h1>Local pace screening</h1><p>Deterministic English timing screen · No LLM calls ·
No audio edits. {len(report["candidates"])} candidate regions. Ratios compare estimated syllable
proxy rates against nearby delivery. They do not prove an unnatural performance.</p>
<audio controls id="audio" src="{src}"></audio><table><thead><tr><th>Rank</th><th>Time</th>
<th>Evidence phrase</th><th>Local contrast</th><th>Context</th></tr></thead><tbody>
{"".join(rows)}</tbody></table><p>Existing word alignment is required. Low-confidence,
zero-duration and unsupported tokens are skipped. No automatic tempo or pause correction.</p>
<script>const audio=document.getElementById('audio');let stop=Infinity;
document.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{{
stop=Number(button.dataset.end);audio.currentTime=Number(button.dataset.start);audio.play();}}));
audio.addEventListener('timeupdate',()=>{{if(audio.currentTime>=stop){{audio.pause();stop=Infinity;}}}});
</script></html>''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--asr", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    asr = json.loads(args.asr.read_text())
    source_hash = sha(args.audio)
    if asr.get("source_sha256") != source_hash:
        raise ValueError("ASR/audio hash mismatch; align the actual input file first")
    policy = json.loads(args.policy.read_text())
    rate, samples = load_pcm(args.audio)
    report = screen(samples, rate, asr, policy)
    report.update(
        audio_sha256=source_hash,
        asr_sha256=sha(args.asr),
        policy_id=policy["id"],
        policy_sha256=sha(args.policy),
        pronunciation_lexicon="cmudict " + cmudict.__version__,
        policy=policy,
        detector_sha256=sha(Path(__file__)),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    columns = [
        "rank",
        "start",
        "end",
        "text",
        "ratio_to_context",
        "ratio_to_course",
        "maximum_side_contrast_ratio",
        "minimum_alignment_probability",
        "status",
    ]
    with (args.out / "candidates.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["candidates"])
    write_html(args.out / "review.html", report, args.audio)
    assert sha(args.audio) == source_hash
    print(
        json.dumps(
            {
                "candidate_regions": len(report["candidates"]),
                "valid_windows": report["valid_windows"],
                "llm_calls": 0,
                "audio_modified": False,
                "report": str((args.out / "report.json").resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
