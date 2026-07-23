import argparse
import json
import os
import secrets
import time
import urllib.error
import urllib.request


class SmokeTestError(RuntimeError):
    pass


class WorkBrainClient:
    def __init__(self, base_url: str, timeout: float = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request_text(self, path: str) -> str:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status != 200:
                raise SmokeTestError(f"GET {path} returned HTTP {response.status}")
            return response.read().decode("utf-8")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        body: dict | None = None,
        token: str | None = None,
        organization_id: int | None = None,
    ) -> dict:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if organization_id is not None:
            headers["X-Organization-ID"] = str(organization_id)

        request = urllib.request.Request(
            f"{self.base_url}/api{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            response_body = error.read().decode("utf-8", errors="replace")
            raise SmokeTestError(
                f"{method} {path} returned HTTP {error.code}: {response_body}"
            ) from error

        if status != expected_status:
            raise SmokeTestError(
                f"{method} {path} returned HTTP {status}, expected {expected_status}"
            )
        return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeTestError(message)


def register_and_login(
    client: WorkBrainClient,
    *,
    username: str,
    password: str,
) -> str:
    client.request_json(
        "POST",
        "/users/register",
        expected_status=200,
        body={"username": username, "password": password},
    )
    login = client.request_json(
        "POST",
        "/users/login",
        expected_status=200,
        body={"username": username, "password": password},
    )
    require(login.get("token_type") == "bearer", "login did not return bearer token")
    return login["access_token"]


def poll_job_until_finished(
    client: WorkBrainClient,
    *,
    job_id: int,
    token: str,
    organization_id: int,
    timeout_seconds: float = 30,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = client.request_json(
            "GET",
            f"/jobs/{job_id}",
            expected_status=200,
            token=token,
            organization_id=organization_id,
        )
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            require(
                job["status"] == "succeeded", f"background job ended as {job['status']}"
            )
            return job
        time.sleep(0.5)
    raise SmokeTestError("background job did not finish before timeout")


def run_smoke(base_url: str) -> dict:
    client = WorkBrainClient(base_url)
    suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
    admin_username = f"smoke-admin-{suffix}"
    member_username = f"smoke-member-{suffix}"
    password = f"Sm0ke-{secrets.token_urlsafe(18)}"

    homepage = client.request_text("/")
    spa_page = client.request_text("/service-requests")
    require("<title>WorkBrain</title>" in homepage, "frontend homepage is invalid")
    require("<title>WorkBrain</title>" in spa_page, "SPA route fallback is invalid")

    readiness = client.request_json(
        "GET",
        "/health/ready",
        expected_status=200,
    )
    require(readiness == {"status": "ready"}, "API is not ready")

    admin_token = register_and_login(
        client,
        username=admin_username,
        password=password,
    )
    member_token = register_and_login(
        client,
        username=member_username,
        password=password,
    )

    organization = client.request_json(
        "POST",
        "/organizations",
        expected_status=201,
        body={"name": f"Smoke Organization {suffix}", "slug": f"smoke-{suffix}"},
        token=admin_token,
    )
    organization_id = organization["id"]

    client.request_json(
        "POST",
        "/organizations/members",
        expected_status=201,
        body={"username": member_username, "role": "member"},
        token=admin_token,
        organization_id=organization_id,
    )
    knowledge_base = client.request_json(
        "POST",
        "/knowledge-bases",
        expected_status=201,
        body={"name": f"Smoke Knowledge Base {suffix}"},
        token=admin_token,
        organization_id=organization_id,
    )
    catalog_item = client.request_json(
        "POST",
        "/service-catalog/items",
        expected_status=201,
        body={
            "name": f"Smoke VPN {suffix}",
            "description": "Production smoke-test service.",
        },
        token=admin_token,
        organization_id=organization_id,
    )
    service_request = client.request_json(
        "POST",
        "/service-requests",
        expected_status=201,
        body={
            "service_catalog_item_id": catalog_item["id"],
            "title": "Production smoke request",
            "description": "Verify the deployed approval workflow.",
        },
        token=member_token,
        organization_id=organization_id,
    )
    require(service_request["status"] == "pending", "request was not created pending")

    approved_request = client.request_json(
        "POST",
        f"/service-requests/{service_request['id']}/approve",
        expected_status=200,
        token=admin_token,
        organization_id=organization_id,
    )
    require(approved_request["status"] == "approved", "request was not approved")
    events = client.request_json(
        "GET",
        f"/service-requests/{service_request['id']}/events",
        expected_status=200,
        token=member_token,
        organization_id=organization_id,
    )
    require(
        [event["action"] for event in events["events"]] == ["create", "approve"],
        "request audit trail is incomplete",
    )

    queued_job = client.request_json(
        "POST",
        "/jobs/example",
        expected_status=202,
        body={"should_fail": False},
        token=member_token,
        organization_id=organization_id,
    )
    finished_job = poll_job_until_finished(
        client,
        job_id=queued_job["id"],
        token=member_token,
        organization_id=organization_id,
    )

    return {
        "status": "passed",
        "organization_id": organization_id,
        "knowledge_base_id": knowledge_base["id"],
        "service_request_id": service_request["id"],
        "background_job_id": finished_job["id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the WorkBrain production smoke test"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WORKBRAIN_BASE_URL", "http://localhost"),
    )
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.base_url), ensure_ascii=False))


if __name__ == "__main__":
    main()
