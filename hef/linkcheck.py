"""Check that indexed links point at a live, public PDF.

* New links are checked first, every run. A new link that doesn't work is
  "blocked" and stays hidden; boards list their newest papers before they are
  public (teachers only), and those open up months later.
* A link that used to work is hidden ("gone") only after ``GONE_AFTER`` failed
  checks in a row, so a board's site having a bad night changes nothing.
* Blocked and gone links keep being rechecked and reappear when they work.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from . import store
from .harvest import new_session

log = logging.getLogger(__name__)

GONE_AFTER = 3
DELAY_PER_HOST = 0.5
TIMEOUT = 30


def check_url(session: requests.Session, url: str) -> tuple[bool, str]:
    try:
        resp = session.head(url, allow_redirects=True, timeout=TIMEOUT)
        if resp.status_code in (403, 405, 501) or resp.status_code >= 500:
            # Some servers refuse HEAD; ask for the first byte instead.
            resp = session.get(url, headers={"Range": "bytes=0-0"}, stream=True, allow_redirects=True, timeout=TIMEOUT)
            resp.close()
    except requests.RequestException as exc:
        return False, type(exc).__name__
    if resp.status_code not in (200, 206):
        return False, f"HTTP {resp.status_code}"
    ctype = resp.headers.get("content-type", "").lower()
    if "html" in ctype:
        # Boards often "remove" a paper by redirecting to a normal web page.
        return False, "redirected to a web page"
    return True, "ok"


def _check_host(session: requests.Session, docs: list[dict]) -> list[tuple[dict, bool, str]]:
    results = []
    for doc in docs:
        ok, why = check_url(session, doc["url"])
        results.append((doc, ok, why))
        time.sleep(DELAY_PER_HOST)
    return results


def run(docs: list[dict], settings: dict, limit: int | None = None) -> dict:
    """Check links, one polite worker per host. Mutates and returns stats."""
    session = new_session(settings)
    new = [d for d in docs if d.get("status", "unchecked") == "unchecked"]
    others = sorted((d for d in docs if d.get("status", "unchecked") != "unchecked"), key=lambda d: d.get("last_checked") or "")
    todo = new + (others[:limit] if limit else others)

    by_host: dict[str, list[dict]] = defaultdict(list)
    for doc in todo:
        by_host[urlparse(doc["url"]).netloc].append(doc)

    stats = {"checked": 0, "ok": 0, "failed": 0, "now_gone": 0, "recovered": 0, "blocked": 0}
    timestamp = store.now()
    with ThreadPoolExecutor(max_workers=max(1, len(by_host))) as pool:
        for results in pool.map(lambda host_docs: _check_host(session, host_docs), by_host.values()):
            for doc, ok, why in results:
                stats["checked"] += 1
                doc["last_checked"] = timestamp
                if ok:
                    stats["ok"] += 1
                    if doc.get("status") in ("gone", "blocked"):
                        stats["recovered"] += 1
                    doc.update(status="ok", fail_count=0, last_error=None)
                else:
                    stats["failed"] += 1
                    doc["fail_count"] = doc.get("fail_count", 0) + 1
                    doc["last_error"] = why
                    if doc.get("status", "unchecked") in ("unchecked", "blocked"):
                        if doc.get("status") != "blocked":
                            stats["blocked"] += 1
                        doc["status"] = "blocked"
                    elif doc["fail_count"] >= GONE_AFTER and doc.get("status") != "gone":
                        doc["status"] = "gone"
                        doc["gone_since"] = timestamp
                        stats["now_gone"] += 1
    return stats
