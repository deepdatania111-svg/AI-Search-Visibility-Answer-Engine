import pandas as pd, streamlit as st
from audit import run_audit, to_markdown

st.set_page_config(page_title="AI Search Visibility Audit", page_icon="🔍", layout="wide")
st.title("🔍 AI Search Visibility & Answer Engine Audit")
st.caption("Checks whether a site clearly answers likely AI-search questions. "
           "Labels: MEASURED (observed) · HEURISTIC (rule-based score) · ESTIMATE (not verified with real AI engines).")

url = st.text_input("Website URL", "https://example.com")
queries = st.text_area("Target queries (one per line)", "what is example domain\nhow to register a domain").splitlines()
pages = st.slider("Max pages to crawl", 1, 25, 8)

if st.button("Run audit", type="primary"):
    with st.spinner("Crawling and analysing..."):
        try: a = run_audit(url, queries, pages)
        except Exception as e: st.error(str(e)); st.stop()
    s = a["scores"]
    cols = st.columns(5)
    for c, (k, v) in zip(cols, s.items()): c.metric(k.replace("_", " ").title(), f"{v}/100")
    st.subheader("Query results (HEURISTIC + ESTIMATE)")
    st.dataframe(pd.DataFrame([{k: r[k] for k in ("query", "status", "score", "page", "citation_likelihood")} for r in a["queries"]]), use_container_width=True)
    for r in a["queries"]:
        with st.expander(f"{r['status']} · {r['query']}"):
            st.write("**Best matching passage (MEASURED):**", r["passage"] or "_none_")
            for x in r["recommendations"]: st.write("- " + x)
    st.subheader("Schema opportunities")
    st.dataframe(pd.DataFrame(a["schema_opportunities"]), use_container_width=True)
    st.subheader("Technical access (MEASURED)")
    st.json(a["technical"])
    st.download_button("Download Markdown report", to_markdown(a), "ai_search_audit.md")
