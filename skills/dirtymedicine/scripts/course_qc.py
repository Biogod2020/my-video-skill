"""Compute current course readiness from version-bound evidence, without cached PASS.

Usage: python scripts/course_qc.py --manifest current-release.json --out release-status.json

This checks contracts, identities, dependencies and declared findings. It neither
hears media nor proves a model's semantic judgement. It never grants user approval.
Paths are relative to the manifest/receipt containing them unless absolute.
"""

import argparse
import hashlib
import json
from pathlib import Path

CONTRACT = "course-qc/1"
CHECK_CONTRACT = "course-qc-check/1"
STATES = {"NOT_RUN", "RUNNING", "PASS", "FAIL", "UNCERTAIN", "ERROR", "STALE"}


def read(path):
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve(base, name):
    path = Path(name)
    return path if path.is_absolute() else base / path


def pointer(value, path):
    if not path:
        return value
    if not path.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def evidence_files(entries, base):
    values, errors = {}, []
    for key, entry in entries.items():
        path = resolve(base, entry["path"])
        if not path.is_file():
            errors.append(f"{key}: missing file")
        elif file_digest(path) != entry["sha256"]:
            errors.append(f"{key}: file hash changed")
        else:
            values[key] = path
    return values, errors


def evaluate(manifest_path):
    """Re-read every required proof and compute eligibility for this exact target."""
    manifest_path = Path(manifest_path).resolve()
    base, manifest = manifest_path.parent, read(manifest_path)
    if manifest.get("schema_version") != CONTRACT:
        raise ValueError("Unknown course QC manifest contract")
    policy_path = resolve(base, manifest["release_policy"])
    policy = read(policy_path)
    target = manifest["target"]
    required = policy["targets"][target]
    if not required:
        raise ValueError("Release target has no required checks")
    artifacts, errors = evidence_files(manifest["artifacts"], base)
    current = manifest["artifacts"]
    policy_files = manifest.get("policy_files", {})
    policy_paths, policy_errors = evidence_files(policy_files, base)
    artifact_errors = {}

    def inspect_artifact(key, visiting):
        if key in artifact_errors:
            return artifact_errors[key]
        if key in visiting:
            raise ValueError("Artifact dependency cycle")
        if key not in current:
            return [f"missing dependency {key}"]
        problems = []
        if key not in artifacts:
            problems.append("artifact missing or hash changed")
        for parent in policy.get("artifact_dependencies", {}).get(key, []):
            if parent not in current[key].get("built_from", {}):
                problems.append(f"missing required provenance edge {parent}")
        for parent, expected in current[key].get("built_from", {}).items():
            if parent not in current or current[parent]["sha256"] != expected:
                problems.append(f"built from another version of {parent}")
            elif inspect_artifact(parent, visiting | {key}):
                problems.append(f"upstream {parent} is stale")
        artifact_errors[key] = problems
        return problems

    for key in current:
        inspect_artifact(key, set())
    checks = {}
    for key in required:
        rule = policy["checks"][key]
        item = manifest.get("checks", {}).get(key)
        reasons, status = [], "PASS"
        if not item:
            checks[key] = {"status": "NOT_RUN", "reasons": ["missing required receipt"]}
            continue
        receipt_path = resolve(base, item["path"])
        if not receipt_path.is_file():
            checks[key] = {"status": "NOT_RUN", "reasons": ["receipt does not exist"]}
            continue
        if file_digest(receipt_path) != item["sha256"]:
            checks[key] = {"status": "STALE", "reasons": ["receipt hash changed"]}
            continue
        receipt = read(receipt_path)
        if (
            receipt.get("schema_version") != CHECK_CONTRACT
            or receipt.get("check_id") != key
            or receipt.get("candidate_id") != manifest["candidate_id"]
            or receipt.get("language") != manifest["language"]
        ):
            checks[key] = {"status": "ERROR", "reasons": ["receipt identity/contract mismatch"]}
            continue
        declared = receipt.get("status")
        if declared not in STATES:
            status, reasons = "ERROR", ["unknown receipt status"]
        elif declared != "PASS":
            status, reasons = declared, ["check did not pass"]
        bound = receipt.get("bindings", {})
        if receipt.get("rule_sha256") != digest(rule):
            status = "STALE"
            reasons.append("this check's release rule changed")
        for artifact in rule["required_artifacts"]:
            if artifact not in bound.get("artifacts", {}):
                status = "ERROR"
                reasons.append(f"missing artifact binding {artifact}")
        for artifact, expected in bound.get("artifacts", {}).items():
            if (
                artifact not in current
                or current[artifact]["sha256"] != expected
                or artifact_errors.get(artifact)
            ):
                status = "STALE"
                reasons.append(f"stale artifact binding {artifact}")
        for family in rule.get("required_policies", []):
            entry = bound.get("policies", {}).get(family)
            expected = policy_files.get(family)
            if not entry or not expected:
                status = "ERROR"
                reasons.append(f"missing required policy family {family}")
            elif (
                entry["sha256"] != expected["sha256"]
                or family not in policy_paths
                or resolve(receipt_path.parent, entry["path"]).resolve()
                != resolve(base, expected["path"]).resolve()
            ):
                status = "STALE"
                reasons.append(f"policy family changed {family}")
        for category in ("tools", "policies"):
            entries = bound.get(category, {})
            if category == "tools" and not entries:
                status = "ERROR"
                reasons.append("no checker/protocol tool identity")
            _, bad = evidence_files(entries, receipt_path.parent)
            if bad:
                status = "STALE"
                reasons.extend(f"{category}/{x}" for x in bad)
        evidence, bad = evidence_files(receipt.get("evidence", {}), receipt_path.parent)
        if bad:
            status = "STALE"
            reasons.extend(f"evidence/{x}" for x in bad)
        for condition in rule["conditions"]:
            try:
                actual = pointer(read(evidence[condition["evidence"]]), condition["pointer"])
                if type(actual) is not type(condition["equals"]) or actual != condition["equals"]:
                    if status == "PASS":
                        status = "FAIL"
                    reasons.append(f"evidence contradicts {condition['pointer']}")
            except (KeyError, IndexError, TypeError, ValueError):
                if status == "PASS":
                    status = "ERROR"
                reasons.append("missing or malformed required result evidence")
        for binding in rule.get("result_identity", []):
            try:
                data = read(evidence[binding["evidence"]])
                actual = pointer(
                    data, binding["pointer"].replace("{language}", manifest["language"])
                )
                artifact = binding["artifact"]
                expected = current[artifact]["sha256"]
                if binding.get("mode") == "draft_language":
                    draft = read(artifacts[artifact])
                    expected = digest(draft["languages"][manifest["language"]])
                if actual != expected:
                    status = "STALE"
                    reasons.append(f"inner result identity differs for {artifact}")
            except (KeyError, IndexError, TypeError, ValueError):
                if status == "PASS":
                    status = "ERROR"
                reasons.append("inner result identity missing")
        for binding in rule.get("literal_identity", []):
            try:
                actual = pointer(read(evidence[binding["evidence"]]), binding["pointer"])
                expected = manifest[binding["manifest_key"]]
                if actual != expected:
                    status = "STALE"
                    reasons.append(f"inner result {binding['manifest_key']} mismatch")
            except (KeyError, IndexError, TypeError, ValueError):
                if status == "PASS":
                    status = "ERROR"
                reasons.append("inner result language/scope identity missing")
        for binding in rule.get("result_tool_identity", []):
            try:
                inner_hash = pointer(read(evidence[binding["evidence"]]), binding["pointer"])
                tool_hashes = {entry["sha256"] for entry in bound.get("tools", {}).values()}
                if inner_hash not in tool_hashes:
                    status = "STALE"
                    reasons.append("inner result checker differs from bound current tool")
            except (KeyError, TypeError, ValueError):
                if status == "PASS":
                    status = "ERROR"
                reasons.append("inner result checker identity missing")
        media = rule.get("full_media_artifact")
        if media:
            try:
                transport = read(evidence["transport"])
                same_media = any(
                    x["sha256"] == current[media]["sha256"] for x in transport["actual_media"]
                )
                if not (
                    same_media
                    and transport["state"] == "complete"
                    and transport["complete_unchanged_media_file"] is True
                    and transport["audio_not_trimmed"] is True
                    and transport["finish_reasons"][-1] == "STOP"
                ):
                    raise ValueError("incomplete or wrong media")
            except (KeyError, IndexError, TypeError, ValueError):
                if status == "PASS":
                    status = "FAIL"
                reasons.append("actual complete media receipt does not match current artifact")
        if receipt.get("reviewer_kind") != rule["reviewer_kind"]:
            status = "ERROR"
            reasons.append("receipt issuer does not match required review kind")
        if rule["reviewer_kind"] == "model":
            if not receipt.get("prompt_sha256") or not receipt.get("independence"):
                if status == "PASS":
                    status = "ERROR"
                reasons.append("model scope/prompt independence evidence missing")
            author = manifest.get("author_session")
            reviewer = receipt.get("reviewer_session")
            if author and reviewer and author == reviewer:
                status = "FAIL"
                reasons.append("review reused author session")
            try:
                transport = read(evidence["transport"])
                prompt_hash = file_digest(evidence["prompt"])
                if not (
                    transport["state"] == "complete"
                    and transport["prompt_sha256"] == prompt_hash == receipt["prompt_sha256"]
                    and (
                        transport.get("stateless") is True
                        or (
                            reviewer
                            and transport.get("conversation_id") == reviewer
                            and reviewer != author
                        )
                    )
                ):
                    raise ValueError("model request scope differs")
            except (KeyError, TypeError, ValueError, OSError):
                if status == "PASS":
                    status = "ERROR"
                reasons.append("model prompt/transport independence is not verified")
        if receipt.get("open_blocking_issues"):
            if status == "PASS":
                status = "FAIL"
            reasons.append("receipt has unresolved blocking findings")
        checks[key] = {
            "status": status,
            "reasons": reasons,
            "receipt": str(receipt_path),
            "gate": rule["gate"],
        }
    issue_errors = []
    for issue in manifest.get("issues", []):
        if issue["original_severity"] != "BLOCKING":
            continue
        if issue["status"] not in {"VERIFIED_FIXED", "REJECTED_WITH_EVIDENCE"}:
            issue_errors.append(f"{issue['id']}: blocking issue not legally closed")
            continue
        proof_path = resolve(base, issue["closure"]["path"])
        if not proof_path.is_file() or file_digest(proof_path) != issue["closure"]["sha256"]:
            issue_errors.append(f"{issue['id']}: missing/stale closure proof")
            continue
        proof = read(proof_path)
        if proof.get("issue_id") != issue["id"] or proof.get("status") != issue["status"]:
            issue_errors.append(f"{issue['id']}: closure proof identity mismatch")
        if not proof.get("evidence") or not proof.get("artifact_bindings"):
            issue_errors.append(f"{issue['id']}: closure lacks actual evidence/version bindings")
        _, bad = evidence_files(proof.get("evidence", {}), proof_path.parent)
        if bad:
            issue_errors.append(f"{issue['id']}: stale closure evidence")
        try:
            decision_ref = proof["evidence"]["decision"]
            decision = read(resolve(proof_path.parent, decision_ref["path"]))
            if (
                decision.get("issue_id") != issue["id"]
                or decision.get("resolved") is not True
                or decision.get("disposition") != issue["status"]
            ):
                issue_errors.append(f"{issue['id']}: actual closure decision contradicts wrapper")
        except (KeyError, TypeError, ValueError, OSError):
            issue_errors.append(f"{issue['id']}: missing issue-specific resolution decision")
        for key, expected in proof.get("artifact_bindings", {}).items():
            if key not in current or current[key]["sha256"] != expected or artifact_errors.get(key):
                issue_errors.append(f"{issue['id']}: closure refers to old {key}")
        if not issue.get("required_checks"):
            issue_errors.append(f"{issue['id']}: no required recheck scope")
        for key in issue.get("required_checks", []):
            if checks.get(key, {}).get("status") != "PASS":
                issue_errors.append(f"{issue['id']}: required recheck {key} not current PASS")
    errors.extend(issue_errors)
    ready = not errors and all(x["status"] == "PASS" for x in checks.values())
    if target == "publish" and not manifest.get("publication_authorization", {}).get("evidence"):
        ready = False
        errors.append("publication authorization evidence missing")
    return {
        "schema_version": CONTRACT,
        "candidate_id": manifest["candidate_id"],
        "language": manifest["language"],
        "target": target,
        "manifest_sha256": file_digest(manifest_path),
        "release_policy_sha256": file_digest(policy_path),
        "evaluator_sha256": file_digest(Path(__file__)),
        "status": "REVIEW_READY" if ready else "NOT_READY",
        "ready_for_target": ready,
        "checks": checks,
        "errors": errors,
        "artifact_dependency_errors": {k: v for k, v in artifact_errors.items() if v},
        "policy_file_errors": policy_errors,
        "user_accepted": manifest.get("user_acceptance", {}).get("accepted") is True,
        "published": manifest.get("publication", {}).get("published") is True,
        "model_pass_does_not_grant_user_acceptance": True,
        "freshly_evaluated": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate(args.manifest)
    except (KeyError, TypeError, ValueError, OSError) as error:
        result = {
            "schema_version": CONTRACT,
            "status": "ERROR",
            "ready_for_target": False,
            "errors": [f"{type(error).__name__}: {error}"],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "ready_for_target")}))
    if not result["ready_for_target"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
