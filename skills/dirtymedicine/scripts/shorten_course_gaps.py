"""Shorten explicitly reviewed quiet gaps without changing retained PCM samples.

Usage:
    python scripts/shorten_course_gaps.py --audio native.wav --alignment ctc.json \
        --plan reviewed-cuts.json --out edited/

No global silence removal or tempo processing. Every cut needs a source-bound
word index, a contextual reason, and measured quiet margins on both sides.
"""

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from build_text_audio_map import load_units, normalized


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def quiet_runs(samples, begin, end, rate, settings):
    window = round(settings["window_seconds"] * rate)
    hop = round(settings["hop_seconds"] * rate)
    rms_limit = 32768 * 10 ** (settings["quiet_rms_dbfs"] / 20)
    peak_limit = 32768 * 10 ** (settings["quiet_peak_dbfs"] / 20)
    runs, start, last = [], None, None
    for pos in range(begin, end - window + 1, hop):
        block = samples[pos:pos + window].astype(float)
        quiet = np.sqrt(np.mean(block ** 2)) <= rms_limit and abs(block).max() <= peak_limit
        if quiet:
            if start is None:
                start = pos
            last = pos + window
        elif start is not None:
            runs.append((start, last))
            start = None
    if start is not None:
        runs.append((start, last))
    return runs


def low_join_sample(samples, center, begin, end, rate, settings, left=False):
    radius = round(settings["join_search_seconds"] * rate)
    positions = np.arange(max(begin, center - radius), min(end, center + radius) + 1)
    probe = positions - 1 if left else positions
    valid = positions[abs(samples[probe].astype(np.int32)) <= settings["join_max_pcm_units"]]
    if not len(valid):
        raise ValueError("No near-zero join sample inside the verified quiet run")
    return int(valid[np.argmin(abs(valid - center))])


