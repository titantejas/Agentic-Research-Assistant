from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str = ""
    tavily_api_key: str = ""
    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5432/agent_db"
    cache_ttl_seconds: int = 3600
    model_name: str = "gpt-4o-mini"
    max_history_messages: int = 12

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
