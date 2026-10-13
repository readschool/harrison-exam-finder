"""Find every qualification a board offers, so new subjects appear on their own.

Each entry under ``discovery:`` in sources.yaml names a board's list of
qualifications, a pattern for the qualification links on it, and how to turn
a qualification page into the page that lists its past papers. The result is
one seed per qualification, exactly like a hand-written seed.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urldefrag

import requests

from . import harvest
from .classify.common import clean, slug

log = logging.getLogger(__name__)

_LEVEL_WORDS = re.compile(
    r"^(pearson\s+)?(edexcel\s+)?(gcses?|as and a levels?|as level|as|a[- ]levels?|a level|aqa certificate( level \d)?|"
    r"level \d certificate|international gcse)\s+",
    re.I,
)


def names(text: str) -> tuple[str, str]:
    """Return (subject, qualification) from a qualification link's text.

    "Biology A (9-1) - Gateway Science Suite J247" -> ("Biology", "Biology A (Gateway)")
    "GCSE Combined Science: Trilogy (8464)"        -> ("Combined Science", "Combined Science: Trilogy")
    """
    t = clean(text)
    t = _LEVEL_WORDS.sub("", t)
    suite = ""
    if re.search(r"gateway", t, re.I):
        suite = " (Gateway)"
    elif re.search(r"twenty first century", t, re.I):
        suite = " (Twenty First Century)"
    t = re.sub(r"\s*[-–]\s*(gateway|twenty first century) science suite", "", t, flags=re.I)
    t = re.sub(r"\(\s*9\s*[-–]\s*1\s*\)", "", t)
    t = re.sub(r"\(\s*\d{4}\s*\)", "", t)                      # (8464) or (2015)
    t = re.sub(r"\b[JHjh]\d{3}\b(\s*,\s*[JHjh]\d{3}\b)*", "", t)  # OCR codes
    t = re.sub(r"\bfrom 20\d\d\b|\b20\d\d\b", "", t, flags=re.I)
    t = clean(t).strip(" -–,:")

    m = re.match(r"^Science ([A-D]), Combined$", t, re.I)
    if m:
        t = f"Combined Science {m.group(1).upper()}"
    qualification = clean(t) + suite

    subject = re.sub(r"\s*\(.*?\)", "", t)
    subject = re.sub(r":.*$", "", subject)
    subject = re.sub(r"\s+[A-D]$", "", subject)
    subject = clean(subject)
    return subject or qualification, qualification


def _codes(slug_text: str, pattern: str) -> list[str]:
    return [c.upper() for c in re.findall(pattern, slug_text, re.I)]


def discover(entry: dict, settings: dict, session: requests.Session) -> tuple[list[dict], list[str]]:
    """Return (seeds, notes) for one discovery entry."""
    notes: list[str] = []
    pattern = re.compile(entry["link_pattern"], re.I)
    found: dict[str, dict] = {}
    for listing in entry["listings"]:
        try:
            links = harvest.page_links(listing, entry.get("listing_mode", "static"), settings, session)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{listing}: {exc}")
            continue
        matched = 0
        for link in links:
            url = urldefrag(link["url"])[0]
            m = pattern.match(url)
            if not m or not link["text"]:
                continue
            matched += 1
            # Keep the most descriptive text if a page links to it twice.
            if url not in found or len(link["text"]) > len(found[url]["text"]):
                found[url] = {"url": url, "text": link["text"], "groups": m.groupdict()}
        notes.append(f"{listing}: {matched} qualification links")

    seeds = []
    for q in found.values():
        groups = q["groups"]
        level = entry["levels"].get(groups.get("level", ""), entry.get("default_level"))
        if not level:
            continue
        subject, qualification = names(q["text"])
        seed = {
            "board": entry["board"],
            "level": level,
            "subject": subject,
            "qualification": qualification,
            "url": entry["seed_url"].format(url=q["url"].rstrip("/"), base=re.sub(r"\.html$", "", q["url"]), **groups),
            "discovered_from": q["url"],
            **entry.get("seed", {}),
        }
        if entry.get("code_pattern"):
            codes = _codes(groups.get("slug", ""), entry["code_pattern"])
            if len(codes) == 2 and level == "A-level":
                seed["spec_codes"] = {"AS": codes[0], "A-level": codes[1]}
            elif codes:
                seed["spec_code"] = "/".join(codes)
        elif groups.get("code"):
            seed["spec_code"] = groups["code"]
        if entry.get("subject_by_spec"):
            seed["subject_by_spec"] = entry["subject_by_spec"]
        seed["id"] = "-".join(filter(None, [
            slug(entry["board"]).split("-")[0], slug(level), slug(qualification),
            slug(seed.get("spec_code") or "-".join((seed.get("spec_codes") or {}).values())),
        ]))
        seeds.append(seed)
    return seeds, notes


def merge_seeds(discovered: list[dict], manual: list[dict]) -> list[dict]:
    """Hand-written seeds win over discovered ones for the same page."""
    def key(seed):
        return urldefrag(seed["url"])[0].rstrip("/").lower()

    by_key = {key(s): s for s in discovered}
    for seed in manual:
        k = key(seed)
        by_key[k] = {**by_key.get(k, {}), **seed}
    # Make ids unique.
    seen: dict[str, int] = {}
    out = []
    for seed in by_key.values():
        n = seen.get(seed["id"], 0)
        seen[seed["id"]] = n + 1
        if n:
            seed = {**seed, "id": f"{seed['id']}-{n + 1}"}
        out.append(seed)
    return out
