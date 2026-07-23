from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlmodel import Session, select

from app.background_jobs import mark_background_job_dispatch_failed
from app.config import UPLOAD_DIR
from app.context import (
    OrganizationContext,
    get_current_organization_context,
)
from app.database import get_session
from app.document_processing import (
    DOCUMENT_PROCESSING_DISPATCH_ERROR,
    DOCUMENT_PROCESSING_JOB_TYPE,
)
from app.models import (
    BackgroundJob,
    Document,
    DocumentChunk,
    DocumentLifecycleEvent,
    DocumentProcessLog,
    DocumentStatus,
    KnowledgeBase,
)
from app.policies import require_organization_approver
from app.routers.documents import (
    archive_document_record,
    dispatch_document_processing_job,
    publish_document_record,
    sanitize_upload_filename,
    save_upload_with_limit,
    validate_text_file_content,
    validate_upload_content_type,
)

router = APIRouter(
    prefix="/knowledge-bases/{knowledge_base_id}/documents",
    tags=["knowledge-base-documents"],
)


def get_context_knowledge_base(
    session: Session,
    *,
    knowledge_base_id: int,
    organization_id: int,
) -> KnowledgeBase:
    knowledge_base = session.exec(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.organization_id == organization_id,
        )
    ).first()

    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="knowledge base not found")

    return knowledge_base


def get_context_document(
    session: Session,
    *,
    document_id: int,
    knowledge_base_id: int,
    organization_id: int,
) -> Document:
    document = session.exec(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.knowledge_base_id == knowledge_base_id,
        )
    ).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    return document


@router.post("", status_code=202)
def upload_knowledge_base_document(
    knowledge_base_id: int,
    file: UploadFile = File(...),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    safe_filename = sanitize_upload_filename(file.filename)
    normalized_content_type = validate_upload_content_type(
        safe_filename,
        file.content_type,
    )
    stored_filename = f"{uuid4()}-{safe_filename}"
    file_path = UPLOAD_DIR / stored_filename

    try:
        save_upload_with_limit(file, file_path)
        validate_text_file_content(file_path)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    document = Document(
        owner_id=context.membership.user_id,
        organization_id=context.organization.id,
        knowledge_base_id=knowledge_base.id,
        original_filename=safe_filename,
        stored_filename=stored_filename,
        file_path=str(file_path),
        content_type=normalized_content_type,
    )
    task_id = str(uuid4())
    job = BackgroundJob(
        organization_id=context.organization.id,
        created_by_user_id=context.membership.user_id,
        job_type=DOCUMENT_PROCESSING_JOB_TYPE,
        celery_task_id=task_id,
    )
    session.add_all([document, job])

    try:
        session.commit()
    except Exception:
        session.rollback()
        file_path.unlink(missing_ok=True)
        raise

    session.refresh(document)
    session.refresh(job)

    try:
        dispatch_document_processing_job(
            job_id=job.id,
            document_id=document.id,
            task_id=task_id,
        )
    except Exception:
        mark_background_job_dispatch_failed(
            session,
            job.id,
            safe_error_message=DOCUMENT_PROCESSING_DISPATCH_ERROR,
        )
        raise HTTPException(
            status_code=503,
            detail=DOCUMENT_PROCESSING_DISPATCH_ERROR,
        ) from None

    return {
        "message": "upload success",
        "document": {
            "id": document.id,
            "owner_id": document.owner_id,
            "organization_id": document.organization_id,
            "knowledge_base_id": document.knowledge_base_id,
            "filename": document.original_filename,
            "content_type": document.content_type,
            "version": document.version,
            "status": document.status,
        },
        "job": {
            "id": job.id,
            "status": job.status,
        },
    }


@router.get("")
def list_knowledge_base_documents(
    knowledge_base_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    documents = session.exec(
        select(Document)
        .where(
            Document.organization_id == context.organization.id,
            Document.knowledge_base_id == knowledge_base.id,
        )
        .order_by(Document.id)
    ).all()
    chunks = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.organization_id == context.organization.id,
            DocumentChunk.knowledge_base_id == knowledge_base.id,
        )
    ).all()
    stats_by_document_id: dict[int, dict[str, int]] = {}

    for chunk in chunks:
        stats = stats_by_document_id.setdefault(
            chunk.document_id,
            {
                "chunk_count": 0,
                "embedded_chunk_count": 0,
                "published_chunk_count": 0,
            },
        )
        stats["chunk_count"] += 1

        if chunk.is_embedded:
            stats["embedded_chunk_count"] += 1

        if chunk.status == DocumentStatus.PUBLISHED.value:
            stats["published_chunk_count"] += 1

    result = []

    for document in documents:
        stats = stats_by_document_id.get(
            document.id,
            {
                "chunk_count": 0,
                "embedded_chunk_count": 0,
                "published_chunk_count": 0,
            },
        )
        has_ready_chunks = (
            document.is_extracted
            and stats["chunk_count"] > 0
            and stats["embedded_chunk_count"] == stats["chunk_count"]
        )
        result.append(
            {
                "id": document.id,
                "owner_id": document.owner_id,
                "organization_id": document.organization_id,
                "knowledge_base_id": document.knowledge_base_id,
                "filename": document.original_filename,
                "content_type": document.content_type,
                "version": document.version,
                "status": document.status,
                "chunk_count": stats["chunk_count"],
                "embedded_chunk_count": stats["embedded_chunk_count"],
                "published_chunk_count": stats["published_chunk_count"],
                "is_ready_for_publish": (
                    document.status == DocumentStatus.READY.value and has_ready_chunks
                ),
                "is_ready_for_rag": (
                    document.status == DocumentStatus.PUBLISHED.value
                    and has_ready_chunks
                    and stats["published_chunk_count"] == stats["chunk_count"]
                ),
            }
        )

    return {
        "knowledge_base_id": knowledge_base.id,
        "documents": result,
    }


