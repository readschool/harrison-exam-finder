"""OCR rules.

OCR filenames are just IDs (``752329-question-paper-pure-mathematics.pdf``),
so OCR relies on link text ("Question paper - Paper 1") and the headings above
the link ("2025 - June series", "Foundation tier", "A Level").
"""

from __future__ import annotations

import re

from . import common

# Unit codes like R093 (Cambridge Nationals) or F501; only the first counts.
UNIT_CODE = re.compile(r"\(\s*([A-Z]\d{3})(?:/\d+)?\b")
# "(R093/01 - PDF 3MB)", "(PDF 557KB)", "(R094-R099 - PDF 457KB)"
BRACKETED_FILE_INFO = re.compile(r"\s*\((?:[^()]*\b)?PDF\b[^()]*\)", re.I)


def classify(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    out: dict = {}
    # Cambridge Nationals/Technicals add the unit and file size in brackets:
    # "Question paper - Creative iMedia in the media industry (R093/01 - PDF 3MB)".
    # The unit code is what ties a paper to its mark scheme and examiner
    # report, whose titles are worded differently ("Creative iMedia (R093)").
    unit = UNIT_CODE.search(text)
    text = BRACKETED_FILE_INFO.sub("", text).strip()

    # "Question paper - Pure mathematics" -> name after the first dash.
    parts = re.split(r"\s+[-–]\s+", text, maxsplit=1)
    if len(parts) == 2:
        out["doc_type"] = common.detect_doc_type(parts[0])
        name = common.component_name(parts[1])
        if out["doc_type"] == "question_paper" and re.search(r"answer (book|booklet)", parts[1], re.I):
            out["doc_type"] = "answer_book"
        out["component_name"] = name
        out["component"] = common.slug(name)
    if unit:
        code = unit.group(1).upper()
        out["component"] = code.lower()
        out["component_name"] = f"{out['component_name']} ({code})" if out.get("component_name") else code

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
