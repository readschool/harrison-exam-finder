"""Group documents into papers and build the static website into ``dist/``."""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import SITE_NAME, store
from .classify.common import DOC_TYPES

SITE_SRC = store.ROOT / "site"
DIST = store.ROOT / "dist"

# Pearson mark schemes / reports are dated after the exam; attach them to a
# question paper sat up to this many days earlier.
ALIGN_WINDOW_DAYS = 160

VISIBLE_STATUSES = {"ok", "unchecked"}


def _family(doc: dict) -> tuple:
    return (doc["board"], doc["level"], doc["spec_code"] or doc["subject"], doc["component"], doc["tier"])


def align_dated_series(docs: list[dict]) -> None:
    """Move date-derived series onto the question paper they belong to."""
    qps: dict[tuple, list[tuple[date, dict]]] = defaultdict(list)
    for doc in docs:
        if doc["doc_type"] == "question_paper" and doc.get("doc_date"):
            qps[_family(doc)].append((date.fromisoformat(doc["doc_date"]), doc))
    for doc in docs:
        if doc.get("series_source") != "date" or doc["doc_type"] == "question_paper" or not doc.get("doc_date"):
            continue
        when = date.fromisoformat(doc["doc_date"])
        candidates = [
            (qp_date, qp) for qp_date, qp in qps.get(_family(doc), [])
            if 0 <= (when - qp_date).days <= ALIGN_WINDOW_DAYS
        ]
        if candidates:
            _, qp = max(candidates, key=lambda c: c[0])
            doc["series"], doc["series_key"] = qp["series"], qp["series_key"]


def _natural(text: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text or "")]


def group_papers(docs: list[dict]) -> list[dict]:
    docs = [dict(d) for d in docs if d.get("status", "unchecked") in VISIBLE_STATUSES]
    align_dated_series(docs)

    papers: dict[tuple, dict] = {}
    for doc in docs:
        key = (*_family(doc), doc["series_key"])
        paper = papers.get(key)
        if paper is None:
            paper = papers[key] = {
                "id": "-".join(str(k).lower().replace(" ", "") for k in key if k),
                "board": doc["board"],
                "level": doc["level"],
                "subject": doc["subject"],
                "spec_code": doc["spec_code"],
                "series": doc["series"],
                "series_key": doc["series_key"],
                "paper": doc["component_name"],
                "tier": doc["tier"],
                "docs": {},
            }
        # The question paper's title is usually the most descriptive name.
        if doc["doc_type"] == "question_paper" and doc["component_name"]:
            paper["paper"] = doc["component_name"]
        paper["docs"].setdefault(doc["doc_type"], doc["url"])

    out = list(papers.values())
    for paper in out:
        paper["docs"] = {t: paper["docs"][t] for t in DOC_TYPES if t in paper["docs"]}
    out.sort(key=lambda p: (
        p["subject"], p["board"], p["level"],
        "".join(chr(255 - ord(c)) for c in p["series_key"]),  # newest series first
        _natural(p["paper"]), p["tier"],
    ))
    return out


def build(docs: list[dict] | None = None, dest: Path = DIST) -> dict:
    docs = store.load() if docs is None else docs
    papers = group_papers(docs)

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SITE_SRC, dest)
    (dest / "data").mkdir(exist_ok=True)

    meta = {
        "site_name": SITE_NAME,
        "generated": store.now(),
        "paper_count": len(papers),
        "document_count": sum(len(p["docs"]) for p in papers),
        "boards": sorted({p["board"] for p in papers}),
        "subjects": sorted({p["subject"] for p in papers}),
        "levels": sorted({p["level"] for p in papers}),
        "hidden_links": sum(1 for d in docs if d.get("status") == "gone"),
    }
    (dest / "data" / "papers.json").write_text(json.dumps(papers, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    (dest / "data" / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta
