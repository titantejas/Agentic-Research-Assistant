import re
import httpx
from langchain_core.tools import tool
from sqlalchemy import text
from .db import SessionLocal
from .config import settings
from .guards import ALLOWED_TABLES, is_select_allowed, calc_eval

@tool
async def web_search(query: str) -> str:
    """Search the web for current/external facts. Input: query string."""
    # Prefer Tavily if key present, else DuckDuckGo instant API (no key)
    if settings.tavily_api_key:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post("https://api.tavily.com/search",
                json={"api_key": settings.tavily_api_key, "query": query, "max_results": 5})
            r.raise_for_status()
            j = r.json()
            out = [f"- {x.get('title')}: {x.get('content','')[:400]} [{x.get('url')}]"
                   for x in j.get("results", [])[:5]]
            return "\n".join(out) or "No results."
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1})
        j = r.json()
        topics = j.get("RelatedTopics", [])[:5]
        lines = []
        for t in topics:
            if isinstance(t, dict) and "Text" in t:
                lines.append(f"- {t['Text'][:400]} [{t.get('FirstURL','')}]")
        return "\n".join(lines) or f"No DDG results for '{query}'."

@tool
async def sql_query(query: str) -> str:
    """Run a READ-ONLY SQL SELECT against whitelisted tables. Input: SQL string."""
    allowed, reason = is_select_allowed(query)
    if not allowed:
        return f"Error: {reason}."
    async with SessionLocal() as s:
        rows = (await s.execute(text(query))).mappings().all()
        return str([dict(r) for r in rows[:20]]) or "0 rows."

@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression. Input e.g. '12*7/2'."""
    return calc_eval(expression)

@tool
async def document_retrieval(query: str) -> str:
    """Retrieve project/domain knowledge from Postgres documents table."""
    async with SessionLocal() as s:
        # Trigram + full-text rank; no pgvector dependency.
        rows = (await s.execute(text(
            "SELECT title, left(content,600) AS snippet FROM documents "
            "WHERE content ILIKE :q "
            "ORDER BY ts_rank(to_tsvector('english', content), plainto_tsquery('english', :q2)) DESC "
            "LIMIT 3"),
            {"q": f"%{query}%", "q2": query})).mappings().all()
        # Fallback for asyncpg <-> operator absence: ILIKE already filters
        if not rows:
            rows = (await s.execute(text(
                "SELECT title, left(content,600) AS snippet FROM documents "
                "WHERE content ILIKE :q LIMIT 3"), {"q": f"%{query.split()[0]}%"})).mappings().all()
        return "\n".join(f"[doc:{r['title']}] {r['snippet']}" for r in rows) or "No docs found."

TOOLS = [web_search, sql_query, calculator, document_retrieval]
