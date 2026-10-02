import json, uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import text
from .schemas import ChatRequest
from .agent import run_stream
from .db import init_db, SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as e:
        print(f"DB init skipped: {e}")
    yield


app = FastAPI(title="Agentic Research Assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/chat/stream")
async def chat_stream(body: ChatRequest):
    async def gen():
        async for frame in run_stream(body.query, str(body.conversation_id) if body.conversation_id else None):
            yield {"data": frame}
    return EventSourceResponse(gen())

@app.get("/conversations/{cid}/tools")
async def tool_history(cid: uuid.UUID):
    async with SessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT tool_name, tool_input, left(tool_output,500) AS output, latency_ms, created_at "
            "FROM tool_logs WHERE conversation_id=:c ORDER BY created_at DESC LIMIT 50"),
            {"c": str(cid)})).mappings().all()
        return [dict(r) for r in rows]

@app.post("/seed")
async def seed():
    docs = [
        ("LangChain Tool Calling", "LangChain tool-calling agents interleave reasoning with tool invocations...", None),
        ("SSE Streaming", "Server-sent events stream tokens over a single HTTP connection...", None),
    ]
    async with SessionLocal() as s:
        for t, c, u in docs:
            await s.execute(text(
                "INSERT INTO documents(title,content,source_url) VALUES(:t,:c,:u) ON CONFLICT DO NOTHING"),
                {"t": t, "c": c, "u": u})
        await s.commit()
    return {"seeded": len(docs)}
