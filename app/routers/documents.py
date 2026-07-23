import re
from codecs import getincrementaldecoder
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlmodel import Session, select

from app.auth import get_current_user
from app.background_jobs import mark_background_job_dispatch_failed
from app.celery_app import celery_app
from app.config import UPLOAD_DIR, UPLOAD_MAX_BYTES
from app.database import get_session
from app.document_parser import extract_text_from_file, split_text_into_chunks
from app.document_processing import (
    DOCUMENT_PROCESSING_DISPATCH_ERROR,
    DOCUMENT_PROCESSING_JOB_TYPE,
    DOCUMENT_PROCESSING_QUEUE,
    DOCUMENT_PROCESSING_TASK_NAME,
    DocumentProcessingError,
    process_document_record,
)
from app.embedding import embedding_to_json, generate_embedding
from app.models import (
    LEGACY_KNOWLEDGE_BASE_ID,
    LEGACY_ORGANIZATION_ID,
    BackgroundJob,
    Document,
    DocumentChunk,
    DocumentLifecycleAction,
    DocumentLifecycleEvent,
    DocumentProcessLog,
    DocumentStatus,
    User,
)
from app.rag import search_chunks_in_database

router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
SAFE_FILENAME_MAX_BYTES = 180
SUPPORTED_UPLOAD_CONTENT_TYPES = {
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
}
BINARY_FILE_SIGNATURES = (
    b"%PDF-",
    b"PK\x03\x04",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    b"\x7fELF",
    b"MZ",
)
ALLOWED_TEXT_CONTROL_CHARACTERS = frozenset({"\n", "\r", "\t"})


def add_document_lifecycle_event(
    session: Session,
    *,
    document: Document,
    actor_user_id: int,
    action: DocumentLifecycleAction,
    from_status: str,
) -> None:
    session.add(
        DocumentLifecycleEvent(
            organization_id=document.organization_id,
            document_id=document.id,
            actor_user_id=actor_user_id,
            action=action.value,
            from_status=from_status,
            to_status=document.status,
            document_version=document.version,
        )
    )


def publish_document_record(
    session: Session,
    *,
    document: Document,
    actor_user_id: int,
) -> int:
    if document.status not in {
        DocumentStatus.READY.value,
        DocumentStatus.PUBLISHED.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="document must be ready before publishing",
        )

    chunks = session.exec(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).all()
    chunks_are_ready = bool(chunks) and all(
        chunk.document_version == document.version
        and chunk.status
        in {
            DocumentStatus.READY.value,
            DocumentStatus.PUBLISHED.value,
        }
        and chunk.is_embedded
        and chunk.embedding_json is not None
        and chunk.embedding_vector is not None
        for chunk in chunks
    )

    if not chunks_are_ready:
        raise HTTPException(
            status_code=409,
            detail="document chunks are not ready for publishing",
        )

    from_status = document.status
    document.status = DocumentStatus.PUBLISHED.value
    session.add(document)

    for chunk in chunks:
        chunk.status = DocumentStatus.PUBLISHED.value
        session.add(chunk)

    add_document_lifecycle_event(
        session,
        document=document,
        actor_user_id=actor_user_id,
        action=DocumentLifecycleAction.PUBLISH,
        from_status=from_status,
    )
    session.commit()
    return len(chunks)


def archive_document_record(
    session: Session,
    *,
    document: Document,
    actor_user_id: int,
) -> int:
    if document.status not in {
        DocumentStatus.PUBLISHED.value,
        DocumentStatus.ARCHIVED.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="only a published document can be archived",
        )

    chunks = session.exec(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).all()
    from_status = document.status
    document.status = DocumentStatus.ARCHIVED.value
    session.add(document)

    for chunk in chunks:
        chunk.status = DocumentStatus.ARCHIVED.value
        session.add(chunk)

    add_document_lifecycle_event(
        session,
        document=document,
        actor_user_id=actor_user_id,
        action=DocumentLifecycleAction.ARCHIVE,
        from_status=from_status,
    )
    session.commit()
    return len(chunks)


