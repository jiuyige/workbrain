from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
from app.models import (
    BackgroundJob,
    Document,
    DocumentChunk,
    DocumentLifecycleEvent,
    DocumentProcessLog,
    DocumentStatus,
    KnowledgeBase,
    User,
)
from app.routers import documents as documents_router
from app.routers import knowledge_base_documents as kb_documents_router
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
def client(monkeypatch, tmp_path):
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    previous_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(kb_documents_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        kb_documents_router,
        "dispatch_document_processing_job",
        lambda **_kwargs: None,
    )

    with TestClient(app) as test_client:
        yield test_client

    if previous_override is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous_override


def register_and_login(client: TestClient, username: str) -> dict[str, str]:
    password = "knowledge-base-document-password"
    assert (
        client.post(
            "/users/register",
            json={"username": username, "password": password},
        ).status_code
        == 200
    )
    login_response = client.post(
        "/users/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200
    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


def create_organization_and_knowledge_base(
    client: TestClient,
    *,
    username: str,
    slug: str,
) -> tuple[dict[str, str], int, int]:
    headers = register_and_login(client, username)
    organization_response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": f"{username} Organization",
            "slug": slug,
        },
    )
    assert organization_response.status_code == 201
    organization_id = organization_response.json()["id"]
    headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    knowledge_base_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": f"{username} Knowledge Base"},
    )
    assert knowledge_base_response.status_code == 201

    return headers, organization_id, knowledge_base_response.json()["id"]


def test_knowledge_base_document_endpoints_require_authentication(client):
    upload_response = client.post(
        "/knowledge-bases/1/documents",
        headers={ORGANIZATION_ID_HEADER: "1"},
        files={"file": ("policy.md", b"policy", "text/markdown")},
    )
    list_response = client.get(
        "/knowledge-bases/1/documents",
        headers={ORGANIZATION_ID_HEADER: "1"},
    )

    assert upload_response.status_code == 401
    assert list_response.status_code == 401


def test_organization_context_is_required_for_knowledge_base_documents(client):
    headers = register_and_login(client, "missing-context-document-user")

    response = client.get(
        "/knowledge-bases/1/documents",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["message"] == "organization context is required"


def test_upload_assigns_explicit_organization_and_knowledge_base(
    client,
    tmp_path,
):
    headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="enterprise-document-uploader",
            slug="enterprise-document-upload",
        )
    )

    response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={
            "file": (
                "security-policy.md",
                "企业安全制度。".encode(),
                "text/markdown",
            )
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["document"]["organization_id"] == organization_id
    assert payload["document"]["knowledge_base_id"] == knowledge_base_id
    assert payload["document"]["status"] == "uploaded"
    assert payload["job"]["status"] == "queued"

    with Session(engine) as session:
        document = session.get(Document, payload["document"]["id"])
        job = session.get(BackgroundJob, payload["job"]["id"])

        assert document.organization_id == organization_id
        assert document.knowledge_base_id == knowledge_base_id
        assert Path(document.file_path).parent == tmp_path
        assert job.organization_id == organization_id
        assert job.created_by_user_id == document.owner_id


def test_cross_organization_knowledge_base_is_hidden_before_file_save(
    client,
    tmp_path,
):
    first_headers, _, _ = create_organization_and_knowledge_base(
        client,
        username="first-document-organization-user",
        slug="first-document-organization",
    )
    _, _, second_knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="second-document-organization-user",
        slug="second-document-organization",
    )

    response = client.post(
        f"/knowledge-bases/{second_knowledge_base_id}/documents",
        headers=first_headers,
        files={"file": ("hidden.md", b"hidden", "text/markdown")},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "knowledge base not found"
    assert list(tmp_path.iterdir()) == []

    with Session(engine) as session:
        assert session.exec(select(Document)).all() == []
        assert session.exec(select(BackgroundJob)).all() == []


def test_organization_member_can_list_team_documents(client):
    admin_headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="team-document-admin",
            slug="team-document-organization",
        )
    )
    member_headers = register_and_login(client, "team-document-member")

    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "team-document-member",
            "role": "member",
        },
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=admin_headers,
        files={"file": ("team.md", b"team knowledge", "text/markdown")},
    )
    assert upload_response.status_code == 202

    response = client.get(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=member_headers,
    )

    assert response.status_code == 200
    assert len(response.json()["documents"]) == 1
    assert (
        response.json()["documents"][0]["id"]
        == (upload_response.json()["document"]["id"])
    )

    with Session(engine) as session:
        uploader = session.get(User, response.json()["documents"][0]["owner_id"])
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)

        assert uploader.username == "team-document-admin"
        assert knowledge_base.organization_id == organization_id


