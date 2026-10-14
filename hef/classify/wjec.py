"""WJEC and Eduqas rules (both boards are run by WJEC CBAC and share a website).

Their past-paper links look like this (an icon name comes first, and is
removed before this point):

    Past Paper - Summer - Biology Unit 1 Foundation: Written:Cells, Organ Systems and Ecosystems - Foundation
    Mark Scheme - Autumn - Maths Component 1 Found Noncalculato:Non-calculator Mathematics (Foundation)
    Past Paper - Autumn - ... (Foundation) [Resource]

and the files are named ``<season letter><yy>-<unit code>[-ms].pdf``:

    s23-C400U10-1.pdf    summer 2023, unit C400U10-1 (Eduqas)
    A24-C300U10-1-ms.pdf autumn 2024 mark scheme
    z22-3402-01.pdf      summer 2022, older WJEC unit 3402-01
    h22-C200N10-1-cm.pdf Welsh-medium copy (N in the code, "cm" mark scheme)

* Season comes from the link text; the year from the filename. Summer is
  the June series; Autumn and Winter are the November series.
* Eduqas unit codes start C (GCSE), B (AS) or A (A-level).
* A code with N instead of U is the Welsh-medium version; those are skipped
  unless the subject itself is taught in Welsh (e.g. Welsh Literature).
* A trailing letter on the code (1A, 1E), or "[Resource]", is the resource booklet.
"""

from __future__ import annotations

import re

from . import common

LEVEL_BY_PREFIX = {"a": "A-level", "b": "AS", "c": "GCSE"}
ALL_COMPONENTS = "_all"

# "Past Paper - Summer - <rest>"; Welsh labels too.
LINK = re.compile(
    r"^(?P<kind>past papers?|question papers?|mark schemes?|examiners?['’]? reports?|"
    r"papur(?: arholiad)?|cynllun(?:iau)? marcio|adroddiad)\s*[-–]\s*"
    r"(?:(?P<season>summer|autumn|winter|spring|january|june|november|haf|hydref|gaeaf|gwanwyn)\s*[-–]\s*)?"
    r"(?P<rest>.*)$",
    re.I,
)
KINDS = {"past": "question_paper", "question": "question_paper", "papur": "question_paper",
         "mark": "mark_scheme", "cynllun": "mark_scheme", "examiner": "examiner_report",
         "adroddiad": "examiner_report"}
SEASON_MONTH = {"summer": 6, "haf": 6, "june": 6, "autumn": 11, "hydref": 11, "winter": 11,
                "gaeaf": 11, "november": 11, "january": 1, "spring": 3, "gwanwyn": 3}
# Filename season letters, used when the link text has no season.
LETTER_MONTH = {"s": 6, "z": 6, "h": 6, "a": 11, "o": 11, "w": 11, "g": 11, "j": 1}

FILE_YEAR = re.compile(r"^(?P<letter>[a-z])(?P<yy>\d{2})[-_]", re.I)
# Reports put it later: "eduqas-a-level-chemistry-report-s24-e.pdf"
FILE_YEAR_ANYWHERE = re.compile(r"[-_](?P<letter>[szhaowgj])(?P<yy>\d{2})(?=[-_.])", re.I)
NEW_UNIT = re.compile(r"(?:^|[-_])(?P<code>[abc]?\d{3,4}(?P<lang>[un])[a-z0-9]{2,3})[-_](?P<part>\d{1,2})(?P<resource>[a-z])?(?=[-_.]|$)", re.I)
OLD_UNIT = re.compile(r"^[a-z]\d{2}[-_](?P<code>\d{4})[-_](?P<part>\d{2})(?P<resource>[a-z])?(?=[-_.]|$)", re.I)
MARK_SCHEME_FILE = re.compile(r"[-_](ms|cm)(?:[-_]\w+)?\.pdf$", re.I)
WELSH_MARK_SCHEME_FILE = re.compile(r"[-_]cm(?:[-_]\w+)?\.pdf$", re.I)
RESOURCE_TEXT = re.compile(r"\s*\[(resource|adnodd|insert)\]\s*", re.I)
LABEL = re.compile(r"\b(unit|uned|component|comp|cydran)\s*([0-9]+[a-z]?)\b(\s+option\s+\w+)?", re.I)
TIER_WORDS = re.compile(r"\s*[-–(]\s*(foundation|higher|sylfaenol|sylfaen|uwch)\s*\)?\s*$", re.I)
WELSH_SUBJECT = re.compile(r"welsh|cymraeg|gymraeg", re.I)

