from typing import Optional

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel
from datetime import datetime, timezone

from app.config import OPENAI_EMBEDDING_DIMENSIONS


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    original_filename: str
    stored_filename: str
    file_path: str
    content_type: Optional[str] = None
    extracted_text: Optional[str] = None
    is_extracted: bool = False

class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    user_message: str
    assistant_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class LLMCallLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    estimated_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Todo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    title: str
    priority: str = "medium"
    is_done: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCallLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    tool_name: str
    arguments_json: str
    result_json: str = "{}"
    is_success: bool = True
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentTrace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    user_message: str
    final_action: str = ""
    final_reply: str = ""
    tool_call_count: int = 0
    is_success: bool = True
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentChunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    document_id: int = Field(index=True)
    chunk_index: int
    content: str
    char_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    embedding_json: Optional[str] = None
    embedding_vector: Optional[list[float]] = Field(
        default=None,
        sa_column=Column(
            VECTOR(OPENAI_EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite"),
            nullable=True,
        ),
    )
    is_embedded: bool = False


class RAGQueryLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    question: str
    top_score: float | None = None
    matched_count: int = 0
    used_llm: bool = False
    source_chunk_ids_json: str = "[]"
    total_latency_ms: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentProcessLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    document_id: int = Field(index=True)
    is_success: bool = False
    text_char_count: int = 0
    chunk_count: int = 0
    embedded_count: int = 0
    total_latency_ms: int = 0
    error_message: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
