"""Fetch seed pages and pull out every PDF link with the context around it.

Two modes:

* ``static``  - plain HTTP request, parse the HTML. Fast; works for OCR.
* ``browser`` - load the page in headless Chromium (Playwright), let its
  JavaScript run, then read the rendered links *and* any JSON the page fetched
  from the board's own search API. Needed for AQA, Pearson and WJEC/Eduqas,
  whose finders load results with JavaScript.

Each harvested link is a dict: ``url``, ``text``, ``context`` (nearby headings,
nearest first), ``extra`` (other fields from API JSON) and ``source_page``.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from .classify.common import clean, is_pdf_url

log = logging.getLogger(__name__)

USER_AGENT = (
    "HarrisonExamFinderBot/0.1 (link-only index of public past papers; "
    "+{contact})"
)
REQUEST_DELAY_SECONDS = 2.0
TIMEOUT = 30

_last_request: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class HarvestError(Exception):
    pass


def user_agent(settings: dict) -> str:
    return USER_AGENT.format(contact=settings.get("contact", "see website"))


def _polite_wait(url: str) -> None:
    host = urlparse(url).netloc
    wait = REQUEST_DELAY_SECONDS - (time.monotonic() - _last_request.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_request[host] = time.monotonic()


def allowed_by_robots(url: str, agent: str, session: requests.Session) -> bool:
    parts = urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots:
        parser = urllib.robotparser.RobotFileParser()
        try:
            resp = session.get(root + "/robots.txt", timeout=TIMEOUT)
            parser.parse(resp.text.splitlines() if resp.ok else [])
            _robots[root] = parser
        except requests.RequestException:
            _robots[root] = None  # unreachable robots.txt: treat as allowed
    parser = _robots[root]
    return parser is None or parser.can_fetch(agent, url)


# --- Context extraction (shared logic for static and browser modes) ----------

HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
LABEL_LEVEL = 7  # accordion summaries, tab labels and similar


def _is_label(el: Tag) -> bool:
    if el.name == "summary" or el.name == "legend":
        return True
    if el.get("role") in ("tab", "heading"):
        return True
    if el.name == "button" and (el.get("aria-controls") or el.get("aria-expanded") is not None):
        return True
    classes = " ".join(el.get("class") or []).lower()
    return any(k in classes for k in ("accordion__title", "accordion-title", "accordion-heading", "panel-title", "series-title"))


def links_from_html(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    for junk in soup(["script", "style", "noscript", "template"]):
        junk.decompose()

    # Real headings form a stack (an h4 replaces the previous h4 and clears h5/h6).
    # Accordion/tab labels sit outside that hierarchy, so the most recent one is
    # kept separately. Context is ordered nearest-first by document position.
    stack: dict[int, tuple[int, str]] = {}
    label: tuple[int, str] | None = None
    found: list[dict] = []
    seen: set[str] = set()
    for pos, el in enumerate(soup.body.descendants if soup.body else []):
        if not isinstance(el, Tag):
            continue
        level = HEADING_TAGS.get(el.name)
        is_label = level is None and _is_label(el)
        if level is not None or is_label:
            text = clean(el.get_text(" "))
            if text and len(text) < 150:
                if is_label:
                    label = (pos, text)
                else:
                    stack[level] = (pos, text)
                    for deeper in [k for k in stack if k > level]:
                        del stack[deeper]
            continue
        if el.name == "a" and el.get("href"):
            url = urljoin(page_url, el["href"].strip())
            if not is_pdf_url(url) or url in seen:
                continue
            seen.add(url)
            text = clean(el.get_text(" ")) or clean(el.get("title")) or clean(el.get("aria-label"))
            entries = list(stack.values()) + ([label] if label else [])
            context = [t for _, t in sorted(entries, reverse=True)]
            found.append({"url": url, "text": text, "context": context, "extra": "", "source_page": page_url})
    return found


def links_from_json(data, page_url: str) -> list[dict]:
    """Walk API JSON and turn any object holding a PDF URL into a link."""
    found: list[dict] = []

    def walk(node, parents: list[str]):
        if isinstance(node, dict):
            strings = {k: v for k, v in node.items() if isinstance(v, str) and len(v) < 300}
            pdfs = [v for v in strings.values() if is_pdf_url(urljoin(page_url, v)) and ("/" in v or v.lower().endswith(".pdf"))]
            label = ""
            for key in ("title", "name", "label", "displayName", "documentTitle", "linkText", "description"):
                for k, v in strings.items():
                    if k.lower() == key.lower() and v and not is_pdf_url(v):
                        label = v
                        break
                if label:
                    break
            others = " | ".join(clean(v) for k, v in strings.items() if v not in pdfs and v != label and not v.startswith("http"))
            for pdf in pdfs:
                found.append({
                    "url": urljoin(page_url, pdf),
                    "text": clean(label),
                    "context": parents[-3:][::-1],
                    "extra": others,
                    "source_page": page_url,
                })
            next_parents = parents + ([clean(label)] if label and not pdfs else [])
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v, next_parents)
        elif isinstance(node, list):
            for item in node:
                walk(item, parents)

    walk(data, [])
    return found


# --- Fetchers ----------------------------------------------------------------

def fetch_static(seed: dict, settings: dict, session: requests.Session) -> list[dict]:
    agent = user_agent(settings)
    if not allowed_by_robots(seed["url"], agent, session):
        raise HarvestError("robots.txt disallows this page")
    _polite_wait(seed["url"])
    resp = session.get(seed["url"], timeout=TIMEOUT)
    if resp.status_code != 200:
        raise HarvestError(f"HTTP {resp.status_code}")
    return links_from_html(resp.text, resp.url)


# Runs inside the page: the same heading logic as links_from_html.
_JS_EXTRACT = r"""
() => {
  const H = {H1:1,H2:2,H3:3,H4:4,H5:5,H6:6};
  const isLabel = el => {
    if (el.tagName === 'SUMMARY' || el.tagName === 'LEGEND') return true;
    const role = el.getAttribute('role');
    if (role === 'tab' || role === 'heading') return true;
    if (el.tagName === 'BUTTON' && (el.hasAttribute('aria-controls') || el.hasAttribute('aria-expanded'))) return true;
    const c = (el.className && el.className.baseVal === undefined ? el.className : '').toLowerCase();
    return ['accordion__title','accordion-title','accordion-heading','panel-title','series-title'].some(k => c.includes(k));
  };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const stack = {}; let label = null; const out = []; const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el; let pos = 0;
  while ((el = walker.nextNode())) {
    pos++;
    if (['SCRIPT','STYLE','NOSCRIPT','TEMPLATE'].includes(el.tagName)) continue;
    const level = H[el.tagName];
    const lab = level === undefined && isLabel(el);
    if (level !== undefined || lab) {
      const t = clean(el.innerText || el.textContent);
      if (t && t.length < 150) {
        if (lab) label = [pos, t];
        else { stack[level] = [pos, t]; Object.keys(stack).forEach(k => { if (+k > level) delete stack[k]; }); }
      }
      continue;
    }
    if (el.tagName === 'A' && el.href) {
      const url = el.href;
      if (!/\.pdf($|[?#])/i.test(url) || seen.has(url)) continue;
      seen.add(url);
      const text = clean(el.innerText || el.textContent) || clean(el.title) || clean(el.getAttribute('aria-label'));
      const entries = Object.values(stack).concat(label ? [label] : []);
      const context = entries.sort((a, b) => b[0] - a[0]).map(e => e[1]);
      out.push({url, text, context, extra: '', source_page: location.href});
    }
  }
  return out;
}
"""


def _settle(page) -> None:
    """Wait for the page's requests to finish, but don't hang on chatty pages."""
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001
        page.wait_for_timeout(3_000)


def fetch_browser(seed: dict, settings: dict, session: requests.Session) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise HarvestError("Playwright is not installed: pip install playwright && playwright install chromium") from exc

    agent = user_agent(settings)
    if not allowed_by_robots(seed["url"], agent, session):
        raise HarvestError("robots.txt disallows this page")

    opts = seed.get("browser", {})
    json_bodies: list = []
    links: list[dict] = []

    def on_response(resp):
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype and resp.request.resource_type in ("xhr", "fetch"):
            try:
                json_bodies.append((resp.url, resp.json()))
            except Exception:  # noqa: BLE001 - malformed JSON is just ignored
                pass

    _polite_wait(seed["url"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=agent)
        page.on("response", on_response)
        resp = page.goto(seed["url"], wait_until="domcontentloaded", timeout=60_000)
        if resp is None or resp.status != 200:
            browser.close()
            raise HarvestError(f"HTTP {resp.status if resp else 'no response'}")
        _settle(page)

        for selector in opts.get("click_before", []):
            try:
                page.click(selector, timeout=5_000)
                _settle(page)
            except Exception:  # noqa: BLE001
                log.warning("%s: could not click %r", seed["id"], selector)
        if opts.get("wait_for"):
            try:
                page.wait_for_selector(opts["wait_for"], timeout=20_000)
            except Exception:  # noqa: BLE001
                log.warning("%s: %r never appeared", seed["id"], opts["wait_for"])
        if opts.get("expand_all", True):
            page.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")

        links.extend(page.evaluate(_JS_EXTRACT))
        for _ in range(int(opts.get("max_pages", 1)) - 1):
            nxt = opts.get("next_selector")
            if not nxt or not page.query_selector(nxt) or page.is_disabled(nxt):
                break
            time.sleep(REQUEST_DELAY_SECONDS)
            page.click(nxt)
            _settle(page)
            links.extend(page.evaluate(_JS_EXTRACT))
        browser.close()

    for url, body in json_bodies:
        links.extend(links_from_json(body, seed["url"]))

    # De-duplicate, keeping the version with the most information.
    best: dict[str, dict] = {}
    for link in links:
        score = len(link["text"]) + len(link["extra"]) + 10 * len(link["context"])
        current = best.get(link["url"])
        if current is None or score > current["_score"]:
            best[link["url"]] = {**link, "_score": score}
    return [{k: v for k, v in link.items() if k != "_score"} for link in best.values()]


def harvest(seed: dict, settings: dict, session: requests.Session | None = None) -> list[dict]:
    session = session or new_session(settings)
    mode = seed.get("mode", "static")
    if mode == "static":
        return fetch_static(seed, settings, session)
    if mode == "browser":
        return fetch_browser(seed, settings, session)
    raise HarvestError(f"unknown mode {mode!r}")


def new_session(settings: dict) -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = user_agent(settings)
    return session


def dump(links: list[dict]) -> str:
    return json.dumps(links, indent=2, ensure_ascii=False)
