import pytest
from sqlmodel import Session

from app.config import OPENAI_EMBEDDING_DIMENSIONS
from app.database import engine
from app.models import DocumentChunk
from app.rag import search_chunks_in_database


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="this test requires PostgreSQL with pgvector",
)


def make_vector(first: float, second: float) -> list[float]:
    vector = [0.0] * OPENAI_EMBEDDING_DIMENSIONS
    vector[0] = first
    vector[1] = second
    return vector


def test_pgvector_returns_most_similar_chunk_first():
    owner_id = 987654
    document_id = 987654
    chunks = [
        DocumentChunk(
            owner_id=owner_id,
            document_id=document_id,
            chunk_index=0,
            content="exact vector match",
            char_count=18,
            embedding_vector=make_vector(1.0, 0.0),
            is_embedded=True,
        ),
        DocumentChunk(
            owner_id=owner_id,
            document_id=document_id,
            chunk_index=1,
            content="medium vector match",
            char_count=19,
            embedding_vector=make_vector(0.8, 0.6),
            is_embedded=True,
        ),
        DocumentChunk(
            owner_id=owner_id,
            document_id=document_id,
            chunk_index=2,
            content="weak vector match",
            char_count=17,
            embedding_vector=make_vector(0.0, 1.0),
            is_embedded=True,
        ),
    ]

    with Session(engine) as session:
        session.add_all(chunks)
        session.flush()

        results = search_chunks_in_database(
            session=session,
            query_embedding=make_vector(1.0, 0.0),
            owner_id=owner_id,
            document_id=document_id,
            query="",
            top_k=3,
        )

        assert len(results) == 3
        assert results[0]["chunk_id"] == chunks[0].id
        assert results[0]["score"] == pytest.approx(1.0, abs=0.0001)

        session.rollback()