def make_document_ready(document_id: int) -> int:
    with Session(engine) as session:
        document = session.get(Document, document_id)
        document.status = DocumentStatus.READY.value
        document.extracted_text = "企业发布审批内容。"
        document.is_extracted = True
        session.add(document)
        chunk = DocumentChunk(
            owner_id=document.owner_id,
            organization_id=document.organization_id,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            document_version=document.version,
            status=DocumentStatus.READY.value,
            chunk_index=0,
            content=document.extracted_text,
            char_count=len(document.extracted_text),
            embedding_json="[1.0, 0.0]",
            embedding_vector=[1.0, 0.0],
            is_embedded=True,
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        return chunk.id


def test_admin_can_publish_and_approver_can_archive_members_document(client):
    admin_headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="document-approval-admin",
            slug="document-approval-organization",
        )
    )
    member_headers = register_and_login(client, "document-approval-member")
    approver_headers = register_and_login(client, "document-approval-approver")

    for username, role in [
        ("document-approval-member", "member"),
        ("document-approval-approver", "approver"),
    ]:
        response = client.post(
            "/organizations/members",
            headers=admin_headers,
            json={"username": username, "role": role},
        )
        assert response.status_code == 201

    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)
    approver_headers[ORGANIZATION_ID_HEADER] = str(organization_id)
    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=member_headers,
        files={"file": ("approval.md", b"approval content", "text/markdown")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]
    chunk_id = make_document_ready(document_id)

    publish_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/publish",
        headers=admin_headers,
    )
    member_archive_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/archive",
        headers=member_headers,
    )
    legacy_archive_response = client.post(
        f"/documents/{document_id}/archive",
        headers=member_headers,
    )
    archive_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/archive",
        headers=approver_headers,
    )

    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == DocumentStatus.PUBLISHED.value
    assert member_archive_response.status_code == 403
    assert member_archive_response.json()["message"] == (
        "organization approver access required"
    )
    assert legacy_archive_response.status_code == 404
    assert legacy_archive_response.json()["message"] == "document not found"
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == DocumentStatus.ARCHIVED.value

    with Session(engine) as session:
        admin = session.exec(
            select(User).where(User.username == "document-approval-admin")
        ).one()
        approver = session.exec(
            select(User).where(User.username == "document-approval-approver")
        ).one()
        document = session.get(Document, document_id)
        chunk = session.get(DocumentChunk, chunk_id)
        events = session.exec(
            select(DocumentLifecycleEvent)
            .where(DocumentLifecycleEvent.document_id == document_id)
            .order_by(DocumentLifecycleEvent.id)
        ).all()

        assert document.status == DocumentStatus.ARCHIVED.value
        assert chunk.status == DocumentStatus.ARCHIVED.value
        assert [event.action for event in events] == ["publish", "archive"]
        assert [event.actor_user_id for event in events] == [
            admin.id,
            approver.id,
        ]


def test_member_cannot_publish_team_document(client):
    admin_headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="member-publish-admin",
            slug="member-publish-organization",
        )
    )
    member_headers = register_and_login(client, "blocked-document-publisher")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "blocked-document-publisher", "role": "member"},
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)
    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=member_headers,
        files={"file": ("blocked.md", b"blocked content", "text/markdown")},
    )
    document_id = upload_response.json()["document"]["id"]
    make_document_ready(document_id)

    response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/publish",
        headers=member_headers,
    )
    legacy_response = client.post(
        f"/documents/{document_id}/publish",
        headers=member_headers,
    )

    assert response.status_code == 403
    assert response.json()["message"] == "organization approver access required"
    assert legacy_response.status_code == 404
    assert legacy_response.json()["message"] == "document not found"

    with Session(engine) as session:
        assert session.get(Document, document_id).status == DocumentStatus.READY.value
        assert session.exec(select(DocumentLifecycleEvent)).all() == []


