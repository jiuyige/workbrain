import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import engine
from app.models import ServiceCatalogItem

mcp = FastMCP(
    "WorkBrain Service Catalog Demo",
    instructions=(
        "Read-only access to active IT services in one server-configured organization."
    ),
)


class ServiceItemResult(BaseModel):
    id: int
    name: str
    description: str | None


class ServiceCatalogResult(BaseModel):
    organization_id: int
    items: list[ServiceItemResult]


def get_configured_organization_id() -> int:
    raw_value = os.getenv("WORKBRAIN_MCP_ORGANIZATION_ID", "").strip()
    try:
        organization_id = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "WORKBRAIN_MCP_ORGANIZATION_ID must be a positive integer"
        ) from exc

    if organization_id <= 0:
        raise RuntimeError("WORKBRAIN_MCP_ORGANIZATION_ID must be a positive integer")
    return organization_id


@mcp.tool(
    title="List active WorkBrain IT services",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=True,
)
def list_active_it_services() -> ServiceCatalogResult:
    """List active IT services in the organization configured for this server."""
    organization_id = get_configured_organization_id()
    with Session(engine) as session:
        items = session.exec(
            select(ServiceCatalogItem)
            .where(
                ServiceCatalogItem.organization_id == organization_id,
                ServiceCatalogItem.is_active.is_(True),
            )
            .order_by(ServiceCatalogItem.name, ServiceCatalogItem.id)
        ).all()

    return ServiceCatalogResult(
        organization_id=organization_id,
        items=[
            ServiceItemResult(
                id=item.id,
                name=item.name,
                description=item.description,
            )
            for item in items
        ],
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
