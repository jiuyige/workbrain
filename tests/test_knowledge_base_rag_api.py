import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
from app.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    RAGQueryLog,
    User,
)
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
    password = "knowledge-base-rag-password"
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

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).one()
        user_id = user.id

    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}, user_id


def create_organization_and_knowledge_base(
    client: TestClient,
    *,
    username: str,
    slug: str,
) -> tuple[dict[str, str], int, int, int]:
    headers, user_id = register_and_login(client, username)
    organization_response = client.post(
        "/organizations",
        headers=headers,
        json={"name": f"{username} Organization", "slug": slug},
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
    return (
        headers,
        user_id,
        organization_id,
        knowledge_base_response.json()["id"],
    )


def create_knowledge_base(client, headers, name: str) -> int:
    response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()["id"]


def seed_document_chunk(
    *,
    owner_id: int,
    organization_id: int,
    knowledge_base_id: int,
    status: str,
    content: str,
) -> tuple[int, int]:
    with Session(engine) as session:
        document = Document(
            owner_id=owner_id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            status=status,
            original_filename="team-policy.md",
            stored_filename="team-policy.md",
            file_path="team-policy.md",
            extracted_text=content,
            is_extracted=True,
        )
        session.add(document)
        session.flush()
        chunk = DocumentChunk(
            owner_id=owner_id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            document_version=document.version,
            status=status,
            chunk_index=0,
            content=content,
            char_count=len(content),
            embedding_json=json.dumps([1.0, 0.0]),
            embedding_vector=[1.0, 0.0],
            is_embedded=True,
        )
        session.add(chunk)
        session.commit()
        session.refresh(document)
        session.refresh(chunk)
        return document.id, chunk.id


def test_knowledge_base_rag_requires_authentication(client):
    response = client.post(
        "/rag/knowledge-bases/1/ask",
        headers={ORGANIZATION_ID_HEADER: "1"},
        json={"question": "如何申请？"},
    )

    assert response.status_code == 401


def test_knowledge_base_rag_requires_organization_context(client):
    headers, _ = register_and_login(client, "rag-missing-context-user")

    response = client.post(
        "/rag/knowledge-bases/1/ask",
        headers=headers,
        json={"question": "如何申请？"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "organization context is required"


def test_member_can_answer_from_another_members_published_document(
    client,
    monkeypatch,
):
    admin_headers, admin_id, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="team-rag-admin",
            slug="team-rag-organization",
        )
    )
    member_headers, member_id = register_and_login(client, "team-rag-member")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "team-rag-member", "role": "member"},
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    published_content = "员工重置密码需要联系 IT 服务台提交申请。"
    published_document_id, published_chunk_id = seed_document_chunk(
        owner_id=admin_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        status=DocumentStatus.PUBLISHED.value,
        content=published_content,
    )
    seed_document_chunk(
        owner_id=admin_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        status=DocumentStatus.READY.value,
        content="未发布内容：员工重置密码可以直接查看管理员密码。",
    )
    other_knowledge_base_id = create_knowledge_base(
        client,
        admin_headers,
        "Other Knowledge Base",
    )
    seed_document_chunk(
        owner_id=admin_id,
        organization_id=organization_id,
        knowledge_base_id=other_knowledge_base_id,
        status=DocumentStatus.PUBLISHED.value,
        content="其他知识库中的员工重置密码说明。",
    )

    monkeypatch.setattr(rag_router, "generate_embedding", lambda _text: [1.0, 0.0])

    def fake_answer(_question, context):
        assert published_content in context
        assert "未发布内容" not in context
        assert "其他知识库" not in context
        return "请联系 IT 服务台提交申请。[S1]"

    monkeypatch.setattr(rag_router, "answer_with_documents", fake_answer)

    response = client.post(
        f"/rag/knowledge-bases/{knowledge_base_id}/ask",
        headers=member_headers,
        json={"question": "员工重置密码需要联系哪个服务台提交申请？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "请联系 IT 服务台提交申请。[S1]"
    assert payload["sources"][0]["reference"] == "[S1]"
    assert payload["sources"][0]["document_id"] == published_document_id
    assert payload["sources"][0]["chunk_id"] == published_chunk_id

    with Session(engine) as session:
        log = session.get(RAGQueryLog, payload["rag_query_log_id"])

        assert log.owner_id == member_id
        assert log.organization_id == organization_id
        assert log.knowledge_base_id == knowledge_base_id
        assert json.loads(log.source_chunk_ids_json) == [published_chunk_id]


def test_cross_organization_knowledge_base_is_hidden_before_embedding(
    client,
    monkeypatch,
):
    first_headers, _, _, _ = create_organization_and_knowledge_base(
        client,
        username="first-team-rag-user",
        slug="first-team-rag-organization",
    )
    _, _, _, second_knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="second-team-rag-user",
        slug="second-team-rag-organization",
    )

    def fail_if_called(_text):
        raise AssertionError("embedding must not run across organizations")

    monkeypatch.setattr(rag_router, "generate_embedding", fail_if_called)

    response = client.post(
        f"/rag/knowledge-bases/{second_knowledge_base_id}/ask",
        headers=first_headers,
        json={"question": "不能检索的问题"},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "knowledge base not found"


def test_knowledge_base_rag_rejects_blank_question_before_embedding(
    client,
    monkeypatch,
):
    headers, _, _, knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="blank-team-rag-user",
        slug="blank-team-rag-organization",
    )

    def fail_if_called(_text):
        raise AssertionError("embedding must not run for a blank question")

    monkeypatch.setattr(rag_router, "generate_embedding", fail_if_called)

    response = client.post(
        f"/rag/knowledge-bases/{knowledge_base_id}/ask",
        headers=headers,
        json={"question": "   "},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "question cannot be empty"


def test_personal_rag_cannot_search_an_enterprise_document_owned_by_caller(
    client,
    monkeypatch,
):
    headers, owner_id, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="personal-rag-enterprise-owner",
            slug="personal-rag-enterprise-owner",
        )
    )
    document_id, _ = seed_document_chunk(
        owner_id=owner_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        status=DocumentStatus.PUBLISHED.value,
        content="企业员工重置密码必须联系 IT 服务台。",
    )
    monkeypatch.setattr(rag_router, "generate_embedding", lambda _text: [1.0, 0.0])
    monkeypatch.setattr(
        rag_router,
        "answer_with_documents",
        lambda _question, _context: "不应使用企业资料回答",
    )

    general_response = client.post(
        "/rag/ask",
        headers=headers,
        json={"question": "企业员工重置密码联系哪个服务台？"},
    )
    direct_response = client.post(
        "/rag/ask",
        headers=headers,
        json={
            "question": "企业员工重置密码联系哪个服务台？",
            "document_id": document_id,
        },
    )

    assert general_response.status_code == 200
    assert general_response.json()["sources"] == []
    assert general_response.json()["retrieval"]["matched_count"] == 0
    assert direct_response.status_code == 404
    assert direct_response.json()["message"] == "document not found"


