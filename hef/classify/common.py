"""Shared helpers for turning link text and page context into paper metadata."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import unquote, urlparse

# Document types, in the order they are shown on the site.
DOC_TYPES = [
    "question_paper",
    "mark_scheme",
    "examiner_report",
    "insert",
    "answer_book",
]

DOC_TYPE_LABELS = {
    "question_paper": "Question paper",
    "mark_scheme": "Mark scheme",
    "examiner_report": "Examiner report",
    "insert": "Insert",
    "answer_book": "Answer book",
}

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
    12: "December",
}

# Exam series are named after the month the exams sit in. "May/June" is the
# summer series, which every board calls June.
SERIES_MONTH_ALIASES = {5: 6, 7: 6}


def series(year: int, month: int) -> tuple[str, str]:
    """Return (label, sort key) for an exam series, e.g. ("June 2024", "2024-06")."""
    month = SERIES_MONTH_ALIASES.get(month, month)
    return f"{MONTH_NAMES[month]} {year}", f"{year:04d}-{month:02d}"


# Icon fonts (e.g. Material Icons) draw an icon from a word such as
# "filter_none" or "picture_as_pdf", which then shows up in the link text.
ICON_WORD = re.compile(r"(^|\s)[a-z]+(?:_[a-z]+)+(?=\s|$)")


def clean(text: str | None) -> str:
    text = ICON_WORD.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def filename(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def is_pdf_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf/" in path and path.endswith("pdf")


# --- Document type -----------------------------------------------------------

_DOC_TYPE_PATTERNS = [
    # Order matters: the more specific phrases come first.
    ("answer_book", r"\banswer (book|booklet)\b"),
    ("examiner_report", r"\bexaminers?['’]? reports?\b|\breports? on the exam(ination)?\b|\bprincipal examiner"),
    ("mark_scheme", r"\bmark ?schemes?\b"),
    ("insert", r"\binserts?\b|\bsource booklet\b|\bresource booklet\b|\bpre-?release\b"),
    ("question_paper", r"\bquestion papers?\b|\bexam(ination)? papers?\b|\bquestion booklet\b|\bpast papers?\b"),
]

# Things that are published next to papers but are not part of one.
_SKIP_PATTERNS = re.compile(
    r"modified|braille|large print|enlarged|\bA3\b|\bsample\b|\bspecimen\b|"
    r"formula(e)? (sheet|booklet)|data (sheet|booklet)|equations? sheet|grade boundar|"
    r"candidate exemplar|exemplar|transcript|audio|\bmp3\b|\bzip\b|"
    # Teaching and practice material published next to real papers.
    r"practice (paper|set|question)|\bmock\b|diagnostic|performance data|analy[sz]er|"
    r"getting started|specification|progression|differences|guidance|guide\b|"
    r"poster|worksheet|practical (booklet|skills|handbook)|scheme of work|"
    r"glossary|command words|checklist|mathematics in science|maths in science|"
    r"moderators?['’]? report|grade descriptor|teaching|delivery|topic test|"
    r"knowledge organi[sz]er|walking talking|\bfaq|why choose|switch(er| to)\b",
    re.I,
)


def detect_doc_type(text: str) -> str | None:
    text = clean(text).lower()
    for doc_type, pattern in _DOC_TYPE_PATTERNS:
        if re.search(pattern, text):
            return doc_type
    return None


def should_skip(text: str) -> bool:
    return bool(_SKIP_PATTERNS.search(text or ""))


# --- Series ------------------------------------------------------------------

_SERIES_PATTERNS = [
    # "2025 - June series"
    re.compile(r"\b(20\d\d)\s*[-–]\s*(january|march|may|june|october|november)\b", re.I),
    # "June 2024", "Summer 2023", "Nov 2022"
    re.compile(r"\b(january|jan|march|mar|may|june|jun|october|oct|november|nov|summer|autumn|winter)\s+(20\d\d)\b", re.I),
    # "June series 2024"
    re.compile(r"\b(january|march|june|october|november)\s+series\s+(20\d\d)\b", re.I),
]

_SEASONS = {"summer": 6, "autumn": 11, "winter": 1}


def detect_series(*texts: str) -> tuple[str, str] | None:
    """Find the first exam series mentioned in any of the texts (nearest first)."""
    for text in texts:
        if not text:
            continue
        for pattern in _SERIES_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            a, b = m.group(1), m.group(2)
            year, word = (a, b) if a.isdigit() else (b, a)
            word = word.lower()
            month = _SEASONS.get(word) or MONTHS.get(word)
            if month:
                return series(int(year), month)
    return None


# --- Tier and level ----------------------------------------------------------

def detect_tier(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        if re.search(r"\bfoundation\b", text, re.I):
            return "Foundation"
        if re.search(r"\bhigher\b(?! education)", text, re.I):
            return "Higher"
    return None


def detect_level(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        if re.search(r"\bAS\s*(/|and|&)\s*A[- ]?level", text, re.I):
            continue  # a page covering both levels says nothing about this paper
        if re.search(r"\bAS\s*(level|-level)\b|\bAS\b(?! and)", text):
            return "AS"
        if re.search(r"\bA\s*-?\s*level\b|\bA2\b", text, re.I):
            return "A-level"
        if re.search(r"\bIGCSE\b|International GCSE", text, re.I):
            return "International GCSE"
        if re.search(r"\bGCSE\b", text):
            return "GCSE"
    return None


# --- Component names ---------------------------------------------------------

_STRIP_FROM_NAME = [
    r"question papers?", r"mark ?schemes?", r"examiners?['’]? reports?",
    r"reports? on the exam(ination)?", r"inserts?", r"answer (book|booklet)",
    r"\(?(foundation|higher)( tier)?\)?", r"(january|march|may|june|october|november|summer|autumn)\s+20\d\d",
    r"20\d\d", r"\bpdf\b", r"\b\d+(\.\d+)?\s*(kb|mb)\b",
]


def component_name(text: str) -> str:
    """Strip doc type, tier and series words from a title, leaving e.g. 'Paper 1'."""
    name = clean(text)
    for pattern in _STRIP_FROM_NAME:
        name = re.sub(pattern, " ", name, flags=re.I)
    # Only spaced dashes, colons, bars and commas are separators; "Non-Calculator" stays.
    name = re.sub(r"\s+[-–]\s+|\s*[:|,]\s*|^\s*[-–]\s*|\s*[-–]\s*$", " - ", name)
    name = re.sub(r"\(\s*\)", " ", name)
    name = re.sub(r"(\s*-\s*)+(?=\s-\s|$)", "", " " + name + " ")
    name = clean(name).strip(" -–:|,")
    if name.count("(") < name.count(")"):
        name = name.rstrip(")").strip()
    if name.count("(") > name.count(")"):
        name = name.lstrip("(").strip()
    return name[:1].upper() + name[1:] if name else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def parse_ymd(value: str) -> date | None:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (ValueError, IndexError):
        return None
