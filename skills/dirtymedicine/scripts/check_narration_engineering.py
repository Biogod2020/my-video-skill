"""Check a complete native narration, its receipt and exact acoustic clock.

Usage: python scripts/check_narration_engineering.py --audio take.wav --receipt take.json \
    --alignment alignment.json --tts-input spoken.txt --asr take.asr.json --out check.json
ASR differences and measured pace are review candidates, never automatic audio edits.
"""
import argparse
import hashlib
import json
import math
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    return "".join(c for c in text.casefold() if unicodedata.category(c)[0] in "LN")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ["audio", "receipt", "alignment", "tts-input", "asr", "out"]:
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--language", choices=["zh-CN", "en-US"], required=True)
    p.add_argument("--native-audio", type=Path)
    p.add_argument("--edl", type=Path)
    a = p.parse_args()
    read = lambda path: json.loads(path.read_text())
    receipt, clock, asr = read(a.receipt), read(a.alignment), read(a.asr)
    samples, rate = sf.read(a.audio, dtype="float64")
    duration = len(samples) / rate
    errors = []
    digest = sha(a.audio)
    for source, key in [(receipt, "audio_sha256"), (clock, "source_sha256"),
                        (asr, "source_sha256")]:
        if source.get(key) != digest:
            errors.append("Audio identity differs from receipt/alignment/ASR")
    text = a.tts_input.read_text().strip()
    if receipt.get("text_sha256") != hashlib.sha256(text.encode()).hexdigest():
        errors.append("The synthesized text receipt differs from reviewed TTS input")
    if not receipt.get("normal_eos") or receipt.get("hit_length_limit"):
        errors.append("Native generation did not terminate normally")
    if receipt.get("decoded_audio_block_count") != 1:
        errors.append("Expected one continuous generated audio block")
    if receipt.get("job", {}).get("target_seconds") is not None:
        errors.append("Duration conditioning was enabled")
    if receipt.get("duration_condition"):
        errors.append("The runtime applied an undeclared duration condition")
    if (receipt.get("native_speed") is not True or receipt.get("time_stretch") is not False
            or receipt.get("waveform_stitching") is not False):
        errors.append("Expected the unretimed continuous native master")
    if samples.ndim != 1 or rate != 24000 or not np.isfinite(samples).all():
        errors.append("Expected finite 24 kHz mono native audio")
    if abs(duration - receipt["duration_seconds"]) > 1 / rate:
        errors.append("Native duration does not match generation receipt")
    if asr.get("asr_expected_text_prompted") is not False:
        errors.append("ASR completeness screen was not independent of expected text")
    heard = normalized("".join(s["text"] for s in asr.get("segments", [])))
    expected = normalized(text)
    matcher = SequenceMatcher(None, expected, heard, autojunk=False)
    asr_candidates = [{"operation": op, "expected": expected[x:y], "heard": heard[u:v],
                       "expected_offset": x, "heard_offset": u}
                      for op, x, y, u, v in matcher.get_opcodes()
                      if op != "equal" and max(y-x, v-u) >= 12]
    if not expected or len(heard) < .7 * len(expected) or matcher.ratio() < .7:
        errors.append("Large independent ASR mismatch requires actual audio investigation")
    if bool(a.native_audio) != bool(a.edl):
        errors.append("Both original native audio and EDL are required for derived verification")
    if receipt.get("silence_edit_derived_master") and not (a.native_audio and a.edl):
        errors.append("A derived master requires sample-level source preservation evidence")
    if a.native_audio and a.edl:
        native, native_rate = sf.read(a.native_audio, dtype="int16")
        delivery, delivery_rate = sf.read(a.audio, dtype="int16")
        edl = read(a.edl)
        if (edl["source_sha256"] != sha(a.native_audio) or edl["output_sha256"] != digest
                or native_rate != delivery_rate or edl.get("tempo_processing") is not False):
            errors.append("Derived master EDL identifies different media or tempo processing")
        cursor, output_cursor = 0, 0
        for before, end, after, new_end in edl["retained_spans"]:
            if before != cursor or after < output_cursor or new_end-after != end-before:
                errors.append("Noncontiguous native retention spans")
                break
            if (not np.array_equal(native[before:end], delivery[after:new_end])
                    or np.any(delivery[output_cursor:after])):
                errors.append("Native PCM changed or inserted material is not silence")
                break
            cursor, output_cursor = end, new_end
        if cursor != len(native) or output_cursor != len(delivery):
            errors.append("EDL does not preserve the complete native waveform")
    if a.language == "zh-CN":
        if "Qwen" not in clock.get("model", ""):
            errors.append("Chinese requires Qwen character alignment")
        units = clock.get("units", [])
    else:
        if "CTC" not in clock.get("alignment_source", ""):
            errors.append("English requires the global CTC acoustic clock")
        units = [w for s in clock.get("segments", []) for w in s["words"]]
    if normalized("".join(w.get("text", w.get("word", "")) for w in units)) != normalized(text):
        errors.append("Acoustic units do not exactly cover the complete text")
    previous = -1.0
    for unit in units:
        start, end = unit["start"], unit["end"]
        if not all(math.isfinite(t) for t in [start, end]) or not 0 <= start <= end <= duration:
            errors.append("Invalid acoustic timestamp")
            break
        if start < previous - 1e-6:
            errors.append("Nonmonotonic acoustic clock")
            break
        previous = start
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples ** 2)))
    clipped_fraction = float(np.mean(np.abs(samples) >= 0.9999))
    if rms < 1e-5 or clipped_fraction > .005:
        errors.append("Silent or substantially clipped waveform")
    report = {"state": "passed" if not errors else "blocked", "unresolved": errors,
              "language": a.language, "audio_sha256": digest,
              "checker_sha256": sha(Path(__file__)),
              "inputs": {k: sha(getattr(a, k)) for k in
                         ["audio", "receipt", "alignment", "tts_input", "asr"]},
              "duration_s": duration, "sample_rate": rate, "peak": peak, "rms": rms,
              "clipped_fraction": clipped_fraction, "acoustic_units": len(units),
              "single_continuous_audio_block": receipt.get("decoded_audio_block_count") == 1,
              "independent_asr_similarity": matcher.ratio(),
              "independent_asr_length_ratio": len(heard) / max(1, len(expected)),
              "asr_discrepancy_candidates": asr_candidates,
              "audio_modified": bool(a.edl and read(a.edl)["edits"]),
              "speech_samples_modified": False, "llm_numeric_calls": 0,
              "sparse_silence_derivation_verified": bool(a.edl and not errors),
              "actual_full_audio_review_required": True,
              "scope": "Native identity, complete acoustic clock and waveform; ASR differences and pace candidates need evidence review, not automatic retiming."}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report["state"], round(duration, 2), errors)
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