def test_team_publish_hides_document_from_another_knowledge_base(client):
    headers, organization_id, first_knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="document-boundary-admin",
            slug="document-boundary-organization",
        )
    )
    second_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "Second Document Boundary Knowledge Base"},
    )
    assert second_response.status_code == 201
    second_knowledge_base_id = second_response.json()["id"]

    with Session(engine) as session:
        admin = session.exec(
            select(User).where(User.username == "document-boundary-admin")
        ).one()
        document = Document(
            owner_id=admin.id,
            organization_id=organization_id,
            knowledge_base_id=second_knowledge_base_id,
            status=DocumentStatus.READY.value,
            original_filename="other-kb.md",
            stored_filename="other-kb.md",
            file_path="other-kb.md",
            extracted_text="其他知识库内容",
            is_extracted=True,
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = document.id

    response = client.post(
        f"/knowledge-bases/{first_knowledge_base_id}/documents/{document_id}/publish",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"


def test_team_publish_hides_another_organizations_document(client):
    first_headers, _, _ = create_organization_and_knowledge_base(
        client,
        username="first-approval-organization-admin",
        slug="first-approval-organization",
    )
    _, second_organization_id, second_knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="second-approval-organization-admin",
            slug="second-approval-organization",
        )
    )

    with Session(engine) as session:
        second_admin = session.exec(
            select(User).where(User.username == "second-approval-organization-admin")
        ).one()
        document = Document(
            owner_id=second_admin.id,
            organization_id=second_organization_id,
            knowledge_base_id=second_knowledge_base_id,
            status=DocumentStatus.READY.value,
            original_filename="private.md",
            stored_filename="private.md",
            file_path="private.md",
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = document.id

    response = client.post(
        f"/knowledge-bases/{second_knowledge_base_id}/documents/{document_id}/publish",
        headers=first_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "knowledge base not found"

    with Session(engine) as session:
        assert session.get(Document, document_id).status == DocumentStatus.READY.value
        assert session.exec(select(DocumentLifecycleEvent)).all() == []


@pytest.mark.parametrize("action", ["publish", "archive"])
def test_team_document_lifecycle_endpoints_require_authentication(client, action):
    response = client.post(
        f"/knowledge-bases/1/documents/1/{action}",
        headers={ORGANIZATION_ID_HEADER: "1"},
    )

    assert response.status_code == 401


def seed_enterprise_document_for_legacy_isolation(
    *,
    username: str,
    organization_id: int,
    knowledge_base_id: int,
    file_path: Path,
) -> tuple[int, int]:
    file_path.write_text("企业内部密码重置流程。", encoding="utf-8")

    with Session(engine) as session:
        owner = session.exec(select(User).where(User.username == username)).one()
        document = Document(
            owner_id=owner.id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            status=DocumentStatus.PUBLISHED.value,
            original_filename="enterprise-private.md",
            stored_filename="enterprise-private.md",
            file_path=str(file_path),
            extracted_text="企业内部密码重置流程。",
            is_extracted=True,
        )
        session.add(document)
        session.flush()
        chunk = DocumentChunk(
            owner_id=owner.id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            document_version=document.version,
            status=DocumentStatus.PUBLISHED.value,
            chunk_index=0,
            content="企业内部密码重置流程。",
            char_count=11,
            embedding_json="[1.0, 0.0]",
            embedding_vector=[1.0, 0.0],
            is_embedded=True,
        )
        session.add(chunk)
        session.commit()
        session.refresh(document)
        return document.id, owner.id


@pytest.mark.parametrize(
    ("method", "suffix", "case_name"),
    [
        ("GET", "/content", "content"),
        ("GET", "/chunks", "list-chunks"),
        ("GET", "/lifecycle-events", "events"),
        ("POST", "/extract", "extract"),
        ("POST", "/chunks", "create-chunks"),
        ("POST", "/process", "process"),
        ("POST", "/embeddings", "embeddings"),
        ("DELETE", "", "delete"),
    ],
)
def test_legacy_document_detail_endpoints_hide_enterprise_documents(
    client,
    monkeypatch,
    tmp_path,
    method,
    suffix,
    case_name,
):
    username = f"isolation-{case_name}"
    headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username=username,
            slug=f"isolation-{case_name}",
        )
    )
    file_path = tmp_path / "enterprise-private.md"
    document_id, _ = seed_enterprise_document_for_legacy_isolation(
        username=username,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        file_path=file_path,
    )

    monkeypatch.setattr(
        documents_router,
        "extract_text_from_file",
        lambda _path: "should not be extracted",
    )
    monkeypatch.setattr(
        documents_router,
        "process_document_record",
        lambda _session, _document: SimpleNamespace(
            document_id=document_id,
            chunk_count=1,
            embedded_count=1,
            process_log_id=1,
        ),
    )
    monkeypatch.setattr(
        documents_router,
        "generate_embedding",
        lambda _text: [1.0, 0.0],
    )

    response = client.request(
        method,
        f"/documents/{document_id}{suffix}",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"

    with Session(engine) as session:
        assert session.get(Document, document_id) is not None
    assert file_path.exists()


def test_legacy_document_collections_exclude_enterprise_data(
    client,
    monkeypatch,
    tmp_path,
):
    username = "legacy-collection-isolation-user"
    headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username=username,
            slug="legacy-collection-isolation",
        )
    )
    document_id, owner_id = seed_enterprise_document_for_legacy_isolation(
        username=username,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        file_path=tmp_path / "enterprise-collection.md",
    )

    with Session(engine) as session:
        session.add(
            DocumentProcessLog(
                owner_id=owner_id,
                organization_id=organization_id,
                document_id=document_id,
                is_success=True,
            )
        )
        session.commit()

    monkeypatch.setattr(
        documents_router,
        "generate_embedding",
        lambda _text: [1.0, 0.0],
    )

    documents_response = client.get("/documents", headers=headers)
    logs_response = client.get("/documents/process-logs", headers=headers)
    search_response = client.post(
        "/documents/search",
        headers=headers,
        params={"query": "企业内部密码重置流程"},
    )

    assert documents_response.status_code == 200
    assert documents_response.json()["documents"] == []
    assert logs_response.status_code == 200
    assert logs_response.json()["logs"] == []
    assert logs_response.json()["pagination"]["total"] == 0
    assert search_response.status_code == 400
    assert search_response.json()["message"] == ("no embedded document chunks found")


