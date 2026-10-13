"""The document store: ``data/documents.json``, one record per PDF link.

It is kept in Git so every change to the index is visible and reversible.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCUMENTS = DATA / "documents.json"
REPORTS = DATA / "reports"

# Fields that come from scraping and may be refreshed on every run.
SCRAPED_FIELDS = (
    "board", "level", "subject", "spec_code", "series", "series_key", "series_source",
    "doc_date", "component", "component_name", "tier", "doc_type", "title",
    "source_page", "seed",
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path: Path = DOCUMENTS) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(docs: list[dict], path: Path = DOCUMENTS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    docs = sorted(docs, key=lambda d: d["url"])
    path.write_text(json.dumps(docs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def merge(existing: list[dict], scraped: list[dict], timestamp: str | None = None) -> tuple[list[dict], dict]:
    """Merge freshly scraped documents into the store.

    New URLs are added; known URLs get their scraped fields refreshed and
    ``last_seen`` updated. Documents not seen this run are kept: the link
    checker, not the scraper, decides when a link has gone.
    """
    timestamp = timestamp or now()
    by_url = {d["url"]: d for d in existing}
    stats = {"added": 0, "updated": 0}
    for doc in scraped:
        current = by_url.get(doc["url"])
        if current is None:
            by_url[doc["url"]] = {
                **doc,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "status": "unchecked",
                "fail_count": 0,
                "last_checked": None,
            }
            stats["added"] += 1
        else:
            for key in SCRAPED_FIELDS:
                if key in doc:
                    current[key] = doc[key]
            current["last_seen"] = timestamp
            stats["updated"] += 1
    return list(by_url.values()), stats
