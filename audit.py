"""AI Search Visibility & Answer Engine Audit - core engine.

Every finding is tagged:
  MEASURED  - directly observed in fetched HTML / robots.txt / sitemap
  HEURISTIC - computed score using transparent rules in this file
  ESTIMATE  - informed judgement; NOT verified against any real AI engine
"""
import json, re, urllib.parse, urllib.robotparser
from collections import deque
import requests
from bs4 import BeautifulSoup

UA = "AISearchAuditBot/1.0"
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
           "PerplexityBot", "Google-Extended", "CCBot", "Applebot-Extended"]
STOP = set("a an the and or of to in on for with is are was be how what why when where who which "
           "do does can i my your you it this that at by from as about best vs".split())
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".zip", ".css", ".js", ".ico", ".xml", ".mp4")
M, H, E = "MEASURED", "HEURISTIC", "ESTIMATE"


def get(url, timeout=10):
    try:
        return requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    except requests.RequestException:
        return None


def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


def jsonld_types(soup):
    types = set()

    def walk(o):
        if isinstance(o, list):
            for x in o: walk(x)
        elif isinstance(o, dict):
            t = o.get("@type")
            if t: types.update(t if isinstance(t, list) else [t])
            for v in o.values():
                if isinstance(v, (dict, list)): walk(v)
    for s in soup.find_all("script", type="application/ld+json"):
        try: walk(json.loads(s.string or ""))
        except Exception: pass
    return sorted(types)


def parse_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    links = [urllib.parse.urljoin(url, a["href"]).split("#")[0] for a in soup.find_all("a", href=True)]
    types = jsonld_types(soup)
    for s in soup.find_all(["script", "style", "nav", "footer"]): s.decompose()
    headings = [(int(h.name[1]), h.get_text(" ", strip=True)) for h in soup.find_all(re.compile("^h[1-3]$"))]
    passages = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "li", "td"])]
    passages = [p for p in passages if len(p.split()) >= 5]
    desc = soup.find("meta", attrs={"name": "description"})
    robots = soup.find("meta", attrs={"name": "robots"})
    imgs = soup.find_all("img")
    text = soup.get_text(" ", strip=True)
    return {
        "url": url,
        "title": soup.title.get_text(strip=True) if soup.title else "",
        "meta_description": (desc.get("content", "") if desc else "").strip(),
        "h1": [t for l, t in headings if l == 1],
        "headings": headings,
        "question_headings": [t for _, t in headings if t.strip().endswith("?")],
        "word_count": len(text.split()),
        "schema_types": types,
        "has_list_or_table": bool(soup.find(["ul", "ol", "table"])),
        "has_steps": bool(soup.find("ol")),
        "has_date": bool(soup.find("time")) or bool(re.search(r"(20\d\d)-\d\d-\d\d", html)),
        "has_author": bool(soup.find(attrs={"rel": "author"}) or soup.find("meta", attrs={"name": "author"})),
        "canonical": bool(soup.find("link", rel="canonical")),
        "noindex": bool(robots and "noindex" in robots.get("content", "").lower()),
        "img_alt_ratio": round(sum(1 for i in imgs if i.get("alt")) / len(imgs), 2) if imgs else None,
        "passages": passages,
        "_links": links,
    }


def crawl(start, max_pages):
    host = urllib.parse.urlparse(start).netloc
    seen, queue, pages = {start}, deque([start]), []
    while queue and len(pages) < max_pages:
        u = queue.popleft()
        r = get(u)
        if not r or r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            continue
        p = parse_page(u, r.text)
        pages.append(p)
        for l in p["_links"]:
            pu = urllib.parse.urlparse(l)
            if pu.netloc == host and pu.scheme in ("http", "https") and l not in seen \
                    and not pu.path.lower().endswith(SKIP_EXT):
                seen.add(l); queue.append(l)
    return pages


