"""Board-agnostic rules based on link text, nearby headings and API fields."""

from __future__ import annotations

from . import common


def fields(url: str, text: str, context: list[str], extra: str, seed: dict) -> dict:
    fname = common.filename(url).replace("-", " ").replace("_", " ")
    out: dict = {}

    out["doc_type"] = (
        common.detect_doc_type(text)
        or common.detect_doc_type(extra)
        or common.detect_doc_type(fname)
    )

    found = common.detect_series(text, extra, *context, fname)
    if found:
        out["series"], out["series_key"] = found
        out["series_source"] = "text"

    out["tier"] = common.detect_tier(text, extra) or common.detect_tier(*context[:2])
    if seed.get("level") in ("A-level", "AS"):
        out["tier"] = None  # A-levels are not tiered.

    out["level"] = common.detect_level(*context) or seed.get("level")

    name = common.component_name(text) if text else ""
    if not name and extra:
        name = common.component_name(extra)
    out["component_name"] = name
    out["component"] = common.slug(name)
    return out
