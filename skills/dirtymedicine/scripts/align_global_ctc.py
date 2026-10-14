"""Globally align existing text to actual waveform CTC emissions, without ASR or LLM timing.

Overlapped acoustic windows retain the exact shared frame grid. A single global
CTC path prevents short independent sentence searches from rewinding in time.
"""

import argparse
import hashlib
import json
import re
from itertools import pairwise
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio
from build_text_audio_map import spoken_only


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--text", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--greedy-only", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(4)
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    model = bundle.get_model().to("cuda").eval()
    metadata = {"dictionary": {label.lower(): i for i, label in enumerate(bundle.get_labels())}}
    layers = model.feature_extractor.conv_layers
    stride, field = 1, 1
    for layer in layers:
        conv = layer.conv
        field += (conv.kernel_size[0] - 1) * stride
        stride *= conv.stride[0]
    assert stride == 320 and field == 400, (stride, field)
    waveform, input_rate = sf.read(args.audio, dtype="float32")
    assert waveform.ndim == 1
    audio = torchaudio.functional.resample(torch.from_numpy(waveform), input_rate, 16000).numpy()
    sample_rate = 16000
    total_frames = (len(audio) - field) // stride + 1
    emissions = torch.empty(total_frames, len(metadata["dictionary"]), dtype=torch.float32)
    filled = np.zeros(total_frames, dtype=bool)
    core_samples = 30 * sample_rate
    context_samples = sample_rate
    with torch.inference_mode():
        for core_start in range(0, len(audio), core_samples):
            core_end = min(len(audio), core_start + core_samples)
            window_start = max(0, core_start - context_samples)
            window_end = min(len(audio), core_end + context_samples)
            assert window_start % stride == 0
            waveform = (
                torch.from_numpy(audio[window_start:window_end].copy()).unsqueeze(0).to("cuda")
            )
            logits = model(waveform)[0][0].log_softmax(-1).float().cpu()
            first = core_start // stride
            last = min(total_frames, core_end // stride)
            local_first = first - window_start // stride
            local_last = local_first + (last - first)
            assert local_last <= len(logits)
            emissions[first:last] = logits[local_first:local_last]
            filled[first:last] = True
            print(
                "ACOUSTIC_GRID",
                round(core_end / sample_rate, 2),
                len(audio) / sample_rate,
                flush=True,
            )
    assert filled.all(), np.flatnonzero(~filled)[:10]
    spoken = spoken_only(args.text.read_text())
    words = re.findall(r"\S+", spoken)
    dictionary = metadata["dictionary"]
    blank = dictionary.get("-", 0)
    labels = bundle.get_labels()
    greedy_ids = torch.unique_consecutive(emissions.argmax(-1)).tolist()
    greedy_text = "".join(labels[i] for i in greedy_ids if i != blank).replace("|", " ").strip()
    greedy_result = {
        "source_sha256": sha(args.audio),
        "transcript": greedy_text,
        "supplied_transcript_used_to_decode": False,
        "decode": "greedy acoustic CTC",
        "model": "torchaudio WAV2VEC2_ASR_BASE_960H",
        "limitation": "Base English ASR; medical terms and letter names can be misrecognized.",
    }
    args.out.with_suffix(".greedy.json").write_text(json.dumps(greedy_result, indent=2))
    print("INDEPENDENT_ACOUSTIC_TRANSCRIPT_SAVED", len(greedy_text.split()), flush=True)
    if args.greedy_only:
        return
    tokens, owners = [], []
    unsupported = []
    for index, word in enumerate(words):
        chars = [c.lower() for c in word if c.lower() in dictionary and c.lower() != "-"]
        # Hyphens and punctuation do not stand for acoustic characters.
        unknown = [c for c in word if c.isdigit()]
        if unknown:
            unsupported.append({"word_index": index, "word": word, "unsupported_digits": unknown})
        assert chars, (index, word)
        if tokens:
            tokens.append(dictionary["|"])
            owners.append(None)
        for char in chars:
            tokens.append(dictionary[char])
            owners.append(index)
    repeats = sum(a == b for a, b in pairwise(tokens))
    assert total_frames >= len(tokens) + repeats
    targets = torch.tensor(tokens, dtype=torch.int32).unsqueeze(0)
    paths, scores = torchaudio.functional.forced_align(emissions.unsqueeze(0), targets, blank=blank)
    spans = torchaudio.functional.merge_tokens(paths[0], scores[0].exp(), blank=blank)
    assert [span.token for span in spans] == tokens
    by_word = [[] for _ in words]
    for owner, span in zip(owners, spans):
        if owner is not None:
            by_word[owner].append(span)
    duration = len(audio) / sample_rate
    rows = []
    current = []
    unsupported_indices = {x["word_index"] for x in unsupported}
    frame_offset = field / 2 / sample_rate
    for index, (word, char_spans) in enumerate(zip(words, by_word)):
        assert char_spans
        start = char_spans[0].start * stride / sample_rate + frame_offset
        end = min(duration, char_spans[-1].end * stride / sample_rate + frame_offset)
        confidence = sum(span.score * (span.end - span.start) for span in char_spans) / sum(
            span.end - span.start for span in char_spans
        )
        if index in unsupported_indices:
            confidence = 0.0
        current.append(
            {
                "word": " " + word,
                "start": start,
                "end": end,
                "probability": float(confidence),
                "confidence_type": "CTC acoustic alignment score; supplied words are not proof of coverage",
            }
        )
        if word.endswith((".", "?", "!")) or index == len(words) - 1:
            rows.append(
                {
                    "start": current[0]["start"],
                    "end": current[-1]["end"],
                    "text": " ".join(q["word"].strip() for q in current),
                    "words": current,
                }
            )
            current = []
    all_words = [q for row in rows for q in row["words"]]
    assert all(a["start"] <= b["start"] for a, b in pairwise(all_words))
    result = {
        "source_sha256": sha(args.audio),
        "segments": rows,
        "language": "en",
        "alignment_source": "single global CTC path over exact overlapped acoustic frame grid",
        "asr_called": False,
        "llm_timing_calls": 0,
        "supplied_transcript_sha256": sha(args.text),
        "spoken_only_sha256": hashlib.sha256(spoken.encode()).hexdigest(),
        "content_coverage_proof": False,
        "model": "torchaudio WAV2VEC2_ASR_BASE_960H",
        "time_scale": 1.0,
        "torchaudio_version": torchaudio.__version__,
        "torch_version": torch.__version__,
        "frame_stride_samples": stride,
        "receptive_field_samples": field,
        "sample_rate_for_analysis": sample_rate,
        "total_ctc_frames": total_frames,
        "analysis_chunk_seconds": 30,
        "context_overlap_seconds": 1,
        "unsupported_digit_words": unsupported,
        "algorithm_sha256": sha(Path(__file__)),
        "word_count": len(all_words),
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("GLOBAL_CTC_ALIGNMENT_DONE", len(all_words), all_words[-1]["end"], flush=True)


if __name__ == "__main__":
    main()
