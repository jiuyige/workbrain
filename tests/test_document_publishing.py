import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.models import (
    Document,
    DocumentChunk,
    DocumentLifecycleEvent,
    DocumentStatus,
    User,
)
from app.rag import search_chunks_in_database
from app.routers import rag as rag_router
from main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    with Session(engine) as session:
        yield session


@pytest.fixture
def client():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    previous_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    if previous_override is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous_override


def register_and_login(
    client: TestClient,
    username: str,
) -> tuple[dict[str, str], int]:
    password = "document-publishing-password"
    register_response = client.post(
        "/users/register",
        json={"username": username, "password": password},
    )
    assert register_response.status_code == 200

    login_response = client.post(
        "/users/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).one()
        user_id = user.id

    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}, user_id


def create_document_with_chunk(
    owner_id: int,
    *,
    document_status: str = DocumentStatus.READY.value,
    chunk_status: str = DocumentStatus.READY.value,
    is_embedded: bool = True,
    content: str = "WorkBrain 发布流程",
) -> tuple[int, int]:
    with Session(engine) as session:
        document = Document(
            owner_id=owner_id,
            status=document_status,
            original_filename="publish.md",
            stored_filename="publish.md",
            file_path="publish.md",
            extracted_text=content,
            is_extracted=True,
        )
        session.add(document)
        session.flush()

        chunk = DocumentChunk(
            owner_id=owner_id,
            document_id=document.id,
            document_version=document.version,
            status=chunk_status,
            chunk_index=0,
            content=content,
            char_count=len(content),
            embedding_json=json.dumps([1.0, 0.0]) if is_embedded else None,
            embedding_vector=[1.0, 0.0] if is_embedded else None,
            is_embedded=is_embedded,
        )
        session.add(chunk)
        session.commit()
        session.refresh(document)
        session.refresh(chunk)

        return document.id, chunk.id


def test_publish_document_requires_authentication(client):
    response = client.post("/documents/1/publish")

    assert response.status_code == 401


def test_ready_document_can_be_published_with_all_chunks(client):
    headers, user_id = register_and_login(client, "document-publisher")
    document_id, chunk_id = create_document_with_chunk(user_id)

    response = client.post(
        f"/documents/{document_id}/publish",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "document published",
        "document_id": document_id,
        "status": DocumentStatus.PUBLISHED.value,
        "published_chunk_count": 1,
    }

    with Session(engine) as session:
        assert session.get(Document, document_id).status == (
            DocumentStatus.PUBLISHED.value
        )
        assert session.get(DocumentChunk, chunk_id).status == (
            DocumentStatus.PUBLISHED.value
        )


