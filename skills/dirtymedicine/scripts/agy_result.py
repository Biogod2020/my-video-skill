"""Select the current final agy JSON, never a stale structured tool result.

The CLI can retain an earlier structured_output when its final response contains
a newer revised JSON document. Validate the actual final response independently.
"""

import hashlib
import json
import re

import jsonschema


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def final_json(raw):
    if not isinstance(raw, str):
        raise TypeError("Final agy response must be text")
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(clean), None
    except json.JSONDecodeError:
        # Allow only redundant trailing envelope closers, never multiple JSON
        # documents, arbitrary commentary, changed strings, or truncated content.
        value, end = json.JSONDecoder().raw_decode(clean)
        tail = clean[end:].strip()
        if tail and set(tail) <= {"}", "]"}:
            return value, "Removed redundant trailing envelope closers: " + tail
        raise


def select_result(outer, schema=None):
    if outer.get("status") != "SUCCESS":
        raise ValueError("agy did not return SUCCESS")
    result, envelope_repair = final_json(outer.get("response", ""))
    if not isinstance(result, dict):
        raise TypeError("Expected one complete final JSON object")
    removed = []
    if schema:
        props = schema.get("properties", {})
        removed = [k for k in ["toolAction", "toolSummary"] if k in result and k not in props]
        result = {k: v for k, v in result.items() if k not in removed}
        jsonschema.validate(result, schema)
    structured = outer.get("structured_output")
    if isinstance(structured, dict):
        if schema:
            structured = {k: v for k, v in structured.items()
                          if k not in {"toolAction", "toolSummary"} or k in schema.get("properties", {})}
        same = canonical_hash(result) == canonical_hash(structured)
    else:
        same = None
    provenance = {
        "result_source": "current final response JSON",
        "final_response_sha256": hashlib.sha256(outer["response"].encode()).hexdigest(),
        "selected_result_sha256": canonical_hash(result),
        "structured_output_present": isinstance(structured, dict),
        "structured_output_matches_final": same,
        "structured_output_sha256": canonical_hash(structured) if isinstance(structured, dict) else None,
        "structured_output_used": False,
        "json_schema_validated": schema is not None,
        "envelope_repair": envelope_repair,
        "removed_outer_tool_metadata": removed,
    }
    return result, provenance
