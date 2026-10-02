import time, json
from typing import AsyncGenerator
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_tool_calling_agent, AgentExecutor
from .config import settings
from .tools import TOOLS
from .prompts import SYSTEM_PROMPT
from . import memory_cache as mem

def build_executor():
    llm = ChatOpenAI(model=settings.model_name, temperature=0, streaming=True)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(llm, TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=TOOLS, verbose=False,
                         return_intermediate_steps=True, max_iterations=6)

executor = build_executor()

async def run_stream(query: str, conv_id: str | None) -> AsyncGenerator[str, None]:
    """Yield SSE data frames (json strings). Handles cache + tool trace events."""
    cid = await mem.ensure_conversation(conv_id, query)
    key = mem.cache_key(query, cid)
    cached = await mem.cache_get(key)
    await mem.save_message(cid, "user", query)

    def evt(t: str, d) -> str:
        return json.dumps({"type": t, "conversation_id": cid, "data": d})

    if cached:
        yield evt("cached", True)
        # Stream cached answer as tokens for consistent UI
        for i in range(0, len(cached), 40):
            yield evt("token", cached[i:i+40])
        yield evt("done", cached)
        return

    history = await mem.get_history(cid, settings.max_history_messages)
    chat_history = [(m["role"], m["content"]) for m in history if m["role"] in ("user", "assistant")]

    yield evt("reasoning", "Planning: checking history, deciding tools…")
    full = ""
    # AgentExecutor astream_events gives llm streaming + tool events
    async for ev in executor.astream_events({"input": query, "chat_history": chat_history}, version="v1"):
        kind = ev["event"]
        if kind == "on_chat_model_stream":
            chunk = ev["data"]["chunk"].content
            if chunk:
                full += chunk if isinstance(chunk, str) else ""
                yield evt("token", chunk if isinstance(chunk, str) else "")
        elif kind == "on_tool_start":
            yield evt("tool_start", {"tool": ev["name"], "input": ev["data"].get("input")})
            ev["_t0"] = time.time()
        elif kind == "on_tool_end":
            out = str(ev["data"].get("output"))[:4000]
            yield evt("tool_end", {"tool": ev["name"], "output": out[:800]})
            # persist tool log (message_id linked later; use None-safe)
            try:
                await mem.log_tool(cid, None, ev["name"],
                    ev["data"].get("input", {}), out, int((time.time()-ev.get("_t0", time.time()))*1000))
            except Exception:
                pass

    await mem.save_message(cid, "assistant", full)
    if full.strip():
        try:
            await mem.cache_set(key, query, full)
        except Exception:
            pass
    yield evt("done", full)
