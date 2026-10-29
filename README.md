# 🔍 AI Search Visibility & Answer Engine Audit

Analyses a website against a set of target queries and reports whether its pages clearly answer likely AI-search questions (ChatGPT, Perplexity, Gemini, Google AI Overviews). It recommends missing answers, schema opportunities and content gaps, and **separates measured facts from estimates**.

**Live demo:** _add your Streamlit URL here_

## Evidence labels
| Label | Meaning |
|---|---|
| `MEASURED` | Directly observed: HTML, headings, JSON-LD, robots.txt, sitemap, llms.txt |
| `HEURISTIC` | Rule-based score computed by transparent logic in `audit.py` |
| `ESTIMATE` | Judgement (e.g. citation likelihood). Not verified against any real AI engine |

## What it checks
- **Query coverage:** best page + best passage per query, answer length (40-60 word sweet spot), question-style headings, term overlap. Status: Answered / Partial / Gap
- **Technical access:** robots.txt rules for 9 AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended...), sitemap, HTTPS, llms.txt
- **Structured data:** existing JSON-LD types and missing opportunities (Organization, FAQPage, Article, HowTo, Product, BreadcrumbList)
- **Content structure:** title, meta description, single H1, lists/tables, depth, canonical

Overall score = 50% query coverage + 20% technical + 15% schema + 15% structure.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py                       # web UI
python audit.py https://example.com -q "what is X" "how to Y" -n 10   # CLI -> report.md + report.json
```

## Deploy (free)
1. Push to GitHub. 2. Go to share.streamlit.io, choose the repo, main file `app.py`. 3. Paste the URL above.

## Limitations
No live AI engine is queried; JavaScript-rendered content is not seen; relevance is keyword-based, not semantic. Possible extensions: embeddings for semantic matching, Playwright rendering, API checks against real answer engines.