_FILENAME_TYPES = [
    ("examiner_report", r"(^|[-_])(report|er|examiners?[-_]report)s?([-_.]|$)"),
    ("insert", r"(^|[-_])(insert|resource[-_]?booklet|pre[-_]?release)([-_.]|$)"),
]


def _tier(text: str) -> str | None:
    if re.search(r"\b(foundation|found|sylfaen|sylfaenol)\b", text, re.I):
        return "Foundation"
    if re.search(r"\b(higher|uwch)\b", text, re.I):
        return "Higher"
    return None


def _name(rest: str) -> str:
    """"Biology Unit 1 Foundation: Written:Cells, Organ ... - Foundation"
    -> "Unit 1: Cells, Organ ..."."""
    parts = [p.strip() for p in rest.split(":")]
    short, title = parts[0], (parts[-1] if len(parts) > 1 else "")
    title = TIER_WORDS.sub("", title).strip(" -–")
    m = LABEL.search(short)
    label = ""
    if m:
        word = {"comp": "Component", "cydran": "Cydran", "uned": "Uned"}.get(m.group(1).lower(), m.group(1).capitalize())
        label = f"{word} {m.group(2).upper()}" + (f" Option {m.group(3).split()[-1]}" if m.group(3) else "")
    if label and title:
        return f"{label}: {title}"
    return label or title or short


def classify(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    out: dict = {}
    fname = common.filename(url)
    welsh_subject = bool(WELSH_SUBJECT.search(f"{seed.get('subject', '')} {seed.get('qualification', '')}"))

    new_unit = NEW_UNIT.search(fname)
    old_unit = OLD_UNIT.search(fname)
    unit = new_unit or old_unit
    if not welsh_subject:
        if new_unit and new_unit.group("lang").lower() == "n":
            return {"skip": True}  # Welsh-medium copy of an English paper
        if WELSH_MARK_SCHEME_FILE.search(fname) or re.search(r"[-_]w(?:elsh)?\.pdf$", fname, re.I):
            return {"skip": True}

    resource = bool(RESOURCE_TEXT.search(text)) or bool(unit and unit.group("resource"))
    clean_text = RESOURCE_TEXT.sub(" ", text).strip()
    m = LINK.match(clean_text)

    # Document type
    doc_type = None
    if m:
        doc_type = KINDS.get(m.group("kind").split()[0].lower().rstrip("s"))
    if MARK_SCHEME_FILE.search(fname):
        doc_type = "mark_scheme"
    if not doc_type:
        doc_type = common.detect_doc_type(clean_text)
    if not doc_type:
        for kind, pattern in _FILENAME_TYPES:
            if re.search(pattern, fname, re.I):
                doc_type = kind
                break
    if not doc_type and unit:
        doc_type = "question_paper"
    if resource and doc_type in (None, "question_paper"):
        doc_type = "insert"
    out["doc_type"] = doc_type

    # Series: an explicit "June 2024" anywhere wins; otherwise the season from
    # the link text (or filename letter) plus the year from the filename.
    found = common.detect_series(clean_text, extra, *context)
    year = FILE_YEAR.match(fname) or FILE_YEAR_ANYWHERE.search(fname)
    if found:
        out["series"], out["series_key"] = found
        out["series_source"] = "heading"
    elif year:
        season = (m.group("season") or "").lower() if m else ""
        month = SEASON_MONTH.get(season) or LETTER_MONTH.get(year.group("letter").lower())
        if month:
            out["series"], out["series_key"] = common.series(2000 + int(year.group("yy")), month)
            out["series_source"] = "filename"

    rest = m.group("rest") if m else clean_text
    if unit:
        code = unit.group("code").upper()
        label = f"{code}-{unit.group('part')}"
        out["component"] = label.lower()
        named = _name(rest) if rest else ""
        out["component_name"] = f"{named} ({label})" if named else f"Unit {label}"
        prefix = code[0].lower()
        if new_unit and prefix in LEVEL_BY_PREFIX and seed.get("level") in ("AS", "A-level", "GCSE"):
            out["level"] = LEVEL_BY_PREFIX[prefix]
    elif doc_type == "examiner_report":
        # One report covers every component; build.py attaches it to each.
        out["component"] = ALL_COMPONENTS
        out["component_name"] = "All components"
        low = fname.lower()
        if seed.get("level") in ("AS", "A-level"):
            if re.search(r"(^|[-_])as([-_]|$)", low):
                out["level"] = "AS"
            elif re.search(r"(^|[-_])a[-_]?level([-_]|$)", low):
                out["level"] = "A-level"

    if seed.get("level") == "GCSE":
        tier = _tier(rest)
        if tier:
            out["tier"] = tier
    return out
