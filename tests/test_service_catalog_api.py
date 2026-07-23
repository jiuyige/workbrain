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


def register_and_login(client: TestClient, username: str) -> dict[str, str]:
    password = "service-catalog-password"
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


def create_organization_context(
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
        json={"username": username, "role": MembershipRole.MEMBER.value},
    )
    assert response.status_code == 201
    member_headers[ORGANIZATION_ID_HEADER] = admin_headers[ORGANIZATION_ID_HEADER]
    return member_headers


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/service-catalog/items", None),
        ("POST", "/service-catalog/items", {"name": "VPN Access"}),
        ("GET", "/service-catalog/items/1", None),
        ("PATCH", "/service-catalog/items/1", {"name": "VPN"}),
    ],
)
def test_service_catalog_endpoints_require_authentication(
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


def test_admin_can_create_update_deactivate_and_reactivate_catalog_item(client):
    headers, organization_id = create_organization_context(
        client,
        username="catalog-admin",
        slug="catalog-admin-organization",
    )
    create_response = client.post(
        "/service-catalog/items",
        headers=headers,
        json={
            "name": "  VPN Access  ",
            "description": "  Request corporate VPN access.  ",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["organization_id"] == organization_id
    assert created["name"] == "VPN Access"
    assert created["description"] == "Request corporate VPN access."
    assert created["is_active"] is True

    list_response = client.get("/service-catalog/items", headers=headers)
    read_response = client.get(
        f"/service-catalog/items/{created['id']}",
        headers=headers,
    )
    deactivate_response = client.patch(
        f"/service-catalog/items/{created['id']}",
        headers=headers,
        json={"name": "Corporate VPN", "is_active": False},
    )
    hidden_list_response = client.get("/service-catalog/items", headers=headers)
    hidden_read_response = client.get(
        f"/service-catalog/items/{created['id']}",
        headers=headers,
    )
    admin_list_response = client.get(
        "/service-catalog/items",
        headers=headers,
        params={"include_inactive": True},
    )
    admin_read_response = client.get(
        f"/service-catalog/items/{created['id']}",
        headers=headers,
        params={"include_inactive": True},
    )
    reactivate_response = client.patch(
        f"/service-catalog/items/{created['id']}",
        headers=headers,
        json={"is_active": True},
    )

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [created["id"]]
    assert read_response.status_code == 200
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["name"] == "Corporate VPN"
    assert deactivate_response.json()["is_active"] is False
    assert hidden_list_response.json()["items"] == []
    assert hidden_read_response.status_code == 404
    assert admin_list_response.status_code == 200
    assert admin_list_response.json()["items"][0]["is_active"] is False
    assert admin_read_response.status_code == 200
    assert admin_read_response.json()["is_active"] is False
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["is_active"] is True


def test_member_can_read_but_cannot_manage_service_catalog(client):
    admin_headers, _ = create_organization_context(
        client,
        username="catalog-member-admin",
        slug="catalog-member-organization",
    )
    created = client.post(
        "/service-catalog/items",
        headers=admin_headers,
        json={"name": "Laptop Repair"},
    ).json()
    member_headers = invite_member(
        client,
        admin_headers=admin_headers,
        username="catalog-member",
    )

    list_response = client.get("/service-catalog/items", headers=member_headers)
    read_response = client.get(
        f"/service-catalog/items/{created['id']}",
        headers=member_headers,
    )
    create_response = client.post(
        "/service-catalog/items",
        headers=member_headers,
        json={"name": "Forbidden Service"},
    )
    update_response = client.patch(
        f"/service-catalog/items/{created['id']}",
        headers=member_headers,
        json={"is_active": False},
    )
    inactive_list_response = client.get(
        "/service-catalog/items",
        headers=member_headers,
        params={"include_inactive": True},
    )
    inactive_read_response = client.get(
        f"/service-catalog/items/{created['id']}",
        headers=member_headers,
        params={"include_inactive": True},
    )

    assert list_response.status_code == 200
    assert read_response.status_code == 200
    assert create_response.status_code == 403
    assert update_response.status_code == 403
    assert inactive_list_response.status_code == 403
    assert inactive_read_response.status_code == 403
    assert create_response.json()["message"] == "organization admin access required"


def test_cross_organization_catalog_item_is_hidden(client):
    first_headers, _ = create_organization_context(
        client,
        username="first-catalog-admin",
        slug="first-catalog-organization",
    )
    second_headers, _ = create_organization_context(
        client,
        username="second-catalog-admin",
        slug="second-catalog-organization",
    )
    created = client.post(
        "/service-catalog/items",
        headers=first_headers,
        json={"name": "Private Service"},
    ).json()

    read_response = client.get(
        f"/service-catalog/items/{created['id']}",
        headers=second_headers,
    )
    update_response = client.patch(
        f"/service-catalog/items/{created['id']}",
        headers=second_headers,
        json={"name": "Cross Organization Update"},
    )

    assert read_response.status_code == 404
    assert update_response.status_code == 404
    assert read_response.json()["message"] == "service catalog item not found"


def test_duplicate_catalog_item_name_returns_conflict(client):
    headers, _ = create_organization_context(
        client,
        username="duplicate-catalog-admin",
        slug="duplicate-catalog-organization",
    )
    first_response = client.post(
        "/service-catalog/items",
        headers=headers,
        json={"name": "Email Account"},
    )
    second_response = client.post(
        "/service-catalog/items",
        headers=headers,
        json={"name": "Email Account"},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["message"] == (
        "service catalog item name already exists"
    )


def test_service_catalog_rejects_blank_name_and_empty_update(client):
    headers, _ = create_organization_context(
        client,
        username="invalid-catalog-admin",
        slug="invalid-catalog-organization",
    )
    created = client.post(
        "/service-catalog/items",
        headers=headers,
        json={"name": "Valid Service"},
    ).json()

    blank_response = client.post(
        "/service-catalog/items",
        headers=headers,
        json={"name": "   "},
    )
    empty_update_response = client.patch(
        f"/service-catalog/items/{created['id']}",
        headers=headers,
        json={},
    )

    assert blank_response.status_code == 422
    assert empty_update_response.status_code == 422


def test_service_catalog_list_supports_pagination(client):
    headers, _ = create_organization_context(
        client,
        username="catalog-pagination-admin",
        slug="catalog-pagination-organization",
    )

    for name in ["Software Installation", "Laptop Repair", "Email Account"]:
        response = client.post(
            "/service-catalog/items",
            headers=headers,
            json={"name": name},
        )
        assert response.status_code == 201

    first_page = client.get(
        "/service-catalog/items",
        headers=headers,
        params={"offset": 0, "limit": 2},
    )
    second_page = client.get(
        "/service-catalog/items",
        headers=headers,
        params={"offset": 2, "limit": 2},
    )

    assert first_page.status_code == 200
    assert [item["name"] for item in first_page.json()["items"]] == [
        "Email Account",
        "Laptop Repair",
    ]
    assert first_page.json()["pagination"] == {
        "offset": 0,
        "limit": 2,
        "total": 3,
        "returned": 2,
    }
    assert [item["name"] for item in second_page.json()["items"]] == [
        "Software Installation"
    ]
    assert second_page.json()["pagination"] == {
        "offset": 2,
        "limit": 2,
        "total": 3,
        "returned": 1,
    }


def test_service_catalog_list_rejects_invalid_pagination(client):
    headers, _ = create_organization_context(
        client,
        username="catalog-invalid-pagination",
        slug="catalog-invalid-pagination",
    )

    for query in ["offset=-1&limit=20", "offset=0&limit=0", "offset=0&limit=101"]:
        response = client.get(
            f"/service-catalog/items?{query}",
            headers=headers,
        )
        assert response.status_code == 422
