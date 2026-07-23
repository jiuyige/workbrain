import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
from app.models import (
    LEGACY_ORGANIZATION_ID,
    LEGACY_ORGANIZATION_SLUG,
    Membership,
    MembershipRole,
    Organization,
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
    password = "organization-test-password"

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


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        (
            "POST",
            "/organizations",
            {
                "name": "Unauthorized Organization",
                "slug": "unauthorized-organization",
            },
        ),
        ("GET", "/organizations", None),
    ],
)
def test_organization_endpoints_require_authentication(
    client,
    method,
    path,
    json_body,
):
    request_kwargs = {}

    if json_body is not None:
        request_kwargs["json"] = json_body

    response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401


def test_create_organization_rejects_invalid_slug(client):
    headers = register_and_login(client, "invalid-slug-user")

    response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": "Invalid Slug Organization",
            "slug": "Invalid_Slug",
        },
    )

    assert response.status_code == 422


def test_create_organization_also_creates_admin_membership(client):
    headers = register_and_login(client, "organization-creator")

    response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": "  WorkBrain Technology  ",
            "slug": "workbrain-technology",
        },
    )

    assert response.status_code == 201

    payload = response.json()
    assert payload["name"] == "WorkBrain Technology"
    assert payload["slug"] == "workbrain-technology"
    assert payload["role"] == MembershipRole.ADMIN.value

    with Session(engine) as session:
        organization = session.exec(
            select(Organization).where(Organization.slug == "workbrain-technology")
        ).one()

        membership = session.exec(
            select(Membership).where(Membership.organization_id == organization.id)
        ).one()

        assert membership.user_id is not None
        assert membership.role == MembershipRole.ADMIN.value


def test_list_organizations_only_returns_current_user_memberships(client):
    first_headers = register_and_login(client, "first-organization-user")
    second_headers = register_and_login(client, "second-organization-user")

    first_create_response = client.post(
        "/organizations",
        headers=first_headers,
        json={
            "name": "First User Organization",
            "slug": "first-user-organization",
        },
    )
    assert first_create_response.status_code == 201

    second_create_response = client.post(
        "/organizations",
        headers=second_headers,
        json={
            "name": "Second User Organization",
            "slug": "second-user-organization",
        },
    )
    assert second_create_response.status_code == 201

    response = client.get(
        "/organizations",
        headers=first_headers,
    )

    assert response.status_code == 200

    organizations = response.json()["organizations"]
    organization_slugs = {organization["slug"] for organization in organizations}

    assert organization_slugs == {
        LEGACY_ORGANIZATION_SLUG,
        "first-user-organization",
    }
    assert "second-user-organization" not in organization_slugs
    created_organization = next(
        organization
        for organization in organizations
        if organization["slug"] == "first-user-organization"
    )

    assert created_organization["role"] == MembershipRole.ADMIN.value


def test_duplicate_organization_slug_returns_conflict(client):
    headers = register_and_login(client, "duplicate-slug-user")

    first_response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": "First Organization",
            "slug": "duplicate-organization",
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": "Second Organization",
            "slug": "duplicate-organization",
        },
    )

    assert second_response.status_code == 409
    assert second_response.json()["code"] == "CONFLICT"

    with Session(engine) as session:
        organizations = session.exec(
            select(Organization).where(Organization.slug == "duplicate-organization")
        ).all()
        memberships = session.exec(
            select(Membership).where(Membership.organization_id == organizations[0].id)
        ).all()

        assert len(organizations) == 1
        assert len(memberships) == 1


