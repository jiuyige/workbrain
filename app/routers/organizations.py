from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth import get_current_user
from app.context import (
    OrganizationContext,
    get_current_organization_context,
)
from app.database import get_session
from app.models import (
    Membership,
    MembershipRole,
    Organization,
    User,
)
from app.policies import require_organization_admin

router = APIRouter(
    prefix="/organizations",
    tags=["organizations"],
)


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized_name = value.strip()

        if not normalized_name:
            raise ValueError("organization name cannot be blank")

        return normalized_name


class OrganizationResponse(BaseModel):
    id: int
    name: str
    slug: str
    role: str
    created_at: datetime


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationResponse]


class MembershipCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    role: MembershipRole = MembershipRole.MEMBER


class MembershipResponse(BaseModel):
    id: int
    user_id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime


class MembershipListResponse(BaseModel):
    members: list[MembershipResponse]


def build_membership_response(
    membership: Membership,
    user: User,
) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        user_id=user.id,
        username=user.username,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
    )


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=201,
)
def create_organization(
    request: OrganizationCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    existing_organization = session.exec(
        select(Organization).where(Organization.slug == request.slug)
    ).first()

    if existing_organization is not None:
        raise HTTPException(
            status_code=409,
            detail="organization slug already exists",
        )

    organization = Organization(
        name=request.name,
        slug=request.slug,
    )
    session.add(organization)

    try:
        session.flush()

        membership = Membership(
            organization_id=organization.id,
            user_id=current_user.id,
            role=MembershipRole.ADMIN.value,
        )
        session.add(membership)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="organization could not be created",
        ) from error

    session.refresh(organization)

    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        role=MembershipRole.ADMIN.value,
        created_at=organization.created_at,
    )


@router.get(
    "",
    response_model=OrganizationListResponse,
)
def list_organizations(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = (
        select(Organization, Membership.role)
        .join(
            Membership,
            Membership.organization_id == Organization.id,
        )
        .where(
            Membership.user_id == current_user.id,
            Membership.is_active.is_(True),
        )
        .order_by(Organization.id)
    )
    rows = session.exec(statement).all()

    return OrganizationListResponse(
        organizations=[
            OrganizationResponse(
                id=organization.id,
                name=organization.name,
                slug=organization.slug,
                role=role,
                created_at=organization.created_at,
            )
            for organization, role in rows
        ]
    )


@router.get(
    "/current",
    response_model=OrganizationResponse,
)
def read_current_organization(
    context: OrganizationContext = Depends(get_current_organization_context),
):
    organization = context.organization
    membership = context.membership

    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        role=membership.role,
        created_at=organization.created_at,
    )


@router.post(
    "/members",
    response_model=MembershipResponse,
    status_code=201,
)
def invite_organization_member(
    request: MembershipCreateRequest,
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    target_user = session.exec(
        select(User).where(User.username == request.username)
    ).first()

    if target_user is None:
        raise HTTPException(
            status_code=404,
            detail="user not found",
        )

    existing_membership = session.exec(
        select(Membership).where(
            Membership.organization_id == context.organization.id,
            Membership.user_id == target_user.id,
        )
    ).first()

    if existing_membership is not None:
        raise HTTPException(
            status_code=409,
            detail="user is already an organization member",
        )

    membership = Membership(
        organization_id=context.organization.id,
        user_id=target_user.id,
        role=request.role.value,
    )
    session.add(membership)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="organization membership could not be created",
        ) from error

    session.refresh(membership)

    return build_membership_response(
        membership,
        target_user,
    )


@router.get(
    "/members",
    response_model=MembershipListResponse,
)
def list_organization_members(
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    statement = (
        select(Membership, User)
        .join(
            User,
            User.id == Membership.user_id,
        )
        .where(Membership.organization_id == context.organization.id)
        .order_by(Membership.id)
    )
    rows = session.exec(statement).all()

    return MembershipListResponse(
        members=[
            build_membership_response(membership, user) for membership, user in rows
        ]
    )


@router.patch(
    "/members/{membership_id}/disable",
    response_model=MembershipResponse,
)
def disable_organization_member(
    membership_id: int,
    context: OrganizationContext = Depends(require_organization_admin),
    session: Session = Depends(get_session),
):
    row = session.exec(
        select(Membership, User)
        .join(
            User,
            User.id == Membership.user_id,
        )
        .where(
            Membership.id == membership_id,
            Membership.organization_id == context.organization.id,
        )
    ).first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="organization member not found",
        )

    membership, user = row

    if membership.user_id == context.membership.user_id:
        raise HTTPException(
            status_code=409,
            detail="cannot disable own membership",
        )

    membership.is_active = False

    session.add(membership)
    session.commit()
    session.refresh(membership)

    return build_membership_response(
        membership,
        user,
    )
