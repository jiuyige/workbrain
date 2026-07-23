from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"


def test_readme_documents_the_complete_implemented_product():
    content = README.read_text(encoding="utf-8")

    for capability in (
        "组织、成员与 RBAC",
        "Celery",
        "pgvector",
        "引用来源",
        "IT 服务目录",
        "申请审批与审计",
        "确认后创建",
        "React",
        "跨组织隔离",
    ):
        assert capability in content

    for path in (
        "/users/register",
        "/organizations",
        "/knowledge-bases",
        "/rag/knowledge-bases/{knowledge_base_id}/ask",
        "/service-catalog/items",
        "/service-requests",
        "/assistant/service-tools",
        "/assistant/service-tools/confirm",
    ):
        assert path in content


def test_readme_contains_reproducible_development_and_production_commands():
    content = README.read_text(encoding="utf-8")

    for command in (
        "docker compose -f docker-compose.yml -f docker-compose.dev.yml",
        "alembic upgrade head",
        "uvicorn app.main:app --reload",
        "celery -A app.celery_app:celery_app worker",
        "npm run dev",
        "docker compose up --build -d",
        "scripts/production_smoke.py --base-url",
        "python -m pytest -q",
        "ruff check .",
        "npm run test",
        "npm run lint",
        "npm run build",
    ):
        assert command in content

    assert content.count("```") % 2 == 0


def test_readme_links_supporting_docs_and_records_deployment_boundaries():
    content = README.read_text(encoding="utf-8")

    for documentation_path in (
        "doc/architecture.md",
        "doc/agent-framework-comparison.md",
        ".env.example",
    ):
        assert documentation_path in content

    for boundary in (
        "X-Organization-ID",
        "不能替代",
        "当前仓库不声明已经部署到公网",
        "不要提交 `.env`",
    ):
        assert boundary in content