def apply(audio, alignment_path, plan_path, out):
    plan, alignment = json.loads(plan_path.read_text()), json.loads(alignment_path.read_text())
    digest = sha(audio)
    assert digest == plan["source_sha256"] == alignment["source_sha256"]
    assert sha(alignment_path) == plan["alignment_sha256"]
    info = sf.info(audio)
    assert info.channels == 1 and info.subtype == "PCM_16"
    samples, rate = sf.read(audio, dtype="int16")
    units, _ = load_units(alignment, "en", info.duration)
    settings = plan["settings"]
    edits = []
    for request in plan["cuts"]:
        assert request["necessary_edit"] is True and request["necessity_reason"].strip()
        index = request["word_index"]
        left, right = units[index], units[index + 1]
        assert not left["flags"] and not right["flags"]
        assert normalized(left["text"]) == normalized(request["left_word"])
        assert normalized(right["text"]) == normalized(request["right_word"])
        gap = right["start"] - left["end"]
        target = request["target_gap_seconds"]
        assert 0 < target < gap
        guard = settings["phonetic_guard_seconds"]
        begin, end = round((left["end"] + guard) * rate), round((right["start"] - guard) * rate)
        runs = quiet_runs(samples, begin, end, rate, settings)
        assert runs, (index, "No protected quiet interval")
        a, b = max(runs, key=lambda span: span[1] - span[0])
        remove = round((gap - target) * rate)
        search = round(settings["join_search_seconds"] * rate)
        assert b - a >= remove + 2 * search, (index, "Insufficient safe quiet; keep original")
        first = a + (b - a - remove) // 2
        start = low_join_sample(samples, first, a, b - 1, rate, settings, left=True)
        finish = low_join_sample(samples, first + remove, a, b - 1, rate, settings)
        assert start < finish and begin <= start < finish <= end
        assert abs(int(samples[start - 1]) - int(samples[finish])) <= 16
        block = samples[start:finish].astype(float)
        for unit in units:
            assert not (unit["start"] * rate < finish and unit["end"] * rate > start)
        edits.append({
            **request, "operation": "remove_verified_quiet_middle",
            "source_start_sample": start, "source_end_sample": finish,
            "removed_samples": finish - start, "removed_seconds": (finish - start) / rate,
            "source_word_gap_seconds": gap,
            "output_word_gap_seconds": gap - (finish - start) / rate,
            "removed_rms_dbfs": float(20 * np.log10(max(np.sqrt(np.mean(block ** 2)), 1) / 32768)),
            "removed_peak_pcm": int(abs(block).max()),
            "join_left_pcm": int(samples[start - 1]), "join_right_pcm": int(samples[finish]),
            "confidence_note": "Quiet energy and aligned guards do not independently prove semantics",
        })
    edits.sort(key=lambda item: item["source_start_sample"])
    assert all(a["source_end_sample"] <= b["source_start_sample"]
               for a, b in itertools.pairwise(edits))
    blocks, spans, cursor, destination = [], [], 0, 0
    for edit in edits:
        end = edit["source_start_sample"]
        blocks.append(samples[cursor:end])
        spans.append([cursor, end, destination, destination + end - cursor])
        destination += end - cursor
        cursor = edit["source_end_sample"]
    blocks.append(samples[cursor:])
    spans.append([cursor, len(samples), destination, destination + len(samples) - cursor])
    result = np.concatenate(blocks)
    for a, b, c, d in spans:
        assert np.array_equal(samples[a:b], result[c:d])
    out.mkdir(parents=True, exist_ok=False)
    target_path = out / "narration.wav"
    sf.write(target_path, result, rate, subtype="PCM_16")
    decoded, decoded_rate = sf.read(target_path, dtype="int16")
    assert decoded_rate == rate and np.array_equal(decoded, result) and sha(audio) == digest

    def remap(t):
        sample = t * rate
        removed = sum(max(0, min(sample, e["source_end_sample"]) - e["source_start_sample"])
                      for e in edits if sample > e["source_start_sample"])
        return (sample - removed) / rate

    mapped = copy.deepcopy(alignment)
    for segment in mapped["segments"]:
        for row in [segment, *segment["words"]]:
            for key in ["start", "end"]:
                row["pre_quiet_cut_" + key] = row[key]
                row[key] = remap(row[key])
    output_digest = sha(target_path)
    mapped.update(source_sha256=output_digest, original_source_sha256=digest,
                  silence_edit_mapping="sample-exact quiet removals", new_model_inference=False)
    save(out / "alignment.json", mapped)
    metadata = json.loads(audio.with_suffix(".json").read_text())
    metadata.update(audio_sha256=output_digest, original_source_sha256=digest,
                    duration_seconds=len(result) / rate, time_stretch=False,
                    silence_edit_derived_master=True)
    metadata["postprocessing"] = [{"operation": "reviewed_quiet_middle_removals",
                                   "edl": str((out / "pause-edl.json").resolve())}]
    save(out / "narration.json", metadata)
    edl = {"source": str(audio.resolve()), "source_sha256": digest,
           "output_sha256": output_digest, "sample_rate": rate,
           "native_duration_seconds": len(samples) / rate,
           "delivery_duration_seconds": len(result) / rate,
           "total_added_seconds": 0, "total_removed_seconds": (len(samples) - len(result)) / rate,
           "edits": edits, "retained_spans": spans, "source_spans_retained_bit_identical": True,
           "tempo_processing": False, "new_speech_generated": False, "llm_timing_calls": 0,
           "plan_sha256": sha(plan_path), "script_sha256": sha(Path(__file__))}
    save(out / "pause-edl.json", edl)
    save(out / "remap.json", {"mapping_rule": "t minus removed samples preceding t", **edl})
    sf.write(out / "audio.flac", result, rate, format="FLAC", subtype="PCM_16")
    assert np.array_equal(sf.read(out / "audio.flac", dtype="int16")[0], result)
    print("REVIEWED_QUIET_CUTS_APPLIED", len(edits), edl["total_removed_seconds"],
          edl["delivery_duration_seconds"])
    return edl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "alignment", "plan", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    apply(args.audio, args.alignment, args.plan, args.out)


if __name__ == "__main__":
    main()
