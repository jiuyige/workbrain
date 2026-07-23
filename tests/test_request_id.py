import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient

from app.middleware import REQUEST_ID_HEADER, request_logger
from main import app

client = TestClient(app)


def test_response_generates_request_id_when_header_is_missing():
    response = client.get("/health")

    assert response.status_code == 200

    request_id = response.headers[REQUEST_ID_HEADER]
    UUID(request_id)


def test_response_reuses_valid_client_request_id():
    client_request_id = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(
        "/health",
        headers={REQUEST_ID_HEADER: client_request_id},
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == client_request_id


def test_invalid_client_request_id_is_replaced():
    response = client.get(
        "/health",
        headers={REQUEST_ID_HEADER: "not-a-uuid"},
    )

    assert response.status_code == 200

    response_request_id = response.headers[REQUEST_ID_HEADER]
    assert response_request_id != "not-a-uuid"
    UUID(response_request_id)


def test_authentication_error_response_contains_request_id():
    response = client.get("/users")

    assert response.status_code == 401

    request_id = response.headers[REQUEST_ID_HEADER]
    UUID(request_id)


def test_request_log_contains_safe_operational_fields(caplog):
    request_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="workbrain.request"):
            response = client.get("/health")
    finally:
        request_logger.removeHandler(caplog.handler)

    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "workbrain.request"
    ]

    assert records == [
        {
            "event": "http_request",
            "request_id": response.headers[REQUEST_ID_HEADER],
            "method": "GET",
            "path": "/health",
            "status_code": 200,
            "duration_ms": records[0]["duration_ms"],
        }
    ]
    assert isinstance(records[0]["duration_ms"], float)
    assert records[0]["duration_ms"] >= 0
