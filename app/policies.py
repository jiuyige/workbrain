from collections.abc import Collection

from fastapi import Depends, HTTPException

from app.context import (
    OrganizationContext,
    get_current_organization_context,
)
from app.models import MembershipRole


def enforce_organization_roles(
    context: OrganizationContext,
    allowed_roles: Collection[MembershipRole],
    *,
    detail: str,
) -> OrganizationContext:
    allowed_role_values = {role.value for role in allowed_roles}

    if context.membership.role not in allowed_role_values:
        raise HTTPException(
            status_code=403,
            detail=detail,
        )

    return context


def require_organization_admin(
    context: OrganizationContext = Depends(get_current_organization_context),
) -> OrganizationContext:
    return enforce_organization_roles(
        context,
        allowed_roles=(MembershipRole.ADMIN,),
        detail="organization admin access required",
    )


def require_organization_approver(
    context: OrganizationContext = Depends(get_current_organization_context),
) -> OrganizationContext:
    return enforce_organization_roles(
        context,
        allowed_roles=(
            MembershipRole.APPROVER,
            MembershipRole.ADMIN,
        ),
        detail="organization approver access required",
    )
