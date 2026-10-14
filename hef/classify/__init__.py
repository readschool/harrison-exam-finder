"""Turn harvested links into document records.

Each board module exposes ``classify(link, seed) -> Result``. The board-specific
rules run first (mostly filename parsing), then the generic text rules fill in
anything still missing. A link is kept only if we know its document type and
exam series; everything else is reported by ``hef doctor`` so the rules can be
improved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import aqa, common, generic, ocr, pearson, wjec

BOARD_CLASSIFIERS = {
    "AQA": aqa.classify,
    "Pearson Edexcel": pearson.classify,
    "OCR": ocr.classify,
    "Eduqas": wjec.classify,
    "WJEC": wjec.classify,
}


@dataclass
class Result:
    doc: dict | None = None
    skipped: bool = False
    reason: str = ""
    fields: dict = field(default_factory=dict)


def classify(link: dict, seed: dict) -> Result:
    text = common.clean(link.get("text"))
    context = [common.clean(c) for c in link.get("context", []) if c]
    extra = common.clean(link.get("extra"))
    url = link["url"]
    fname = common.filename(url)

    if common.should_skip(" ".join([text, fname])):
        return Result(skipped=True, reason="not a paper (modified, specimen, data sheet, etc.)")

    fields: dict = {}
    board_rules = BOARD_CLASSIFIERS.get(seed["board"])
    if board_rules:
        board_fields = board_rules(url, text, context, extra, seed)
        if board_fields.get("skip"):
            return Result(skipped=True, reason="modified or alternative version")
        fields.update({k: v for k, v in board_fields.items() if v})

    # Generic rules only fill gaps.
    for key, value in generic.fields(url, text, context, extra, seed).items():
        if value and not fields.get(key):
            fields[key] = value

    missing = [k for k in ("doc_type", "series") if not fields.get(k)]
    if missing:
        return Result(reason="could not work out " + " and ".join(m.replace("_", " ") for m in missing), fields=fields)

    level = fields.get("level") or seed.get("level")
    spec_code = (
        fields.get("spec_code")
        or (seed.get("spec_codes") or {}).get(level)
        or seed.get("spec_code")
        or ""
    )
    mapped = (seed.get("subject_by_spec") or {}).get(spec_code)
    doc = {
        "url": url,
        "board": seed["board"],
        "level": level,
        "subject": mapped or seed["subject"],
        "spec_code": spec_code,
        "qualification": mapped or seed.get("qualification") or seed["subject"],
        "series": fields["series"],
        "series_key": fields["series_key"],
        "series_source": fields.get("series_source", "text"),
        "doc_date": fields.get("doc_date"),
        "component": fields.get("component") or common.slug(fields.get("component_name", "")) or "paper",
        "component_name": fields.get("component_name") or "Paper",
        "tier": fields.get("tier") or "",
        "doc_type": fields["doc_type"],
        "title": text or common.filename(url),
        "source_page": link.get("source_page", seed["url"]),
        "seed": seed["id"],
    }
    return Result(doc=doc, fields=fields)