def test_membership_failure_rolls_back_organization(client):
    headers = register_and_login(client, "rollback-test-user")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TRIGGER fail_membership_insert
            BEFORE INSERT ON membership
            BEGIN
                SELECT RAISE(ABORT, 'forced membership insert failure');
            END
            """
        )

    try:
        response = client.post(
            "/organizations",
            headers=headers,
            json={
                "name": "Rollback Organization",
                "slug": "rollback-organization",
            },
        )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER fail_membership_insert")

    assert response.status_code == 409

    with Session(engine) as session:
        organization = session.exec(
            select(Organization).where(Organization.slug == "rollback-organization")
        ).first()
        memberships = session.exec(select(Membership)).all()

        assert organization is None
        assert len(memberships) == 1
        assert memberships[0].organization_id == (LEGACY_ORGANIZATION_ID)


def test_current_organization_requires_organization_header(client):
    headers = register_and_login(client, "missing-context-user")

    create_response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": "Missing Context Organization",
            "slug": "missing-context-organization",
        },
    )
    assert create_response.status_code == 201

    response = client.get(
        "/organizations/current",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["message"] == "organization context is required"


def test_current_organization_rejects_malformed_id(client):
    headers = register_and_login(client, "malformed-context-user")
    headers[ORGANIZATION_ID_HEADER] = "not-an-integer"

    response = client.get(
        "/organizations/current",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["message"] == ("organization id must be a positive integer")


def test_current_organization_rejects_nonexistent_id(client):
    headers = register_and_login(client, "nonexistent-context-user")
    headers[ORGANIZATION_ID_HEADER] = "999999"

    response = client.get(
        "/organizations/current",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["message"] == "organization access denied"


def test_current_organization_rejects_non_member(client):
    creator_headers = register_and_login(client, "context-creator")
    outsider_headers = register_and_login(client, "context-outsider")

    create_response = client.post(
        "/organizations",
        headers=creator_headers,
        json={
            "name": "Private Organization",
            "slug": "private-organization",
        },
    )
    assert create_response.status_code == 201

    organization_id = create_response.json()["id"]
    outsider_headers[ORGANIZATION_ID_HEADER] = str(organization_id)

    response = client.get(
        "/organizations/current",
        headers=outsider_headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["message"] == "organization access denied"


def test_current_organization_returns_member_context(client):
    headers = register_and_login(client, "valid-context-user")

    create_response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": "Current Organization",
            "slug": "current-organization",
        },
    )
    assert create_response.status_code == 201

    created_organization = create_response.json()
    headers[ORGANIZATION_ID_HEADER] = str(created_organization["id"])

    response = client.get(
        "/organizations/current",
        headers=headers,
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["id"] == created_organization["id"]
    assert payload["name"] == "Current Organization"
    assert payload["slug"] == "current-organization"
    assert payload["role"] == MembershipRole.ADMIN.value


def test_admin_can_invite_and_list_organization_members(client):
    admin_headers, _ = create_organization_context(
        client,
        username="member-admin",
        name="Member Management Organization",
        slug="member-management-organization",
    )
    register_and_login(client, "invited-approver")

    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "invited-approver",
            "role": MembershipRole.APPROVER.value,
        },
    )

    assert invite_response.status_code == 201
    invited_member = invite_response.json()
    assert invited_member["username"] == "invited-approver"
    assert invited_member["role"] == MembershipRole.APPROVER.value
    assert invited_member["is_active"] is True

    list_response = client.get(
        "/organizations/members",
        headers=admin_headers,
    )

    assert list_response.status_code == 200

    members = list_response.json()["members"]
    members_by_username = {member["username"]: member for member in members}

    assert set(members_by_username) == {
        "member-admin",
        "invited-approver",
    }
    assert members_by_username["member-admin"]["role"] == (MembershipRole.ADMIN.value)
    assert members_by_username["invited-approver"]["role"] == (
        MembershipRole.APPROVER.value
    )


def test_invite_member_rejects_unknown_role(client):
    admin_headers, _ = create_organization_context(
        client,
        username="invalid-role-admin",
        name="Invalid Role Organization",
        slug="invalid-role-organization",
    )
    register_and_login(client, "invalid-role-target")

    response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "invalid-role-target",
            "role": "owner",
        },
    )

    assert response.status_code == 422


def test_invite_member_rejects_duplicate_membership(client):
    admin_headers, _ = create_organization_context(
        client,
        username="duplicate-member-admin",
        name="Duplicate Member Organization",
        slug="duplicate-member-organization",
    )
    register_and_login(client, "duplicate-member-target")

    first_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "duplicate-member-target",
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "duplicate-member-target",
            "role": MembershipRole.ADMIN.value,
        },
    )

    assert second_response.status_code == 409
    assert second_response.json()["code"] == "CONFLICT"


def test_member_cannot_manage_organization_members(client):
    admin_headers, _ = create_organization_context(
        client,
        username="permission-admin",
        name="Permission Organization",
        slug="permission-organization",
    )
    member_headers = register_and_login(client, "permission-member")
    register_and_login(client, "permission-target")

    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "permission-member",
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert invite_response.status_code == 201

    membership_id = invite_response.json()["id"]
    member_headers[ORGANIZATION_ID_HEADER] = admin_headers[ORGANIZATION_ID_HEADER]

    responses = [
        client.post(
            "/organizations/members",
            headers=member_headers,
            json={
                "username": "permission-target",
                "role": MembershipRole.MEMBER.value,
            },
        ),
        client.get(
            "/organizations/members",
            headers=member_headers,
        ),
        client.patch(
            f"/organizations/members/{membership_id}/disable",
            headers=member_headers,
        ),
    ]

    for response in responses:
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"
        assert response.json()["message"] == ("organization admin access required")


def test_disabled_member_cannot_access_organization(client):
    admin_headers, _ = create_organization_context(
        client,
        username="disable-admin",
        name="Disable Member Organization",
        slug="disable-member-organization",
    )
    member_headers = register_and_login(client, "disabled-member")

    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={
            "username": "disabled-member",
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert invite_response.status_code == 201

    membership_id = invite_response.json()["id"]
    member_headers[ORGANIZATION_ID_HEADER] = admin_headers[ORGANIZATION_ID_HEADER]

    before_disable_response = client.get(
        "/organizations/current",
        headers=member_headers,
    )
    assert before_disable_response.status_code == 200

    disable_response = client.patch(
        f"/organizations/members/{membership_id}/disable",
        headers=admin_headers,
    )

    assert disable_response.status_code == 200
    assert disable_response.json()["is_active"] is False

    after_disable_response = client.get(
        "/organizations/current",
        headers=member_headers,
    )

    assert after_disable_response.status_code == 403
    assert after_disable_response.json()["code"] == "FORBIDDEN"
    assert after_disable_response.json()["message"] == ("organization access denied")


def test_disabled_membership_is_not_returned_in_organization_list(client):
    admin_headers, organization = create_organization_context(
        client,
        username="disabled-list-admin",
        name="Disabled List Organization",
        slug="disabled-list-organization",
    )
    member_headers = register_and_login(client, "disabled-list-member")
    invite_response = client.post(
        "/organizations/members",
        headers=admin_headers,
        json={"username": "disabled-list-member", "role": "member"},
    )
    assert invite_response.status_code == 201
    membership_id = invite_response.json()["id"]
    before_disable = client.get("/organizations", headers=member_headers)
    assert organization["id"] in {
        item["id"] for item in before_disable.json()["organizations"]
    }

    disable_response = client.patch(
        f"/organizations/members/{membership_id}/disable",
        headers=admin_headers,
    )
    after_disable = client.get("/organizations", headers=member_headers)

    assert disable_response.status_code == 200
    assert organization["id"] not in {
        item["id"] for item in after_disable.json()["organizations"]
    }


def test_registration_assigns_legacy_membership(client):
    headers = register_and_login(
        client,
        "legacy-membership-user",
    )

    response = client.get(
        "/organizations",
        headers=headers,
    )

    assert response.status_code == 200

    organizations = response.json()["organizations"]
    legacy_organization = next(
        organization
        for organization in organizations
        if organization["slug"] == LEGACY_ORGANIZATION_SLUG
    )

    assert legacy_organization["id"] == (LEGACY_ORGANIZATION_ID)
    assert legacy_organization["role"] == (MembershipRole.MEMBER.value)