def test_member_can_read_team_document_content_chunks_and_lifecycle_events(
    client,
):
    admin_headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="team-document-reader-admin",
            slug="team-document-reader-organization",
        )
    )
    member_headers = register_and_login(client, "team-document-reader-member")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "team-document-reader-member", "role": "member"},
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=member_headers,
        files={"file": ("readable.md", b"readable content", "text/markdown")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]
    chunk_id = make_document_ready(document_id)
    publish_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/publish",
        headers=admin_headers,
    )
    assert publish_response.status_code == 200

    content_response = client.get(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/content",
        headers=member_headers,
    )
    chunks_response = client.get(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/chunks",
        headers=member_headers,
    )
    events_response = client.get(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/lifecycle-events",
        headers=member_headers,
        params={"offset": 0, "limit": 10},
    )

    assert content_response.status_code == 200
    assert content_response.json()["document"] == {
        "id": document_id,
        "owner_id": upload_response.json()["document"]["owner_id"],
        "organization_id": organization_id,
        "knowledge_base_id": knowledge_base_id,
        "filename": "readable.md",
        "content": "企业发布审批内容。",
        "version": 1,
        "status": "published",
    }
    assert chunks_response.status_code == 200
    assert chunks_response.json()["chunks"] == [
        {
            "id": chunk_id,
            "chunk_index": 0,
            "content": "企业发布审批内容。",
            "char_count": 9,
            "document_version": 1,
            "status": "published",
        }
    ]
    assert events_response.status_code == 200
    assert events_response.json()["document_id"] == document_id
    assert events_response.json()["events"][0]["action"] == "publish"
    assert events_response.json()["events"][0]["to_status"] == "published"
    assert events_response.json()["pagination"] == {
        "offset": 0,
        "limit": 10,
        "total": 1,
        "returned": 1,
    }


