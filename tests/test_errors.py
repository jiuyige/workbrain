from uuid import UUID

from fastapi.testclient import TestClient

from app.middleware import REQUEST_ID_HEADER
from main import app

client = TestClient(app)


def assert_error_response(
    response,
    *,
    expected_status: int,
    expected_code: str,
    expected_message: str,
):
    assert response.status_code == expected_status

    payload = response.json()

    assert payload == {
        "code": expected_code,
        "message": expected_message,
        "request_id": response.headers[REQUEST_ID_HEADER],
    }

    UUID(payload["request_id"])


def test_not_found_uses_standard_error_response():
    client_request_id = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(
        "/route-that-does-not-exist",
        headers={REQUEST_ID_HEADER: client_request_id},
    )

    assert_error_response(
        response,
        expected_status=404,
        expected_code="NOT_FOUND",
        expected_message="Not Found",
    )
    assert response.json()["request_id"] == client_request_id


def test_authentication_error_uses_standard_error_response():
    response = client.get("/users")

    assert_error_response(
        response,
        expected_status=401,
        expected_code="AUTHENTICATION_REQUIRED",
        expected_message="Not authenticated",
    )


def test_validation_error_uses_standard_error_response():
    response = client.post(
        "/users/register",
        json={},
    )

    assert_error_response(
        response,
        expected_status=422,
        expected_code="VALIDATION_ERROR",
        expected_message="request validation failed",
    )
