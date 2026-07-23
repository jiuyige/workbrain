import importlib

from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.middleware import REQUEST_ID_HEADER
from main import app

client = TestClient(app)


def test_existing_health_endpoint_remains_available():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers[REQUEST_ID_HEADER]


def test_liveness_does_not_access_database(monkeypatch):
    main_module = importlib.import_module("app.main")

    def fail_if_called():
        raise AssertionError("liveness must not access the database")

    monkeypatch.setattr(
        main_module,
        "check_database_connection",
        fail_if_called,
    )

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers[REQUEST_ID_HEADER]


def test_readiness_succeeds_when_database_is_available(monkeypatch):
    main_module = importlib.import_module("app.main")
    check_calls = []

    monkeypatch.setattr(
        main_module,
        "check_database_connection",
        lambda: check_calls.append("checked"),
    )
    monkeypatch.setattr(
        main_module,
        "check_broker_connection",
        lambda: check_calls.append("broker_checked"),
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers[REQUEST_ID_HEADER]
    assert check_calls == ["checked", "broker_checked"]


def test_readiness_fails_when_database_is_unavailable(monkeypatch):
    main_module = importlib.import_module("app.main")

    def fail_database_check():
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(
        main_module,
        "check_database_connection",
        fail_database_check,
    )

    response = client.get("/health/ready")

    assert response.status_code == 503

    payload = response.json()
    assert payload == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "database is not ready",
        "request_id": response.headers[REQUEST_ID_HEADER],
    }


def test_readiness_fails_when_broker_is_unavailable(monkeypatch):
    main_module = importlib.import_module("app.main")

    monkeypatch.setattr(
        main_module,
        "check_database_connection",
        lambda: None,
    )

    def fail_broker_check():
        raise RedisError("broker unavailable")

    monkeypatch.setattr(
        main_module,
        "check_broker_connection",
        fail_broker_check,
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "task broker is not ready",
        "request_id": response.headers[REQUEST_ID_HEADER],
    }
