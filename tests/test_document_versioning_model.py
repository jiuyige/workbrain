import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeBase,
    Organization,
    User,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def create_document_parents(session: Session):
    user = User(
        username="document-version-user",
        hashed_password="hashed-password",
    )
    organization = Organization(
        name="Document Version Organization",
        slug="document-version-organization",
    )
    session.add_all([user, organization])
    session.flush()

    knowledge_base = KnowledgeBase(
        organization_id=organization.id,
        created_by_user_id=user.id,
        name="Versioned Documents",
    )
    session.add(knowledge_base)
    session.flush()

    return user, organization, knowledge_base


def make_document(
    user: User,
    organization: Organization,
    knowledge_base: KnowledgeBase,
    **overrides,
) -> Document:
    values = {
        "owner_id": user.id,
        "organization_id": organization.id,
        "knowledge_base_id": knowledge_base.id,
        "original_filename": "policy.txt",
        "stored_filename": "stored-policy.txt",
        "file_path": "/tmp/stored-policy.txt",
    }
    values.update(overrides)
    return Document(**values)


def test_document_and_chunk_store_version_boundary_metadata():
    with Session(engine) as session:
        user, organization, knowledge_base = create_document_parents(session)
        document = make_document(
            user,
            organization,
            knowledge_base,
            version=2,
            status=DocumentStatus.READY.value,
        )
        session.add(document)
        session.flush()

        chunk = DocumentChunk(
            owner_id=user.id,
            organization_id=organization.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            document_version=document.version,
            status=document.status,
            chunk_index=0,
            content="versioned policy content",
            char_count=24,
        )
        session.add(chunk)
        session.commit()
        session.refresh(document)
        session.refresh(chunk)

        assert document.version == 2
        assert document.status == DocumentStatus.READY.value
        assert chunk.knowledge_base_id == knowledge_base.id
        assert chunk.document_version == document.version
        assert chunk.status == document.status


def test_document_version_must_be_positive():
    with Session(engine) as session:
        user, organization, knowledge_base = create_document_parents(session)
        session.add(
            make_document(
                user,
                organization,
                knowledge_base,
                version=0,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_document_rejects_unknown_status():
    with Session(engine) as session:
        user, organization, knowledge_base = create_document_parents(session)
        session.add(
            make_document(
                user,
                organization,
                knowledge_base,
                status="unknown",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("document_version", 0),
        ("status", "unknown"),
    ],
)
def test_document_chunk_rejects_invalid_boundary_metadata(
    field_name: str,
    invalid_value: int | str,
):
    with Session(engine) as session:
        user, organization, knowledge_base = create_document_parents(session)
        document = make_document(user, organization, knowledge_base)
        session.add(document)
        session.flush()

        values = {
            "owner_id": user.id,
            "organization_id": organization.id,
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "document_version": document.version,
            "status": DocumentStatus.PROCESSING.value,
            "chunk_index": 0,
            "content": "invalid metadata",
            "char_count": 16,
        }
        values[field_name] = invalid_value
        session.add(DocumentChunk(**values))

        with pytest.raises(IntegrityError):
            session.commit()
