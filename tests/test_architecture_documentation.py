from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DOCUMENT = PROJECT_ROOT / "doc" / "architecture.md"


def test_architecture_document_covers_the_implemented_system_and_core_flows():
    content = ARCHITECTURE_DOCUMENT.read_text(encoding="utf-8")

    for implemented_component in (
        "React",
        "Caddy",
        "Nginx",
        "FastAPI",
        "Celery Worker",
        "Redis AOF",
        "PostgreSQL",
        "pgvector",
        "DeepSeek",
        "OpenAI Embeddings",
    ):
        assert implemented_component in content

    assert content.count("```mermaid") == 3
    assert "Document ingestion to cited RAG answer" in content
    assert "Agent service request confirmation and approval" in content
    assert "https://www.figma.com/board/fF2aP8n862VyO7EXWZdQjR" in content


def test_architecture_document_records_security_and_reliability_boundaries():
    content = ARCHITECTURE_DOCUMENT.read_text(encoding="utf-8")

    for boundary in (
        "organization_id",
        "member / approver / admin",
        "原子领取",
        "幂等",
        "确认令牌只保存哈希",
        "仅公开 80/443",
        "MCP Demo 不属于生产运行架构",
    ):
        assert boundary in content

    for unimplemented_component in ("Kafka", "Kubernetes", "LangGraph 生产运行时"):
        assert unimplemented_component not in content
