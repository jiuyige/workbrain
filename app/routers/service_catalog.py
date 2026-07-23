from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.context import OrganizationContext, get_current_organization_context
from app.database import get_session
from app.models import MembershipRole, ServiceCatalogItem
from app.policies import enforce_organization_roles, require_organization_admin

router = APIRouter(
    prefix="/service-catalog/items",
    tags=["service-catalog"],
)


def normalize_name(value: str) -> str:
    normalized_name = value.strip()

    if not normalized_name:
        raise ValueError("service catalog item name cannot be blank")

    return normalized_name


def normalize_description(value: str | None) -> str | None:
    if value is None:
        return None

    normalized_description = value.strip()
    return normalized_description or None


class ServiceCatalogItemCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def normalize_request_name(cls, value: str) -> str:
        return normalize_name(value)

    @field_validator("description")
    @classmethod
    def normalize_request_description(cls, value: str | None) -> str | None:
        return normalize_description(value)


class ServiceCatalogItemUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_request_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("service catalog item name cannot be null")

        return normalize_name(value)

    @field_validator("description")
    @classmethod
    def normalize_request_description(cls, value: str | None) -> str | None:
        return normalize_description(value)

    @field_validator("is_active")
    @classmethod
    def reject_null_active_status(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("service catalog item active status cannot be null")

        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")

        return self


class ServiceCatalogItemResponse(BaseModel):
    id: int
    organization_id: int
    created_by_user_id: int
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ServiceCatalogItemListResponse(BaseModel):
    items: list[ServiceCatalogItemResponse]
    pagination: dict[str, int]


def build_service_catalog_item_response(
    item: ServiceCatalogItem,
) -> ServiceCatalogItemResponse:
    return ServiceCatalogItemResponse(
        id=item.id,
        organization_id=item.organization_id,
        created_by_user_id=item.created_by_user_id,
        name=item.name,
        description=item.description,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def get_organization_catalog_item(
    session: Session,
    *,
    item_id: int,
    organization_id: int,
    active_only: bool,
) -> ServiceCatalogItem:
    conditions = [
        ServiceCatalogItem.id == item_id,
        ServiceCatalogItem.organization_id == organization_id,
    ]

    if active_only:
        conditions.append(ServiceCatalogItem.is_active.is_(True))

    item = session.exec(select(ServiceCatalogItem).where(*conditions)).first()

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="service catalog item not found",
        )

    return item


@router.post("", response_model=ServiceCatalogItemResponse, status_code=201)
def create_service_catalog_item(
    request: ServiceCatalogItemCreateRequest,
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    existing_item = session.exec(
        select(ServiceCatalogItem).where(
            ServiceCatalogItem.organization_id == context.organization.id,
            ServiceCatalogItem.name == request.name,
        )
    ).first()

    if existing_item is not None:
        raise HTTPException(
            status_code=409,
            detail="service catalog item name already exists",
        )

    item = ServiceCatalogItem(
        organization_id=context.organization.id,
        created_by_user_id=context.membership.user_id,
        name=request.name,
        description=request.description,
    )
    session.add(item)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="service catalog item name already exists",
        ) from error

    session.refresh(item)
    return build_service_catalog_item_response(item)


@router.get("", response_model=ServiceCatalogItemListResponse)
def list_service_catalog_items(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    include_inactive: bool = Query(default=False),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    if include_inactive:
        enforce_organization_roles(
            context,
            allowed_roles=(MembershipRole.ADMIN,),
            detail="organization admin access required",
        )

    conditions = [
        ServiceCatalogItem.organization_id == context.organization.id,
    ]

    if not include_inactive:
        conditions.append(ServiceCatalogItem.is_active.is_(True))

    total = session.exec(
        select(func.count()).select_from(ServiceCatalogItem).where(*conditions)
    ).one()
    items = session.exec(
        select(ServiceCatalogItem)
        .where(*conditions)
        .order_by(ServiceCatalogItem.name, ServiceCatalogItem.id)
        .offset(offset)
        .limit(limit)
    ).all()

    return ServiceCatalogItemListResponse(
        items=[build_service_catalog_item_response(item) for item in items],
        pagination={
            "offset": offset,
            "limit": limit,
            "total": total,
            "returned": len(items),
        },
    )


@router.get("/{item_id}", response_model=ServiceCatalogItemResponse)
def read_service_catalog_item(
    item_id: int,
    include_inactive: bool = Query(default=False),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    if include_inactive:
        enforce_organization_roles(
            context,
            allowed_roles=(MembershipRole.ADMIN,),
            detail="organization admin access required",
        )

    item = get_organization_catalog_item(
        session,
        item_id=item_id,
        organization_id=context.organization.id,
        active_only=not include_inactive,
    )
    return build_service_catalog_item_response(item)


@router.patch("/{item_id}", response_model=ServiceCatalogItemResponse)
def update_service_catalog_item(
    item_id: int,
    request: ServiceCatalogItemUpdateRequest,
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    item = get_organization_catalog_item(
        session,
        item_id=item_id,
        organization_id=context.organization.id,
        active_only=False,
    )

    if "name" in request.model_fields_set:
        duplicate_item = session.exec(
            select(ServiceCatalogItem).where(
                ServiceCatalogItem.organization_id == context.organization.id,
                ServiceCatalogItem.name == request.name,
                ServiceCatalogItem.id != item.id,
            )
        ).first()

        if duplicate_item is not None:
            raise HTTPException(
                status_code=409,
                detail="service catalog item name already exists",
            )

        item.name = request.name

    if "description" in request.model_fields_set:
        item.description = request.description

    if "is_active" in request.model_fields_set:
        item.is_active = request.is_active

    item.updated_at = datetime.now(timezone.utc)
    session.add(item)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="service catalog item name already exists",
        ) from error

    session.refresh(item)
    return build_service_catalog_item_response(item)
