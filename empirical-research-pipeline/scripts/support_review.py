"""Explicit contextual support review, separate from mechanical prose checks.

Software checks identity/currency of evidence and the required attestations.
The reviewing Agent/human must actually read those sources; a receipt cannot
establish semantic truth merely because its fields are populated.
"""
from pathlib import Path
import contract_v2 as C


def context(project, data):
    bindings = []
    for support in data.get("support", []):
        kind = {"result": "model_result", "ref": "reference"}.get(support.get("kind"), support.get("kind"))
        if kind in C.STATUSES:
            record = project.latest(kind, support["id"])
            if record is None:
                raise ValueError(f"missing support: {kind}:{support['id']}")
            bindings.append({"kind": kind, "id": record["id"], "signature": C.signature(record)})
        else:
            path = Path(support.get("path") or support.get("id") or "")
            path = path if path.is_absolute() else project.root / path
            if not path.is_file():
                raise ValueError("material support needs an actual source path")
            bindings.append({"kind": "source", "path": str(path.resolve()), "sha256": C.file_sha256(path)})
    return C.canonical_hash({"text": data["text_fingerprint"], "scope": data.get("scope", {}),
                             "type": data["claim_type"], "block_id": data["block_id"], "support": bindings})


def review(project, claim_id, *, decision, reviewer, note, reread_scopes):
    import claims as CL
    if decision not in ("supported", "unsupported", "pending") or not reviewer.strip() or not note.strip() or note.lower() in ("ok", "verified", "done"):
        raise ValueError("support review needs a decision, reviewer and contextual assessment")
    claim = project.latest("claim", claim_id)
    if claim is None:
        raise ValueError("unknown claim")
    if claim["data"]["claim_type"] != "connection" and not reread_scopes:
        raise ValueError("factual support review needs actual reopened source locations")
    for scope in reread_scopes:
        path = Path(scope["path"])
        path = path if path.is_absolute() else project.root / path
        if not scope.get("locator") or not path.is_file() or scope.get("sha256") != C.file_sha256(path):
            raise ValueError("support reread scope missing, changed or without locator")
    machine = CL.check_claim(project, claim)
    if decision == "supported" and machine["status"] != "supported":
        raise ValueError("semantic review cannot override contradictory/missing numeric evidence")
    attestation = {"decision": decision, "reviewer": reviewer, "note": note, "reread_scopes": list(reread_scopes),
                   "context": context(project, claim["data"]), "checked_at": C._now()}
    return CL._write_status(project, claim, decision, patch={"semantic_review": attestation}, reason="explicit contextual source reread")


def is_current(project, claim):
    data = claim["data"]
    attestation = data.get("semantic_review") or {}
    try:
        return bool(attestation.get("decision") == "supported" and attestation.get("context") == context(project, data)
                    and all((project.root/s["path"]).is_file() and C.file_sha256(project.root/s["path"]) == s["sha256"]
                            for s in attestation["reread_scopes"]))
    except (ValueError, KeyError, OSError):
        return False
