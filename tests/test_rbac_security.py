import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.context import (
    ORGANIZATION_ID_HEADER,
    OrganizationContext,
)
from app.database import get_session
from app.models import (
    Membership,
    MembershipRole,
    Organization,
)
from app.policies import enforce_organization_roles
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
    password = "rbac-security-password"

    register_response = client.post(
        "/users/register",
        json={
            "username": username,
            "password": password,
        },
    )
    assert register_response.status_code == 200

    login_response = client.post(
        "/users/login",
        json={
            "username": username,
            "password": password,
        },
    )
    assert login_response.status_code == 200

    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


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
        json={
            "name": name,
            "slug": slug,
        },
    )
    assert response.status_code == 201

    organization = response.json()
    headers[ORGANIZATION_ID_HEADER] = str(organization["id"])

    return headers, organization


def make_policy_context(
    role: MembershipRole,
) -> OrganizationContext:
    organization = Organization(
        id=1,
        name="Policy Organization",
        slug="policy-organization",
    )
    membership = Membership(
        id=1,
        organization_id=1,
        user_id=1,
        role=role.value,
    )

    return OrganizationContext(
        organization=organization,
        membership=membership,
    )


@pytest.mark.parametrize(
    ("role", "is_allowed"),
    [
        (MembershipRole.ADMIN, True),
        (MembershipRole.APPROVER, False),
        (MembershipRole.MEMBER, False),
    ],
)
def test_admin_policy_role_matrix(role, is_allowed):
    context = make_policy_context(role)

    if is_allowed:
        result = enforce_organization_roles(
            context,
            allowed_roles=(MembershipRole.ADMIN,),
            detail="organization admin access required",
        )

        assert result is context
        return

    with pytest.raises(HTTPException) as exception:
        enforce_organization_roles(
            context,
            allowed_roles=(MembershipRole.ADMIN,),
            detail="organization admin access required",
        )

    assert exception.value.status_code == 403
    assert exception.value.detail == ("organization admin access required")


def test_user_cannot_read_another_organization_resources(client):
    first_headers, _ = create_organization_context(
        client,
        username="first-tenant-admin",
        name="First Tenant",
        slug="first-tenant",
    )
    _, second_organization = create_organization_context(
        client,
        username="second-tenant-admin",
        name="Second Tenant",
        slug="second-tenant",
    )

    forged_headers = dict(first_headers)
    forged_headers[ORGANIZATION_ID_HEADER] = str(second_organization["id"])

    responses = [
        client.get(
            "/organizations/current",
            headers=forged_headers,
        ),
        client.get(
            "/organizations/members",
            headers=forged_headers,
        ),
    ]

    for response in responses:
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"
        assert response.json()["message"] == ("organization access denied")


def test_admin_cannot_disable_another_organization_membership(client):
    first_headers, _ = create_organization_context(
        client,
        username="first-disable-admin",
        name="First Disable Tenant",
        slug="first-disable-tenant",
    )
    second_headers, _ = create_organization_context(
        client,
        username="second-disable-admin",
        name="Second Disable Tenant",
        slug="second-disable-tenant",
    )
    register_and_login(client, "second-tenant-member")

    invite_response = client.post(
        "/organizations/members",
        headers=second_headers,
        json={
            "username": "second-tenant-member",
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert invite_response.status_code == 201

    second_membership_id = invite_response.json()["id"]

    cross_tenant_response = client.patch(
        (f"/organizations/members/{second_membership_id}/disable"),
        headers=first_headers,
    )
    missing_resource_response = client.patch(
        "/organizations/members/999999/disable",
        headers=first_headers,
    )

    assert cross_tenant_response.status_code == 404
    assert missing_resource_response.status_code == 404
    assert cross_tenant_response.json()["message"] == ("organization member not found")
    assert missing_resource_response.json()["message"] == (
        "organization member not found"
    )

    with Session(engine) as session:
        membership = session.get(
            Membership,
            second_membership_id,
        )

        assert membership is not None
        assert membership.is_active is True


def test_admin_cannot_disable_own_active_membership(client):
    headers, _ = create_organization_context(
        client,
        username="self-disable-admin",
        name="Self Disable Tenant",
        slug="self-disable-tenant",
    )
    members_response = client.get(
        "/organizations/members",
        headers=headers,
    )
    admin_membership = next(
        member
        for member in members_response.json()["members"]
        if member["username"] == "self-disable-admin"
    )

    response = client.patch(
        f"/organizations/members/{admin_membership['id']}/disable",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["message"] == "cannot disable own membership"
    assert client.get("/organizations/current", headers=headers).status_code == 200


def test_role_is_scoped_to_each_organization(client):
    dual_user_headers, _ = create_organization_context(
        client,
        username="dual-role-user",
        name="Admin Tenant",
        slug="admin-tenant",
    )
    second_admin_headers, second_organization = create_organization_context(
        client,
        username="dual-role-second-admin",
        name="Member Tenant",
        slug="member-tenant",
    )

    invite_response = client.post(
        "/organizations/members",
        headers=second_admin_headers,
        json={
            "username": "dual-role-user",
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert invite_response.status_code == 201

    admin_response = client.get(
        "/organizations/members",
        headers=dual_user_headers,
    )
    assert admin_response.status_code == 200

    member_headers = dict(dual_user_headers)
    member_headers[ORGANIZATION_ID_HEADER] = str(second_organization["id"])

    member_response = client.get(
        "/organizations/members",
        headers=member_headers,
    )

    assert member_response.status_code == 403
    assert member_response.json()["code"] == "FORBIDDEN"
    assert member_response.json()["message"] == ("organization admin access required")
