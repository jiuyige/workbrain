from dataclasses import dataclass
from time import perf_counter

from sqlmodel import Session, select

from app.config import RAG_MAX_CHUNKS_PER_DOCUMENT, RAG_MAX_DOCUMENT_CHARS
from app.document_parser import extract_text_from_file, split_text_into_chunks
from app.embedding import embedding_to_json, generate_embedding
from app.models import (
    Document,
    DocumentChunk,
    DocumentProcessLog,
    DocumentStatus,
)

DOCUMENT_PROCESSING_JOB_TYPE = "document_processing"
DOCUMENT_PROCESSING_TASK_NAME = "workbrain.process_document_job"
DOCUMENT_PROCESSING_QUEUE = "document_processing"
DOCUMENT_PROCESSING_DISPATCH_ERROR = "document processing could not be queued"
DOCUMENT_PROCESSING_TASK_ERROR = "document processing failed"
INVALID_DOCUMENT_PROCESSING_JOB_ERROR = "document processing job is invalid"


class DocumentProcessingError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DocumentProcessingResult:
    document_id: int
    text_char_count: int
    chunk_count: int
    embedded_count: int
    process_log_id: int


def save_document_process_log(
    session: Session,
    *,
    owner_id: int,
    organization_id: int,
    document_id: int,
    is_success: bool,
    text_char_count: int,
    chunk_count: int,
    embedded_count: int,
    total_latency_ms: int,
    error_message: str | None = None,
) -> DocumentProcessLog:
    log = DocumentProcessLog(
        owner_id=owner_id,
        organization_id=organization_id,
        document_id=document_id,
        is_success=is_success,
        text_char_count=text_char_count,
        chunk_count=chunk_count,
        embedded_count=embedded_count,
        total_latency_ms=total_latency_ms,
        error_message=error_message,
    )

    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def process_document_record(
    session: Session,
    document: Document,
) -> DocumentProcessingResult:
    if document.id is None:
        raise RuntimeError("document must be persisted before processing")

    document_id = document.id
    owner_id = document.owner_id
    organization_id = document.organization_id
    knowledge_base_id = document.knowledge_base_id
    document_version = document.version
    started_at = perf_counter()
    text_char_count = 0
    chunk_count = 0
    prepared_chunks: list[tuple[str, str, list[float]]] = []

    def fail(status_code: int, detail: str):
        session.rollback()
        save_document_process_log(
            session,
            owner_id=owner_id,
            organization_id=organization_id,
            document_id=document_id,
            is_success=False,
            text_char_count=text_char_count,
            chunk_count=chunk_count,
            embedded_count=len(prepared_chunks),
            total_latency_ms=int((perf_counter() - started_at) * 1000),
            error_message=detail,
        )
        raise DocumentProcessingError(status_code, detail)

    try:
        extracted_text = extract_text_from_file(document.file_path)
    except FileNotFoundError:
        fail(404, "file not found")
    except ValueError as error:
        fail(400, str(error))

    text_char_count = len(extracted_text)

    if text_char_count > RAG_MAX_DOCUMENT_CHARS:
        fail(413, "document exceeds maximum character count")

    try:
        chunk_contents = split_text_into_chunks(extracted_text)
    except ValueError as error:
        fail(400, str(error))

    chunk_count = len(chunk_contents)

    if not chunk_contents:
        fail(400, "document has no text chunks")

    if chunk_count > RAG_MAX_CHUNKS_PER_DOCUMENT:
        fail(413, "document exceeds maximum chunk count")

    try:
        for content in chunk_contents:
            embedding = generate_embedding(content)
            prepared_chunks.append(
                (
                    content,
                    embedding_to_json(embedding),
                    embedding,
                )
            )
    except Exception:
        fail(502, "failed to create embedding")

    old_chunks = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.owner_id == owner_id,
        )
    ).all()

    for chunk in old_chunks:
        session.delete(chunk)

    document.extracted_text = extracted_text
    document.is_extracted = True
    document.status = DocumentStatus.READY.value
    session.add(document)

    for index, (
        content,
        embedding_json,
        embedding_vector,
    ) in enumerate(prepared_chunks):
        session.add(
            DocumentChunk(
                owner_id=owner_id,
                organization_id=organization_id,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                document_version=document_version,
                status=DocumentStatus.READY.value,
                chunk_index=index,
                content=content,
                char_count=len(content),
                embedding_json=embedding_json,
                embedding_vector=embedding_vector,
                is_embedded=True,
            )
        )

    try:
        session.commit()
    except Exception:
        fail(500, "failed to save processed document")

    log = save_document_process_log(
        session,
        owner_id=owner_id,
        organization_id=organization_id,
        document_id=document_id,
        is_success=True,
        text_char_count=text_char_count,
        chunk_count=chunk_count,
        embedded_count=len(prepared_chunks),
        total_latency_ms=int((perf_counter() - started_at) * 1000),
    )

    return DocumentProcessingResult(
        document_id=document_id,
        text_char_count=text_char_count,
        chunk_count=chunk_count,
        embedded_count=len(prepared_chunks),
        process_log_id=log.id,
    )
