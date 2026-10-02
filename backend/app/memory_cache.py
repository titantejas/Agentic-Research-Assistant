import hashlib, json
from datetime import datetime, timedelta
from sqlalchemy import text
from .db import SessionLocal
from .config import settings

def cache_key(query: str, conversation_id: str | None) -> str:
    h = hashlib.sha256(f"{query.strip().lower()}|{conversation_id or 'none'}".encode()).hexdigest()[:32]
    return h

async def cache_get(key: str) -> str | None:
    async with SessionLocal() as s:
        r = (await s.execute(text(
            "SELECT response FROM response_cache WHERE cache_key=:k AND expires_at > now()"),
            {"k": key})).scalar()
        return r

async def cache_set(key: str, query: str, response: str):
    async with SessionLocal() as s:
        await s.execute(text(
            "INSERT INTO response_cache(cache_key,query,response,expires_at) "
            "VALUES(:k,:q,:r, now() + (:ttl || ' seconds')::interval) "
            "ON CONFLICT(cache_key) DO UPDATE SET response=:r, expires_at=now()+(:ttl || ' seconds')::interval"),
            {"k": key, "q": query, "r": response, "ttl": str(settings.cache_ttl_seconds)})
        await s.commit()

async def get_history(conversation_id: str, limit: int) -> list[dict]:
    async with SessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT role, content FROM messages WHERE conversation_id=:c "
            "ORDER BY created_at DESC LIMIT :l"), {"c": conversation_id, "l": limit})).mappings().all()
        return list(reversed([dict(r) for r in rows]))

async def save_message(conv_id, role, content, reasoning=None):
    async with SessionLocal() as s:
        r = (await s.execute(text(
            "INSERT INTO messages(conversation_id,role,content,reasoning) "
            "VALUES(:c,:r,:x,:z) RETURNING id"),
            {"c": conv_id, "r": role, "x": content, "z": reasoning})).scalar()
        await s.commit()
        return str(r)

async def log_tool(conv_id, msg_id, name, inp, out, ms: int):
    async with SessionLocal() as s:
        await s.execute(text(
            "INSERT INTO tool_logs(conversation_id,message_id,tool_name,tool_input,tool_output,latency_ms) "
            "VALUES(:c,:m,:n,:i,:o,:ms)"),
            {"c": conv_id, "m": msg_id, "n": name, "i": json.dumps(inp), "o": out[:4000], "ms": ms})
        await s.commit()

async def ensure_conversation(conv_id: str | None, first_query: str) -> str:
    async with SessionLocal() as s:
        if conv_id:
            exists = (await s.execute(text("SELECT 1 FROM conversations WHERE id=:c"), {"c": conv_id})).scalar()
            if exists:
                return conv_id
        r = (await s.execute(text(
            "INSERT INTO conversations(title) VALUES(:t) RETURNING id"),
            {"t": first_query[:60]})).scalar()
        await s.commit()
        return str(r)