def _truncate_filename_bytes(filename: str) -> str:
    encoded_filename = filename.encode("utf-8")

    if len(encoded_filename) <= SAFE_FILENAME_MAX_BYTES:
        return filename

    suffix = Path(filename).suffix
    encoded_suffix = suffix.encode("utf-8")

    if len(encoded_suffix) >= SAFE_FILENAME_MAX_BYTES:
        return encoded_filename[:SAFE_FILENAME_MAX_BYTES].decode(
            "utf-8",
            errors="ignore",
        )

    stem = filename[: -len(suffix)] if suffix else filename
    stem_byte_limit = SAFE_FILENAME_MAX_BYTES - len(encoded_suffix)
    safe_stem = stem.encode("utf-8")[:stem_byte_limit].decode(
        "utf-8",
        errors="ignore",
    )
    return f"{safe_stem.rstrip(' .')}{suffix}"


def sanitize_upload_filename(filename: str | None) -> str:
    if filename is None:
        raise HTTPException(status_code=400, detail="invalid filename")

    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    sanitized = re.sub(r"[^\w.\- ]", "_", basename)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    sanitized = _truncate_filename_bytes(sanitized)

    if not sanitized:
        raise HTTPException(status_code=400, detail="invalid filename")

    return sanitized


def save_upload_with_limit(file: UploadFile, file_path: Path) -> int:
    total_bytes = 0

    try:
        with file_path.open("wb") as buffer:
            while chunk := file.file.read(UPLOAD_READ_CHUNK_BYTES):
                total_bytes += len(chunk)

                if total_bytes > UPLOAD_MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="file exceeds maximum upload size",
                    )

                buffer.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    return total_bytes


def validate_upload_content_type(
    filename: str,
    content_type: str | None,
) -> str:
    extension = Path(filename).suffix.lower()
    allowed_content_types = SUPPORTED_UPLOAD_CONTENT_TYPES.get(extension)

    if allowed_content_types is None:
        raise HTTPException(
            status_code=415,
            detail="unsupported file extension",
        )

    normalized_content_type = (content_type or "").partition(";")[0].strip().lower()

    if normalized_content_type not in allowed_content_types:
        raise HTTPException(
            status_code=415,
            detail="content type does not match file extension",
        )

    return normalized_content_type


def validate_text_file_content(file_path: Path) -> None:
    decoder = getincrementaldecoder("utf-8")(errors="strict")
    has_visible_text = False
    is_first_chunk = True

    try:
        with file_path.open("rb") as file_buffer:
            while chunk := file_buffer.read(UPLOAD_READ_CHUNK_BYTES):
                if is_first_chunk:
                    is_first_chunk = False

                    if any(
                        chunk.startswith(signature)
                        for signature in BINARY_FILE_SIGNATURES
                    ):
                        raise HTTPException(
                            status_code=415,
                            detail="file content does not match text format",
                        )

                decoded_chunk = decoder.decode(chunk)

                if any(
                    not character.isprintable()
                    and character not in ALLOWED_TEXT_CONTROL_CHARACTERS
                    for character in decoded_chunk
                ):
                    raise HTTPException(
                        status_code=415,
                        detail="file content does not match text format",
                    )

                if decoded_chunk.strip():
                    has_visible_text = True

            final_text = decoder.decode(b"", final=True)
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=415,
            detail="file content does not match text format",
        ) from error

    if final_text.strip():
        has_visible_text = True

    if not has_visible_text:
        raise HTTPException(
            status_code=415,
            detail="file content is empty",
        )


def dispatch_document_processing_job(
    *,
    job_id: int,
    document_id: int,
    task_id: str,
) -> None:
    celery_app.send_task(
        DOCUMENT_PROCESSING_TASK_NAME,
        args=[job_id, document_id],
        task_id=task_id,
        queue=DOCUMENT_PROCESSING_QUEUE,
    )


@router.post("", status_code=202)
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
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
        owner_id=current_user.id,
        original_filename=safe_filename,
        stored_filename=stored_filename,
        file_path=str(file_path),
        content_type=normalized_content_type,
    )
    task_id = str(uuid4())
    job = BackgroundJob(
        organization_id=document.organization_id,
        created_by_user_id=current_user.id,
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
            "filename": document.original_filename,
            "content_type": document.content_type,
            "knowledge_base_id": document.knowledge_base_id,
            "version": document.version,
            "status": document.status,
        },
        "job": {
            "id": job.id,
            "status": job.status,
        },
    }


