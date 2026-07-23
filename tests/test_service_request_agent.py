import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import service_agent
from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
from app.models import (
    AgentTrace,
    ServiceRequest,
    ServiceRequestConfirmation,
    ServiceRequestEvent,
    ToolCallLog,
)
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
def client(monkeypatch):
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    previous_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(
        service_agent,
        "generate_tool_final_answer",
        lambda _messages: "企业服务工具执行完成",
    )

    with TestClient(app) as test_client:
        yield test_client

    if previous_override is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous_override


def tool_call(name: str, arguments: dict | str):
    serialized_arguments = (
        arguments if isinstance(arguments, str) else json.dumps(arguments)
    )
    return SimpleNamespace(
        id=f"call-{name}",
        function=SimpleNamespace(name=name, arguments=serialized_arguments),
    )


def install_plan(monkeypatch, *, name: str | None, arguments: dict | str = None):
    calls = [] if name is None else [tool_call(name, arguments or {})]
    message = SimpleNamespace(content="普通对话", tool_calls=calls)
    monkeypatch.setattr(
        service_agent,
        "plan_service_request_with_tools",
        lambda _message: (message, [{"role": "user", "content": _message}]),
    )


def register_and_login(client: TestClient, username: str) -> dict[str, str]:
    password = "service-agent-password"
    assert (
        client.post(
            "/users/register",
            json={"username": username, "password": password},
        ).status_code
        == 200
    )
    response = client.post(
        "/users/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_organization(
    client: TestClient,
    *,
    username: str,
    slug: str,
) -> tuple[dict[str, str], int]:
    headers = register_and_login(client, username)
    response = client.post(
        "/organizations",
        headers=headers,
        json={"name": f"{username} Organization", "slug": slug},
    )
    assert response.status_code == 201
    organization_id = response.json()["id"]
    headers[ORGANIZATION_ID_HEADER] = str(organization_id)
    return headers, organization_id


def create_catalog_item(
    client: TestClient,
    headers: dict[str, str],
    name: str,
) -> int:
    response = client.post(
        "/service-catalog/items",
        headers=headers,
        json={"name": name, "description": f"Request {name}."},
    )
    assert response.status_code == 201
    return response.json()["id"]


def call_agent(client, headers, message="test"):
    return client.post(
        "/assistant/service-tools",
        headers=headers,
        json={"message": message},
    )


def test_service_agent_requires_authentication_and_organization_context(
    client,
    monkeypatch,
):
    install_plan(monkeypatch, name="list_service_catalog", arguments={})
    unauthenticated = client.post(
        "/assistant/service-tools",
        headers={ORGANIZATION_ID_HEADER: "1"},
        json={"message": "查询服务目录"},
    )
    headers = register_and_login(client, "service-agent-no-context")
    missing_context = call_agent(client, headers, "查询服务目录")

    assert unauthenticated.status_code == 401
    assert missing_context.status_code == 400


def test_agent_lists_only_current_organizations_active_catalog(
    client,
    monkeypatch,
):
    first_headers, organization_id = create_organization(
        client,
        username="agent-catalog-first",
        slug="agent-catalog-first",
    )
    second_headers, _ = create_organization(
        client,
        username="agent-catalog-second",
        slug="agent-catalog-second",
    )
    active_id = create_catalog_item(client, first_headers, "VPN Access")
    inactive_id = create_catalog_item(client, first_headers, "Inactive Service")
    create_catalog_item(client, second_headers, "Other Organization Service")
    assert (
        client.patch(
            f"/service-catalog/items/{inactive_id}",
            headers=first_headers,
            json={"is_active": False},
        ).status_code
        == 200
    )
    install_plan(monkeypatch, name="list_service_catalog", arguments={})

    response = call_agent(client, first_headers, "有哪些 IT 服务？")

    assert response.status_code == 200
    assert response.json()["action"] == "list_service_catalog"
    assert response.json()["result"]["items"] == [
        {"id": active_id, "name": "VPN Access", "description": "Request VPN Access."}
    ]

    with Session(engine) as session:
        log = session.exec(select(ToolCallLog)).one()
        trace = session.exec(select(AgentTrace)).one()
        assert log.organization_id == organization_id
        assert trace.organization_id == organization_id


