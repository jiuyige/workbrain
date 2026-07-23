import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
from app.models import MembershipRole
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
) -> dict[str, str]:
    password = "knowledge-base-api-password"
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

    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


def create_organization_context(
    client: TestClient,
    *,
    username: str,
    name: str,
    slug: str,
):
    headers = register_and_login(client, username)
    response = client.post(
        "/organizations",
        headers=headers,
        json={"name": name, "slug": slug},
    )
    assert response.status_code == 201

    organization = response.json()
    headers[ORGANIZATION_ID_HEADER] = str(organization["id"])

    return headers, organization


def invite_member(
    client: TestClient,
    *,
    admin_headers: dict[str, str],
    username: str,
) -> dict[str, str]:
    member_headers = register_and_login(client, username)
    response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": username,
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert response.status_code == 201

    member_headers[ORGANIZATION_ID_HEADER] = admin_headers[ORGANIZATION_ID_HEADER]
    return member_headers


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/knowledge-bases", None),
        ("POST", "/knowledge-bases", {"name": "Unauthorized"}),
        ("GET", "/knowledge-bases/1", None),
        ("PATCH", "/knowledge-bases/1", {"name": "Unauthorized"}),
    ],
)
def test_knowledge_base_endpoints_require_authentication(
    client,
    method,
    path,
    json_body,
):
    request_kwargs = {"headers": {ORGANIZATION_ID_HEADER: "1"}}
    if json_body is not None:
        request_kwargs["json"] = json_body

    response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401


def test_admin_can_create_list_read_and_update_knowledge_base(client):
    headers, organization = create_organization_context(
        client,
        username="knowledge-admin",
        name="Knowledge Admin Organization",
        slug="knowledge-admin-organization",
    )

    create_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={
            "name": "  IT Support  ",
            "description": "  Internal support articles.  ",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["organization_id"] == organization["id"]
    assert created["name"] == "IT Support"
    assert created["description"] == "Internal support articles."

    list_response = client.get("/knowledge-bases", headers=headers)
    read_response = client.get(
        f"/knowledge-bases/{created['id']}",
        headers=headers,
    )
    update_response = client.patch(
        f"/knowledge-bases/{created['id']}",
        headers=headers,
        json={
            "name": "IT Service Desk",
            "description": None,
        },
    )

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["knowledge_bases"]] == [
        created["id"]
    ]
    assert read_response.status_code == 200
    assert read_response.json()["name"] == "IT Support"
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "IT Service Desk"
    assert update_response.json()["description"] is None


def test_member_can_read_but_cannot_write_knowledge_bases(client):
    admin_headers, _ = create_organization_context(
        client,
        username="knowledge-member-admin",
        name="Member Access Organization",
        slug="member-access-organization",
    )
    create_response = client.post(
        "/knowledge-bases",
        headers=admin_headers,
        json={"name": "Employee Handbook"},
    )
    assert create_response.status_code == 201
    knowledge_base_id = create_response.json()["id"]

    member_headers = invite_member(
        client,
        admin_headers=admin_headers,
        username="knowledge-reader",
    )

    list_response = client.get("/knowledge-bases", headers=member_headers)
    read_response = client.get(
        f"/knowledge-bases/{knowledge_base_id}",
        headers=member_headers,
    )
    create_as_member_response = client.post(
        "/knowledge-bases",
        headers=member_headers,
        json={"name": "Forbidden Knowledge"},
    )
    update_as_member_response = client.patch(
        f"/knowledge-bases/{knowledge_base_id}",
        headers=member_headers,
        json={"name": "Forbidden Update"},
    )

    assert list_response.status_code == 200
    assert read_response.status_code == 200
    assert create_as_member_response.status_code == 403
    assert update_as_member_response.status_code == 403
    assert create_as_member_response.json()["message"] == (
        "organization admin access required"
    )


def test_cross_organization_knowledge_base_is_hidden(client):
    first_headers, _ = create_organization_context(
        client,
        username="first-knowledge-admin",
        name="First Knowledge Tenant",
        slug="first-knowledge-tenant",
    )
    second_headers, _ = create_organization_context(
        client,
        username="second-knowledge-admin",
        name="Second Knowledge Tenant",
        slug="second-knowledge-tenant",
    )
    create_response = client.post(
        "/knowledge-bases",
        headers=first_headers,
        json={"name": "Private Knowledge"},
    )
    assert create_response.status_code == 201
    knowledge_base_id = create_response.json()["id"]

    read_response = client.get(
        f"/knowledge-bases/{knowledge_base_id}",
        headers=second_headers,
    )
    update_response = client.patch(
        f"/knowledge-bases/{knowledge_base_id}",
        headers=second_headers,
        json={"name": "Cross Tenant Update"},
    )

    assert read_response.status_code == 404
    assert update_response.status_code == 404
    assert read_response.json()["message"] == "knowledge base not found"
    assert update_response.json()["message"] == "knowledge base not found"


def test_duplicate_knowledge_base_name_returns_conflict(client):
    headers, _ = create_organization_context(
        client,
        username="duplicate-knowledge-admin",
        name="Duplicate Knowledge Organization",
        slug="duplicate-knowledge-organization",
    )
    first_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "Shared Knowledge"},
    )
    second_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "Shared Knowledge"},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["message"] == ("knowledge base name already exists")


def test_knowledge_base_rejects_blank_name_and_empty_update(client):
    headers, _ = create_organization_context(
        client,
        username="invalid-knowledge-admin",
        name="Invalid Knowledge Organization",
        slug="invalid-knowledge-organization",
    )
    create_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "Valid Knowledge"},
    )
    assert create_response.status_code == 201
    knowledge_base_id = create_response.json()["id"]

    blank_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": "   "},
    )
    empty_update_response = client.patch(
        f"/knowledge-bases/{knowledge_base_id}",
        headers=headers,
        json={},
    )

    assert blank_response.status_code == 422
    assert empty_update_response.status_code == 422
