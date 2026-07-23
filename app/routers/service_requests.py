from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.context import OrganizationContext, get_current_organization_context
from app.database import get_session
from app.models import (
    MembershipRole,
    ServiceCatalogItem,
    ServiceRequest,
    ServiceRequestAction,
    ServiceRequestEvent,
    ServiceRequestStatus,
)
from app.policies import require_organization_approver

router = APIRouter(prefix="/service-requests", tags=["service-requests"])


def normalize_required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} cannot be blank")

    return normalized


class ServiceRequestCreateRequest(BaseModel):
    service_catalog_item_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return normalize_required_text(value, field_name="title")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return normalize_required_text(value, field_name="description")


class ServiceRequestRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return normalize_required_text(value, field_name="reason")


def build_service_request_response(request: ServiceRequest) -> dict:
    return {
        "id": request.id,
        "organization_id": request.organization_id,
        "requester_user_id": request.requester_user_id,
        "service_catalog_item_id": request.service_catalog_item_id,
        "title": request.title,
        "description": request.description,
        "status": request.status,
        "decided_by_user_id": request.decided_by_user_id,
        "decision_reason": request.decision_reason,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "decided_at": request.decided_at,
    }


def add_service_request_event(
    session: Session,
    *,
    request: ServiceRequest,
    actor_user_id: int,
    action: ServiceRequestAction,
    from_status: str | None,
    reason: str | None = None,
) -> None:
    session.add(
        ServiceRequestEvent(
            organization_id=request.organization_id,
            service_request_id=request.id,
            actor_user_id=actor_user_id,
            action=action.value,
            from_status=from_status,
            to_status=request.status,
            reason=reason,
        )
    )


def get_organization_service_request(
    session: Session,
    *,
    request_id: int,
    organization_id: int,
) -> ServiceRequest:
    request = session.exec(
        select(ServiceRequest).where(
            ServiceRequest.id == request_id,
            ServiceRequest.organization_id == organization_id,
        )
    ).first()

    if request is None:
        raise HTTPException(status_code=404, detail="service request not found")

    return request


def get_visible_service_request(
    session: Session,
    *,
    request_id: int,
    context: OrganizationContext,
) -> ServiceRequest:
    request = get_organization_service_request(
        session,
        request_id=request_id,
        organization_id=context.organization.id,
    )
    privileged_roles = {
        MembershipRole.APPROVER.value,
        MembershipRole.ADMIN.value,
    }

    if (
        context.membership.role not in privileged_roles
        and request.requester_user_id != context.membership.user_id
    ):
        raise HTTPException(status_code=404, detail="service request not found")

    return request


@router.post("", status_code=201)
def create_service_request(
    body: ServiceRequestCreateRequest,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    catalog_item = session.exec(
        select(ServiceCatalogItem).where(
            ServiceCatalogItem.id == body.service_catalog_item_id,
            ServiceCatalogItem.organization_id == context.organization.id,
            ServiceCatalogItem.is_active.is_(True),
        )
    ).first()

    if catalog_item is None:
        raise HTTPException(status_code=404, detail="service catalog item not found")

    request = ServiceRequest(
        organization_id=context.organization.id,
        requester_user_id=context.membership.user_id,
        service_catalog_item_id=catalog_item.id,
        title=body.title,
        description=body.description,
    )
    session.add(request)
    session.flush()
    add_service_request_event(
        session,
        request=request,
        actor_user_id=context.membership.user_id,
        action=ServiceRequestAction.CREATE,
        from_status=None,
    )
    session.commit()
    session.refresh(request)
    return build_service_request_response(request)


@router.get("")
def list_service_requests(
    status: ServiceRequestStatus | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    conditions = [ServiceRequest.organization_id == context.organization.id]
    privileged_roles = {
        MembershipRole.APPROVER.value,
        MembershipRole.ADMIN.value,
    }

    if context.membership.role not in privileged_roles:
        conditions.append(
            ServiceRequest.requester_user_id == context.membership.user_id
        )

    if status is not None:
        conditions.append(ServiceRequest.status == status.value)

    all_requests = session.exec(
        select(ServiceRequest)
        .where(*conditions)
        .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
    ).all()
    page = all_requests[offset : offset + limit]

    return {
        "requests": [build_service_request_response(item) for item in page],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": len(all_requests),
            "returned": len(page),
        },
    }


@router.get("/{request_id}")
def read_service_request(
    request_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    request = get_visible_service_request(
        session,
        request_id=request_id,
        context=context,
    )
    return build_service_request_response(request)


def decide_service_request(
    session: Session,
    *,
    request: ServiceRequest,
    actor_user_id: int,
    status: ServiceRequestStatus,
    action: ServiceRequestAction,
    reason: str | None,
) -> ServiceRequest:
    if request.requester_user_id == actor_user_id:
        raise HTTPException(
            status_code=403,
            detail="requester cannot approve own service request",
        )

    if request.status != ServiceRequestStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail="service request is already finished",
        )

    from_status = request.status
    now = datetime.now(timezone.utc)
    request.status = status.value
    request.decided_by_user_id = actor_user_id
    request.decision_reason = reason
    request.decided_at = now
    request.updated_at = now
    session.add(request)
    add_service_request_event(
        session,
        request=request,
        actor_user_id=actor_user_id,
        action=action,
        from_status=from_status,
        reason=reason,
    )
    session.commit()
    session.refresh(request)
    return request


@router.post("/{request_id}/approve")
def approve_service_request(
    request_id: int,
    context: OrganizationContext = Depends(require_organization_approver),
    session: Session = Depends(get_session),
):
    request = get_organization_service_request(
        session,
        request_id=request_id,
        organization_id=context.organization.id,
    )
    decided = decide_service_request(
        session,
        request=request,
        actor_user_id=context.membership.user_id,
        status=ServiceRequestStatus.APPROVED,
        action=ServiceRequestAction.APPROVE,
        reason=None,
    )
    return build_service_request_response(decided)


@router.post("/{request_id}/reject")
def reject_service_request(
    request_id: int,
    body: ServiceRequestRejectRequest,
    context: OrganizationContext = Depends(require_organization_approver),
    session: Session = Depends(get_session),
):
    request = get_organization_service_request(
        session,
        request_id=request_id,
        organization_id=context.organization.id,
    )
    decided = decide_service_request(
        session,
        request=request,
        actor_user_id=context.membership.user_id,
        status=ServiceRequestStatus.REJECTED,
        action=ServiceRequestAction.REJECT,
        reason=body.reason,
    )
    return build_service_request_response(decided)


@router.get("/{request_id}/events")
def list_service_request_events(
    request_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    request = get_visible_service_request(
        session,
        request_id=request_id,
        context=context,
    )
    events = session.exec(
        select(ServiceRequestEvent)
        .where(
            ServiceRequestEvent.service_request_id == request.id,
            ServiceRequestEvent.organization_id == context.organization.id,
        )
        .order_by(ServiceRequestEvent.created_at, ServiceRequestEvent.id)
    ).all()

    return {
        "service_request_id": request.id,
        "events": [
            {
                "id": event.id,
                "actor_user_id": event.actor_user_id,
                "action": event.action,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "reason": event.reason,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }
