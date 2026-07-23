import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

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


def register_and_login(client: TestClient, username: str) -> dict[str, str]:
    password = "service-request-password"
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


def invite_user(
    client: TestClient,
    *,
    admin_headers: dict[str, str],
    username: str,
    role: str,
) -> dict[str, str]:
    headers = register_and_login(client, username)
    response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": username, "role": role},
    )
    assert response.status_code == 201
    headers[ORGANIZATION_ID_HEADER] = admin_headers[ORGANIZATION_ID_HEADER]
    return headers


def create_catalog_item(
    client: TestClient,
    headers: dict[str, str],
    name: str = "VPN Access",
) -> int:
    response = client.post(
        "/service-catalog/items",
        headers=headers,
        json={"name": name, "description": f"Request {name}."},
    )
    assert response.status_code == 201
    return response.json()["id"]


def submit_request(
    client: TestClient,
    headers: dict[str, str],
    catalog_item_id: int,
    *,
    title: str = "Need VPN access",
    description: str = "Access is required for remote work.",
):
    return client.post(
        "/service-requests",
        headers=headers,
        json={
            "service_catalog_item_id": catalog_item_id,
            "title": title,
            "description": description,
        },
    )


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/service-requests", None),
        (
            "POST",
            "/service-requests",
            {
                "service_catalog_item_id": 1,
                "title": "VPN",
                "description": "Remote work",
            },
        ),
        ("GET", "/service-requests/1", None),
        ("POST", "/service-requests/1/approve", None),
        ("POST", "/service-requests/1/reject", {"reason": "Missing details"}),
        ("GET", "/service-requests/1/events", None),
    ],
)
def test_service_request_endpoints_require_authentication(
    client,
    method,
    path,
    json_body,
):
    kwargs = {"headers": {ORGANIZATION_ID_HEADER: "1"}}
    if json_body is not None:
        kwargs["json"] = json_body

    response = client.request(method, path, **kwargs)

    assert response.status_code == 401


def test_member_can_submit_list_and_read_own_request(client):
    admin_headers, organization_id = create_organization(
        client,
        username="request-owner-admin",
        slug="request-owner-organization",
    )
    catalog_item_id = create_catalog_item(client, admin_headers)
    member_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-owner-member",
        role="member",
    )

    response = submit_request(client, member_headers, catalog_item_id)

    assert response.status_code == 201
    created = response.json()
    assert created["organization_id"] == organization_id
    assert created["service_catalog_item_id"] == catalog_item_id
    assert created["title"] == "Need VPN access"
    assert created["description"] == "Access is required for remote work."
    assert created["status"] == "pending"

    list_response = client.get("/service-requests", headers=member_headers)
    detail_response = client.get(
        f"/service-requests/{created['id']}",
        headers=member_headers,
    )

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["requests"]] == [created["id"]]
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == created["id"]


def test_member_cannot_read_another_members_request_but_approver_can(client):
    admin_headers, _ = create_organization(
        client,
        username="request-visibility-admin",
        slug="request-visibility-organization",
    )
    catalog_item_id = create_catalog_item(client, admin_headers)
    owner_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-visibility-owner",
        role="member",
    )
    other_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-visibility-other",
        role="member",
    )
    approver_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-visibility-approver",
        role="approver",
    )
    request_id = submit_request(client, owner_headers, catalog_item_id).json()["id"]

    other_list = client.get("/service-requests", headers=other_headers)
    other_detail = client.get(
        f"/service-requests/{request_id}",
        headers=other_headers,
    )
    approver_list = client.get("/service-requests", headers=approver_headers)
    approver_detail = client.get(
        f"/service-requests/{request_id}",
        headers=approver_headers,
    )

    assert other_list.json()["requests"] == []
    assert other_detail.status_code == 404
    assert approver_list.status_code == 200
    assert approver_list.json()["requests"][0]["id"] == request_id
    assert approver_detail.status_code == 200


def test_request_rejects_inactive_and_cross_organization_catalog_items(client):
    first_headers, _ = create_organization(
        client,
        username="request-catalog-first",
        slug="request-catalog-first",
    )
    second_headers, _ = create_organization(
        client,
        username="request-catalog-second",
        slug="request-catalog-second",
    )
    inactive_item_id = create_catalog_item(client, first_headers, "Inactive Service")
    other_item_id = create_catalog_item(client, second_headers, "Other Service")
    assert (
        client.patch(
            f"/service-catalog/items/{inactive_item_id}",
            headers=first_headers,
            json={"is_active": False},
        ).status_code
        == 200
    )

    inactive_response = submit_request(client, first_headers, inactive_item_id)
    cross_organization_response = submit_request(client, first_headers, other_item_id)

    assert inactive_response.status_code == 404
    assert cross_organization_response.status_code == 404
    assert inactive_response.json()["message"] == "service catalog item not found"
    assert cross_organization_response.json()["message"] == (
        "service catalog item not found"
    )


