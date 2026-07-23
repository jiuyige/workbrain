import argparse
import json
import os
import re
import secrets
import time
from importlib import import_module
from typing import Any

try:
    production_smoke = import_module("scripts.production_smoke")
except ModuleNotFoundError:
    production_smoke = import_module("production_smoke")
SmokeTestError = production_smoke.SmokeTestError
WorkBrainClient = production_smoke.WorkBrainClient
register_and_login = production_smoke.register_and_login
require = production_smoke.require

SUFFIX_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def seed_demo_data(
    client: Any,
    *,
    suffix: str,
    password: str,
) -> dict:
    readiness = client.request_json(
        "GET",
        "/health/ready",
        expected_status=200,
    )
    require(readiness == {"status": "ready"}, "API is not ready")

    usernames = {
        "admin": f"demo-admin-{suffix}",
        "approver": f"demo-approver-{suffix}",
        "member": f"demo-member-{suffix}",
    }
    tokens = {
        role: register_and_login(
            client,
            username=username,
            password=password,
        )
        for role, username in usernames.items()
    }

    organization = client.request_json(
        "POST",
        "/organizations",
        expected_status=201,
        body={
            "name": f"WorkBrain Demo {suffix}",
            "slug": f"workbrain-demo-{suffix}",
        },
        token=tokens["admin"],
    )
    organization_id = organization["id"]

    for role in ("approver", "member"):
        client.request_json(
            "POST",
            "/organizations/members",
            expected_status=201,
            body={
                "username": usernames[role],
                "role": role,
            },
            token=tokens["admin"],
            organization_id=organization_id,
        )

    knowledge_base = client.request_json(
        "POST",
        "/knowledge-bases",
        expected_status=201,
        body={
            "name": "Enterprise IT Service Handbook",
            "description": "Demo policies for cited enterprise RAG answers.",
        },
        token=tokens["admin"],
        organization_id=organization_id,
    )

    catalog_definitions = [
        {
            "name": "VPN Access",
            "description": "Secure remote access to internal systems.",
        },
        {
            "name": "Software Installation",
            "description": "Request approved software for a managed device.",
        },
        {
            "name": "Laptop Replacement",
            "description": "Replace a failed or end-of-life company laptop.",
        },
    ]
    catalog_items = []
    for definition in catalog_definitions:
        item = client.request_json(
            "POST",
            "/service-catalog/items",
            expected_status=201,
            body=definition,
            token=tokens["admin"],
            organization_id=organization_id,
        )
        catalog_items.append(
            {
                "id": item["id"],
                "name": definition["name"],
            }
        )

    request_definitions = [
        {
            "service_catalog_item_id": catalog_items[0]["id"],
            "title": "Remote-work VPN access",
            "description": "Access the source repository during on-call support.",
        },
        {
            "service_catalog_item_id": catalog_items[1]["id"],
            "title": "Install diagramming software",
            "description": "Create architecture diagrams for the platform team.",
        },
        {
            "service_catalog_item_id": catalog_items[2]["id"],
            "title": "Replace unstable development laptop",
            "description": "The device restarts during container builds.",
        },
    ]
    created_requests = [
        client.request_json(
            "POST",
            "/service-requests",
            expected_status=201,
            body=definition,
            token=tokens["member"],
            organization_id=organization_id,
        )
        for definition in request_definitions
    ]
    for request in created_requests:
        require(
            request["status"] == "pending",
            "demo request was not created pending",
        )

    approved = client.request_json(
        "POST",
        f"/service-requests/{created_requests[0]['id']}/approve",
        expected_status=200,
        token=tokens["approver"],
        organization_id=organization_id,
    )
    rejected = client.request_json(
        "POST",
        f"/service-requests/{created_requests[1]['id']}/reject",
        expected_status=200,
        body={"reason": "License justification is required."},
        token=tokens["approver"],
        organization_id=organization_id,
    )
    require(approved["status"] == "approved", "demo approval failed")
    require(rejected["status"] == "rejected", "demo rejection failed")

    expected_events = {
        approved["id"]: ["create", "approve"],
        rejected["id"]: ["create", "reject"],
    }
    for request_id, expected_actions in expected_events.items():
        events = client.request_json(
            "GET",
            f"/service-requests/{request_id}/events",
            expected_status=200,
            token=tokens["member"],
            organization_id=organization_id,
        )
        actions = [event["action"] for event in events["events"]]
        require(
            actions == expected_actions,
            f"demo request {request_id} audit trail is incomplete",
        )

    return {
        "status": "seeded",
        "organization_id": organization_id,
        "knowledge_base_id": knowledge_base["id"],
        "credentials": {
            role: {"username": username} for role, username in usernames.items()
        }
        | {"password": password},
        "catalog_items": catalog_items,
        "service_requests": [
            {
                "id": approved["id"],
                "title": request_definitions[0]["title"],
                "status": approved["status"],
            },
            {
                "id": rejected["id"],
                "title": request_definitions[1]["title"],
                "status": rejected["status"],
            },
            {
                "id": created_requests[2]["id"],
                "title": request_definitions[2]["title"],
                "status": created_requests[2]["status"],
            },
        ],
        "sample_document": "evals/enterprise_it_service_handbook.md",
    }


def validate_suffix(value: str) -> str:
    if len(value) > 24 or SUFFIX_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "suffix must contain at most 24 lowercase letters, numbers, or hyphens"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a complete WorkBrain portfolio demo dataset."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WORKBRAIN_BASE_URL", "http://localhost"),
    )
    parser.add_argument(
        "--suffix",
        help="Optional lowercase suffix for repeatable demo usernames.",
    )
    parser.add_argument(
        "--password",
        help="Optional shared demo password; a random value is used by default.",
    )
    args = parser.parse_args()

    raw_suffix = args.suffix or f"{int(time.time())}-{secrets.token_hex(3)}"
    try:
        suffix = validate_suffix(raw_suffix)
    except ValueError as error:
        parser.error(str(error))

    password = args.password or f"Demo-{secrets.token_urlsafe(18)}"
    if len(password) < 8:
        parser.error("password must contain at least 8 characters")

    client = WorkBrainClient(args.base_url)
    try:
        result = seed_demo_data(
            client,
            suffix=suffix,
            password=password,
        )
    except SmokeTestError as error:
        parser.exit(status=1, message=f"demo seed failed: {error}\n")

    result["base_url"] = args.base_url.rstrip("/")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