def test_agent_lists_only_current_users_service_requests(client, monkeypatch):
    headers, _ = create_organization(
        client,
        username="agent-request-list",
        slug="agent-request-list",
    )
    item_id = create_catalog_item(client, headers, "Laptop Repair")
    assert (
        client.post(
            "/service-requests",
            headers=headers,
            json={
                "service_catalog_item_id": item_id,
                "title": "Repair laptop",
                "description": "The screen is broken.",
            },
        ).status_code
        == 201
    )
    install_plan(monkeypatch, name="list_my_service_requests", arguments={})

    response = call_agent(client, headers, "查看我的服务申请")

    assert response.status_code == 200
    assert response.json()["action"] == "list_my_service_requests"
    assert len(response.json()["result"]["requests"]) == 1
    assert response.json()["result"]["requests"][0]["title"] == "Repair laptop"


def test_agent_returns_candidates_and_missing_fields_without_writing(
    client,
    monkeypatch,
):
    headers, _ = create_organization(
        client,
        username="agent-missing-info",
        slug="agent-missing-info",
    )
    vpn_id = create_catalog_item(client, headers, "VPN Access")
    create_catalog_item(client, headers, "Laptop Repair")

    install_plan(
        monkeypatch,
        name="prepare_service_request",
        arguments={"title": "Need access", "description": "Remote work"},
    )
    candidate_response = call_agent(client, headers, "我想申请 IT 服务")

    install_plan(
        monkeypatch,
        name="prepare_service_request",
        arguments={"service_catalog_item_id": vpn_id, "title": "Need VPN"},
    )
    missing_response = call_agent(client, headers, "申请 VPN")

    assert candidate_response.status_code == 200
    assert candidate_response.json()["action"] == "request_service_information"
    assert len(candidate_response.json()["result"]["candidates"]) == 2
    assert (
        "service_catalog_item" in candidate_response.json()["result"]["missing_fields"]
    )
    assert missing_response.json()["action"] == "request_service_information"
    assert missing_response.json()["result"]["missing_fields"] == ["description"]

    with Session(engine) as session:
        assert session.exec(select(ServiceRequest)).all() == []


