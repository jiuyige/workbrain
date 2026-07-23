import pytest
from sqlmodel import Session

from app.config import OPENAI_EMBEDDING_DIMENSIONS
from app.database import engine
from app.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeBase,
    Organization,
    User,
)
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
    with Session(engine) as session:
        user = User(
            username="pgvector-integration-user",
            hashed_password="unused",
        )
        organization = Organization(
            name="Pgvector Integration Organization",
            slug="pgvector-integration-organization",
        )
        session.add_all([user, organization])
        session.flush()

        knowledge_base = KnowledgeBase(
            organization_id=organization.id,
            created_by_user_id=user.id,
            name="Pgvector Integration Knowledge Base",
        )
        session.add(knowledge_base)
        session.flush()

        document = Document(
            owner_id=user.id,
            organization_id=organization.id,
            knowledge_base_id=knowledge_base.id,
            status=DocumentStatus.PUBLISHED.value,
            original_filename="vectors.txt",
            stored_filename="vectors.txt",
            file_path="/tmp/vectors.txt",
        )
        session.add(document)
        session.flush()

        chunks = [
            DocumentChunk(
                owner_id=user.id,
                organization_id=organization.id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                document_version=document.version,
                status=DocumentStatus.PUBLISHED.value,
                chunk_index=0,
                content="exact vector match",
                char_count=18,
                embedding_vector=make_vector(1.0, 0.0),
                is_embedded=True,
            ),
            DocumentChunk(
                owner_id=user.id,
                organization_id=organization.id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                document_version=document.version,
                status=DocumentStatus.PUBLISHED.value,
                chunk_index=1,
                content="medium vector match",
                char_count=19,
                embedding_vector=make_vector(0.8, 0.6),
                is_embedded=True,
            ),
            DocumentChunk(
                owner_id=user.id,
                organization_id=organization.id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                document_version=document.version,
                status=DocumentStatus.PUBLISHED.value,
                chunk_index=2,
                content="weak vector match",
                char_count=17,
                embedding_vector=make_vector(0.0, 1.0),
                is_embedded=True,
            ),
        ]
        session.add_all(chunks)
        session.flush()

        results = search_chunks_in_database(
            session=session,
            query_embedding=make_vector(1.0, 0.0),
            owner_id=user.id,
            document_id=document.id,
            query="",
            top_k=3,
        )

        assert len(results) == 3
        assert results[0]["chunk_id"] == chunks[0].id
        assert results[0]["score"] == pytest.approx(1.0, abs=0.0001)

        knowledge_base_results = search_chunks_in_database(
            session=session,
            query_embedding=make_vector(1.0, 0.0),
            owner_id=None,
            organization_id=organization.id,
            knowledge_base_id=knowledge_base.id,
            query="",
            top_k=3,
        )

        assert len(knowledge_base_results) == 3
        assert knowledge_base_results[0]["chunk_id"] == chunks[0].id
        assert knowledge_base_results[0]["score"] == pytest.approx(
            1.0,
            abs=0.0001,
        )

        session.rollback()
