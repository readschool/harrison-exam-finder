"""Tests for the fixes made after the first live scrape."""

from pathlib import Path

from hef import build, discover, linkcheck, store
from hef.classify import classify
from hef.harvest import links_from_html

FIX = Path(__file__).parent / "fixtures"
OCR_SEED = {"id": "ocr-gcse-biology", "board": "OCR", "level": "GCSE", "subject": "Biology",
            "qualification": "Biology A (Gateway)", "spec_code": "J247",
            "url": "https://www.ocr.org.uk/qualifications/gcse/x/assessment/"}


def test_ocr_series_from_accordion_links():
    links = links_from_html((FIX / "ocr_gcse_accordion.html").read_text(), OCR_SEED["url"])
    results = {l["url"].rsplit("/", 1)[-1]: classify(l, OCR_SEED) for l in links}
    qp = results["753453-question-paper-paper-1.pdf"].doc
    assert (qp["series"], qp["tier"], qp["qualification"]) == ("June 2025", "Foundation", "Biology A (Gateway)")
    assert results["753460-question-paper-paper-5.pdf"].doc["tier"] == "Higher"
    assert results["720001-question-paper-paper-1.pdf"].doc["series"] == "November 2024"
    assert results["720009-practice-paper-set-1.pdf"].skipped


def test_practice_and_support_material_skipped():
    seed = {"id": "aqa", "board": "AQA", "level": "GCSE", "subject": "Mathematics", "url": "u"}
    for text in ["8300 Practice paper set 2 - Paper 1", "Mock exam analyser", "Grades 4-5 diagnostic test",
                 "Getting started guide", "Mathematics in Science - Paper 1 2023"]:
        assert classify({"url": "https://x/y.pdf", "text": text, "context": []}, seed).skipped, text


def test_pearson_as_papers_on_alevel_page():
    seed = {"id": "p", "board": "Pearson Edexcel", "level": "A-level", "subject": "Mathematics", "url": "u"}
    link = {"url": "https://qualifications.pearson.com/x/8ma0-01-que-20230517.pdf", "text": "", "context": []}
    doc = classify(link, seed).doc
    assert doc["level"] == "AS" and doc["spec_code"] == "8MA0"


def test_discovery(monkeypatch):
    listing = [
        {"url": "https://www.aqa.org.uk/subjects/biology/gcse/biology-8461", "text": "GCSE Biology (8461)"},
        {"url": "https://www.aqa.org.uk/subjects/chemistry/as-level/chemistry-7404", "text": "AS Chemistry (7404)"},
        {"url": "https://www.aqa.org.uk/subjects/english/elc/english-5970", "text": "ELC English (5970)"},
        {"url": "https://www.aqa.org.uk/subjects/science/gcse/science-8464", "text": "GCSE Combined Science: Trilogy (8464)"},
    ]
    monkeypatch.setattr(discover.harvest, "page_links", lambda *a, **k: listing)
    entry = {
        "board": "AQA", "listings": ["L"],
        "link_pattern": r"^https://www\.aqa\.org\.uk/subjects/[^/]+/(?P<level>gcse|as-level|a-level)/(?P<slug>[^/?#]+?-(?P<code>\d{4}))/?$",
        "levels": {"gcse": "GCSE", "as-level": "AS", "a-level": "A-level"},
        "seed_url": "{url}/assessment-resources", "seed": {"mode": "browser"},
    }
    seeds, notes = discover.discover(entry, {}, None)
    by_code = {s["spec_code"]: s for s in seeds}
    assert set(by_code) == {"8461", "7404", "8464"}
    assert by_code["7404"]["level"] == "AS"
    assert by_code["8464"]["subject"] == "Combined Science"
    assert by_code["8461"]["url"].endswith("/biology-8461/assessment-resources")
    assert by_code["8461"]["mode"] == "browser"


def test_discovery_ocr_codes(monkeypatch):
    listing = [{"url": "https://www.ocr.org.uk/qualifications/as-and-a-level/biology-a-h020-h420-from-2015/", "text": "Biology A"}]
    monkeypatch.setattr(discover.harvest, "page_links", lambda *a, **k: listing)
    entry = {"board": "OCR", "listings": ["L"],
             "link_pattern": r"^https://www\.ocr\.org\.uk/qualifications/(?P<level>gcse|as-and-a-level)/(?P<slug>[a-z0-9-]*[jh]\d{3}[a-z0-9-]*)/?$",
             "code_pattern": r"[jh]\d{3}", "levels": {"as-and-a-level": "A-level"}, "seed_url": "{url}/assessment/"}
    (seed,), _ = discover.discover(entry, {}, None)
    assert seed["spec_codes"] == {"AS": "H020", "A-level": "H420"}
    assert seed["url"] == "https://www.ocr.org.uk/qualifications/as-and-a-level/biology-a-h020-h420-from-2015/assessment/"


def test_manual_seed_overrides_discovered():
    found = [{"id": "a", "url": "https://x/p#frag", "board": "AQA", "mode": "browser"}]
    manual = [{"id": "mine", "url": "https://x/p", "board": "AQA", "enabled": False}]
    (merged,) = discover.merge_seeds(found, manual)
    assert merged["id"] == "mine" and merged["enabled"] is False and merged["mode"] == "browser"


def test_new_links_that_fail_are_blocked(monkeypatch):
    results = {"https://a/ok.pdf": (True, "ok"), "https://a/locked.pdf": (False, "redirected to a web page"),
               "https://a/old.pdf": (False, "HTTP 404")}
    monkeypatch.setattr(linkcheck, "check_url", lambda session, url: results[url])
    monkeypatch.setattr(linkcheck, "DELAY_PER_HOST", 0)
    docs = [{"url": "https://a/ok.pdf", "status": "unchecked"},
            {"url": "https://a/locked.pdf", "status": "unchecked"},
            {"url": "https://a/old.pdf", "status": "ok", "fail_count": 0}]
    stats = linkcheck.run(docs, {})
    status = {d["url"]: d["status"] for d in docs}
    assert status == {"https://a/ok.pdf": "ok", "https://a/locked.pdf": "blocked", "https://a/old.pdf": "ok"}
    assert stats["blocked"] == 1


def test_unlisted_docs_hidden_after_grace():
    old = {"url": "u1", "seed": "s", "status": "ok", "board": "OCR", "level": "GCSE", "subject": "Biology",
           "spec_code": "J247", "component": "1", "component_name": "Paper 1", "tier": "", "series": "June 2025",
           "series_key": "2025-06", "doc_type": "question_paper"}
    docs, stats = store.merge([old], [], "2026-01-01T00:00:00+00:00", scraped_seeds={"s"})
    assert stats["unlisted"] == 1 and docs[0]["unlisted_since"] == "2026-01-01T00:00:00+00:00"
    assert build.group_papers(docs) == []  # long past the grace period
    docs[0]["unlisted_since"] = store.now()
    assert len(build.group_papers(docs)) == 1