def test_personal_rag_logs_exclude_enterprise_queries(client):
    headers, owner_id, organization_id, _ = create_organization_and_knowledge_base(
        client,
        username="personal-rag-log-isolation",
        slug="personal-rag-log-isolation",
    )

    with Session(engine) as session:
        session.add(
            RAGQueryLog(
                owner_id=owner_id,
                organization_id=organization_id,
                question="企业知识库问题",
            )
        )
        session.commit()

    response = client.get("/rag/logs", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


def test_member_can_read_paginated_knowledge_base_rag_logs(client):
    admin_headers, admin_id, organization_id, knowledge_base_id = (
        create_organization_and_knowledge_base(
            client,
            username="team-rag-log-admin",
            slug="team-rag-log-organization",
        )
    )
    member_headers, _ = register_and_login(client, "team-rag-log-member")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "team-rag-log-member", "role": "member"},
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)
    other_knowledge_base_id = create_knowledge_base(
        client,
        admin_headers,
        "Other RAG Log Knowledge Base",
    )

    with Session(engine) as session:
        session.add_all(
            [
                RAGQueryLog(
                    owner_id=admin_id,
                    organization_id=organization_id,
                    knowledge_base_id=knowledge_base_id,
                    question="第一次知识库问题",
                    matched_count=1,
                    used_llm=True,
                    source_chunk_ids_json="[11]",
                    total_latency_ms=40,
                ),
                RAGQueryLog(
                    owner_id=admin_id,
                    organization_id=organization_id,
                    knowledge_base_id=knowledge_base_id,
                    question="第二次知识库问题",
                    matched_count=1,
                    used_llm=True,
                    source_chunk_ids_json="[12]",
                    total_latency_ms=55,
                ),
                RAGQueryLog(
                    owner_id=admin_id,
                    organization_id=organization_id,
                    knowledge_base_id=other_knowledge_base_id,
                    question="其他知识库问题",
                ),
            ]
        )
        session.commit()

    response = client.get(
        f"/rag/knowledge-bases/{knowledge_base_id}/logs",
        headers=member_headers,
        params={"offset": 0, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledge_base_id"] == knowledge_base_id
    assert payload["logs"] == [
        {
            "id": payload["logs"][0]["id"],
            "owner_id": admin_id,
            "question": "第二次知识库问题",
            "top_score": None,
            "matched_count": 1,
            "used_llm": True,
            "source_chunk_ids": [12],
            "total_latency_ms": 55,
            "created_at": payload["logs"][0]["created_at"],
        }
    ]
    assert payload["pagination"] == {
        "offset": 0,
        "limit": 1,
        "total": 2,
        "returned": 1,
    }


def test_knowledge_base_rag_logs_hide_another_organizations_data(client):
    first_headers, _, _, _ = create_organization_and_knowledge_base(
        client,
        username="first-rag-log-org",
        slug="first-rag-log-org",
    )
    _, _, _, second_knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="second-rag-log-org",
        slug="second-rag-log-org",
    )

    response = client.get(
        f"/rag/knowledge-bases/{second_knowledge_base_id}/logs",
        headers=first_headers,
    )

    assert response.status_code == 404
    assert response.json()["message"] == "knowledge base not found"


def test_knowledge_base_rag_logs_require_authentication(client):
    response = client.get(
        "/rag/knowledge-bases/1/logs",
        headers={ORGANIZATION_ID_HEADER: "1"},
    )

    assert response.status_code == 401


def test_knowledge_base_rag_logs_require_organization_context(client):
    headers, _ = register_and_login(client, "rag-log-missing-context")

    response = client.get("/rag/knowledge-bases/1/logs", headers=headers)

    assert response.status_code == 400
    assert response.json()["message"] == "organization context is required"


def test_knowledge_base_rag_logs_reject_invalid_pagination(client):
    headers, _, _, knowledge_base_id = create_organization_and_knowledge_base(
        client,
        username="rag-log-pagination",
        slug="rag-log-pagination",
    )

    for query in ["offset=-1&limit=20", "offset=0&limit=0", "offset=0&limit=101"]:
        response = client.get(
            f"/rag/knowledge-bases/{knowledge_base_id}/logs?{query}",
            headers=headers,
        )
        assert response.status_code == 422