@router.get("")
def list_documents(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    documents = session.exec(
        select(Document).where(
            Document.owner_id == current_user.id,
            Document.organization_id == LEGACY_ORGANIZATION_ID,
        )
    ).all()

    chunks = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.owner_id == current_user.id,
            DocumentChunk.organization_id == LEGACY_ORGANIZATION_ID,
        )
    ).all()

    stats_by_document_id = {}

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
        is_ready_for_publish = (
            document.status == DocumentStatus.READY.value and has_ready_chunks
        )
        is_ready_for_rag = (
            document.status == DocumentStatus.PUBLISHED.value
            and has_ready_chunks
            and stats["published_chunk_count"] == stats["chunk_count"]
        )

        result.append(
            {
                "id": document.id,
                "filename": document.original_filename,
                "content_type": document.content_type,
                "is_extracted": document.is_extracted,
                "knowledge_base_id": document.knowledge_base_id,
                "version": document.version,
                "status": document.status,
                "chunk_count": stats["chunk_count"],
                "embedded_chunk_count": stats["embedded_chunk_count"],
                "published_chunk_count": stats["published_chunk_count"],
                "is_ready_for_publish": is_ready_for_publish,
                "is_ready_for_rag": is_ready_for_rag,
            }
        )

    return {"documents": result}


@router.post("/{document_id}/publish")
def publish_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    document = session.exec(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
            Document.organization_id == LEGACY_ORGANIZATION_ID,
        )
    ).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    published_chunk_count = publish_document_record(
        session,
        document=document,
        actor_user_id=current_user.id,
    )

    return {
        "message": "document published",
        "document_id": document.id,
        "status": document.status,
        "published_chunk_count": published_chunk_count,
    }


@router.post("/{document_id}/archive")
def archive_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    document = session.exec(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
            Document.organization_id == LEGACY_ORGANIZATION_ID,
        )
    ).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    archived_chunk_count = archive_document_record(
        session,
        document=document,
        actor_user_id=current_user.id,
    )

    return {
        "message": "document archived",
        "document_id": document.id,
        "status": document.status,
        "archived_chunk_count": archived_chunk_count,
    }


