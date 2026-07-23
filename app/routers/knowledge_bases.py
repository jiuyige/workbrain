from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.context import (
    OrganizationContext,
    get_current_organization_context,
)
from app.database import get_session
from app.models import KnowledgeBase
from app.policies import require_organization_admin

router = APIRouter(
    prefix="/knowledge-bases",
    tags=["knowledge-bases"],
)


def normalize_name(value: str) -> str:
    normalized_name = value.strip()

    if not normalized_name:
        raise ValueError("knowledge base name cannot be blank")

    return normalized_name


def normalize_description(value: str | None) -> str | None:
    if value is None:
        return None

    normalized_description = value.strip()
    return normalized_description or None


class KnowledgeBaseCreateRequest(BaseModel):
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


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def normalize_request_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("knowledge base name cannot be null")

        return normalize_name(value)

    @field_validator("description")
    @classmethod
    def normalize_request_description(cls, value: str | None) -> str | None:
        return normalize_description(value)

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")

        return self


class KnowledgeBaseResponse(BaseModel):
    id: int
    organization_id: int
    created_by_user_id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseResponse]


def build_knowledge_base_response(
    knowledge_base: KnowledgeBase,
) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        id=knowledge_base.id,
        organization_id=knowledge_base.organization_id,
        created_by_user_id=knowledge_base.created_by_user_id,
        name=knowledge_base.name,
        description=knowledge_base.description,
        created_at=knowledge_base.created_at,
        updated_at=knowledge_base.updated_at,
    )


def get_organization_knowledge_base(
    session: Session,
    *,
    knowledge_base_id: int,
    organization_id: int,
) -> KnowledgeBase:
    knowledge_base = session.exec(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.organization_id == organization_id,
        )
    ).first()

    if knowledge_base is None:
        raise HTTPException(
            status_code=404,
            detail="knowledge base not found",
        )

    return knowledge_base


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=201,
)
def create_knowledge_base(
    request: KnowledgeBaseCreateRequest,
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    existing_knowledge_base = session.exec(
        select(KnowledgeBase).where(
            KnowledgeBase.organization_id == context.organization.id,
            KnowledgeBase.name == request.name,
        )
    ).first()

    if existing_knowledge_base is not None:
        raise HTTPException(
            status_code=409,
            detail="knowledge base name already exists",
        )

    knowledge_base = KnowledgeBase(
        organization_id=context.organization.id,
        created_by_user_id=context.membership.user_id,
        name=request.name,
        description=request.description,
    )
    session.add(knowledge_base)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="knowledge base name already exists",
        ) from error

    session.refresh(knowledge_base)
    return build_knowledge_base_response(knowledge_base)


@router.get(
    "",
    response_model=KnowledgeBaseListResponse,
)
def list_knowledge_bases(
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_bases = session.exec(
        select(KnowledgeBase)
        .where(KnowledgeBase.organization_id == context.organization.id)
        .order_by(KnowledgeBase.name, KnowledgeBase.id)
    ).all()

    return KnowledgeBaseListResponse(
        knowledge_bases=[
            build_knowledge_base_response(knowledge_base)
            for knowledge_base in knowledge_bases
        ]
    )


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
def read_knowledge_base(
    knowledge_base_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    knowledge_base = get_organization_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )
    return build_knowledge_base_response(knowledge_base)


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
def update_knowledge_base(
    knowledge_base_id: int,
    request: KnowledgeBaseUpdateRequest,
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    knowledge_base = get_organization_knowledge_base(
        session,
        knowledge_base_id=knowledge_base_id,
        organization_id=context.organization.id,
    )

    if "name" in request.model_fields_set:
        duplicate_knowledge_base = session.exec(
            select(KnowledgeBase).where(
                KnowledgeBase.organization_id == context.organization.id,
                KnowledgeBase.name == request.name,
                KnowledgeBase.id != knowledge_base.id,
            )
        ).first()

        if duplicate_knowledge_base is not None:
            raise HTTPException(
                status_code=409,
                detail="knowledge base name already exists",
            )

        knowledge_base.name = request.name

    if "description" in request.model_fields_set:
        knowledge_base.description = request.description

    knowledge_base.updated_at = datetime.now(timezone.utc)
    session.add(knowledge_base)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="knowledge base name already exists",
        ) from error

    session.refresh(knowledge_base)
    return build_knowledge_base_response(knowledge_base)
