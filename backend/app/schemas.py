from pydantic import BaseModel
from typing import Any, Optional
import uuid

class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[uuid.UUID] = None

class SSEEvent(BaseModel):
    type: str  # token | reasoning | tool_start | tool_end | done | cached
    data: Any