def technical(start):
    pu = urllib.parse.urlparse(start)
    base = f"{pu.scheme}://{pu.netloc}"
    res = {"https": pu.scheme == "https", "bots": {}, "robots_found": False, "sitemap": False, "llms_txt": False}
    r = get(base + "/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    if r and r.status_code == 200 and "<html" not in r.text[:200].lower():
        res["robots_found"] = True
        rp.parse(r.text.splitlines())
        res["sitemap"] = "sitemap:" in r.text.lower()
        for b in AI_BOTS: res["bots"][b] = rp.can_fetch(b, start)
    else:
        for b in AI_BOTS: res["bots"][b] = True  # no robots.txt = not blocked
    if not res["sitemap"]:
        s = get(base + "/sitemap.xml")
        res["sitemap"] = bool(s and s.status_code == 200 and ("<urlset" in s.text or "<sitemapindex" in s.text))
    l = get(base + "/llms.txt")
    res["llms_txt"] = bool(l and l.status_code == 200 and "<html" not in l.text[:200].lower())
    allowed = sum(res["bots"].values())
    res["score"] = round(60 * allowed / len(AI_BOTS) + (25 if res["sitemap"] else 0) + (15 if res["https"] else 0))
    return res


def score_query(query, pages):
    q = set(tokens(query))
    if not q: return None
    best = None
    for p in pages:
        title = set(tokens(p["title"] + " " + " ".join(p["h1"])))
        heads = set(tokens(" ".join(t for _, t in p["headings"])))
        qh = max([len(q & set(tokens(h))) / len(q) for h in p["question_headings"]] or [0])
        bp, bo = "", 0
        for para in p["passages"]:
            o = len(q & set(tokens(para))) / len(q)
            if o > bo or (o == bo and o > 0 and 20 <= len(para.split()) <= 80): bp, bo = para, o
        n = len(bp.split())
        sc = 40 * bo + 20 * len(q & heads) / len(q) + 15 * len(q & title) / len(q) \
            + (15 if 20 <= n <= 80 and bo >= .5 else 0) + (10 if qh >= .6 else 0)
        if not best or sc > best["score"]:
            best = {"page": p["url"], "score": round(sc), "passage": bp[:300], "passage_words": n,
                    "term_overlap": round(bo, 2), "question_heading_match": qh >= .6,
                    "heading_overlap": round(len(q & heads) / len(q), 2)}
    s = best["score"] if best else 0
    status = "Answered" if s >= 65 else "Partial" if s >= 40 else "Gap"
    best = best or {"page": None, "score": 0, "passage": "", "passage_words": 0}
    best.update(query=query, status=status,
                citation_likelihood={"Answered": "Medium-High", "Partial": "Low-Medium", "Gap": "Low"}[status])
    best["recommendations"] = query_recs(query, best)
    return best


def query_recs(query, b):
    r = []
    if b["status"] == "Gap":
        r.append(f"No page clearly addresses '{query}'. Create a dedicated page or section with a heading phrased as this question.")
    if not b.get("question_heading_match"):
        r.append("Add an H2/H3 that mirrors the query wording (e.g. as a question).")
    if b.get("passage_words", 0) > 80:
        r.append("Best matching passage is long; lead with a 40-60 word direct answer, then elaborate.")
    elif 0 < b.get("passage_words", 0) < 20:
        r.append("Best matching passage is too thin to stand alone as an answer; expand with specifics (numbers, names, steps).")
    if b.get("term_overlap", 0) < .6 and b["status"] != "Gap":
        r.append("Key query terms are missing from the answer text; use the exact entities and terms users search for.")
    return r


def page_type(p):
    path = urllib.parse.urlparse(p["url"]).path.lower().strip("/")
    if path == "": return "home"
    if "faq" in path or len(p["question_headings"]) >= 3: return "faq"
    if p["has_steps"] and ("how" in p["title"].lower() or "guide" in path): return "howto"
    if any(k in path for k in ("product", "pricing", "shop", "plan")): return "product"
    if any(k in path for k in ("blog", "article", "news", "post")) or p["has_date"]: return "article"
    return "generic"


def schema_recs(p):
    have, t, out = set(p["schema_types"]), page_type(p), []
    def add(s, why):
        if s not in have: out.append({"page": p["url"], "schema": s, "why": why, "label": H})
    if t == "home":
        add("Organization", "Entity definition for brand/knowledge-graph understanding."); add("WebSite", "Site name + search action.")
    if t == "faq" or len(p["question_headings"]) >= 2:
        add("FAQPage", f"{len(p['question_headings'])} question-style headings found. Note: Google limits FAQ rich results to a few site types, but the markup still helps machines parse Q&A.")
    if t == "article":
        add("Article", "Dated/blog-style content; add author + datePublished + dateModified.")
    if t == "howto": add("HowTo", "Ordered steps detected (rich result deprecated by Google; still useful semantic markup).")
    if t == "product": add("Product", "Pricing/product page; add Offer, price, availability.")
    if t != "home": add("BreadcrumbList", "Clarifies page hierarchy.")
    return out


def structure_score(p):
    return (10 * bool(p["title"]) + 15 * bool(p["meta_description"]) + 20 * (len(p["h1"]) == 1)
            + 15 * p["has_list_or_table"] + 15 * bool(p["question_headings"])
            + 15 * (p["word_count"] >= 300) + 10 * p["canonical"])


def run_audit(url, queries, max_pages=10):
    if not url.startswith("http"): url = "https://" + url
    pages = crawl(url, max_pages)
    if not pages: raise RuntimeError("Could not fetch any pages from " + url)
    tech = technical(url)
    qres = [r for r in (score_query(q, pages) for q in queries if q.strip()) if r]
    cov = round(sum(r["score"] for r in qres) / len(qres)) if qres else 0
    schema = round(100 * sum(1 for p in pages if p["schema_types"]) / len(pages))
    struct = round(sum(structure_score(p) for p in pages) / len(pages))
    overall = round(.5 * cov + .2 * tech["score"] + .15 * schema + .15 * struct)
    gaps = [r["query"] for r in qres if r["status"] == "Gap"]
    for p in pages: p.pop("_links", None)
    return {"url": url, "pages": pages, "technical": tech, "queries": qres,
            "schema_opportunities": [s for p in pages for s in schema_recs(p)],
            "content_gaps": gaps,
            "scores": {"overall": overall, "query_coverage": cov, "technical_access": tech["score"],
                       "structured_data": schema, "content_structure": struct}}


def to_markdown(a):
    s, t = a["scores"], a["technical"]
    L = [f"# AI Search Visibility Audit: {a['url']}", "",
         "**Evidence labels:** `MEASURED` = observed in fetched HTML/robots.txt; `HEURISTIC` = rule-based score from this tool; "
         "`ESTIMATE` = judgement, not verified against any real AI engine.", "",
         "## Scores (HEURISTIC)", "| Area | Score /100 |", "|---|---|"]
    L += [f"| {k.replace('_', ' ').title()} | {v} |" for k, v in s.items()]
    L += ["", f"## Technical access (MEASURED, {len(a['pages'])} pages crawled)",
          f"- HTTPS: {t['https']} | robots.txt found: {t['robots_found']} | sitemap: {t['sitemap']} | llms.txt: {t['llms_txt']} (informational; no confirmed ranking effect)"]
    blocked = [b for b, ok in t["bots"].items() if not ok]
    L.append(f"- AI crawlers blocked by robots.txt: {', '.join(blocked) if blocked else 'none'}")
    L += ["", "## Query-by-query results", "| Query | Status (HEURISTIC) | Score | Best page | Citation likelihood (ESTIMATE) |", "|---|---|---|---|---|"]
    L += [f"| {r['query']} | {r['status']} | {r['score']} | {r['page']} | {r['citation_likelihood']} |" for r in a["queries"]]
    for r in a["queries"]:
        if r["recommendations"]:
            L += ["", f"**{r['query']}**"] + [f"- {x}" for x in r["recommendations"]]
    L += ["", "## Content gaps (HEURISTIC)"] + ([f"- {g}" for g in a["content_gaps"]] or ["- None detected"])
    L += ["", "## Schema opportunities (HEURISTIC)"] + [f"- `{x['schema']}` on {x['page']}: {x['why']}" for x in a["schema_opportunities"]]
    L += ["", "## Page facts (MEASURED)", "| Page | Words | H1s | Q-headings | Schema |", "|---|---|---|---|---|"]
    L += [f"| {p['url']} | {p['word_count']} | {len(p['h1'])} | {len(p['question_headings'])} | {', '.join(p['schema_types']) or '-'} |" for p in a["pages"]]
    L += ["", "## Limitations", "- No live AI engine (ChatGPT, Perplexity, Gemini) was queried; citation likelihood is an estimate.",
          "- Content is read from static HTML; JavaScript-rendered content is not seen.",
          "- Relevance uses keyword overlap, not semantic understanding."]
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AI Search Visibility Audit")
    ap.add_argument("url"); ap.add_argument("-q", "--queries", nargs="+", required=True)
    ap.add_argument("-n", "--max-pages", type=int, default=10); ap.add_argument("-o", "--out", default="report.md")
    a = ap.parse_args()
    res = run_audit(a.url, a.queries, a.max_pages)
    open(a.out, "w").write(to_markdown(res)); open(a.out.rsplit(".", 1)[0] + ".json", "w").write(json.dumps(res, indent=2))
    print(f"Done. Overall score {res['scores']['overall']}/100 -> {a.out}")
