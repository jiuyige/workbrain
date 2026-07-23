import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app import service_agent
from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
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

    tool_call = SimpleNamespace(
        id="call-prepare-service-request",
        function=SimpleNamespace(
            name="prepare_service_request",
            arguments=json.dumps(
                {
                    "service_name": "VPN Access",
                    "title": "Need VPN access",
                    "description": "Required for remote incident support.",
                }
            ),
        ),
    )
    planned_message = SimpleNamespace(content="", tool_calls=[tool_call])
    monkeypatch.setattr(
        service_agent,
        "plan_service_request_with_tools",
        lambda message: (
            planned_message,
            [{"role": "user", "content": message}],
        ),
    )
    monkeypatch.setattr(
        service_agent,
        "generate_tool_final_answer",
        lambda _messages: "信息已完整，请确认申请内容。",
    )

    with TestClient(app) as test_client:
        yield test_client

    if previous_override is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous_override


def register_and_login(client: TestClient, username: str) -> dict[str, str]:
    password = "mvp-end-to-end-password"
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
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_request_to_approval_matches_frontend_contract(client):
    admin_headers = register_and_login(client, "mvp-admin")
    organization_response = client.post(
        "/organizations",
        headers=admin_headers,
        json={"name": "MVP Organization", "slug": "mvp-organization"},
    )
    assert organization_response.status_code == 201
    organization_id = organization_response.json()["id"]
    admin_headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    member_headers = register_and_login(client, "mvp-member")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "mvp-member", "role": "member"},
    )
    assert invite_response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    catalog_response = client.post(
        "/service-catalog/items",
        headers=admin_headers,
        json={
            "name": "VPN Access",
            "description": "Secure remote access for employees.",
        },
    )
    assert catalog_response.status_code == 201
    catalog_item = catalog_response.json()

    preview_response = client.post(
        "/assistant/service-tools",
        headers=member_headers,
        json={"message": "帮我申请 VPN，用于远程处理线上故障。"},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview == {
        "action": "confirm_service_request",
        "reply": "信息已完整，请确认申请内容。",
        "result": {
            "requires_confirmation": True,
            "confirmation_token": preview["result"]["confirmation_token"],
            "service": {
                "id": catalog_item["id"],
                "name": "VPN Access",
            },
            "title": "Need VPN access",
            "description": "Required for remote incident support.",
        },
    }
    confirmation_token = preview["result"]["confirmation_token"]
    assert len(confirmation_token) >= 20

    confirm_response = client.post(
        "/assistant/service-tools/confirm",
        headers=member_headers,
        json={"confirmation_token": confirmation_token},
    )
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["action"] == "create_service_request"
    assert confirmed["reply"] == "申请单已创建，当前状态为待审批。"
    assert confirmed["result"]["created"] is True
    request = confirmed["result"]["service_request"]
    assert request["organization_id"] == organization_id
    assert request["service_catalog_item_id"] == catalog_item["id"]
    assert request["title"] == "Need VPN access"
    assert request["description"] == "Required for remote incident support."
    assert request["status"] == "pending"
    assert request["decision_reason"] is None

    pending_list_response = client.get(
        "/service-requests?limit=100&status=pending",
        headers=member_headers,
    )
    assert pending_list_response.status_code == 200
    pending_list = pending_list_response.json()
    assert pending_list["pagination"]["total"] == 1
    assert pending_list["requests"][0]["id"] == request["id"]

    approve_response = client.post(
        f"/service-requests/{request['id']}/approve",
        headers=admin_headers,
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["decided_by_user_id"] is not None
    assert approved["decided_at"] is not None

    detail_response = client.get(
        f"/service-requests/{request['id']}",
        headers=member_headers,
    )
    events_response = client.get(
        f"/service-requests/{request['id']}/events",
        headers=member_headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "approved"
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert [event["action"] for event in events] == ["create", "approve"]
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "pending"
    assert events[1]["from_status"] == "pending"
    assert events[1]["to_status"] == "approved"
