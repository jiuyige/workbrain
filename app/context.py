from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models import Membership, Organization, User

ORGANIZATION_ID_HEADER = "X-Organization-ID"


@dataclass(frozen=True)
class OrganizationContext:
    organization: Organization
    membership: Membership


def get_current_organization_context(
    organization_id_header: str | None = Header(
        default=None,
        alias=ORGANIZATION_ID_HEADER,
    ),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> OrganizationContext:
    if organization_id_header is None:
        raise HTTPException(
            status_code=400,
            detail="organization context is required",
        )

    try:
        organization_id = int(organization_id_header)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="organization id must be a positive integer",
        )

    if organization_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="organization id must be a positive integer",
        )

    statement = (
        select(Organization, Membership)
        .join(
            Membership,
            Membership.organization_id == Organization.id,
        )
        .where(
            Organization.id == organization_id,
            Membership.user_id == current_user.id,
            Membership.is_active.is_(True),
        )
    )
    row = session.exec(statement).first()

    if row is None:
        raise HTTPException(
            status_code=403,
            detail="organization access denied",
        )

    organization, membership = row

    return OrganizationContext(
        organization=organization,
        membership=membership,
    )
