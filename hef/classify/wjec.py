"""WJEC and Eduqas rules (both boards are run by WJEC CBAC and share a website).

Their filenames usually carry the exam series and unit code, e.g.
``s23-c400u10-1.pdf`` (summer 2023, unit C400U10-1) or
``eduqas-gcse-media-studies-report-s23-e.pdf`` (an examiner report).

* Series: ``s`` = summer (June); ``w`` = winter (November for GCSE resits,
  January for some older AS/A-level units). A series heading on the page
  wins over the filename, since it settles which winter series it was.
* Unit codes: Eduqas uses C = GCSE, B = AS and A = A-level as the first
  letter (C420U10-1). WJEC uses four digits (3300U10-1).
* A trailing ``-e``/``-w`` marks the English or Welsh-language version;
  the Welsh copies are skipped so each paper appears once.
"""

from __future__ import annotations

import re

from . import common

SERIES = re.compile(r"(?:^|[-_ ])([swj])(\d{2})(?=[-_ .]|$)", re.I)
UNIT = re.compile(r"(?:^|[-_ ])([abc]?\d{3,4}u[a-z0-9]{2,3})(?:[-_ ]?(\d{1,2}))?(?=[-_ .a-z]|$)", re.I)
WELSH = re.compile(r"[-_]w(?:elsh)?(?:[-_]\d+)?\.pdf$|[-_]cym(?:raeg)?[-_.]", re.I)
LEVEL_BY_PREFIX = {"a": "A-level", "b": "AS", "c": "GCSE"}
ALL_COMPONENTS = "_all"

_FILENAME_TYPES = [
    ("mark_scheme", r"(^|[-_])(ms|mark[-_]?scheme)s?([-_.]|$)"),
    ("examiner_report", r"(^|[-_])(report|er|examiners?[-_]report)s?([-_.]|$)"),
    ("insert", r"(^|[-_])(insert|resource[-_]?booklet|pre[-_]?release)([-_.]|$)"),
]


def classify(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    out: dict = {}
    fname = common.filename(url).lower()

    if WELSH.search(fname) or re.search(r"\bwelsh[- ]medium\b|\bcymraeg\b", text, re.I):
        return {"skip": True}

    # Document type: link text first, then filename.
    doc_type = common.detect_doc_type(text) or common.detect_doc_type(extra)
    if not doc_type:
        for kind, pattern in _FILENAME_TYPES:
            if re.search(pattern, fname):
                doc_type = kind
                break
    unit = UNIT.search(fname)
    if not doc_type and unit:
        doc_type = "question_paper"  # a bare unit code is the paper itself
    out["doc_type"] = doc_type

    # Series: heading or link text first, then the code in the filename.
    found = common.detect_series(text, extra, *context)
    if found:
        out["series"], out["series_key"] = found
        out["series_source"] = "heading"
    else:
        m = SERIES.search(fname)
        if m:
            season, yy = m.group(1).lower(), int(m.group(2))
            month = {"s": 6, "w": 11, "j": 1}[season]
            out["series"], out["series_key"] = common.series(2000 + yy, month)
            out["series_source"] = "filename"

    if unit:
        code = unit.group(1).upper()
        part = unit.group(2)
        out["component"] = (code + (f"-{part}" if part else "")).lower()
        named = common.component_name(text) if text else ""
        label = code + (f"-{part}" if part else "")
        out["component_name"] = f"{named} ({label})" if named and label.lower() not in named.lower() else (named or f"Unit {label}")
        prefix = code[0].lower()
        if prefix in LEVEL_BY_PREFIX and seed.get("level") in ("AS", "A-level", "GCSE"):
            out["level"] = LEVEL_BY_PREFIX[prefix]

    elif doc_type == "examiner_report":
        # One report covers every component; build.py attaches it to each.
        out["component"] = ALL_COMPONENTS
        out["component_name"] = "All components"
        if seed.get("level") in ("AS", "A-level"):
            if re.search(r"(^|[-_])as([-_]|$)", fname):
                out["level"] = "AS"
            elif re.search(r"(^|[-_])a[-_]?level([-_]|$)", fname):
                out["level"] = "A-level"

    tier = common.detect_tier(text, *context[:2])
    if tier and seed.get("level") == "GCSE":
        out["tier"] = tier
    return out
