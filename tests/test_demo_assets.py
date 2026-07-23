import subprocess
import sys
from importlib import import_module
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeWorkBrainClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.catalog_item_id = 300
        self.service_request_id = 400

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
        self.calls.append(
            {
                "method": method,
                "path": path,
                "expected_status": expected_status,
                "body": body,
                "token": token,
                "organization_id": organization_id,
            }
        )

        if path == "/health/ready":
            return {"status": "ready"}
        if path == "/users/register":
            return {"message": "register success"}
        if path == "/users/login":
            return {
                "access_token": f"{body['username']}-token",
                "token_type": "bearer",
            }
        if path == "/organizations" and method == "POST":
            return {"id": 100}
        if path == "/organizations/members":
            return {"id": len(self.calls)}
        if path == "/knowledge-bases":
            return {"id": 200}
        if path == "/service-catalog/items":
            self.catalog_item_id += 1
            return {"id": self.catalog_item_id}
        if path == "/service-requests":
            self.service_request_id += 1
            return {
                "id": self.service_request_id,
                "status": "pending",
            }
        if path.endswith("/approve"):
            return {
                "id": 401,
                "status": "approved",
            }
        if path.endswith("/reject"):
            return {
                "id": 402,
                "status": "rejected",
            }
        if path == "/service-requests/401/events":
            return {
                "events": [
                    {"action": "create"},
                    {"action": "approve"},
                ]
            }
        if path == "/service-requests/402/events":
            return {
                "events": [
                    {"action": "create"},
                    {"action": "reject"},
                ]
            }

        raise AssertionError(f"unexpected request: {method} {path}")


def test_demo_seed_builds_roles_catalog_and_all_request_states():
    demo_seed = import_module("scripts.seed_demo_data")
    client = FakeWorkBrainClient()

    result = demo_seed.seed_demo_data(
        client,
        suffix="portfolio",
        password="Demo-password-123",
    )

    assert result["status"] == "seeded"
    assert result["organization_id"] == 100
    assert result["knowledge_base_id"] == 200
    assert result["credentials"]["admin"]["username"] == "demo-admin-portfolio"
    assert result["credentials"]["approver"]["username"] == ("demo-approver-portfolio")
    assert result["credentials"]["member"]["username"] == "demo-member-portfolio"
    assert [item["status"] for item in result["service_requests"]] == [
        "approved",
        "rejected",
        "pending",
    ]

    membership_roles = [
        call["body"]["role"]
        for call in client.calls
        if call["path"] == "/organizations/members"
    ]
    assert membership_roles == ["approver", "member"]

    decision_calls = [
        (call["method"], call["path"], call["token"], call["body"])
        for call in client.calls
        if call["path"].endswith(("/approve", "/reject"))
    ]
    assert decision_calls == [
        (
            "POST",
            "/service-requests/401/approve",
            "demo-approver-portfolio-token",
            None,
        ),
        (
            "POST",
            "/service-requests/402/reject",
            "demo-approver-portfolio-token",
            {"reason": "License justification is required."},
        ),
    ]


def test_demo_seed_cli_can_be_started_as_a_script():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "seed_demo_data.py"),
            "--help",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Create a complete WorkBrain portfolio demo dataset." in (completed.stdout)


def test_demo_and_career_documents_are_linked_and_honest():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    demo_guide = (PROJECT_ROOT / "doc" / "demo-guide.md").read_text(encoding="utf-8")
    career_guide = (PROJECT_ROOT / "doc" / "resume-and-interview.md").read_text(
        encoding="utf-8"
    )

    assert "scripts/seed_demo_data.py --base-url" in readme
    assert "doc/demo-guide.md" in readme
    assert "doc/resume-and-interview.md" in readme

    for demo_section in (
        "录制前检查",
        "5 分钟演示脚本",
        "Agent 确认",
        "跨组织隔离",
        "evals/enterprise_it_service_handbook.md",
    ):
        assert demo_section in demo_guide

    for career_section in (
        "简历项目描述",
        "30 秒介绍",
        "两阶段确认",
        "为什么没有使用 LangGraph",
        "不能声称",
    ):
        assert career_section in career_guide
