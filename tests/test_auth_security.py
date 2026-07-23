from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.config import ALGORITHM, SECRET_KEY
from app.database import get_session
from app.models import User
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


def register(client: TestClient, username: str, password: str = "secure-password"):
    return client.post(
        "/users/register",
        json={"username": username, "password": password},
    )


def login(client: TestClient, username: str, password: str = "secure-password"):
    response = client.post(
        "/users/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sub": "jwt-user",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        {
            "sub": ["jwt-user"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
    ],
)
def test_invalid_jwt_claims_are_rejected(client, payload):
    assert register(client, "jwt-user").status_code == 200
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["message"] == "could not validate credentials"


def test_jwt_signed_with_another_secret_is_rejected(client):
    assert register(client, "signed-user").status_code == 200
    token = jwt.encode(
        {
            "sub": "signed-user",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "another-secret-key-that-is-not-valid",
        algorithm=ALGORITHM,
    )

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("valid-user", "short"),
        ("contains spaces", "secure-password"),
        ("x" * 51, "secure-password"),
    ],
)
def test_registration_rejects_unsafe_credentials(client, username, password):
    response = register(client, username, password)

    assert response.status_code == 422
    with Session(engine) as session:
        assert session.exec(select(User)).all() == []


def test_user_listing_does_not_disclose_other_accounts(client):
    assert register(client, "visible-user").status_code == 200
    assert register(client, "private-user").status_code == 200
    token = login(client, "visible-user")

    response = client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "users": [{"id": response.json()["users"][0]["id"], "username": "visible-user"}]
    }
