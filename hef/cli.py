"""Command line: ``python -m hef <command>``.

  discover      list every qualification page that will be scraped
  scrape        harvest seed pages, classify links, update data/documents.json
  merge         merge per-board results from `scrape --out` into the store
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
from . import discover, harvest, linkcheck, store
from .classify import classify

CONFIG = store.ROOT / "config" / "sources.yaml"
log = logging.getLogger("hef")


def load_config(path: Path = CONFIG) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config.setdefault("seeds", [])
    config.setdefault("discovery", [])
    for seed in config["seeds"]:
        seed.setdefault("mode", "static")
        seed.setdefault("enabled", True)
    return config


def _board_match(board: str, wanted: str | None) -> bool:
    return not wanted or board.lower().startswith(wanted.lower())


def all_seeds(config: dict, settings: dict, session, board: str | None) -> tuple[list[dict], list[dict]]:
    """Discovered seeds plus hand-written ones. Returns (seeds, discovery report)."""
    discovered, report = [], []
    for entry in config["discovery"]:
        if not entry.get("enabled", True) or not _board_match(entry["board"], board):
            continue
        seeds, notes = discover.discover(entry, settings, session)
        log.info("%s: discovered %d qualifications", entry["board"], len(seeds))
        discovered.extend(seeds)
        report.append({"board": entry["board"], "found": len(seeds), "notes": notes})
    manual = [s for s in config["seeds"] if _board_match(s["board"], board)]
    seeds = discover.merge_seeds(discovered, manual)
    for seed in seeds:
        seed.setdefault("mode", "static")
        seed.setdefault("enabled", True)
    return [s for s in seeds if s["enabled"]], report


def discover_cmd(args) -> int:
    config = load_config()
    settings = config.get("settings", {})
    seeds, report = all_seeds(config, settings, harvest.new_session(settings), args.board)
    store.REPORTS.mkdir(parents=True, exist_ok=True)
    out = store.REPORTS / "seeds.json"
    out.write_text(json.dumps(seeds, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in report:
        print(f"{r['board']}: {r['found']} qualifications ({'; '.join(r['notes'])})")
    print(f"{len(seeds)} seeds in total, written to {out}")
    return 0


def scrape(args) -> int:
    config = load_config()
    settings = config.get("settings", {})
    session = harvest.new_session(settings)
    if args.seed:
        seeds, discovery_report = all_seeds(config, settings, session, args.board)
        seeds = [s for s in seeds if s["id"] == args.seed]
    else:
        seeds, discovery_report = all_seeds(config, settings, session, args.board)
    if not seeds:
        log.error("No matching seeds. Run `python -m hef discover` to list them.")
        return 1

    all_docs: list[dict] = []
    report: list[dict] = []
    for n, seed in enumerate(seeds, 1):
        entry = {"seed": seed["id"], "board": seed["board"], "url": seed["url"], "mode": seed["mode"]}
        notes: list[str] = []
        try:
            links = harvest.harvest(seed, settings, session, notes)
        except Exception as exc:  # noqa: BLE001 - one bad seed must not stop the run
            log.warning("[%d/%d] %s: %s", n, len(seeds), seed["id"], str(exc).splitlines()[0])
            entry["error"] = str(exc).splitlines()[0][:300]
            entry["notes"] = notes
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
        series = sorted({(d["series_key"], d["series"]) for d in kept}, reverse=True)
        entry.update(
            links=len(links), kept=len(kept), skipped=dict(skipped), unclassified=unclassified, notes=notes,
            doc_types=dict(Counter(d["doc_type"] for d in kept)),
            series=[label for _, label in series],
            levels=dict(Counter(d["level"] for d in kept)),
        )
        report.append(entry)
        log.info("[%d/%d] %s: %d links, %d kept, %d unclassified", n, len(seeds), seed["id"], len(links), len(kept), len(unclassified))
        if args.save_raw:
            raw = store.REPORTS / "raw" / f"{seed['id']}.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(harvest.dump(links), encoding="utf-8")

    scraped_seeds = sorted(r["seed"] for r in report if "error" not in r and r.get("links"))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"docs": all_docs, "scraped_seeds": scraped_seeds,
                                   "report": report, "discovery": discovery_report}, ensure_ascii=False), encoding="utf-8")
        log.info("Wrote %d documents to %s", len(all_docs), out)
    elif not args.dry_run:
        docs, stats = store.merge(store.load(), all_docs, scraped_seeds=set(scraped_seeds))
        store.save(docs)
        log.info("Store: %s, %d total", stats, len(docs))
    write_report(report, discovery_report)

    if all("error" in r or not r.get("kept") for r in report):
        log.error("Every seed failed or found nothing; see data/reports/scrape-report.md")
        return 2
    return 0


def merge_cmd(args) -> int:
    """Merge partial scrape results (one file per board) into the store."""
    docs, seeds, report, discovery_report = [], set(), [], []
    for name in args.files:
        part = json.loads(Path(name).read_text(encoding="utf-8"))
        docs += part["docs"]
        seeds |= set(part["scraped_seeds"])
        report += part["report"]
        discovery_report += part.get("discovery", [])
    if not report:
        log.error("No scrape results to merge.")
        return 1
    merged, stats = store.merge(store.load(), docs, scraped_seeds=seeds)
    store.save(merged)
    log.info("Store: %s, %d total", stats, len(merged))
    write_report(report, discovery_report)
    return 0


def _problem(r: dict) -> str | None:
    if "error" in r:
        return f"ERROR: {r['error']}"
    if not r["links"]:
        return "No PDF links found"
    if not r["kept"]:
        return "Links found but none classified"
    if len(r["unclassified"]) > max(10, r["kept"] * 0.25):
        return "Many unclassified links"
    return None


def write_report(report: list[dict], discovery_report: list[dict] | None = None) -> Path:
    store.REPORTS.mkdir(parents=True, exist_ok=True)
    (store.REPORTS / "scrape-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = [r for r in report if not _problem(r)]
    problems = [r for r in report if _problem(r)]
    lines = ["# Scrape report", "", f"Generated {store.now()}", "",
             f"- Pages read: {len(report)}",
             f"- Working well: {len(ok)}",
             f"- Need attention: {len(problems)}",
             f"- Documents kept: {sum(r.get('kept', 0) for r in report)}", ""]
    if discovery_report:
        lines += ["## Qualifications found", ""]
        for d in discovery_report:
            lines.append(f"- {d['board']}: {d['found']} ({'; '.join(d['notes'])})")
        lines.append("")
    if problems:
        lines += ["## Need attention", "", "| Page | Links | Kept | Unclassified | Problem |", "|---|---|---|---|---|"]
        for r in problems:
            lines.append(f"| {r['seed']} | {r.get('links', '-')} | {r.get('kept', '-')} | {len(r.get('unclassified', []))} | {_problem(r)} |")
        lines.append("")
    lines += ["## All pages", "", "| Page | Links | Kept | Series | Notes |", "|---|---|---|---|---|"]
    for r in report:
        series = r.get("series", [])
        span = f"{series[-1]} to {series[0]}" if len(series) > 1 else (series[0] if series else "-")
        lines.append(f"| {r['seed']} | {r.get('links', '-')} | {r.get('kept', '-')} | {span} | {'; '.join(r.get('notes', []))} |")
    for r in problems:
        lines += ["", f"### {r['seed']}", "", f"Source: {r['url']} ({r['mode']})"]
        if r.get("kept"):
            lines.append(f"- Document types: {r['doc_types']}")
            lines.append(f"- Levels: {r['levels']}")
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
    p.add_argument("--out", help="write results to this file instead of the store (merge them later)")
    p.set_defaults(func=scrape)

    p = sub.add_parser("discover", help="list every qualification page that will be scraped")
    p.add_argument("--board")
    p.set_defaults(func=discover_cmd)

    p = sub.add_parser("merge", help="merge per-board scrape results into the store")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=merge_cmd)

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
