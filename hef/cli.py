"""Command line: ``python -m hef <command>``.

  scrape        harvest seed pages, classify links, update data/documents.json
  check-links   check indexed links, hide ones that have gone
  build         group into papers and build the website into dist/
  doctor        explain what a scrape found per seed (also written by scrape)
  serve         preview dist/ at http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

from . import build as builder
from . import harvest, linkcheck, store
from .classify import classify

CONFIG = store.ROOT / "config" / "sources.yaml"
log = logging.getLogger("hef")


def load_config(path: Path = CONFIG) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for seed in config["seeds"]:
        seed.setdefault("mode", "static")
        seed.setdefault("enabled", True)
    return config


def select_seeds(config: dict, board: str | None, seed_id: str | None) -> list[dict]:
    seeds = [s for s in config["seeds"] if s["enabled"]]
    if board:
        seeds = [s for s in seeds if s["board"].lower().startswith(board.lower())]
    if seed_id:
        seeds = [s for s in seeds if s["id"] == seed_id]
    return seeds


def scrape(args) -> int:
    config = load_config()
    settings = config.get("settings", {})
    seeds = select_seeds(config, args.board, args.seed)
    if not seeds:
        log.error("No matching seeds.")
        return 1

    session = harvest.new_session(settings)
    all_docs: list[dict] = []
    report: list[dict] = []
    for seed in seeds:
        entry = {"seed": seed["id"], "board": seed["board"], "url": seed["url"], "mode": seed["mode"]}
        try:
            links = harvest.harvest(seed, settings, session)
        except Exception as exc:  # noqa: BLE001 - one bad seed must not stop the run
            log.warning("%s: %s", seed["id"], exc)
            entry["error"] = str(exc)
            report.append(entry)
            continue

        kept, skipped, unclassified = [], Counter(), []
        for link in links:
            result = classify(link, seed)
            if result.doc:
                kept.append(result.doc)
            elif result.skipped:
                skipped[result.reason] += 1
            else:
                unclassified.append({"url": link["url"], "text": link["text"], "context": link["context"][:3], "why": result.reason})
        all_docs.extend(kept)
        entry.update(
            links=len(links), kept=len(kept), skipped=dict(skipped), unclassified=unclassified,
            doc_types=dict(Counter(d["doc_type"] for d in kept)),
            series=sorted({d["series"] for d in kept}, reverse=True),
            levels=dict(Counter(d["level"] for d in kept)),
        )
        report.append(entry)
        log.info("%s: %d links, %d kept, %d unclassified", seed["id"], len(links), len(kept), len(unclassified))
        if args.save_raw:
            raw = store.REPORTS / "raw" / f"{seed['id']}.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(harvest.dump(links), encoding="utf-8")

    if not args.dry_run:
        docs, stats = store.merge(store.load(), all_docs)
        store.save(docs)
        log.info("Store: %d added, %d updated, %d total", stats["added"], stats["updated"], len(docs))
    write_report(report)

    failed = [r for r in report if "error" in r or not r.get("kept")]
    if failed and len(failed) == len(report):
        log.error("Every seed failed or found nothing; see data/reports/scrape-report.md")
        return 2
    return 0


def write_report(report: list[dict]) -> Path:
    store.REPORTS.mkdir(parents=True, exist_ok=True)
    (store.REPORTS / "scrape-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = ["# Scrape report", "", f"Generated {store.now()}", "",
             "| Seed | Links | Kept | Unclassified | Status |", "|---|---|---|---|---|"]
    for r in report:
        if "error" in r:
            status = f"ERROR: {r['error']}"
        elif not r["links"]:
            status = "No PDF links found - page may need `mode: browser` or a new URL"
        elif not r["kept"]:
            status = "Links found but none classified - check samples below"
        else:
            status = "OK"
        lines.append(f"| {r['seed']} | {r.get('links', '-')} | {r.get('kept', '-')} | {len(r.get('unclassified', []))} | {status} |")
    for r in report:
        if r.get("unclassified") or r.get("kept"):
            lines += ["", f"## {r['seed']}", "", f"Source: {r['url']} ({r['mode']})"]
            if r.get("kept"):
                lines.append(f"- Document types: {r['doc_types']}")
                lines.append(f"- Levels: {r['levels']}")
                lines.append(f"- Series: {', '.join(r['series'][:8])}{' ...' if len(r['series']) > 8 else ''}")
            if r.get("skipped"):
                lines.append(f"- Skipped: {r['skipped']}")
            if r.get("unclassified"):
                lines.append(f"- Unclassified samples (of {len(r['unclassified'])}):")
                for u in r["unclassified"][:10]:
                    lines.append(f"  - `{u['text'] or '(no text)'}` - {u['why']} - context: {' > '.join(u['context']) or '(none)'} - {u['url']}")
    path = store.REPORTS / "scrape-report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return path


def check_links(args) -> int:
    config = load_config()
    docs = store.load()
    stats = linkcheck.run(docs, config.get("settings", {}), limit=args.limit)
    store.save(docs)
    log.info("Link check: %s", stats)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## Link check\n\n{json.dumps(stats)}\n")
    return 0


def build(args) -> int:
    meta = builder.build()
    log.info("Built %d papers (%d documents) into dist/", meta["paper_count"], meta["document_count"])
    return 0


def doctor(args) -> int:
    path = store.REPORTS / "scrape-report.md"
    if not path.exists():
        log.error("No report yet. Run: python -m hef scrape --dry-run")
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def serve(args) -> int:
    import functools
    import http.server

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(builder.DIST))
    print(f"Serving {builder.DIST} at http://localhost:{args.port}")
    http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hef", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scrape", help="harvest and classify")
    p.add_argument("--board", help="only this board (prefix match, e.g. aqa, ocr, pearson)")
    p.add_argument("--seed", help="only this seed id")
    p.add_argument("--dry-run", action="store_true", help="report only; do not update the store")
    p.add_argument("--save-raw", action="store_true", help="also save raw harvested links per seed")
    p.set_defaults(func=scrape)

    p = sub.add_parser("check-links", help="check indexed links")
    p.add_argument("--limit", type=int, help="check at most N links (oldest-checked first)")
    p.set_defaults(func=check_links)

    sub.add_parser("build", help="build the website").set_defaults(func=build)
    sub.add_parser("doctor", help="show the last scrape report").set_defaults(func=doctor)
    p = sub.add_parser("serve", help="preview the built site")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=serve)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
