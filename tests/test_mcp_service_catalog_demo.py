import asyncio

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import Organization, ServiceCatalogItem, User
from experiments import mcp_service_catalog_server

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture(autouse=True)
def reset_database(monkeypatch):
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(mcp_service_catalog_server, "engine", engine)


def seed_catalog() -> tuple[int, int]:
    with Session(engine) as session:
        user = User(username="mcp-admin", hashed_password="unused")
        first_organization = Organization(name="MCP First", slug="mcp-first")
        second_organization = Organization(name="MCP Second", slug="mcp-second")
        session.add_all([user, first_organization, second_organization])
        session.flush()
        session.add_all(
            [
                ServiceCatalogItem(
                    organization_id=first_organization.id,
                    created_by_user_id=user.id,
                    name="VPN Access",
                    description="Secure remote access",
                ),
                ServiceCatalogItem(
                    organization_id=first_organization.id,
                    created_by_user_id=user.id,
                    name="Retired Laptop Service",
                    is_active=False,
                ),
                ServiceCatalogItem(
                    organization_id=second_organization.id,
                    created_by_user_id=user.id,
                    name="Other Organization Service",
                ),
            ]
        )
        session.commit()
        return first_organization.id, second_organization.id


def test_mcp_demo_registers_one_read_only_tool_without_organization_arguments():
    tools = asyncio.run(mcp_service_catalog_server.mcp.list_tools())

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "list_active_it_services"
    assert tool.inputSchema["properties"] == {}
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False


def test_mcp_demo_only_returns_active_items_from_configured_organization(monkeypatch):
    first_organization_id, _ = seed_catalog()
    monkeypatch.setenv(
        "WORKBRAIN_MCP_ORGANIZATION_ID",
        str(first_organization_id),
    )

    _, structured_result = asyncio.run(
        mcp_service_catalog_server.mcp.call_tool(
            "list_active_it_services",
            {},
        )
    )

    assert structured_result == {
        "organization_id": first_organization_id,
        "items": [
            {
                "id": 1,
                "name": "VPN Access",
                "description": "Secure remote access",
            }
        ],
    }


@pytest.mark.parametrize("value", [None, "", "0", "not-an-integer"])
def test_mcp_demo_rejects_missing_or_invalid_organization_scope(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("WORKBRAIN_MCP_ORGANIZATION_ID", raising=False)
    else:
        monkeypatch.setenv("WORKBRAIN_MCP_ORGANIZATION_ID", value)

    with pytest.raises(RuntimeError, match="WORKBRAIN_MCP_ORGANIZATION_ID"):
        mcp_service_catalog_server.get_configured_organization_id()