def test_complete_agent_request_requires_confirmation_then_is_idempotent(
    client,
    monkeypatch,
):
    headers, organization_id = create_organization(
        client,
        username="agent-confirmation",
        slug="agent-confirmation",
    )
    item_id = create_catalog_item(client, headers, "VPN Access")
    install_plan(
        monkeypatch,
        name="prepare_service_request",
        arguments={
            "service_catalog_item_id": item_id,
            "title": "Need VPN access",
            "description": "Required for remote support.",
        },
    )

    preview_response = call_agent(client, headers, "帮我申请 VPN")

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["action"] == "confirm_service_request"
    assert preview["result"]["requires_confirmation"] is True
    assert preview["result"]["service"] == {"id": item_id, "name": "VPN Access"}
    assert preview["result"]["title"] == "Need VPN access"
    assert preview["result"]["description"] == "Required for remote support."
    token = preview["result"]["confirmation_token"]

    with Session(engine) as session:
        assert session.exec(select(ServiceRequest)).all() == []
        tool_log = session.exec(select(ToolCallLog)).one()
        assert token not in tool_log.result_json
        assert '"confirmation_token": "[REDACTED]"' in tool_log.result_json

    confirm_response = client.post(
        "/assistant/service-tools/confirm",
        headers=headers,
        json={"confirmation_token": token},
    )
    repeat_response = client.post(
        "/assistant/service-tools/confirm",
        headers=headers,
        json={"confirmation_token": token},
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["action"] == "create_service_request"
    assert confirm_response.json()["result"]["created"] is True
    created = confirm_response.json()["result"]["service_request"]
    assert created["status"] == "pending"
    assert repeat_response.status_code == 200
    assert repeat_response.json()["result"]["created"] is False
    assert repeat_response.json()["result"]["service_request"]["id"] == created["id"]

    with Session(engine) as session:
        requests = session.exec(select(ServiceRequest)).all()
        events = session.exec(select(ServiceRequestEvent)).all()
        assert len(requests) == 1
        assert requests[0].organization_id == organization_id
        assert len(events) == 1
        assert events[0].action == "create"


def test_confirmation_revalidates_active_service_and_user_scope(client, monkeypatch):
    owner_headers, _ = create_organization(
        client,
        username="agent-confirm-owner",
        slug="agent-confirm-owner",
    )
    other_headers, _ = create_organization(
        client,
        username="agent-confirm-other",
        slug="agent-confirm-other",
    )
    item_id = create_catalog_item(client, owner_headers, "Email Account")
    install_plan(
        monkeypatch,
        name="prepare_service_request",
        arguments={
            "service_catalog_item_id": item_id,
            "title": "Create mailbox",
            "description": "Needed for a contractor.",
        },
    )
    token = call_agent(client, owner_headers).json()["result"]["confirmation_token"]

    forged_response = client.post(
        "/assistant/service-tools/confirm",
        headers=other_headers,
        json={"confirmation_token": token},
    )
    assert (
        client.patch(
            f"/service-catalog/items/{item_id}",
            headers=owner_headers,
            json={"is_active": False},
        ).status_code
        == 200
    )
    disabled_response = client.post(
        "/assistant/service-tools/confirm",
        headers=owner_headers,
        json={"confirmation_token": token},
    )

    assert forged_response.status_code == 404
    assert disabled_response.status_code == 409
    assert disabled_response.json()["message"] == (
        "service catalog item is no longer available"
    )

    with Session(engine) as session:
        assert session.exec(select(ServiceRequest)).all() == []


def test_expired_confirmation_cannot_create_request(client, monkeypatch):
    headers, _ = create_organization(
        client,
        username="agent-expired-confirmation",
        slug="agent-expired-confirmation",
    )
    item_id = create_catalog_item(client, headers, "Database Access")
    install_plan(
        monkeypatch,
        name="prepare_service_request",
        arguments={
            "service_catalog_item_id": item_id,
            "title": "Need database access",
            "description": "Required for incident analysis.",
        },
    )
    token = call_agent(client, headers).json()["result"]["confirmation_token"]
    with Session(engine) as session:
        confirmation = session.exec(select(ServiceRequestConfirmation)).one()
        confirmation.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.add(confirmation)
        session.commit()

    response = client.post(
        "/assistant/service-tools/confirm",
        headers=headers,
        json={"confirmation_token": token},
    )

    assert response.status_code == 410
    assert response.json()["message"] == "confirmation has expired"
    with Session(engine) as session:
        assert session.exec(select(ServiceRequest)).all() == []


def test_agent_rejects_invalid_json_and_unsupported_tools_with_org_logs(
    client,
    monkeypatch,
):
    headers, organization_id = create_organization(
        client,
        username="agent-invalid-tool",
        slug="agent-invalid-tool",
    )
    install_plan(
        monkeypatch,
        name="prepare_service_request",
        arguments="{invalid-json",
    )
    invalid_response = call_agent(client, headers)

    install_plan(monkeypatch, name="create_service_request", arguments={})
    unsupported_response = call_agent(client, headers)

    assert invalid_response.status_code == 502
    assert invalid_response.json()["message"] == "tool arguments are invalid json"
    assert unsupported_response.status_code == 502
    assert unsupported_response.json()["message"] == "unsupported tool call"

    with Session(engine) as session:
        logs = session.exec(select(ToolCallLog).order_by(ToolCallLog.id)).all()
        assert len(logs) == 2
        assert all(log.organization_id == organization_id for log in logs)
        assert all(log.is_success is False for log in logs)


def test_ordinary_or_todo_intent_does_not_create_service_request(
    client,
    monkeypatch,
):
    headers, _ = create_organization(
        client,
        username="agent-intent-separation",
        slug="agent-intent-separation",
    )
    install_plan(monkeypatch, name=None)

    ordinary_response = call_agent(client, headers, "解释一下 JWT")
    todo_response = call_agent(client, headers, "创建一个学习待办")

    assert ordinary_response.status_code == 200
    assert ordinary_response.json()["action"] == "chat"
    assert todo_response.status_code == 200
    assert todo_response.json()["action"] == "chat"

    with Session(engine) as session:
        assert session.exec(select(ServiceRequest)).all() == []
