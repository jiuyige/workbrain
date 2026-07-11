from time import perf_counter
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlmodel import Session, select

from app.document_parser import extract_text_from_file, split_text_into_chunks

from app.auth import get_current_user
from app.config import (
    RAG_MAX_CHUNKS_PER_DOCUMENT,
    RAG_MAX_DOCUMENT_CHARS,
    UPLOAD_DIR,
)
from app.database import get_session
from app.models import (
    Document,
    DocumentChunk,
    DocumentProcessLog,
    User,
)

from app.embedding import embedding_to_json, generate_embedding
from app.rag import search_chunks_in_database


router = APIRouter(prefix="/documents", tags=["documents"])

def save_document_process_log(
    session: Session,
    owner_id: int,
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


@router.post("")
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stored_filename = f"{uuid4()}-{file.filename}"
    file_path = UPLOAD_DIR / stored_filename

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    document = Document(
        owner_id=current_user.id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_path=str(file_path),
        content_type=file.content_type,
    )

    session.add(document)
    session.commit()
    session.refresh(document)

    return {
        "message": "upload success",
        "document": {
            "id": document.id,
            "filename": document.original_filename,
            "content_type": document.content_type,
        },
    }


@router.get("")
def list_documents(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    documents = session.exec(
        select(Document).where(Document.owner_id == current_user.id)
    ).all()

    chunks = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.owner_id == current_user.id
        )
    ).all()

    stats_by_document_id = {}

    for chunk in chunks:
        stats = stats_by_document_id.setdefault(
            chunk.document_id,
            {
                "chunk_count": 0,
                "embedded_chunk_count": 0,
            },
        )
        stats["chunk_count"] += 1

        if chunk.is_embedded:
            stats["embedded_chunk_count"] += 1

    result = []

    for document in documents:
        stats = stats_by_document_id.get(
            document.id,
            {
                "chunk_count": 0,
                "embedded_chunk_count": 0,
            },
        )

        is_ready_for_rag = (
            document.is_extracted
            and stats["chunk_count"] > 0
            and stats["embedded_chunk_count"] == stats["chunk_count"]
        )

        result.append(
            {
                "id": document.id,
                "filename": document.original_filename,
                "content_type": document.content_type,
                "is_extracted": document.is_extracted,
                "chunk_count": stats["chunk_count"],
                "embedded_chunk_count": stats["embedded_chunk_count"],
                "is_ready_for_rag": is_ready_for_rag,
            }
        )

    return {"documents": result}


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == current_user.id,
    )
    document = session.exec(statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunk_statement = select(DocumentChunk).where(
        DocumentChunk.document_id == document.id,
        DocumentChunk.owner_id == current_user.id,
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
    )
    document = session.exec(statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    if not document.is_extracted or document.extracted_text is None:
        raise HTTPException(status_code=400, detail="document is not extracted")

    old_chunks_statement = select(DocumentChunk).where(
        DocumentChunk.document_id == document.id,
        DocumentChunk.owner_id == current_user.id,
    )
    old_chunks = session.exec(old_chunks_statement).all()

    for chunk in old_chunks:
        session.delete(chunk)

    chunks = split_text_into_chunks(document.extracted_text)

    saved_chunks = []

    for index, content in enumerate(chunks):
        chunk = DocumentChunk(
            owner_id=current_user.id,
            document_id=document.id,
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
    )
    document = session.exec(document_statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunk_statement = (
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.owner_id == current_user.id,
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
        )
    ).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    started_at = perf_counter()
    text_char_count = 0
    chunk_count = 0
    prepared_chunks = []

    def fail(status_code: int, detail: str):
        session.rollback()

        save_document_process_log(
            session=session,
            owner_id=current_user.id,
            document_id=document.id,
            is_success=False,
            text_char_count=text_char_count,
            chunk_count=chunk_count,
            embedded_count=len(prepared_chunks),
            total_latency_ms=int((perf_counter() - started_at) * 1000),
            error_message=detail,
        )

        raise HTTPException(status_code=status_code, detail=detail)

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
                (content, embedding_to_json(embedding), embedding)
            )
    except RuntimeError as error:
        fail(500, str(error))
    except Exception:
        fail(502, "failed to create embedding")

    old_chunks = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.owner_id == current_user.id,
        )
    ).all()

    for chunk in old_chunks:
        session.delete(chunk)

    document.extracted_text = extracted_text
    document.is_extracted = True
    session.add(document)

    for index, (
        content,
        embedding_json,
        embedding_vector,
    ) in enumerate(prepared_chunks):
        session.add(
            DocumentChunk(
                owner_id=current_user.id,
                document_id=document.id,
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
        session=session,
        owner_id=current_user.id,
        document_id=document.id,
        is_success=True,
        text_char_count=text_char_count,
        chunk_count=chunk_count,
        embedded_count=len(prepared_chunks),
        total_latency_ms=int((perf_counter() - started_at) * 1000),
    )

    return {
        "message": "document processed",
        "document_id": document.id,
        "chunk_count": len(prepared_chunks),
        "embedded_count": len(prepared_chunks),
        "is_ready_for_rag": True,
        "process_log_id": log.id,
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
    )
    document = session.exec(document_statement).first()

    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunk_statement = select(DocumentChunk).where(
        DocumentChunk.document_id == document.id,
        DocumentChunk.owner_id == current_user.id,
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
            session.add(chunk)
            embedded_count += 1

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
    owner_condition = DocumentProcessLog.owner_id == current_user.id

    total = session.exec(
        select(func.count())
        .select_from(DocumentProcessLog)
        .where(owner_condition)
    ).one()

    logs = session.exec(
        select(DocumentProcessLog)
        .where(owner_condition)
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
