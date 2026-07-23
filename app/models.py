from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import JSON, CheckConstraint, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.config import OPENAI_EMBEDDING_DIMENSIONS

LEGACY_ORGANIZATION_ID = 999_999_999
LEGACY_ORGANIZATION_NAME = "WorkBrain Legacy Workspace"
LEGACY_ORGANIZATION_SLUG = "workbrain-legacy-workspace"
LEGACY_KNOWLEDGE_BASE_ID = 999_999_999
LEGACY_KNOWLEDGE_BASE_NAME = "Legacy Documents"


class MembershipRole(str, Enum):
    MEMBER = "member"
    APPROVER = "approver"
    ADMIN = "admin"


class BackgroundJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class DocumentLifecycleAction(str, Enum):
    PUBLISH = "publish"
    ARCHIVE = "archive"


class ServiceRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ServiceRequestAction(str, Enum):
    CREATE = "create"
    APPROVE = "approve"
    REJECT = "reject"


class Organization(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 100",
            name="ck_organization_name_length",
        ),
        CheckConstraint(
            "length(slug) BETWEEN 3 AND 63",
            name="ck_organization_slug_length",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    slug: str = Field(max_length=63, index=True, unique=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str


class Membership(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_membership_organization_user",
        ),
        CheckConstraint(
            "role IN ('member', 'approver', 'admin')",
            name="ck_membership_role",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(
        foreign_key="organization.id",
        index=True,
    )
    user_id: int = Field(
        foreign_key="user.id",
        index=True,
    )
    role: str = Field(
        default=MembershipRole.MEMBER.value,
        max_length=20,
    )
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeBase(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_knowledgebase_organization_name",
        ),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 100",
            name="ck_knowledgebase_name_length",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(
        foreign_key="organization.id",
        index=True,
    )
    created_by_user_id: int = Field(
        foreign_key="user.id",
        index=True,
    )
    name: str = Field(max_length=100)
    description: str | None = Field(
        default=None,
        max_length=1000,
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class ServiceCatalogItem(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_servicecatalogitem_organization_name",
        ),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 100",
            name="ck_servicecatalogitem_name_length",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(
        foreign_key="organization.id",
        index=True,
    )
    created_by_user_id: int = Field(
        foreign_key="user.id",
        index=True,
    )
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class ServiceRequest(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_servicerequest_status",
        ),
        CheckConstraint(
            """
            (
                status = 'pending'
                AND decided_by_user_id IS NULL
                AND decided_at IS NULL
                AND decision_reason IS NULL
            )
            OR (
                status = 'approved'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NULL
            )
            OR (
                status = 'rejected'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NOT NULL
                AND length(trim(decision_reason)) > 0
            )
            """,
            name="ck_servicerequest_decision_state",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", index=True)
    requester_user_id: int = Field(foreign_key="user.id", index=True)
    service_catalog_item_id: int = Field(
        foreign_key="servicecatalogitem.id",
        index=True,
    )
    title: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    status: str = Field(
        default=ServiceRequestStatus.PENDING.value,
        max_length=20,
        index=True,
    )
    decided_by_user_id: int | None = Field(
        default=None,
        foreign_key="user.id",
        index=True,
    )
    decision_reason: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    decided_at: datetime | None = None


class ServiceRequestEvent(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "action IN ('create', 'approve', 'reject')",
            name="ck_servicerequestevent_action",
        ),
        CheckConstraint(
            """
            (
                action = 'create'
                AND from_status IS NULL
                AND to_status = 'pending'
                AND reason IS NULL
            )
            OR (
                action = 'approve'
                AND from_status = 'pending'
                AND to_status = 'approved'
                AND reason IS NULL
            )
            OR (
                action = 'reject'
                AND from_status = 'pending'
                AND to_status = 'rejected'
                AND reason IS NOT NULL
                AND length(trim(reason)) > 0
            )
            """,
            name="ck_servicerequestevent_transition",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", index=True)
    service_request_id: int = Field(foreign_key="servicerequest.id", index=True)
    actor_user_id: int = Field(foreign_key="user.id", index=True)
    action: str = Field(max_length=20)
    from_status: str | None = Field(default=None, max_length=20)
    to_status: str = Field(max_length=20)
    reason: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class ServiceRequestConfirmation(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            """
            (
                service_request_id IS NULL
                AND confirmed_at IS NULL
            )
            OR (
                service_request_id IS NOT NULL
                AND confirmed_at IS NOT NULL
            )
            """,
            name="ck_servicerequestconfirmation_consumption_state",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", index=True)
    requester_user_id: int = Field(foreign_key="user.id", index=True)
    service_catalog_item_id: int = Field(
        foreign_key="servicecatalogitem.id",
        index=True,
    )
    confirmation_token_hash: str = Field(
        max_length=64,
        index=True,
        unique=True,
    )
    title: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    expires_at: datetime = Field(index=True)
    service_request_id: int | None = Field(
        default=None,
        foreign_key="servicerequest.id",
        index=True,
        unique=True,
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    confirmed_at: datetime | None = None


class BackgroundJob(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "length(trim(job_type)) BETWEEN 1 AND 50",
            name="ck_backgroundjob_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_backgroundjob_status",
        ),
        CheckConstraint(
            """
            (
                status = 'queued'
                AND started_at IS NULL
                AND finished_at IS NULL
            )
            OR (
                status = 'running'
                AND started_at IS NOT NULL
                AND finished_at IS NULL
            )
            OR (
                status IN ('succeeded', 'failed')
                AND started_at IS NOT NULL
                AND finished_at IS NOT NULL
            )
            OR (
                status = 'cancelled'
                AND finished_at IS NOT NULL
            )
            """,
            name="ck_backgroundjob_status_timestamps",
        ),
        CheckConstraint(
            """
            (
                status = 'failed'
                AND error_message IS NOT NULL
                AND length(trim(error_message)) > 0
            )
            OR (
                status != 'failed'
                AND error_message IS NULL
            )
            """,
            name="ck_backgroundjob_error_message",
        ),
        CheckConstraint(
            """
            (started_at IS NULL OR started_at >= created_at)
            AND (finished_at IS NULL OR finished_at >= created_at)
            AND (
                started_at IS NULL
                OR finished_at IS NULL
                OR finished_at >= started_at
            )
            """,
            name="ck_backgroundjob_timestamp_order",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_backgroundjob_attempt_count_nonnegative",
        ),
        CheckConstraint(
            """
            (status = 'queued' OR next_retry_at IS NULL)
            AND (next_retry_at IS NULL OR next_retry_at >= created_at)
            """,
            name="ck_backgroundjob_retry_state",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(
        foreign_key="organization.id",
        index=True,
    )
    created_by_user_id: int = Field(
        foreign_key="user.id",
        index=True,
    )
    job_type: str = Field(max_length=50)
    status: str = Field(
        default=BackgroundJobStatus.QUEUED.value,
        max_length=20,
    )
    celery_task_id: str | None = Field(
        default=None,
        max_length=255,
        index=True,
        unique=True,
    )
    error_message: str | None = Field(
        default=None,
        max_length=1000,
    )
    attempt_count: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Document(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "version >= 1",
            name="ck_document_version_positive",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'published', 'archived')",
            name="ck_document_status",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    knowledge_base_id: int = Field(
        default=LEGACY_KNOWLEDGE_BASE_ID,
        foreign_key="knowledgebase.id",
        index=True,
    )
    version: int = 1
    status: str = Field(
        default=DocumentStatus.UPLOADED.value,
        max_length=20,
        index=True,
    )
    original_filename: str
    stored_filename: str
    file_path: str
    content_type: Optional[str] = None
    extracted_text: Optional[str] = None
    is_extracted: bool = False


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    user_message: str
    assistant_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LLMCallLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
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
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    title: str
    priority: str = "medium"
    is_done: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCallLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    tool_name: str
    arguments_json: str
    result_json: str = "{}"
    is_success: bool = True
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentTrace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    user_message: str
    final_action: str = ""
    final_reply: str = ""
    tool_call_count: int = 0
    is_success: bool = True
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentChunk(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "document_version >= 1",
            name="ck_documentchunk_document_version_positive",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'published', 'archived')",
            name="ck_documentchunk_status",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    knowledge_base_id: int = Field(
        default=LEGACY_KNOWLEDGE_BASE_ID,
        foreign_key="knowledgebase.id",
        index=True,
    )
    document_id: int = Field(
        foreign_key="document.id",
        index=True,
    )
    document_version: int = 1
    status: str = Field(
        default=DocumentStatus.PROCESSING.value,
        max_length=20,
        index=True,
    )
    chunk_index: int
    content: str
    char_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    embedding_json: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
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
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    knowledge_base_id: int | None = Field(
        default=None,
        foreign_key="knowledgebase.id",
        index=True,
    )
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
    organization_id: int = Field(
        default=LEGACY_ORGANIZATION_ID,
        foreign_key="organization.id",
        index=True,
    )
    document_id: int = Field(index=True)
    is_success: bool = False
    text_char_count: int = 0
    chunk_count: int = 0
    embedded_count: int = 0
    total_latency_ms: int = 0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentLifecycleEvent(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "document_version >= 1",
            name="ck_documentlifecycleevent_version_positive",
        ),
        CheckConstraint(
            """
            (
                action = 'publish'
                AND from_status IN ('ready', 'published')
                AND to_status = 'published'
            )
            OR (
                action = 'archive'
                AND from_status IN ('published', 'archived')
                AND to_status = 'archived'
            )
            """,
            name="ck_documentlifecycleevent_transition",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(
        foreign_key="organization.id",
        index=True,
    )
    document_id: int = Field(index=True)
    actor_user_id: int = Field(
        foreign_key="user.id",
        index=True,
    )
    action: str = Field(max_length=20)
    from_status: str = Field(max_length=20)
    to_status: str = Field(max_length=20)
    document_version: int
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
