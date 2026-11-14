# -*- coding: utf-8 -*-
"""References: metadata, what was actually read, and what it can support.

A DOI is an identifier, not a reading.  This module separates three things that
are routinely conflated:

* **existence** - the DOI/URL resolves and its metadata matches the citation;
* **access** - what we actually obtained: ``full_text`` / ``abstract`` /
  ``metadata`` / ``unavailable``, with the evidence path and time;
* **support** - which sentence, in which section, supports which claim, quoted
  verbatim, with direction/denominator/units/time scope kept separate.

``check_reference`` refuses to let an abstract-level access support a
full-text claim, and refuses a quote that is not literally present in the text
we stored.  Network lookups are optional: metadata can be supplied from a local
record, and a failed lookup never silently upgrades access.

CLI::

    python refs.py --root . add --cite C1 --authors "Zhang, Li" \\
        --title "..." --year 2021 --venue "..." --doi 10.1234/x
    python refs.py --root . access --cite C1 --text paper.txt --level full_text
    python refs.py --root . support --cite C1 --claim K3 --quote "..." \\
        --section "Results" --page 4
    python refs.py --root . check --cite C1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

ACCESS_LEVELS = ("full_text", "abstract", "metadata", "unavailable")
CLAIM_LEVELS = ("full_text", "abstract", "metadata")


def _producer(**kw) -> dict:
    return C.producer_for("refs", version="2.0", module_file=__file__, **kw)


class RefError(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _norm_quote(text: str) -> str:
    """Normalise quotes the way a printed page differs from a plain text dump."""
    text = text.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"-\s*\n\s*", "", text)          # de-hyphenate line breaks
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def register(project: C.Project, cite_id: str, *, authors: str, title: str,
             year: str, venue: str, doi: str | None = None,
             url: str | None = None,
             access: Mapping | None = None) -> dict:
    if not cite_id.strip():
        raise RefError("cite_id is required")
    for name, value in (("authors", authors), ("title", title), ("year", year),
                        ("venue", venue)):
        if not str(value).strip():
            raise RefError(f"reference {cite_id}: {name} is required")
    payload = {"cite_id": cite_id, "authors": authors, "title": title,
               "year": str(year), "venue": venue,
               "access": dict(access or {"level": "metadata",
                                         "obtained": None,
                                         "checked_at": None,
                                         "evidence": []})}
    if doi:
        payload["doi"] = doi
    if url:
        payload["url"] = url
    rec = C.make_record("reference", cite_id, payload, producer=_producer(),
                        status="unverifiable")
    prev = project.latest("reference", cite_id)
    if prev is not None:
        identity = ("authors", "title", "year", "venue", "doi", "url")
        unchanged = all(prev["data"].get(k) == payload.get(k) for k in identity)
        if unchanged:
            payload = {**prev["data"], **payload, "access": prev["data"]["access"]}
        rec = C.make_record("reference", cite_id, payload, producer=_producer(),
                            status=prev["status"] if unchanged else "unverifiable",
                            revision=prev["revision"] + 1)
    project.append("reference", rec, enforce_transition=False)
    return rec


def crossref(doi: str, *, timeout: float = 20.0) -> dict:
    """Fetch DOI metadata from Crossref.  Raises on network/parse failure."""
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={
        "User-Agent": "empirical-research-pipeline/2.0 (mailto:noreply@example.org)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = data.get("message") or {}
    authors = msg.get("author") or []
    names = ", ".join(
        f"{a.get('family', '')} {a.get('given', '')}".strip() for a in authors)
    year = ""
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    return {"doi": msg.get("DOI") or doi,
            "title": (msg.get("title") or [""])[0],
            "authors": names, "year": year,
            "venue": (msg.get("container-title") or [""])[0],
            "type": msg.get("type"),
            "publisher": msg.get("publisher")}


def compare_metadata(claimed: Mapping, actual: Mapping) -> dict:
    problems = []
    if _norm(claimed.get("title", "")).lower() != _norm(actual.get("title", "")).lower():
        problems.append({"field": "title", "claimed": claimed.get("title"),
                         "actual": actual.get("title")})
    if str(claimed.get("year", "")) != str(actual.get("year", "")):
        problems.append({"field": "year", "claimed": claimed.get("year"),
                         "actual": actual.get("year")})
    claimed_first = _norm(claimed.get("authors", "")).split(",")[0].split()
    actual_first = _norm(actual.get("authors", "")).split(",")[0].split()
    if claimed_first and actual_first and \
            claimed_first[0].lower() not in [w.lower() for w in actual_first]:
        problems.append({"field": "authors", "claimed": claimed.get("authors"),
                         "actual": actual.get("authors")})
    return {"ok": not problems, "problems": problems}


def verify_doi(project: C.Project, cite_id: str, *, metadata: Mapping | None = None,
               fetch: bool = True) -> dict:
    rec = project.latest("reference", cite_id)
    if rec is None:
        raise RefError(f"unknown reference {cite_id}")
    doi = rec["data"].get("doi")
    if not doi:
        raise RefError(f"reference {cite_id} has no DOI to verify")
    if metadata is None:
        if not fetch:
            raise RefError("no metadata supplied and fetching is disabled")
        try:
            metadata = crossref(doi)
        except Exception as exc:                    # noqa: BLE001
            payload = dict(rec["data"])
            payload["doi_check"] = {"ok": False, "error": str(exc),
                                    "checked_at": C._now()}
            new = C.make_record("reference", cite_id, payload,
                                producer=_producer(), status=rec["status"],
                                revision=rec["revision"] + 1)
            project.append("reference", new, enforce_transition=False)
            return {"ok": False, "error": str(exc), "record": new["id"]}
    cmp = compare_metadata(rec["data"], metadata)
    payload = dict(rec["data"])
    payload["doi_check"] = {"ok": cmp["ok"], "metadata": metadata,
                            "problems": cmp["problems"],
                            "checked_at": C._now()}
    new = C.make_record("reference", cite_id, payload, producer=_producer(),
                        status=rec["status"], revision=rec["revision"] + 1)
    project.append("reference", new, enforce_transition=False)
    return {"ok": cmp["ok"], "problems": cmp["problems"], "record": new["id"]}


def verify_access(project: C.Project, cite_id: str, *, text_path: str,
                  level: str, obtained: str | None = None, scope_note: str = "") -> dict:
    """Record what was actually obtained; the text is stored for quote checks."""
    if level not in ACCESS_LEVELS:
        raise RefError(f"access level must be one of {ACCESS_LEVELS}")
    rec = project.latest("reference", cite_id)
    if rec is None:
        raise RefError(f"unknown reference {cite_id}")
    path = Path(text_path)
    if not path.is_absolute():
        path = project.root / path
    if not path.is_file():
        raise RefError(f"access text missing: {path}")
    text = path.read_text(encoding="utf-8-sig")
    if level == "full_text" and len(text.strip()) < 400 and not scope_note.strip():
        raise RefError("a full-text access cannot be claimed from this little "
                       "text; the file looks like an abstract")
    if level != "full_text" and not scope_note.strip() and re.search(r"^(references|bibliography)\s*$",
                                                                   text, re.I | re.M):
        raise RefError("this file contains a reference list, so it is the full "
                       "text; do not record it as abstract")
    stored = project.path("refs", f"{C.canonical_hash(cite_id)}.txt")
    stored.write_text(text, encoding="utf-8")
    payload = dict(rec["data"])
    payload["access"] = {
        "level": level,
        "obtained": obtained or C._now(),
        "checked_at": C._now(),
        "text_path": stored.relative_to(project.root).as_posix(),
        "text_sha256": C.file_sha256(stored),
        "chars": len(text),
        "scope_note": scope_note, "original_path": str(path.resolve()), "original_sha256": C.file_sha256(path),
        "evidence": [{"path": stored.relative_to(project.root).as_posix(),
                      "sha256": C.file_sha256(stored)}],
    }
    new = C.make_record("reference", cite_id, payload, producer=_producer(),
                        status="verified" if level == "full_text" else "partial_access",
                        revision=rec["revision"] + 1)
    project.append("reference", new, enforce_transition=False)
    return new


def record_publication_status(project, cite_id, *, status, evidence_path, source_url, reviewer, note):
    """Bind an actual publisher/registry status lookup without inferring absence.

    A clean search is 'not_reported_in_checked_source', never a universal proof
    that a paper cannot have a correction or retraction elsewhere.
    """
    allowed = ("not_reported_in_checked_source", "corrected", "retracted", "expression_of_concern", "unavailable")
    if status not in allowed or not all(str(v).strip() for v in (source_url, reviewer, note)):
        raise RefError("publication status needs source, reviewer, scope note and a declared status")
    rec = project.latest("reference", cite_id)
    if rec is None:
        raise RefError("unknown reference")
    path = Path(evidence_path)
    path = path if path.is_absolute() else project.root / path
    text = path.read_text(encoding="utf-8")
    identifiers = [rec["data"].get("doi"), rec["data"]["title"]]
    if not any(_norm(identifier).lower() in _norm(text).lower() for identifier in identifiers if identifier):
        raise RefError("status evidence does not identify the cited work")
    payload = dict(rec["data"])
    payload["publication_status"] = {"status": status, "evidence": str(path.resolve()), "sha256": C.file_sha256(path),
                                     "source_url": source_url, "reviewer": reviewer, "scope_note": note, "checked_at": C._now()}
    new = C.make_record("reference", cite_id, payload, producer=_producer(), status=rec["status"], revision=rec["revision"]+1)
    project.append("reference", new, enforce_transition=False)
    return new


def support(project: C.Project, cite_id: str, *, claim_id: str, quote: str,
            section: str, page: int | str | None = None,
            claim_level: str = "full_text", note: str = "") -> dict:
    """Attach a verbatim quotation as the support for one claim."""
    if claim_level not in CLAIM_LEVELS:
        raise RefError(f"claim_level must be one of {CLAIM_LEVELS}")
    rec = project.latest("reference", cite_id)
    if rec is None:
        raise RefError(f"unknown reference {cite_id}")
    access = rec["data"].get("access") or {}
    level = access.get("level")
    if claim_level == "full_text" and level != "full_text":
        raise RefError(
            f"{cite_id}: access is {level!r}; an abstract/metadata reading "
            f"cannot support a full-text claim")
    quote_norm = _norm_quote(quote)
    if len(quote_norm) < 20:
        raise RefError("a supporting quotation must be a sentence, not a word")
    found = False
    text_path = access.get("text_path")
    if text_path:
        text = (project.root / text_path).read_text(encoding="utf-8-sig")
        found = quote_norm in _norm_quote(text)
        if access.get("text_sha256") and \
                C.file_sha256(project.root / text_path) != access["text_sha256"]:
            raise RefError("the stored access text changed after it was bound")
        if not found:
            raise RefError(f"the quotation is not present in the stored text for "
                           f"{cite_id}; a paraphrase is not a quotation")
    entry = {"cite_id": cite_id, "claim": claim_id, "quote": quote,
             "quote_sha256": C.canonical_hash(quote_norm),
             "section": section, "page": page, "claim_level": claim_level,
             "quote_verified": found, "note": note,
             "recorded_at": C._now()}
    payload = dict(rec["data"])
    supports = list(payload.get("supports") or [])
    supports.append(entry)
    payload["supports"] = supports
    new = C.make_record("reference", cite_id, payload, producer=_producer(),
                        status=rec["status"], revision=rec["revision"] + 1)
    project.append("reference", new, enforce_transition=False)
    return {"record": new["id"], "quote_verified": found, "entry": entry}


def check_reference(project: C.Project, cite_id: str, *, formal=False) -> dict:
    rec = project.latest("reference", cite_id)
    if rec is None:
        raise RefError(f"unknown reference {cite_id}")
    data = rec["data"]
    problems = []
    access = data.get("access") or {}
    publication = data.get("publication_status") or {}
    if formal and not publication:
        problems.append({"check": "publication_status_unassessed", "detail": "correction/retraction status has no actual lookup evidence"})
    if publication:
        path = Path(publication["evidence"])
        if not path.is_file() or C.file_sha256(path) != publication["sha256"]:
            problems.append({"check": "publication_status_stale", "detail": "lookup evidence changed"})
        if publication["status"] in ("retracted", "expression_of_concern", "unavailable"):
            problems.append({"check": "publication_status_restricts_support", "detail": publication["status"]})
    if data.get("doi") and not (data.get("doi_check") or {}).get("ok"):
        problems.append({"check": "doi_unverified",
                         "detail": "DOI metadata was never confirmed"})
    if access.get("level") in (None, "", "metadata") and data.get("supports"):
        problems.append({"check": "support_without_access",
                         "detail": "quotes are attached but nothing was read"})
    text = None
    if access.get("text_path"):
        path = project.root / access["text_path"]
        if not path.is_file():
            problems.append({"check": "access_text_missing", "detail": access["text_path"]})
        else:
            try:text = _norm_quote(path.read_text(encoding="utf-8-sig"))
            except UnicodeError:
                problems.append({"check":"access_text_encoding","detail":"stored access text is not valid UTF-8; select an explicit lossless conversion and bind it again"})
            if access.get("text_sha256") and C.file_sha256(path) != access["text_sha256"]:
                problems.append({"check": "access_text_changed",
                                 "detail": access["text_path"]})
    for entry in data.get("supports") or []:
        if entry["claim_level"] == "full_text" and access.get("level") != "full_text":
            problems.append({"check": "claim_level_mismatch",
                             "detail": f"{entry['claim']} claims full text but "
                                       f"access is {access.get('level')}"})
        if text is not None and _norm_quote(entry["quote"]) not in text:
            problems.append({"check": "quote_not_found",
                             "detail": entry["quote"][:80]})
        if not entry.get("section"):
            problems.append({"check": "section_missing",
                             "detail": entry["claim"]})
    return {"cite_id": cite_id, "ok": not problems, "problems": problems,
            "access": access.get("level"), "supports": len(data.get("supports") or [])}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="reference metadata and support")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_a = sub.add_parser("add")
    p_a.add_argument("--cite", required=True)
    p_a.add_argument("--authors", required=True)
    p_a.add_argument("--title", required=True)
    p_a.add_argument("--year", required=True)
    p_a.add_argument("--venue", required=True)
    p_a.add_argument("--doi")
    p_a.add_argument("--url")
    p_v = sub.add_parser("verify")
    p_v.add_argument("--cite", required=True)
    p_v.add_argument("--metadata")
    p_v.add_argument("--no-fetch", action="store_true")
    p_x = sub.add_parser("access")
    p_x.add_argument("--cite", required=True)
    p_x.add_argument("--text", required=True)
    p_x.add_argument("--level", required=True, choices=list(ACCESS_LEVELS))
    p_x.add_argument("--scope-note", default="")
    p_status = sub.add_parser("publication-status")
    p_status.add_argument("--cite", required=True)
    p_status.add_argument("--status", required=True)
    p_status.add_argument("--evidence", required=True)
    p_status.add_argument("--source-url", required=True)
    p_status.add_argument("--reviewer", required=True)
    p_status.add_argument("--note", required=True)
    p_s = sub.add_parser("support")
    p_s.add_argument("--cite", required=True)
    p_s.add_argument("--claim", required=True)
    p_s.add_argument("--quote", required=True)
    p_s.add_argument("--section", required=True)
    p_s.add_argument("--page")
    p_s.add_argument("--claim-level", default="full_text",
                     choices=list(CLAIM_LEVELS))
    p_c = sub.add_parser("check")
    p_c.add_argument("--cite", required=True)
    sub.add_parser("list")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "add":
        print(json.dumps(register(proj, args.cite, authors=args.authors,
                                  title=args.title, year=args.year,
                                  venue=args.venue, doi=args.doi,
                                  url=args.url)["data"], ensure_ascii=False,
                         indent=1))
        return 0
    if args.cmd == "verify":
        metadata = None
        if args.metadata:
            metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        res = verify_doi(proj, args.cite, metadata=metadata,
                         fetch=not args.no_fetch)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    if args.cmd == "access":
        rec = verify_access(proj, args.cite, text_path=args.text,
                            level=args.level, scope_note=args.scope_note)
        print(json.dumps(rec["data"]["access"], ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "publication-status":
        print(json.dumps(record_publication_status(proj, args.cite, status=args.status, evidence_path=args.evidence,
                                                   source_url=args.source_url, reviewer=args.reviewer, note=args.note), ensure_ascii=False))
        return 0
    if args.cmd == "support":
        res = support(proj, args.cite, claim_id=args.claim, quote=args.quote,
                      section=args.section, page=args.page,
                      claim_level=args.claim_level)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["quote_verified"] else 2
    if args.cmd == "check":
        res = check_reference(proj, args.cite)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    if args.cmd == "list":
        for rec in proj.read("reference"):
            print(f"{rec['id']} {rec['data']['year']} {rec['data']['title'][:60]} "
                  f"access={rec['data']['access'].get('level')}")
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
