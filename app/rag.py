import json
import math
import re

from sqlmodel import Session, select

from app.models import DocumentChunk


LEXICAL_RELEVANCE_THRESHOLD = 0.25
MIN_LEXICAL_MATCH_COUNT = 2


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    if len(vector_a) != len(vector_b):
        raise ValueError("embedding dimensions do not match")

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def lexical_overlap(query: str, content: str) -> tuple[float, int]:
    query_terms = _lexical_terms(query)

    if not query_terms:
        return 0.0, 0

    content_terms = _lexical_terms(content)
    matched_term_count = len(query_terms & content_terms)
    return matched_term_count / len(query_terms), matched_term_count


def _lexical_terms(text: str) -> set[str]:
    english_terms = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", text.lower())
    chinese_bigrams = [
        text_run[index : index + 2]
        for text_run in re.findall(r"[\u4e00-\u9fff]+", text)
        for index in range(len(text_run) - 1)
    ]
    return set(english_terms + chinese_bigrams)


def search_chunks(
    query_embedding: list[float],
    chunks,
    top_k: int = 3,
    query: str = "",
) -> list[dict]:
    results = []

    for chunk in chunks:
        if not chunk.embedding_json:
            continue

        chunk_embedding = json.loads(chunk.embedding_json)
        semantic_score = cosine_similarity(query_embedding, chunk_embedding)
        lexical_score, lexical_match_count = lexical_overlap(query, chunk.content)
        rank_score = min(1.0, semantic_score + lexical_score)

        results.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "score": round(semantic_score, 4),
                "lexical_score": round(lexical_score, 4),
                "lexical_match_count": lexical_match_count,
                "rank_score": round(rank_score, 4),
            }
        )

    results.sort(
        key=lambda item: (
            item["lexical_score"] >= LEXICAL_RELEVANCE_THRESHOLD
            and item["lexical_match_count"] >= MIN_LEXICAL_MATCH_COUNT,
            item["lexical_score"],
            item["rank_score"],
        ),
        reverse=True,
    )
    return results[:top_k]


def search_chunks_in_database(
    session: Session,
    query_embedding: list[float],
    owner_id: int,
    top_k: int = 3,
    query: str = "",
    document_id: int | None = None,
) -> list[dict]:
    """Use pgvector in PostgreSQL, with a SQLite fallback for local tests."""
    if session.bind is None or session.bind.dialect.name != "postgresql":
        statement = select(DocumentChunk).where(
            DocumentChunk.owner_id == owner_id,
            DocumentChunk.is_embedded.is_(True),
        )
        if document_id is not None:
            statement = statement.where(DocumentChunk.document_id == document_id)

        return search_chunks(
            query_embedding=query_embedding,
            chunks=session.exec(statement).all(),
            top_k=top_k,
            query=query,
        )

    distance = DocumentChunk.embedding_vector.cosine_distance(query_embedding)
    candidate_limit = max(top_k * 5, top_k)
    statement = (
        select(DocumentChunk, distance.label("distance"))
        .where(
            DocumentChunk.owner_id == owner_id,
            DocumentChunk.is_embedded.is_(True),
            DocumentChunk.embedding_vector.is_not(None),
        )
        .order_by(distance)
        .limit(candidate_limit)
    )
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)

    results = []
    for chunk, cosine_distance in session.exec(statement).all():
        semantic_score = 1.0 - float(cosine_distance)
        lexical_score, lexical_match_count = lexical_overlap(query, chunk.content)
        rank_score = min(1.0, semantic_score + lexical_score)
        results.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "score": round(semantic_score, 4),
                "lexical_score": round(lexical_score, 4),
                "lexical_match_count": lexical_match_count,
                "rank_score": round(rank_score, 4),
            }
        )

    results.sort(
        key=lambda item: (
            item["lexical_score"] >= LEXICAL_RELEVANCE_THRESHOLD
            and item["lexical_match_count"] >= MIN_LEXICAL_MATCH_COUNT,
            item["lexical_score"],
            item["rank_score"],
        ),
        reverse=True,
    )
    return results[:top_k]


def build_context(results: list[dict]) -> str:
    return "\n\n".join(
        f"[{item['reference']}]\n{item['content']}"
        for item in results
    )
