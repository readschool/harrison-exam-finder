# Harrison Exam Finder

A free website for searching UK past exam papers from every board in one place: no adverts, no paywall, no sign-up, no cookies.

It **never hosts the papers**. It keeps an index of links to the official PDFs on each exam board's own website, and checks those links every night. That keeps the site small, free to run and on the right side of the boards' copyright.

## How it works

```
Exam board websites  ->  scrapers (weekly)  ->  data/documents.json  ->  website (GitHub Pages)
                                                      ^
                                     link checker (nightly)
```

| Part | Where | What it does |
|---|---|---|
| Sources | `config/sources.yaml` | Where each board lists its qualifications. Every GCSE, AS and A-level found there becomes a page to read ("seed"), so new subjects are picked up automatically |
| Discovery | `hef/discover.py` | Reads those lists and turns each qualification into the page that holds its past papers |
| Scrapers | `hef/harvest.py` | Reads each page, either as plain HTML or in a headless browser for pages built with JavaScript, and collects every PDF link with the headings around it |
| Rules | `hef/classify/` | Works out board, subject, level, series, paper, tier and document type. AQA and Pearson put most of this in their filenames; OCR puts it in link text and headings |
| Index | `data/documents.json` | One record per PDF. Kept in Git, so every change is visible and can be undone |
| Link checker | `hef/linkcheck.py` | Checks new links straight away and older ones on a rolling basis each night. Only working links are shown. A new link that doesn't work (often a paper still restricted to teachers) stays hidden until it opens up; a link that used to work is hidden after 3 failed checks in a row |
| Website | `site/` | A static search page. It groups each paper's question paper, mark scheme and examiner report together and runs entirely in the browser |
| Automation | `.github/workflows/` | Runs everything on a schedule and publishes the site |

Running costs: GitHub hosting and automation are free for a public repository. A custom domain is optional (around £10 a year).

## Setting it up (about 15 minutes)

1. **Create a GitHub account** at github.com if you don't have one.
2. **Create a new public repository** called `harrison-exam-finder`, then upload everything in this folder (drag and drop works, but make sure the hidden `.github` folder is included; the GitHub Desktop app is the easiest way).
3. **Put your details in:**
   - `config/sources.yaml`: set `contact` to your repository's address. It's sent to the boards with every request so they know who's visiting.
   - `site/about.html`: replace `YOUR-USERNAME` in the "Report a problem" link.
4. **Let the automation save its work:** Settings → Actions → General → Workflow permissions → choose **Read and write permissions** → Save.
5. **Turn on the website:** Settings → Pages → Build and deployment → Source: **GitHub Actions**.
6. **Run the first update:** Actions tab → **Update index and deploy** → **Run workflow**. Each board is scraped in its own job at the same time. A full run reads roughly 250 qualification pages and takes 2 to 4 hours, mostly because it waits between requests to be polite; the first link check after a big scrape adds another hour or two.
7. When it finishes, the site is live at `https://YOUR-USERNAME.github.io/harrison-exam-finder/`.

From then on it updates itself: a full scrape every Monday, a link check every night. To scrape just one board after changing its settings, use **Run workflow** and type `aqa`, `ocr` or `pearson` in the board box.

## The first run: what to expect

The scrapers were written without being able to run against the live board websites, so **expect some seeds to need adjusting on the first run.** Every run writes a **scrape report** to its run summary (Actions tab → click the run). For each seed it shows how many links were found, how many were understood, and examples of any that weren't.

| What the report says | What it usually means | Fix |
|---|---|---|
| `ERROR: HTTP 404` | The board moved the page | Find the qualification's past papers page on the board's site and update `url` in `sources.yaml` |
| `No PDF links found` | The page builds its list with JavaScript, needs a tab clicking, or uses "Load more" | Set `mode: browser`; add the tab to `click_before`; check `next_selector` matches the page's Next button |
| `Links found but none classified` | The page labels documents in a way the rules don't recognise | Look at the samples, then adjust the board's file in `hef/classify/` (or open an issue and paste the samples) |
| A few unclassified links | Usually harmless: specifications, guides and so on | Nothing |

The report starts with a summary and a "Need attention" table, so you don't have to read every row.

To see every page that will be read, and to test one on your own computer:

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m hef discover --board aqa          # writes data/reports/seeds.json
python -m hef scrape --seed aqa-gcse-biology-8461 --dry-run --save-raw
python -m hef doctor
```

`--save-raw` writes everything the scraper saw to `data/reports/raw/<seed>.json`, which is the quickest way to see why something wasn't recognised.

## Adding subjects and boards

**New subjects** are found automatically from each board's qualification list. To add a page that discovery misses, or change the settings for one page, add it under `seeds:` in `config/sources.yaml`; a seed with the same `url` as a discovered page overrides it (for example `enabled: false` to skip it).

**A new board** (WJEC/Eduqas, CCEA, SQA): add a `discovery:` entry pointing at the board's list of qualifications, or add individual seeds with `board:` set to the board's name. The generic rules read link text and headings, so they often work on their own. If the board has informative filenames like AQA and Pearson do, add a rules file in `hef/classify/` and register it in `hef/classify/__init__.py`.

## Working on it locally

```bash
python -m hef scrape            # all seeds (add --board ocr to limit)
python -m hef check-links       # add --limit 200 to check a sample
python -m hef build             # builds the site into dist/
python -m hef serve             # preview at http://localhost:8000
python -m pytest -q             # tests (pip install pytest)
```

## Staying a good citizen

- **Links only.** Never change the site to download and re-host PDFs. Many papers contain third-party material the boards themselves only licensed for limited use.
- **Polite scraping.** The scrapers obey robots.txt, wait 2 seconds between requests to the same site, identify themselves with your contact address, and only run weekly. Please keep it that way.
- **Check each board's website terms** before adding it, and respect any request from a board to stop. The about page tells boards how to reach you.
- **It isn't official.** The site and its footer say clearly that it isn't affiliated with any exam board. Keep that wording.

This isn't legal advice. If the project grows, it's worth writing to each board's copyright team to tell them what the site does and confirm they're happy with it.

## Licence

The code is released under the MIT licence (see `LICENSE`). The fonts in `site/fonts` are under the SIL Open Font Licence (licence files alongside). Past papers, mark schemes and reports belong to their exam boards and are not part of this project.
