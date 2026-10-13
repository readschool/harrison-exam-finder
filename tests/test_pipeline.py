import json
from pathlib import Path

import pytest

from hef import build, store
from hef.classify import classify
from hef.classify import common
from hef.harvest import links_from_html, links_from_json

FIX = Path(__file__).parent / "fixtures"

OCR_SEED = {"id": "ocr-gcse-biology-a", "board": "OCR", "level": "GCSE", "subject": "Biology",
            "spec_code": "J247", "url": "https://www.ocr.org.uk/qualifications/gcse/x/assessment/"}
OCR_AL_SEED = {"id": "ocr-alevel-maths-a", "board": "OCR", "level": "A-level", "subject": "Mathematics",
               "spec_codes": {"AS": "H230", "A-level": "H240"}, "url": "https://www.ocr.org.uk/x/"}
AQA_SEED = {"id": "aqa-gcse-maths", "board": "AQA", "level": "GCSE", "subject": "Mathematics",
            "spec_code": "8300", "url": "https://www.aqa.org.uk/x"}
PEARSON_SEED = {"id": "pearson-gcse-maths", "board": "Pearson Edexcel", "level": "GCSE",
                "subject": "Mathematics", "spec_code": "1MA1",
                "url": "https://qualifications.pearson.com/en/qualifications/edexcel-gcses/mathematics-2015.coursematerials.html"}


def classify_all(links, seed):
    results = [classify(link, seed) for link in links]
    return [r.doc for r in results if r.doc], results


def test_ocr_static_page():
    html = (FIX / "ocr_assessment.html").read_text()
    links = links_from_html(html, OCR_SEED["url"])
    docs, results = classify_all(links, OCR_SEED)
    by_url = {d["url"].rsplit("/", 1)[-1]: d for d in docs}

    qp = by_url["753453-question-paper-paper-1.pdf"]
    assert qp["doc_type"] == "question_paper"
    assert qp["series"] == "June 2025" and qp["series_key"] == "2025-06"
    assert qp["tier"] == "Foundation"
    assert qp["component_name"] == "Paper 1"

    assert by_url["753219-examiners-report-paper-1.pdf"]["doc_type"] == "examiner_report"
    assert by_url["753460-question-paper-paper-5.pdf"]["tier"] == "Higher"
    assert by_url["720001-question-paper-paper-1.pdf"]["series"] == "November 2024"

    names = [l["url"] for l in links]
    assert not any("formulae" in u for u in by_url)  # skipped
    assert not any("modified" in u for u in by_url)  # skipped
    assert any("1-nav.pdf" in n for n in names)  # harvested, but not a paper
    assert "1-nav.pdf" not in str(list(by_url))
    unclassified = [r for r in results if not r.doc and not r.skipped]
    assert len(unclassified) == 1  # "Something unexpected" ("Specification" is skipped)


def test_ocr_alevel_and_as_split():
    links = links_from_html((FIX / "ocr_alevel.html").read_text(), OCR_AL_SEED["url"])
    docs, _ = classify_all(links, OCR_AL_SEED)
    levels = {d["url"].rsplit("/", 1)[-1]: (d["level"], d["spec_code"], d["doc_type"]) for d in docs}
    assert levels["752329-question-paper-pure-mathematics.pdf"] == ("A-level", "H240", "question_paper")
    assert levels["752328-question-paper-pure-mathematics-answer-book.pdf"][2] == "answer_book"
    assert levels["750001-question-paper-pure-mathematics.pdf"][:2] == ("AS", "H230")
    assert all(d["tier"] == "" for d in docs)


@pytest.mark.parametrize("name,expected", [
    ("AQA-83001F-QP-JUN23.PDF", ("question_paper", "June 2023", "Foundation", "1")),
    ("AQA-83002H-MS-NOV22.PDF", ("mark_scheme", "November 2022", "Higher", "2")),
    ("AQA-83003F-WRE-JUN23.PDF", ("examiner_report", "June 2023", "Foundation", "3")),
    ("AQA-87001-INS-JUN23.PDF", ("insert", "June 2023", "", "1")),
])
def test_aqa_filenames(name, expected):
    link = {"url": f"https://filestore.aqa.org.uk/sample-papers-and-mark-schemes/2023/june/{name}", "text": "", "context": []}
    doc = classify(link, AQA_SEED).doc
    assert (doc["doc_type"], doc["series"], doc["tier"], doc["component"]) == expected


def test_aqa_modified_paper_is_skipped():
    link = {"url": "https://filestore.aqa.org.uk/x/AQA-83001F-QP-MODA4-JUN23.PDF", "text": "Question paper (Modified A4 18pt)", "context": []}
    assert classify(link, AQA_SEED).skipped


def test_pearson_json_and_series_alignment():
    data = json.loads((FIX / "pearson_api.json").read_text())
    links = links_from_json(data, PEARSON_SEED["url"])
    assert len(links) == 5
    assert links[0]["url"].startswith("https://qualifications.pearson.com/content/dam/")
    docs, _ = classify_all(links, PEARSON_SEED)
    assert len(docs) == 5
    for d in docs:
        d["status"] = "ok"
    papers = build.group_papers(docs)
    assert len(papers) == 2
    june = next(p for p in papers if p["series"] == "June 2023")
    assert set(june["docs"]) == {"question_paper", "mark_scheme", "examiner_report"}
    assert june["tier"] == "Foundation" and june["paper"] == "Paper 1 (Non-Calculator)"
    nov = next(p for p in papers if p["series"] == "November 2022")
    assert set(nov["docs"]) == {"question_paper", "mark_scheme"}


def test_merge_preserves_history():
    first, stats = store.merge([], [{"url": "u1", "doc_type": "question_paper"}], "2026-01-01T00:00:00+00:00")
    assert stats["added"] == 1 and first[0]["status"] == "unchecked"
    first[0]["status"] = "ok"
    second, stats = store.merge(first, [{"url": "u1", "doc_type": "mark_scheme"}], "2026-02-01T00:00:00+00:00")
    assert stats["updated"] == 1
    assert second[0]["first_seen"] == "2026-01-01T00:00:00+00:00"
    assert second[0]["last_seen"] == "2026-02-01T00:00:00+00:00"
    assert second[0]["status"] == "ok" and second[0]["doc_type"] == "mark_scheme"


def test_gone_links_hidden():
    doc = {"board": "OCR", "level": "GCSE", "spec_code": "J247", "subject": "Biology", "component": "1",
           "component_name": "Paper 1", "tier": "Foundation", "series": "June 2025", "series_key": "2025-06",
           "doc_type": "question_paper", "url": "u", "status": "gone"}
    assert build.group_papers([doc]) == []


def test_series_detection():
    assert common.detect_series("2025 - June series") == ("June 2025", "2025-06")
    assert common.detect_series("Summer 2019") == ("June 2019", "2019-06")
    assert common.detect_series("May 2023") == ("June 2023", "2023-06")
    assert common.detect_series("nothing here") is None
