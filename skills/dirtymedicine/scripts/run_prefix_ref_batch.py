"""Run frozen reference-selection probes and decode exact evidence, with bounded IO retries.

Usage: python scripts/run_prefix_ref_batch.py --manifest requests.json --out results.json
Only transport or malformed JSON is retried once. Valid judgements are never retried
for their verdict. Protocol, input, schema and actual prompt identities are verified.
"""

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from check_prefix_review import build_prefix_prompt
from prefix_review_refs import build_api_review_schema, build_ref_index, decode_ref_review


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def ref(p):
    return {"path": str(Path(p).resolve()), "sha256": sha(p)}


def run_case(c, protocol, api_enum_limit=0):
    for key in ["input", "prompt", "api_schema", "ref_index"]:
        if sha(c[key]["path"]) != c[key]["sha256"]:
            raise ValueError("Frozen request file changed: " + key)
    inp = read(c["input"]["path"])
    index = build_ref_index(inp, granularity="sentence")
    assert index == read(c["ref_index"]["path"])
    assert build_prefix_prompt(inp, protocol) == Path(c["prompt"]["path"]).read_text()
    assert build_api_review_schema(index) == read(c["api_schema"]["path"])
    api_schema_path = c["api_schema"]["path"]
    transport_schema = None
    if api_enum_limit:
        def compact(value):
            if isinstance(value, list):
                return [compact(v) for v in value]
            if isinstance(value, dict):
                return {k: compact(v) for k, v in value.items()
                        if not (k == "enum" and len(v) > api_enum_limit)}
            return value
        # Backend complexity limits do not weaken the full local ID/order decoder.
        target = Path(c["review_dir"] + ".transport-schema.json")
        assert not target.exists(), "Preserve every transport schema"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(compact(read(api_schema_path)), ensure_ascii=False, indent=2))
        api_schema_path, transport_schema = str(target), ref(target)
    attempts = []
    selected = None
    for attempt in range(2):
        out = Path(c["review_dir"] + (f".retry-{attempt}" if attempt else ""))
        assert not out.exists(), "Use new attempt paths; no overwrite"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("gemini_qc_review.py")),
                "--prompt",
                c["prompt"]["path"],
                "--schema",
                api_schema_path,
                "--constrain-schema",
                "--out",
                str(out),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=1150,
        )
        meta = read(out / "manifest.json")
        attempts.append(
            {"directory": str(out), "state": meta["state"], "exit_code": result.returncode}
        )
        if meta["state"] == "complete":
            selected = out
            break
        # No feedback about expected labels or previous verdicts is sent.
        if attempt == 0:
            time.sleep(15)
    row = {**c, "attempts": attempts, "state": "transport_error"}
    if transport_schema:
        row["transport_schema"] = transport_schema
        row["api_enum_limit"] = api_enum_limit
    if selected:
        raw = (selected / "result.json").read_bytes()
        try:
            decoded = decode_ref_review(index, json.loads(raw), original_result_bytes=raw)
            dp = selected / "decoded.json"
            dp.write_text(json.dumps(decoded, ensure_ascii=False, indent=2) + "\n")
            cp = selected / "canonical-result.json"
            cp.write_text(json.dumps(decoded["result"], ensure_ascii=False, indent=2) + "\n")
            row.update(
                state="decoded",
                result=ref(cp),
                raw_result=ref(selected / "result.json"),
                decoded=ref(dp),
                transport=ref(selected / "manifest.json"),
            )
        except (ValueError, KeyError, TypeError) as e:
            row.update(
                state="decoder_error",
                error=str(e),
                raw_result=ref(selected / "result.json"),
                transport=ref(selected / "manifest.json"),
            )
    print(c["case_id"], row["state"], flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--api-enum-limit", type=int, default=0,
                   help="Compact only backend enums; keep strict frozen local reference validation")
    a = p.parse_args()
    m = read(a.manifest)
    assert sha(m["reviewer_protocol"]["path"]) == m["reviewer_protocol"]["sha256"]
    protocol = Path(m["reviewer_protocol"]["path"]).read_text()
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        rows = list(pool.map(lambda c: run_case(c, protocol, a.api_enum_limit), m["cases"]))
    output = {
        **m,
        "cases": rows,
        "state": "complete" if all(r["state"] == "decoded" for r in rows) else "incomplete",
        "runner_sha256": sha(__file__),
    }
    a.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(0 if output["state"] == "complete" else 1)


if __name__ == "__main__":
    main()
