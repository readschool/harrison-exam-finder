"""AQA rules.

AQA filenames carry nearly everything we need, e.g.
``AQA-83001F-QP-JUN23.PDF`` = spec 8300, paper 1, Foundation, question paper,
June 2023. ``WRE`` is the examiner report ("written report on the exam").
"""

from __future__ import annotations

import re

from . import common

_NAME = re.compile(
    r"^AQA-(?P<spec>\d{4})(?P<comp>[0-9A-Z]*)-(?P<type>[A-Z]+)(?P<extra>(-[A-Z0-9]+)*?)-(?P<mon>[A-Z]{3})(?P<yy>\d{2})\b",
    re.I,
)

_TYPES = {
    "QP": "question_paper",
    "MS": "mark_scheme",
    "WRE": "examiner_report",
    "ER": "examiner_report",
    "INS": "insert",
    "PM": "insert",  # pre-release material
    "SB": "insert",  # source booklet
}


def classify(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    out: dict = {}
    m = _NAME.match(common.filename(url))
    if not m:
        return out
    if "MOD" in (m.group("extra") or "").upper():
        return {"skip": True}  # modified (large print / A3) version

    out["spec_code"] = m.group("spec")
    out["doc_type"] = _TYPES.get(m.group("type").upper())

    month = common.MONTHS.get(m.group("mon").lower())
    if month:
        out["series"], out["series_key"] = common.series(2000 + int(m.group("yy")), month)
        out["series_source"] = "filename"

    comp = m.group("comp").upper()
    if comp and comp[-1] in "FH" and seed.get("level") == "GCSE":
        out["tier"] = "Foundation" if comp[-1] == "F" else "Higher"
        comp = comp[:-1]
    if comp:
        out["component"] = comp.lower()
        named = common.component_name(text) if text else ""
        digits = re.sub(r"\D", "", comp) or comp
        if re.search(r"\b(paper|component|unit)\s*" + re.escape(digits) + r"\b", named, re.I):
            out["component_name"] = named
        else:
            out["component_name"] = f"Paper {comp}"
    return out
