/* Harrison Exam Finder - search over data/papers.json, entirely in the browser. */
(() => {
  "use strict";

  const PAGE_SIZE = 30; // groups shown per "Show more"
  const DOC_LABELS = {
    question_paper: "Question paper",
    mark_scheme: "Mark scheme",
    examiner_report: "Examiner report",
    insert: "Insert",
    answer_book: "Answer book",
  };
  const CORE = ["question_paper", "mark_scheme", "examiner_report"];
  const FIELDS = ["q", "subject", "level", "board", "year", "tier"];

  const $ = (id) => document.getElementById(id);
  const form = $("filters");
  const list = $("list");
  const count = $("count");
  const more = $("more");
  const groupTpl = $("group-tpl");

  let papers = [];
  let groups = [];
  let shown = 0;

  const host = (url) => {
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "the exam board"; }
  };
  const fmtDate = (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  const norm = (s) => (s || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]+/g, " ");

  function el(tag, attrs = {}, text) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fillSelect(id, values) {
    const select = $(id);
    for (const v of values) select.append(el("option", { value: v }, v));
  }

  // ---- State lives in the URL so any search can be bookmarked or shared ----

  function readState() {
    const params = new URLSearchParams(location.search);
    for (const f of FIELDS) {
      const input = form.elements[f];
      const value = params.get(f) || "";
      if (input.tagName === "SELECT" && value && ![...input.options].some((o) => o.value === value)) continue;
      input.value = value;
    }
  }

  function writeState() {
    const params = new URLSearchParams();
    for (const f of FIELDS) {
      const v = form.elements[f].value.trim();
      if (v) params.set(f, v);
    }
    const qs = params.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function markSetBoxes() {
    for (const f of FIELDS) {
      form.elements[f].closest(".box").classList.toggle("is-set", form.elements[f].value.trim() !== "");
    }
  }

  // ---- Filtering ----

  function matches(p, s, terms) {
    if (s.subject && p.subject !== s.subject) return false;
    if (s.level && p.level !== s.level) return false;
    if (s.board && p.board !== s.board) return false;
    if (s.year && !p.series_key.startsWith(s.year)) return false;
    if (s.tier && p.tier !== s.tier) return false;
    return terms.every((t) => p._text.includes(t));
  }

  function run() {
    const s = Object.fromEntries(FIELDS.map((f) => [f, form.elements[f].value.trim()]));
    const terms = norm(s.q).split(/\s+/).filter(Boolean);
    const hits = papers.filter((p) => matches(p, s, terms));

    // Group by qualification (board + level + subject + spec), keeping data order.
    const byKey = new Map();
    for (const p of hits) {
      const key = `${p.board}|${p.level}|${p.qualification || p.subject}|${p.spec_code}`;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(p);
    }
    groups = [...byKey.values()];
    list.replaceChildren();
    shown = 0;

    if (!hits.length) {
      count.textContent = "";
      renderEmpty();
      more.hidden = true;
      return;
    }
    const n = hits.length;
    count.textContent = `${n.toLocaleString("en-GB")} ${n === 1 ? "paper" : "papers"} in ${groups.length} ${groups.length === 1 ? "qualification" : "qualifications"}`;
    showMore();
  }

  function showMore() {
    const next = groups.slice(shown, shown + PAGE_SIZE);
    for (const g of next) list.append(renderGroup(g));
    shown += next.length;
    more.hidden = shown >= groups.length;
  }

  // ---- Rendering ----

  function renderGroup(items) {
    const first = items[0];
    const node = groupTpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".group__title").textContent = `${first.board} ${first.level} ${first.qualification || first.subject}`;
    const codes = [...new Set(items.map((p) => p.spec_code).filter(Boolean))];
    node.querySelector(".group__spec").textContent = codes.length ? `Specification ${codes.join(", ")}` : "";

    const rows = node.querySelector(".group__rows");
    const bySeries = new Map();
    for (const p of items) {
      if (!bySeries.has(p.series)) bySeries.set(p.series, []);
      bySeries.get(p.series).push(p);
    }
    for (const [series, ps] of bySeries) {
      const block = el("div", { class: "series" });
      block.append(el("h3", { class: "series__name" }, series));
      const inner = el("div", { class: "series__rows" });
      for (const p of ps) inner.append(renderRow(p));
      block.append(inner);
      rows.append(block);
    }
    return node;
  }

  function renderRow(p) {
    const row = el("div", { class: "row" });
    const name = el("p", { class: "row__name" }, p.paper);
    if (p.tier) name.append(el("span", { class: "tier" }, p.tier));
    row.append(name);

    const docs = el("ul", { class: "docs" });
    // The three main documents always take the same slot so columns line up.
    const types = ["question_paper", "mark_scheme", "examiner_report", ...Object.keys(p.docs).filter((t) => !CORE.includes(t))];
    for (const type of types) {
      const url = p.docs[type];
      if (!url) {
        docs.append(el("li", { class: "docs__gap", "aria-hidden": "true" }));
        continue;
      }
      const label = DOC_LABELS[type] || type;
      const a = el("a", {
        class: `doc doc--${type}`,
        href: url,
        target: "_blank",
        rel: "noopener",
        "aria-label": `${label}: ${p.paper}${p.tier ? " " + p.tier : ""}, ${p.series} (PDF on ${host(url)}, opens in a new tab)`,
      }, label);
      const li = el("li");
      li.append(a);
      docs.append(li);
    }
    row.append(docs);
    return row;
  }

  function renderEmpty() {
    const box = el("div", { class: "empty" });
    box.append(el("h2", {}, "No papers match these choices"));
    box.append(el("p", {}, "Try removing a filter or searching for fewer words. If your subject isn't listed, we don't index it yet."));
    const clear = el("button", { type: "button" }, "Clear all filters");
    clear.addEventListener("click", () => {
      form.reset();
      update();
      form.elements.q.focus();
    });
    box.append(clear);
    list.append(box);
  }

  function update() {
    markSetBoxes();
    writeState();
    run();
  }

  // ---- Start ----

  async function start() {
    try {
      const [pRes, mRes] = await Promise.all([fetch("data/papers.json"), fetch("data/meta.json")]);
      if (!pRes.ok || !mRes.ok) throw new Error(`HTTP ${pRes.status}/${mRes.status}`);
      papers = await pRes.json();
      const meta = await mRes.json();

      for (const p of papers) {
        p._text = norm([p.subject, p.qualification, p.board, p.level, p.spec_code, p.paper, p.series, p.tier].join(" "));
      }
      fillSelect("subject", meta.subjects);
      fillSelect("level", meta.levels);
      fillSelect("board", meta.boards);
      fillSelect("year", [...new Set(papers.map((p) => p.series_key.slice(0, 4)))].sort().reverse());

      if (!papers.length) {
        $("info").textContent = "The index is being built. Papers will appear after the first weekly update.";
        count.textContent = "";
        list.replaceChildren(el("div", { class: "empty" }, "No papers are indexed yet. Please check back soon."));
        return;
      }
      $("info").textContent =
        `The index links to ${meta.paper_count.toLocaleString("en-GB")} papers from ${meta.boards.join(", ").replace(/, ([^,]*)$/, " and $1")}. ` +
        `It was last updated on ${fmtDate(meta.generated)}.`;

      readState();
      markSetBoxes();
      run();
    } catch (err) {
      $("info").textContent = "The index could not be loaded. Refresh the page to try again.";
      count.textContent = "";
      list.replaceChildren(el("div", { class: "empty" }, "The paper index didn't load. Check your connection and refresh the page."));
      console.error(err);
    }
  }

  let timer;
  form.addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(update, e.target.id === "q" ? 150 : 0);
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); update(); $("results").focus(); });
  more.addEventListener("click", showMore);

  start();
})();
