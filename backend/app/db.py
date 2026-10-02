from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from .config import settings

engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with SessionLocal() as s:
        yield s

async def init_db():
    # Tables created via schema.sql; this validates connectivity
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
