"""OCR rules.

OCR filenames are just IDs (``752329-question-paper-pure-mathematics.pdf``),
so OCR relies on link text ("Question paper - Paper 1") and the headings above
the link ("2025 - June series", "Foundation tier", "A Level").
"""

from __future__ import annotations

import re

from . import common


def classify(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    out: dict = {}
    # "Question paper - Pure mathematics" -> name after the first dash.
    parts = re.split(r"\s+[-–]\s+", text, maxsplit=1)
    if len(parts) == 2:
        out["doc_type"] = common.detect_doc_type(parts[0])
        name = common.component_name(parts[1])
        if out["doc_type"] == "question_paper" and re.search(r"answer (book|booklet)", parts[1], re.I):
            out["doc_type"] = "answer_book"
        out["component_name"] = name
        out["component"] = common.slug(name)

    # Nearest series heading wins; OCR also lists future series with only
    # formulae sheets, which are skipped elsewhere.
    found = common.detect_series(*context)
    if found:
        out["series"], out["series_key"] = found
        out["series_source"] = "heading"

    out["tier"] = common.detect_tier(*context[:3]) if seed.get("level") == "GCSE" else None
    for c in context:
        if re.fullmatch(r"AS( Level)?", c, re.I):
            out["level"] = "AS"
            break
        if re.fullmatch(r"A Level", c, re.I):
            out["level"] = "A-level"
            break
    return out
