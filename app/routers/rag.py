import json
from time import perf_counter

from app.models import Document, RAGQueryLog, User


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.embedding import generate_embedding
from app.llm import answer_with_documents
from app.rag import (
    LEXICAL_RELEVANCE_THRESHOLD,
    MIN_LEXICAL_MATCH_COUNT,
    build_context,
    search_chunks_in_database,
)

from app.config import RAG_MIN_SCORE

router = APIRouter(prefix="/rag", tags=["rag"])


class RAGAskRequest(BaseModel):
    question: str
    document_id: int | None = None


def save_rag_query_log(
    session: Session,
    owner_id: int,
    question: str,
    top_score: float | None,
    matched_count: int,
    used_llm: bool,
    source_chunk_ids: list[int],
    total_latency_ms: int,
) -> RAGQueryLog:
    log = RAGQueryLog(
        owner_id=owner_id,
        question=question,
        top_score=top_score,
        matched_count=matched_count,
        used_llm=used_llm,
        source_chunk_ids_json=json.dumps(source_chunk_ids),
        total_latency_ms=total_latency_ms,
    )

    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.post("/ask")
def ask_rag(
    body: RAGAskRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    started_at = perf_counter()

    question = body.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="question cannot be empty")


    if body.document_id is not None:
        document = session.exec(
            select(Document).where(
                Document.id == body.document_id,
                Document.owner_id == current_user.id,
            )
        ).first()
    
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
    
    query_embedding = generate_embedding(question)

    candidate_results = search_chunks_in_database(
        session=session,
        query_embedding=query_embedding,
        owner_id=current_user.id,
        top_k=3,
        query=question,
        document_id=body.document_id,
    )

    grounded_results = [
        item
        for item in candidate_results
        if item["lexical_score"] >= LEXICAL_RELEVANCE_THRESHOLD
        and item["lexical_match_count"] >= MIN_LEXICAL_MATCH_COUNT
    ]
    top_score = grounded_results[0]["rank_score"] if grounded_results else None

    results = [
        item
        for item in grounded_results
        if item["rank_score"] >= RAG_MIN_SCORE
    ]

    if not results:
        log = save_rag_query_log(
            session=session,
            owner_id=current_user.id,
            question=question,
            top_score=top_score,
            matched_count=len(results),
            used_llm=False,
            source_chunk_ids=[item["chunk_id"] for item in results],
            total_latency_ms=int((perf_counter() - started_at) * 1000),
        )

        return {
            "answer": "资料库中没有足够相关的内容，暂时无法回答这个问题。",
            "sources": [],
            "rag_query_log_id": log.id,
            "retrieval": {
                "top_score": top_score,
                "min_score": RAG_MIN_SCORE,
                "matched_count": 0,
            },
        }

    for index, item in enumerate(results, start=1):
        item["reference"] = f"S{index}"

    context = build_context(results)
    answer = answer_with_documents(question, context)

    log = save_rag_query_log(
        session=session,
        owner_id=current_user.id,
        question=question,
        top_score=top_score,
        matched_count=len(results),
        used_llm=True,
        source_chunk_ids=[item["chunk_id"] for item in results],
        total_latency_ms=int((perf_counter() - started_at) * 1000),
    )

    return {
        "answer": answer,
        "sources": [
            {
                "reference": f"[{item['reference']}]",
                "document_id": item["document_id"],
                "chunk_id": item["chunk_id"],
                "chunk_index": item["chunk_index"],
                "score": item["rank_score"],
                "semantic_score": item["score"],
                "lexical_score": item["lexical_score"],
                "preview": item["content"][:120],
            }
            for item in results
        ],
        "rag_query_log_id": log.id,
        "retrieval": {
            "top_score": top_score,
            "min_score": RAG_MIN_SCORE,
            "matched_count": len(results),
        },
    }


@router.get("/logs")
def list_rag_logs(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    logs = session.exec(
        select(RAGQueryLog)
        .where(RAGQueryLog.owner_id == current_user.id)
        .order_by(RAGQueryLog.created_at.desc())
        .limit(20)
    ).all()

    return [
        {
            "id": log.id,
            "question": log.question,
            "top_score": log.top_score,
            "matched_count": log.matched_count,
            "used_llm": log.used_llm,
            "source_chunk_ids": json.loads(log.source_chunk_ids_json),
            "total_latency_ms": log.total_latency_ms,
            "created_at": log.created_at,
        }
        for log in logs
    ]