@router.get("/{document_id}/content")
def get_team_document_content(
    knowledge_base_id: int,
    document_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    document = get_context_document(
        session,
        document_id=document_id,
        knowledge_base_id=knowledge_base.id,
        organization_id=context.organization.id,
    )

    if not document.is_extracted:
        raise HTTPException(status_code=400, detail="document is not extracted")

    return {
        "document": {
            "id": document.id,
            "owner_id": document.owner_id,
            "organization_id": document.organization_id,
            "knowledge_base_id": document.knowledge_base_id,
            "filename": document.original_filename,
            "content": document.extracted_text,
            "version": document.version,
            "status": document.status,
        }
    }


@router.get("/{document_id}/chunks")
def list_team_document_chunks(
    knowledge_base_id: int,
    document_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    document = get_context_document(
        session,
        document_id=document_id,
        knowledge_base_id=knowledge_base.id,
        organization_id=context.organization.id,
    )
    chunks = session.exec(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.organization_id == context.organization.id,
            DocumentChunk.knowledge_base_id == knowledge_base.id,
        )
        .order_by(DocumentChunk.chunk_index)
    ).all()

    return {
        "document": {
            "id": document.id,
            "filename": document.original_filename,
            "version": document.version,
            "status": document.status,
        },
        "chunks": [
            {
                "id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "char_count": chunk.char_count,
                "document_version": chunk.document_version,
                "status": chunk.status,
            }
            for chunk in chunks
        ],
    }


@router.get("/{document_id}/lifecycle-events")
def list_team_document_lifecycle_events(
    knowledge_base_id: int,
    document_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    document = get_context_document(
        session,
        document_id=document_id,
        knowledge_base_id=knowledge_base.id,
        organization_id=context.organization.id,
    )
    event_conditions = (
        DocumentLifecycleEvent.document_id == document.id,
        DocumentLifecycleEvent.organization_id == context.organization.id,
    )
    total = session.exec(
        select(func.count())
        .select_from(DocumentLifecycleEvent)
        .where(*event_conditions)
    ).one()
    events = session.exec(
        select(DocumentLifecycleEvent)
        .where(*event_conditions)
        .order_by(
            DocumentLifecycleEvent.created_at.desc(),
            DocumentLifecycleEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "document_id": document.id,
        "events": [
            {
                "id": event.id,
                "actor_user_id": event.actor_user_id,
                "action": event.action,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "document_version": event.document_version,
                "created_at": event.created_at,
            }
            for event in events
        ],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "returned": len(events),
        },
    }


@router.get("/{document_id}/process-logs")
def list_team_document_process_logs(
    knowledge_base_id: int,
    document_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    document = get_context_document(
        session,
        document_id=document_id,
        knowledge_base_id=knowledge_base.id,
        organization_id=context.organization.id,
    )
    log_conditions = (
        DocumentProcessLog.document_id == document.id,
        DocumentProcessLog.organization_id == context.organization.id,
    )
    total = session.exec(
        select(func.count()).select_from(DocumentProcessLog).where(*log_conditions)
    ).one()
    logs = session.exec(
        select(DocumentProcessLog)
        .where(*log_conditions)
        .order_by(
            DocumentProcessLog.created_at.desc(),
            DocumentProcessLog.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "document_id": document.id,
        "logs": [
            {
                "id": log.id,
                "owner_id": log.owner_id,
                "is_success": log.is_success,
                "text_char_count": log.text_char_count,
                "chunk_count": log.chunk_count,
                "embedded_count": log.embedded_count,
                "total_latency_ms": log.total_latency_ms,
                "error_message": log.error_message,
                "created_at": log.created_at,
            }
            for log in logs
        ],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "returned": len(logs),
        },
    }


@router.post("/{document_id}/publish")
def publish_team_document(
    knowledge_base_id: int,
    document_id: int,
    context: OrganizationContext = Depends(require_organization_approver),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    document = get_context_document(
        session,
        document_id=document_id,
        knowledge_base_id=knowledge_base.id,
        organization_id=context.organization.id,
    )
    published_chunk_count = publish_document_record(
        session,
        document=document,
        actor_user_id=context.membership.user_id,
    )

    return {
        "message": "document published",
        "document_id": document.id,
        "status": document.status,
        "published_chunk_count": published_chunk_count,
    }


@router.post("/{document_id}/archive")
def archive_team_document(
    knowledge_base_id: int,
    document_id: int,
    context: OrganizationContext = Depends(require_organization_approver),
    session: Session = Depends(get_session),
):
    knowledge_base = get_context_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    document = get_context_document(
        session,
        document_id=document_id,
        knowledge_base_id=knowledge_base.id,
        organization_id=context.organization.id,
    )
    archived_chunk_count = archive_document_record(
        session,
        document=document,
        actor_user_id=context.membership.user_id,
    )

    return {
        "message": "document archived",
        "document_id": document.id,
        "status": document.status,
        "archived_chunk_count": archived_chunk_count,
    }