@pytest.mark.parametrize(
    "suffix",
    ["content", "chunks", "lifecycle-events"],
)
def test_team_document_read_endpoints_hide_another_knowledge_bases_document(
    client,
    suffix,
):
    headers, _, first_knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username=f"read-boundary-{suffix}",
        slug=f"read-boundary-{suffix}",
    )
    second_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "Second Read Boundary Knowledge Base"},
    )
    assert second_response.status_code == 201
    second_knowledge_base_id = second_response.json()["id"]
    upload_response = client.post(
        f"/knowledge-bases/{second_knowledge_base_id}/documents",
        headers=headers,
        files={"file": ("hidden.md", b"hidden content", "text/markdown")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]

    response = client.get(
        f"/knowledge-bases/{first_knowledge_base_id}/documents/{document_id}/{suffix}",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"


@pytest.mark.parametrize(
    "suffix",
    ["content", "chunks", "lifecycle-events"],
)
def test_team_document_read_endpoints_require_authentication(client, suffix):
    response = client.get(
        f"/knowledge-bases/1/documents/1/{suffix}",
        headers={ORGANIZATION_ID_HEADER: "1"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "suffix",
    ["content", "chunks", "lifecycle-events"],
)
def test_team_document_read_endpoints_hide_another_organizations_data(
    client,
    suffix,
):
    first_headers, _, _ = create_organization_and_knowledge_base(
        client,
        username=f"first-read-org-{suffix}",
        slug=f"first-read-org-{suffix}",
    )
    second_headers, _, second_knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username=f"second-read-org-{suffix}",
            slug=f"second-read-org-{suffix}",
        )
    )
    upload_response = client.post(
        f"/knowledge-bases/{second_knowledge_base_id}/documents",
        headers=second_headers,
        files={"file": ("private.md", b"private content", "text/markdown")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]

    response = client.get(
        f"/knowledge-bases/{second_knowledge_base_id}/documents/{document_id}/{suffix}",
        headers=first_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "knowledge base not found"


def test_team_document_content_requires_completed_extraction(client):
    headers, _, knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="unextracted-team-reader",
        slug="unextracted-team-reader",
    )
    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={"file": ("processing.md", b"processing", "text/markdown")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]

    response = client.get(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/content",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["message"] == "document is not extracted"


def test_member_can_read_paginated_team_document_process_logs(client):
    admin_headers, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="team-process-log-admin",
            slug="team-process-log-organization",
        )
    )
    member_headers = register_and_login(client, "team-process-log-member")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "team-process-log-member", "role": "member"},
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)
    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=admin_headers,
        files={"file": ("processing.md", b"processing content", "text/markdown")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]

    with Session(engine) as session:
        owner = session.exec(
            select(User).where(User.username == "team-process-log-admin")
        ).one()
        session.add_all(
            [
                DocumentProcessLog(
                    owner_id=owner.id,
                    organization_id=organization_id,
                    document_id=document_id,
                    is_success=True,
                    text_char_count=120,
                    chunk_count=2,
                    embedded_count=2,
                    total_latency_ms=80,
                ),
                DocumentProcessLog(
                    owner_id=owner.id,
                    organization_id=organization_id,
                    document_id=document_id,
                    is_success=False,
                    text_char_count=120,
                    chunk_count=2,
                    embedded_count=1,
                    total_latency_ms=95,
                    error_message="failed to create embedding",
                ),
            ]
        )
        session.commit()

    response = client.get(
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/process-logs",
        headers=member_headers,
        params={"offset": 0, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert len(payload["logs"]) == 1
    assert (
        payload["logs"][0]["owner_id"] == upload_response.json()["document"]["owner_id"]
    )
    assert payload["logs"][0]["is_success"] is False
    assert payload["logs"][0]["text_char_count"] == 120
    assert payload["logs"][0]["chunk_count"] == 2
    assert payload["logs"][0]["embedded_count"] == 1
    assert payload["logs"][0]["total_latency_ms"] == 95
    assert payload["logs"][0]["error_message"] == "failed to create embedding"
    assert payload["pagination"] == {
        "offset": 0,
        "limit": 1,
        "total": 2,
        "returned": 1,
    }


def test_team_document_process_logs_hide_another_knowledge_bases_document(client):
    headers, _, first_knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="process-log-kb-boundary",
        slug="process-log-kb-boundary",
    )
    second_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "Second Process Log Knowledge Base"},
    )
    assert second_response.status_code == 201
    second_knowledge_base_id = second_response.json()["id"]
    upload_response = client.post(
        f"/knowledge-bases/{second_knowledge_base_id}/documents",
        headers=headers,
        files={"file": ("hidden.md", b"hidden", "text/markdown")},
    )
    document_id = upload_response.json()["document"]["id"]

    response = client.get(
        f"/knowledge-bases/{first_knowledge_base_id}/documents/{document_id}/process-logs",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "document not found"


def test_team_document_process_logs_hide_another_organizations_data(client):
    first_headers, _, _ = create_organization_and_knowledge_base(
        client,
        username="first-process-log-org",
        slug="first-process-log-org",
    )
    second_headers, _, second_knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="second-process-log-org",
            slug="second-process-log-org",
        )
    )
    upload_response = client.post(
        f"/knowledge-bases/{second_knowledge_base_id}/documents",
        headers=second_headers,
        files={"file": ("private.md", b"private", "text/markdown")},
    )
    document_id = upload_response.json()["document"]["id"]

    response = client.get(
        f"/knowledge-bases/{second_knowledge_base_id}/documents/{document_id}/process-logs",
        headers=first_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "knowledge base not found"


def test_team_document_process_logs_require_authentication(client):
    response = client.get(
        "/knowledge-bases/1/documents/1/process-logs",
        headers={ORGANIZATION_ID_HEADER: "1"},
    )

    assert response.status_code == 401


def test_team_document_process_logs_reject_invalid_pagination(client):
    headers, _, knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="process-log-pagination",
        slug="process-log-pagination",
    )
    upload_response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={"file": ("pagination.md", b"pagination", "text/markdown")},
    )
    document_id = upload_response.json()["document"]["id"]

    for query in ["offset=-1&limit=20", "offset=0&limit=0", "offset=0&limit=101"]:
        response = client.get(
            f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/process-logs?{query}",
            headers=headers,
        )
        assert response.status_code == 422
