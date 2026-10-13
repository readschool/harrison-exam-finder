"""Pearson Edexcel rules.

Pearson filenames look like ``1ma1-1f-que-20230520.pdf``: spec code, paper and
tier, document type (que / rms / pef / ins), and the date the file was dated.
That date is the exam date for question papers but a later date for mark
schemes and examiner reports, so non-question-paper files are re-attached to
the matching question paper's series when the index is built (see build.py).
"""

from __future__ import annotations

import re

from . import common

_NAME = re.compile(
    r"^(?P<spec>[0-9][a-z0-9]{3,4})[-_](?P<comp>[0-9a-z]{1,4})[-_](?P<type>que|rms|pef|ins|ans)[-_](?P<date>\d{8})",
    re.I,
)

_TYPES = {
    "que": "question_paper",
    "rms": "mark_scheme",
    "pef": "examiner_report",
    "ins": "insert",
    "ans": "answer_book",
}


def classify(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    out: dict = {}
    m = _NAME.match(common.filename(url))
    if not m:
        return out

    out["spec_code"] = m.group("spec").upper()
    # A-level pages also carry the AS papers: AS codes start 8, A-level codes 9.
    if seed.get("level") in ("A-level", "AS") and out["spec_code"][0] in "89":
        out["level"] = "AS" if out["spec_code"][0] == "8" else "A-level"
    out["doc_type"] = _TYPES[m.group("type").lower()]

    comp = m.group("comp").lower()
    if comp[-1] in "fh" and seed.get("level") in ("GCSE", "International GCSE"):
        out["tier"] = "Foundation" if comp[-1] == "f" else "Higher"
        comp = comp[:-1]
    comp = comp.lstrip("0") or comp
    out["component"] = comp
    named = common.component_name(text) if text else ""
    if re.search(r"\b(paper|component|unit)\s*" + re.escape(comp) + r"\b", named, re.I):
        out["component_name"] = named
    else:
        out["component_name"] = f"Paper {comp.upper()}"

    # Prefer an explicit series from the page or API data; fall back to the date.
    found = common.detect_series(text, extra)
    dated = common.parse_ymd(m.group("date"))
    if dated:
        out["doc_date"] = dated.isoformat()
    if found:
        out["series"], out["series_key"] = found
        out["series_source"] = "text"
    elif dated:
        out["series"], out["series_key"] = common.series(dated.year, dated.month)
        out["series_source"] = "date"
    return out