def test_approver_can_approve_pending_request_and_audit_is_recorded(client):
    admin_headers, _ = create_organization(
        client,
        username="request-approve-admin",
        slug="request-approve-organization",
    )
    catalog_item_id = create_catalog_item(client, admin_headers)
    member_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-approve-member",
        role="member",
    )
    approver_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-approver",
        role="approver",
    )
    request_id = submit_request(client, member_headers, catalog_item_id).json()["id"]

    approve_response = client.post(
        f"/service-requests/{request_id}/approve",
        headers=approver_headers,
    )
    repeat_response = client.post(
        f"/service-requests/{request_id}/approve",
        headers=admin_headers,
    )
    events_response = client.get(
        f"/service-requests/{request_id}/events",
        headers=member_headers,
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert repeat_response.status_code == 409
    assert repeat_response.json()["message"] == "service request is already finished"
    assert events_response.status_code == 200
    assert [event["action"] for event in events_response.json()["events"]] == [
        "create",
        "approve",
    ]
    assert events_response.json()["events"][1]["from_status"] == "pending"
    assert events_response.json()["events"][1]["to_status"] == "approved"


def test_rejection_requires_reason_and_records_it(client):
    admin_headers, _ = create_organization(
        client,
        username="request-reject-admin",
        slug="request-reject-organization",
    )
    catalog_item_id = create_catalog_item(client, admin_headers)
    member_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-reject-member",
        role="member",
    )
    approver_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-reject-approver",
        role="approver",
    )
    request_id = submit_request(client, member_headers, catalog_item_id).json()["id"]

    missing_reason = client.post(
        f"/service-requests/{request_id}/reject",
        headers=approver_headers,
        json={"reason": "   "},
    )
    reject_response = client.post(
        f"/service-requests/{request_id}/reject",
        headers=approver_headers,
        json={"reason": "Business justification is missing."},
    )
    events_response = client.get(
        f"/service-requests/{request_id}/events",
        headers=approver_headers,
    )

    assert missing_reason.status_code == 422
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert reject_response.json()["decision_reason"] == (
        "Business justification is missing."
    )
    assert events_response.json()["events"][1]["reason"] == (
        "Business justification is missing."
    )


def test_member_cannot_approve_and_requester_cannot_approve_own_request(client):
    admin_headers, _ = create_organization(
        client,
        username="request-self-admin",
        slug="request-self-organization",
    )
    catalog_item_id = create_catalog_item(client, admin_headers)
    member_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-self-member",
        role="member",
    )
    approver_headers = invite_user(
        client,
        admin_headers=admin_headers,
        username="request-self-approver",
        role="approver",
    )
    member_request_id = submit_request(
        client,
        member_headers,
        catalog_item_id,
    ).json()["id"]
    approver_request_id = submit_request(
        client,
        approver_headers,
        catalog_item_id,
        title="Approver's own request",
    ).json()["id"]

    member_response = client.post(
        f"/service-requests/{member_request_id}/approve",
        headers=member_headers,
    )
    self_response = client.post(
        f"/service-requests/{approver_request_id}/approve",
        headers=approver_headers,
    )

    assert member_response.status_code == 403
    assert member_response.json()["message"] == (
        "organization approver access required"
    )
    assert self_response.status_code == 403
    assert self_response.json()["message"] == (
        "requester cannot approve own service request"
    )


def test_cross_organization_request_is_hidden_from_approver(client):
    first_headers, _ = create_organization(
        client,
        username="request-cross-first",
        slug="request-cross-first",
    )
    second_headers, _ = create_organization(
        client,
        username="request-cross-second",
        slug="request-cross-second",
    )
    second_item_id = create_catalog_item(client, second_headers)
    second_request_id = submit_request(
        client,
        second_headers,
        second_item_id,
    ).json()["id"]

    detail_response = client.get(
        f"/service-requests/{second_request_id}",
        headers=first_headers,
    )
    approve_response = client.post(
        f"/service-requests/{second_request_id}/approve",
        headers=first_headers,
    )
    events_response = client.get(
        f"/service-requests/{second_request_id}/events",
        headers=first_headers,
    )

    assert detail_response.status_code == 404
    assert approve_response.status_code == 404
    assert events_response.status_code == 404
