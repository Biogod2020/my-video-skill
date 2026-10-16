"""Run an agy author/reviewer with proxy and verify the current final JSON.

Usage: python scripts/run_agy_json.py --prompt prompt.txt --schema schema.json --out run
The output directory must be new. Raw responses stay private; credentials are not logged.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from agy_result import select_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--conversation")
    parser.add_argument("--role", choices=["author", "review"], default="author")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--local-schema-only",
        action="store_true",
        help="Validate the final response locally without a CLI schema tool",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    prompt, schema = args.prompt.read_text(), json.loads(args.schema.read_text())
    manifest = {
        "state": "submitted",
        "model_requested": "gemini-3.8-flash-high",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(args.schema.read_bytes()).hexdigest(),
        "role": args.role,
        "conversation_resumed": bool(args.conversation),
        "model_returned": "not_exposed_by_cli",
        "client_retries": 0,
        "schema_enforcement": "local_only" if args.local_schema_only else "cli_and_local",
    }
    (args.out / "prompt.txt").write_text(prompt)

    def save():
        (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    save()
    binary = os.environ.get("AGY_BIN", str(Path.home() / ".local/bin/agy"))
    cmd = [
        "zsh",
        "-ic",
        'proxy >/dev/null || exit; exec "$@"',
        "agy-json",
        binary,
        "--model",
        manifest["model_requested"],
        "--effort",
        "high",
        "--mode",
        "plan",
        "--output-format",
        "json",
    ]
    if not args.local_schema_only:
        cmd += ["--json-schema", str(args.schema.resolve())]
    if args.conversation:
        cmd += ["--conversation", args.conversation]
    cmd += ["--print", prompt]
    started = time.monotonic()
    print("AGY_JSON_SUBMITTED", args.role, flush=True)
    try:
        with (
            (args.out / "response.json").open("w") as raw,
            (args.out / "stderr.log").open("w") as err,
        ):
            process = subprocess.run(cmd, stdout=raw, stderr=err, timeout=args.timeout, check=False)
        if process.returncode:
            raise RuntimeError(f"CLI exited {process.returncode}")
        outer = json.loads((args.out / "response.json").read_text())
        result, checks = select_result(outer, schema)
        (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        (args.out / "selection-checks.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2)
        )
        manifest.update(
            state="complete",
            conversation_id=outer.get("conversation_id"),
            json_schema_validated=True,
            current_final_response_selected=True,
        )
    except (subprocess.TimeoutExpired, RuntimeError, ValueError, TypeError, OSError) as error:
        manifest.update(state="failed", error_type=type(error).__name__, error=str(error))
    finally:
        manifest["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save()
    print("AGY_JSON", manifest["state"], flush=True)
    if manifest["state"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