@pytest.mark.parametrize(
    ("document_status", "chunk_status", "is_embedded", "expected_message"),
    [
        (
            DocumentStatus.UPLOADED.value,
            DocumentStatus.PROCESSING.value,
            False,
            "document must be ready before publishing",
        ),
        (
            DocumentStatus.READY.value,
            DocumentStatus.READY.value,
            False,
            "document chunks are not ready for publishing",
        ),
    ],
)
def test_unready_document_cannot_be_published(
    client,
    document_status,
    chunk_status,
    is_embedded,
    expected_message,
):
    headers, user_id = register_and_login(
        client,
        f"unready-publisher-{document_status}-{is_embedded}",
    )
    document_id, _ = create_document_with_chunk(
        user_id,
        document_status=document_status,
        chunk_status=chunk_status,
        is_embedded=is_embedded,
    )

    response = client.post(
        f"/documents/{document_id}/publish",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["message"] == expected_message


def test_publish_hides_another_users_document(client):
    _, owner_id = register_and_login(client, "publication-owner")
    outsider_headers, _ = register_and_login(client, "publication-outsider")
    document_id, _ = create_document_with_chunk(owner_id)

    response = client.post(
        f"/documents/{document_id}/publish",
        headers=outsider_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"


def test_publishing_an_already_published_document_is_idempotent(client):
    headers, user_id = register_and_login(client, "idempotent-publisher")
    document_id, _ = create_document_with_chunk(user_id)

    first_response = client.post(
        f"/documents/{document_id}/publish",
        headers=headers,
    )
    second_response = client.post(
        f"/documents/{document_id}/publish",
        headers=headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == DocumentStatus.PUBLISHED.value
    assert second_response.json()["published_chunk_count"] == 1


def test_database_search_only_returns_published_documents(client):
    _, user_id = register_and_login(client, "published-search-user")
    ready_document_id, _ = create_document_with_chunk(
        user_id,
        content="ready content",
    )
    published_document_id, published_chunk_id = create_document_with_chunk(
        user_id,
        document_status=DocumentStatus.PUBLISHED.value,
        chunk_status=DocumentStatus.PUBLISHED.value,
        content="published content",
    )

    with Session(engine) as session:
        results = search_chunks_in_database(
            session=session,
            query_embedding=[1.0, 0.0],
            owner_id=user_id,
            top_k=10,
        )

    assert [result["chunk_id"] for result in results] == [published_chunk_id]
    assert all(result["document_id"] != ready_document_id for result in results)
    assert results[0]["document_id"] == published_document_id


def test_rag_rejects_explicit_unpublished_document_before_embedding(
    client,
    monkeypatch,
):
    headers, user_id = register_and_login(client, "unpublished-rag-user")
    document_id, _ = create_document_with_chunk(user_id)

    def fail_if_called(_question):
        raise AssertionError("embedding must not run for an unpublished document")

    monkeypatch.setattr(rag_router, "generate_embedding", fail_if_called)

    response = client.post(
        "/rag/ask",
        headers=headers,
        json={
            "question": "发布了吗？",
            "document_id": document_id,
        },
    )

    assert response.status_code == 409
    assert response.json()["message"] == "document is not published"


def test_archive_document_requires_authentication(client):
    response = client.post("/documents/1/archive")

    assert response.status_code == 401


def test_published_document_can_be_archived_and_leaves_search(client):
    headers, user_id = register_and_login(client, "document-archiver")
    document_id, chunk_id = create_document_with_chunk(
        user_id,
        document_status=DocumentStatus.PUBLISHED.value,
        chunk_status=DocumentStatus.PUBLISHED.value,
    )

    with Session(engine) as session:
        before_archive = search_chunks_in_database(
            session=session,
            query_embedding=[1.0, 0.0],
            owner_id=user_id,
            top_k=10,
        )

    response = client.post(
        f"/documents/{document_id}/archive",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "document archived",
        "document_id": document_id,
        "status": DocumentStatus.ARCHIVED.value,
        "archived_chunk_count": 1,
    }
    assert [result["chunk_id"] for result in before_archive] == [chunk_id]

    with Session(engine) as session:
        document = session.get(Document, document_id)
        chunk = session.get(DocumentChunk, chunk_id)
        after_archive = search_chunks_in_database(
            session=session,
            query_embedding=[1.0, 0.0],
            owner_id=user_id,
            top_k=10,
        )

        assert document.status == DocumentStatus.ARCHIVED.value
        assert chunk.status == DocumentStatus.ARCHIVED.value
        assert after_archive == []


def test_ready_document_cannot_be_archived(client):
    headers, user_id = register_and_login(client, "unpublished-archiver")
    document_id, chunk_id = create_document_with_chunk(user_id)

    response = client.post(
        f"/documents/{document_id}/archive",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["message"] == ("only a published document can be archived")

    with Session(engine) as session:
        assert session.get(Document, document_id).status == (DocumentStatus.READY.value)
        assert session.get(DocumentChunk, chunk_id).status == (
            DocumentStatus.READY.value
        )


def test_archive_hides_another_users_document(client):
    _, owner_id = register_and_login(client, "archive-owner")
    outsider_headers, _ = register_and_login(client, "archive-outsider")
    document_id, _ = create_document_with_chunk(
        owner_id,
        document_status=DocumentStatus.PUBLISHED.value,
        chunk_status=DocumentStatus.PUBLISHED.value,
    )

    response = client.post(
        f"/documents/{document_id}/archive",
        headers=outsider_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"


def test_archiving_an_already_archived_document_is_idempotent(client):
    headers, user_id = register_and_login(client, "idempotent-archiver")
    document_id, _ = create_document_with_chunk(
        user_id,
        document_status=DocumentStatus.PUBLISHED.value,
        chunk_status=DocumentStatus.PUBLISHED.value,
    )

    first_response = client.post(
        f"/documents/{document_id}/archive",
        headers=headers,
    )
    second_response = client.post(
        f"/documents/{document_id}/archive",
        headers=headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == DocumentStatus.ARCHIVED.value
    assert second_response.json()["archived_chunk_count"] == 1


def test_publish_and_archive_create_lifecycle_history(client):
    headers, user_id = register_and_login(client, "lifecycle-history-user")
    document_id, _ = create_document_with_chunk(user_id)

    publish_response = client.post(
        f"/documents/{document_id}/publish",
        headers=headers,
    )
    archive_response = client.post(
        f"/documents/{document_id}/archive",
        headers=headers,
    )
    history_response = client.get(
        f"/documents/{document_id}/lifecycle-events",
        headers=headers,
    )

    assert publish_response.status_code == 200
    assert archive_response.status_code == 200
    assert history_response.status_code == 200

    payload = history_response.json()
    assert [event["action"] for event in payload["events"]] == [
        "archive",
        "publish",
    ]
    assert payload["events"][0]["from_status"] == "published"
    assert payload["events"][0]["to_status"] == "archived"
    assert payload["events"][1]["from_status"] == "ready"
    assert payload["events"][1]["to_status"] == "published"
    assert all(event["actor_user_id"] == user_id for event in payload["events"])
    assert all(event["document_version"] == 1 for event in payload["events"])
    assert payload["pagination"] == {
        "offset": 0,
        "limit": 20,
        "total": 2,
        "returned": 2,
    }


def test_idempotent_requests_are_visible_in_paginated_history(client):
    headers, user_id = register_and_login(client, "lifecycle-pagination-user")
    document_id, _ = create_document_with_chunk(user_id)

    client.post(f"/documents/{document_id}/publish", headers=headers)
    client.post(f"/documents/{document_id}/publish", headers=headers)
    client.post(f"/documents/{document_id}/archive", headers=headers)

    response = client.get(
        f"/documents/{document_id}/lifecycle-events?offset=1&limit=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["pagination"] == {
        "offset": 1,
        "limit": 1,
        "total": 3,
        "returned": 1,
    }
    assert response.json()["events"][0]["action"] == "publish"
    assert response.json()["events"][0]["from_status"] == "published"
    assert response.json()["events"][0]["to_status"] == "published"


def test_lifecycle_history_requires_authentication(client):
    response = client.get("/documents/1/lifecycle-events")

    assert response.status_code == 401


def test_lifecycle_history_hides_another_users_document(client):
    _, owner_id = register_and_login(client, "lifecycle-owner")
    outsider_headers, _ = register_and_login(client, "lifecycle-outsider")
    document_id, _ = create_document_with_chunk(owner_id)

    response = client.get(
        f"/documents/{document_id}/lifecycle-events",
        headers=outsider_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"


def test_failed_transition_does_not_create_lifecycle_event(client):
    headers, user_id = register_and_login(client, "failed-lifecycle-user")
    document_id, _ = create_document_with_chunk(
        user_id,
        document_status=DocumentStatus.UPLOADED.value,
        chunk_status=DocumentStatus.PROCESSING.value,
        is_embedded=False,
    )

    response = client.post(
        f"/documents/{document_id}/publish",
        headers=headers,
    )

    assert response.status_code == 409

    with Session(engine) as session:
        events = session.exec(
            select(DocumentLifecycleEvent).where(
                DocumentLifecycleEvent.document_id == document_id
            )
        ).all()

        assert events == []