@router.get("/{document_id}/lifecycle-events")
def list_document_lifecycle_events(
    document_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    document = session.exec(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
            Document.organization_id == LEGACY_ORGANIZATION_ID,
        )
    ).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    event_condition = DocumentLifecycleEvent.document_id == document.id
    total = session.exec(
        select(func.count()).select_from(DocumentLifecycleEvent).where(event_condition)
    ).one()
    events = session.exec(
        select(DocumentLifecycleEvent)
        .where(event_condition)
        .order_by(
            DocumentLifecycleEvent.created_at.desc(),
            DocumentLifecycleEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "events": [
            {
                "id": event.id,
                "document_id": event.document_id,
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


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
        Document.organization_id == LEGACY_ORGANIZATION_ID,
    )
    document = session.exec(statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunk_statement = select(DocumentChunk).where(
        DocumentChunk.document_id == document.id,
        DocumentChunk.owner_id == current_user.id,
        DocumentChunk.organization_id == LEGACY_ORGANIZATION_ID,
    )
    chunks = session.exec(chunk_statement).all()

    for chunk in chunks:
        session.delete(chunk)

    file_path = Path(document.file_path)

    if file_path.exists():
        file_path.unlink()

    session.delete(document)
    session.commit()

    return {
        "message": "delete success",
        "deleted_chunk_count": len(chunks),
    }


@router.post("/{document_id}/extract")
def extract_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
        Document.organization_id == LEGACY_ORGANIZATION_ID,
    )
    document = session.exec(statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    try:
        extracted_text = extract_text_from_file(document.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file not found")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    document.extracted_text = extracted_text
    document.is_extracted = True
    document.status = DocumentStatus.PROCESSING.value

    session.add(document)
    session.commit()
    session.refresh(document)

    return {
        "message": "extract success",
        "document": {
            "id": document.id,
            "filename": document.original_filename,
            "text_length": len(extracted_text),
            "is_extracted": document.is_extracted,
            "status": document.status,
        },
    }


@router.get("/{document_id}/content")
def get_document_content(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
        Document.organization_id == LEGACY_ORGANIZATION_ID,
    )
    document = session.exec(statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    if not document.is_extracted:
        raise HTTPException(status_code=400, detail="document is not extracted")

    return {
        "document": {
            "id": document.id,
            "filename": document.original_filename,
            "content": document.extracted_text,
        }
    }


@router.post("/{document_id}/chunks")
def create_document_chunks(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
        Document.organization_id == LEGACY_ORGANIZATION_ID,
    )
    document = session.exec(statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    if not document.is_extracted or document.extracted_text is None:
        raise HTTPException(status_code=400, detail="document is not extracted")

    old_chunks_statement = select(DocumentChunk).where(
        DocumentChunk.document_id == document.id,
        DocumentChunk.owner_id == current_user.id,
        DocumentChunk.organization_id == LEGACY_ORGANIZATION_ID,
    )
    old_chunks = session.exec(old_chunks_statement).all()

    for chunk in old_chunks:
        session.delete(chunk)

    chunks = split_text_into_chunks(document.extracted_text)

    saved_chunks = []
    document.status = DocumentStatus.PROCESSING.value
    session.add(document)

    for index, content in enumerate(chunks):
        chunk = DocumentChunk(
            owner_id=current_user.id,
            organization_id=document.organization_id,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            document_version=document.version,
            status=DocumentStatus.PROCESSING.value,
            chunk_index=index,
            content=content,
            char_count=len(content),
        )
        session.add(chunk)
        saved_chunks.append(chunk)

    session.commit()

    for chunk in saved_chunks:
        session.refresh(chunk)

    return {
        "message": "chunks created",
        "document_id": document.id,
        "chunk_count": len(saved_chunks),
        "chunks": [
            {
                "id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "char_count": chunk.char_count,
                "preview": chunk.content[:100],
                "document_version": chunk.document_version,
                "status": chunk.status,
            }
            for chunk in saved_chunks
        ],
    }


@router.get("/{document_id}/chunks")
def list_document_chunks(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    document_statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
        Document.organization_id == LEGACY_ORGANIZATION_ID,
    )
    document = session.exec(document_statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunk_statement = (
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.owner_id == current_user.id,
            DocumentChunk.organization_id == LEGACY_ORGANIZATION_ID,
        )
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = session.exec(chunk_statement).all()

    return {
        "document": {
            "id": document.id,
            "filename": document.original_filename,
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


@router.post("/{document_id}/process")
def process_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    document = session.exec(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == current_user.id,
            Document.organization_id == LEGACY_ORGANIZATION_ID,
        )
    ).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    try:
        result = process_document_record(session, document)
    except DocumentProcessingError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    return {
        "message": "document processed",
        "document_id": result.document_id,
        "chunk_count": result.chunk_count,
        "embedded_count": result.embedded_count,
        "is_ready_for_publish": True,
        "is_ready_for_rag": False,
        "process_log_id": result.process_log_id,
    }


@router.post("/{document_id}/embeddings")
def create_document_embeddings(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    document_statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
        Document.organization_id == LEGACY_ORGANIZATION_ID,
    )
    document = session.exec(document_statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunk_statement = select(DocumentChunk).where(
        DocumentChunk.document_id == document.id,
        DocumentChunk.owner_id == current_user.id,
        DocumentChunk.organization_id == LEGACY_ORGANIZATION_ID,
    )
    chunks = session.exec(chunk_statement).all()

    if len(chunks) == 0:
        raise HTTPException(status_code=400, detail="document has no chunks")

    embedded_count = 0

    try:
        for chunk in chunks:
            embedding = generate_embedding(chunk.content)
            chunk.embedding_json = embedding_to_json(embedding)
            chunk.embedding_vector = embedding
            chunk.is_embedded = True
            chunk.status = DocumentStatus.READY.value
            session.add(chunk)
            embedded_count += 1

        document.status = DocumentStatus.READY.value
        session.add(document)
        session.commit()
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except Exception:
        raise HTTPException(status_code=502, detail="failed to create embedding")

    return {
        "message": "embeddings created",
        "document_id": document.id,
        "chunk_count": len(chunks),
        "embedded_count": embedded_count,
    }


@router.post("/search")
def search_document_chunks(
    query: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = query.strip()

    if not query:
        raise HTTPException(status_code=400, detail="query cannot be empty")

    query_embedding = generate_embedding(query)

    results = search_chunks_in_database(
        session=session,
        query_embedding=query_embedding,
        owner_id=current_user.id,
        organization_id=LEGACY_ORGANIZATION_ID,
        knowledge_base_id=LEGACY_KNOWLEDGE_BASE_ID,
        top_k=3,
        query=query,
    )

    if not results:
        raise HTTPException(
            status_code=400,
            detail="no embedded document chunks found",
        )

    return {
        "query": query,
        "results": results,
    }


@router.get("/process-logs")
def list_document_process_logs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    log_conditions = (
        DocumentProcessLog.owner_id == current_user.id,
        DocumentProcessLog.organization_id == LEGACY_ORGANIZATION_ID,
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
        "logs": [
            {
                "id": log.id,
                "document_id": log.document_id,
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
