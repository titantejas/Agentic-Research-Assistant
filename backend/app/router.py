"""Deterministic tool router (stdlib-only).

Mirrors the SYSTEM_PROMPT policy so evals and offline tests run without
an OpenAI key. The live LangChain agent uses the same policy via its
system prompt; this router is the testable specification of it.
"""
import re

DOC_KEYWORDS = (
    "langchain", "sse", "server-sent", "postgres", "schema", "conversation",
    "memory", "tool log", "tool-log", "tool_call", "tool-call", "tool call",
    "cache", "caching", "cached", "stream", "streaming", "docs",
    "prompt", "agent", "reasoning", "trace", "document", "retrieval",
    "embedding", "fastapi", "react", "typescript", "ttl", "history",
    "trigram", "whitelist", "scratchpad", "citations",
)
WEB_HINTS = (
    "latest", "today", "current", "news", "2025", "2026", "price",
    "stock", "who won", "election", "weather", "release date",
    "what happened", "breaking",
)
SQL_HINTS = (
    "select", "sql", "how many messages", "tool logs", "tool_logs",
    "list documents", "query the database", "show conversations",
    "count rows", "from documents", "from messages",
)


def predict_tool(query: str) -> str:
    q = query.lower().strip()

    # 1. Explicit SQL / DB requests win (read-only analytics).
    # Malicious input still routes here so the guardrail can reject it.
    if any(h in q for h in SQL_HINTS):
        # Malicious "select ... drop" still routes to sql_query so the
        # guardrail can reject it — that is the correct behaviour.
        if q.startswith("select") or "sql" in q or "database" in q or "how many" in q or "list " in q or "show " in q or "count" in q:
            return "sql_query"

    # 2. Arithmetic: bare expression or calculate/what-is with numbers+operator
    has_num = bool(re.search(r"\d", q))
    has_op = bool(re.search(r"[+\-*/%^()]|plus|minus|times|divided|modulo|power", q))
    if has_num and has_op and re.search(r"\b(calculat\w*|comput\w*|evaluat\w*|what is|solve)\b", q):
        return "calculator"
    # Bare expression like "12*7/2" or "(15 + 8) * 2"
    if re.fullmatch(r"\s*[\d\s+\-*/%().*]+\s*\??\s*", q) and has_num and has_op:
        return "calculator"

    # 3. Project / domain knowledge -> docs
    if any(k in q for k in DOC_KEYWORDS):
        return "document_retrieval"

    # 4. Current / external facts -> web
    if any(h in q for h in WEB_HINTS):
        return "web_search"

    # 5. Default: docs for how/what-is-project questions, else web
    if re.search(r"\b(how does|how do|what is|explain|describe)\b", q):
        return "document_retrieval"
    return "web_search"
