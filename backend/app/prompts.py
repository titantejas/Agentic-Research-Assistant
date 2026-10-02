SYSTEM_PROMPT = """You are a research assistant. Use tools when needed.
Rules:
1. Prefer document_retrieval for project/domain knowledge, web_search for current/external facts.
2. Use sql_query ONLY for read-only SELECTs against whitelisted tables (documents, tool_logs, messages).
3. Use calculator for arithmetic; never do math in your head when numbers are present.
4. Be concise, cite sources as [doc:title] or [web:url].
5. If the answer is in conversation history or cache context, answer directly without tools.
"""

# Prompt optimization: short system prompt + history truncation keeps p95 tokens ~1.2k
# vs ~3.5k naive (all history + verbose instructions).
RESEARCH_TEMPLATE = """History:
{history}

Question: {query}

Think step-by-step. If you need a tool, call it. Otherwise answer directly."""
