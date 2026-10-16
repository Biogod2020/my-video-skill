"""Stateless Gemini JSON review of text or unchanged complete media.

Usage: python scripts/gemini_qc_review.py --prompt prompt.txt --schema schema.json --out run
Add --media for actual images/audio/video. Credentials stay in ignored local config.
"""

import argparse
import base64
import hashlib
import json
import mimetypes
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonschema

ROOT = Path(__file__).resolve().parent
OUT = None
VIDEO = None
MODEL = "gemini-3.8-flash-high"


def main():
    global OUT, VIDEO
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--media", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--constrain-schema", action="store_true",
                        help="Also send the supplied schema via responseJsonSchema")
    parser.add_argument("--max-output-tokens", type=int, default=24000)
    parser.add_argument("--video-fps", type=float, default=2.0)
    parser.add_argument("--media-resolution", choices=["LOW", "MEDIUM", "HIGH"], default="MEDIUM")
    args = parser.parse_args()
    OUT = args.out
    VIDEO = args.media
    OUT.mkdir(parents=True, exist_ok=False)
    prompt = args.prompt.read_text()
    (OUT / "prompt.txt").write_text(prompt)
    parts, actual_media = [], []
    for path in VIDEO:
        data = path.read_bytes()
        parts.append({"text": "Actual complete attached media: " + path.name})
        parts.append(
            {
                "inlineData": {
                    "mimeType": mimetypes.guess_type(path.name)[0],
                    "data": base64.b64encode(data).decode(),
                },
                **({"videoMetadata": {"fps": args.video_fps}} if path.suffix == ".mp4" else {}),
            }
        )
        actual_media.append(
            {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    parts.append({"text": prompt})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "maxOutputTokens": args.max_output_tokens,
            "thinkingConfig": {"thinkingLevel": "high"},
            "mediaResolution": "MEDIA_RESOLUTION_" + args.media_resolution,
        },
    }
    if args.constrain_schema:
        if not args.schema:
            parser.error("--constrain-schema requires --schema")
        payload["generationConfig"]["responseJsonSchema"] = json.loads(args.schema.read_text())
    body = json.dumps(payload, ensure_ascii=False).encode()
    manifest = {
        "model_requested": MODEL,
        "state": "prepared",
        "transport": "native_SSE",
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "actual_media": actual_media,
        "request_sha256": hashlib.sha256(body).hexdigest(),
        "request_bytes": len(body),
        "complete_unchanged_media_file": True,
        "audio_not_trimmed": True,
        "video_visual_sampling_fps": args.video_fps
        if any(x.suffix == ".mp4" for x in VIDEO)
        else None,
        "model_visual_media_resolution": args.media_resolution,
        "client_retries": 0,
        "fallback_model": False,
        "stateless": True,
        "conversation_mode": "single_contents_request",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(args.schema.read_bytes()).hexdigest()
        if args.schema
        else None,
        "schema_sent_to_backend": args.constrain_schema,
        "max_output_tokens": args.max_output_tokens,
    }

    def save_manifest():
        (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    save_manifest()
    credentials = json.loads(
        (Path.home() / ".config/cliproxyapi-audio-review/client.json").read_text()
    )
    request = urllib.request.Request(
        credentials["base_url"].rstrip("/")
        + f"/v1beta/models/{MODEL}:streamGenerateContent?alt=sse",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": "Bearer " + credentials["api_key"],
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    events, texts, finish_reasons = [], [], []

    def consume_event(lines):
        value = "\n".join(lines)
        if not value or value == "[DONE]":
            return
        event = json.loads(value)
        events.append(event)
        if "error" in event:
            raise RuntimeError("Upstream SSE error; see saved response event")
        if event.get("modelVersion"):
            manifest["model_returned"] = event["modelVersion"]
        if event.get("usageMetadata"):
            manifest["usage"] = event["usageMetadata"]
        for candidate in event.get("candidates", []):
            if candidate.get("index", 0) != 0:
                continue
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part and not part.get("thought"):
                    texts.append(part["text"])
            if candidate.get("finishReason"):
                finish_reasons.append(candidate["finishReason"])
        manifest["event_count"] = len(events)
        save_manifest()

    try:
        manifest["state"] = "submitted"
        save_manifest()
        print("SUBMITTED_COMPLETE_MEDIA_SSE", MODEL, flush=True)
        with opener.open(request, timeout=540) as response:
            manifest.update(
                http_status=response.status,
                state="stream_open",
                response_content_type=response.headers.get("Content-Type"),
            )
            save_manifest()
            print("STREAM_OPEN", response.status, flush=True)
            pending = []
            with (OUT / "response.sse").open("wb") as raw_file:
                for raw_line in response:
                    raw_file.write(raw_line)
                    raw_file.flush()
                    if time.monotonic() - started > 1100:
                        raise TimeoutError("Bounded total SSE review deadline exceeded")
                    line = raw_line.decode().rstrip("\r\n")
                    if not line:
                        consume_event(pending)
                        pending = []
                    elif line.startswith("data:"):
                        pending.append(line[5:].lstrip(" "))
                consume_event(pending)
        reply = "".join(texts)
        (OUT / "reply.txt").write_text(reply)
        if not finish_reasons or finish_reasons[-1] != "STOP":
            raise RuntimeError("Incomplete model response")
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
        result = json.loads(cleaned)
        if args.schema:
            jsonschema.validate(result, json.loads(args.schema.read_text()))
            manifest["json_schema_validated"] = True
        (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        manifest.update(state="complete", finish_reasons=finish_reasons)
        print("COMPLETE", manifest.get("model_returned"), len(reply), flush=True)
    except urllib.error.HTTPError as error:
        (OUT / "error-response.txt").write_bytes(error.read())
        manifest.update(state="http_error", http_status=error.code)
        print("REVIEW_HTTP_ERROR", error.code, flush=True)
    except TimeoutError:
        manifest["state"] = "transport_timeout"
        print("REVIEW_TRANSPORT_TIMEOUT", flush=True)
    except (RuntimeError, ValueError, OSError, UnicodeError, jsonschema.ValidationError) as error:
        manifest.update(state="failed", error_type=type(error).__name__, error_summary=str(error))
        print("REVIEW_FAILED", type(error).__name__, flush=True)
    finally:
        (OUT / "response-events.json").write_text(json.dumps(events, ensure_ascii=False))
        manifest["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save_manifest()

    if manifest["state"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
