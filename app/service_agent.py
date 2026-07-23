import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import HTTPException
from sqlmodel import Session, select

from app.context import OrganizationContext
from app.llm import generate_tool_final_answer, plan_service_request_with_tools
from app.models import (
    AgentTrace,
    ServiceCatalogItem,
    ServiceRequest,
    ServiceRequestAction,
    ServiceRequestConfirmation,
    ServiceRequestStatus,
    ToolCallLog,
)
from app.routers.service_requests import (
    add_service_request_event,
    build_service_request_response,
)

SERVICE_CONFIRMATION_TTL_MINUTES = 15
SERVICE_TOOL_NAMES = {
    "list_service_catalog",
    "list_my_service_requests",
    "prepare_service_request",
}


def redact_service_tool_result(result: dict | None) -> dict:
    safe_result = dict(result or {})
    if "confirmation_token" in safe_result:
        safe_result["confirmation_token"] = "[REDACTED]"
    return safe_result


def hash_confirmation_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def save_service_tool_log(
    session: Session,
    *,
    context: OrganizationContext,
    tool_name: str,
    arguments: dict,
    result: dict | None = None,
    error_message: str | None = None,
) -> None:
    session.add(
        ToolCallLog(
            owner_id=context.membership.user_id,
            organization_id=context.organization.id,
            tool_name=tool_name,
            arguments_json=json.dumps(arguments, ensure_ascii=False, default=str),
            result_json=json.dumps(
                redact_service_tool_result(result),
                ensure_ascii=False,
                default=str,
            ),
            is_success=error_message is None,
            error_message=error_message,
        )
    )
    session.commit()


def save_service_agent_trace(
    session: Session,
    *,
    context: OrganizationContext,
    user_message: str,
    final_action: str = "",
    final_reply: str = "",
    tool_call_count: int = 0,
    error_message: str | None = None,
) -> None:
    session.add(
        AgentTrace(
            owner_id=context.membership.user_id,
            organization_id=context.organization.id,
            user_message=user_message,
            final_action=final_action,
            final_reply=final_reply,
            tool_call_count=tool_call_count,
            is_success=error_message is None,
            error_message=error_message,
        )
    )
    session.commit()


def fail_service_tool_call(
    session: Session,
    *,
    context: OrganizationContext,
    tool_name: str,
    arguments: dict,
    error_message: str,
    status_code: int = 502,
) -> None:
    save_service_tool_log(
        session,
        context=context,
        tool_name=tool_name,
        arguments=arguments,
        error_message=error_message,
    )
    raise HTTPException(status_code=status_code, detail=error_message)


def list_active_catalog_items(
    session: Session,
    *,
    organization_id: int,
) -> list[ServiceCatalogItem]:
    return list(
        session.exec(
            select(ServiceCatalogItem)
            .where(
                ServiceCatalogItem.organization_id == organization_id,
                ServiceCatalogItem.is_active.is_(True),
            )
            .order_by(ServiceCatalogItem.name, ServiceCatalogItem.id)
        ).all()
    )


def build_catalog_item(item: ServiceCatalogItem) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
    }


def normalize_optional_text(
    session: Session,
    *,
    context: OrganizationContext,
    tool_name: str,
    arguments: dict,
    field_name: str,
    max_length: int,
) -> str:
    value = arguments.get(field_name)

    if value is None:
        return ""

    if not isinstance(value, str):
        fail_service_tool_call(
            session,
            context=context,
            tool_name=tool_name,
            arguments=arguments,
            error_message=f"{field_name} must be a string",
        )

    normalized = value.strip()
    if len(normalized) > max_length:
        fail_service_tool_call(
            session,
            context=context,
            tool_name=tool_name,
            arguments=arguments,
            error_message=f"{field_name} is too long",
        )

    return normalized


def select_catalog_item(
    session: Session,
    *,
    context: OrganizationContext,
    tool_name: str,
    arguments: dict,
    active_items: list[ServiceCatalogItem],
) -> tuple[ServiceCatalogItem | None, list[ServiceCatalogItem]]:
    item_id = arguments.get("service_catalog_item_id")
    service_name = normalize_optional_text(
        session,
        context=context,
        tool_name=tool_name,
        arguments=arguments,
        field_name="service_name",
        max_length=100,
    )

    if item_id is not None:
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            fail_service_tool_call(
                session,
                context=context,
                tool_name=tool_name,
                arguments=arguments,
                error_message=("service_catalog_item_id must be a positive integer"),
            )

        selected = next((item for item in active_items if item.id == item_id), None)
        if selected is None:
            fail_service_tool_call(
                session,
                context=context,
                tool_name=tool_name,
                arguments=arguments,
                error_message="service catalog item not found",
                status_code=404,
            )
        return selected, []

    if not service_name:
        return None, active_items

    normalized_name = service_name.casefold()
    exact_matches = [
        item for item in active_items if item.name.casefold() == normalized_name
    ]
    if len(exact_matches) == 1:
        return exact_matches[0], []

    candidates = [
        item for item in active_items if normalized_name in item.name.casefold()
    ]
    if len(candidates) == 1:
        return candidates[0], []

    return None, candidates or active_items


def prepare_service_request(
    session: Session,
    *,
    context: OrganizationContext,
    tool_name: str,
    arguments: dict,
) -> dict:
    active_items = list_active_catalog_items(
        session,
        organization_id=context.organization.id,
    )
    selected_item, candidates = select_catalog_item(
        session,
        context=context,
        tool_name=tool_name,
        arguments=arguments,
        active_items=active_items,
    )
    title = normalize_optional_text(
        session,
        context=context,
        tool_name=tool_name,
        arguments=arguments,
        field_name="title",
        max_length=200,
    )
    description = normalize_optional_text(
        session,
        context=context,
        tool_name=tool_name,
        arguments=arguments,
        field_name="description",
        max_length=2000,
    )

    missing_fields = []
    if selected_item is None:
        missing_fields.append("service_catalog_item")
    if not title:
        missing_fields.append("title")
    if not description:
        missing_fields.append("description")

    if missing_fields:
        return {
            "action": "request_service_information",
            "tool_result": {
                "missing_fields": missing_fields,
                "candidates": [build_catalog_item(item) for item in candidates],
            },
        }

    raw_token = token_urlsafe(32)
    confirmation = ServiceRequestConfirmation(
        organization_id=context.organization.id,
        requester_user_id=context.membership.user_id,
        service_catalog_item_id=selected_item.id,
        confirmation_token_hash=hash_confirmation_token(raw_token),
        title=title,
        description=description,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=SERVICE_CONFIRMATION_TTL_MINUTES),
    )
    session.add(confirmation)
    session.commit()

    return {
        "action": "confirm_service_request",
        "tool_result": {
            "requires_confirmation": True,
            "confirmation_token": raw_token,
            "service": {
                "id": selected_item.id,
                "name": selected_item.name,
            },
            "title": title,
            "description": description,
        },
    }


def execute_service_tool(
    session: Session,
    *,
    context: OrganizationContext,
    tool_name: str,
    arguments: dict,
) -> dict:
    if tool_name == "list_service_catalog":
        items = list_active_catalog_items(
            session,
            organization_id=context.organization.id,
        )
        return {
            "action": "list_service_catalog",
            "tool_result": {
                "items": [build_catalog_item(item) for item in items],
            },
        }

    if tool_name == "list_my_service_requests":
        requests = session.exec(
            select(ServiceRequest)
            .where(
                ServiceRequest.organization_id == context.organization.id,
                ServiceRequest.requester_user_id == context.membership.user_id,
            )
            .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
        ).all()
        return {
            "action": "list_my_service_requests",
            "tool_result": {
                "requests": [build_service_request_response(item) for item in requests]
            },
        }

    if tool_name == "prepare_service_request":
        return prepare_service_request(
            session,
            context=context,
            tool_name=tool_name,
            arguments=arguments,
        )

    fail_service_tool_call(
        session,
        context=context,
        tool_name=tool_name,
        arguments=arguments,
        error_message="unsupported tool call",
    )


def run_service_request_agent(
    *,
    message_text: str,
    context: OrganizationContext,
    session: Session,
) -> dict:
    try:
        message, messages = plan_service_request_with_tools(message_text)
    except RuntimeError as error:
        save_service_agent_trace(
            session,
            context=context,
            user_message=message_text,
            error_message=str(error),
        )
        raise HTTPException(status_code=500, detail=str(error))
    except Exception:
        save_service_agent_trace(
            session,
            context=context,
            user_message=message_text,
            error_message="failed to call llm provider",
        )
        raise HTTPException(status_code=502, detail="failed to call llm provider")

    if not message.tool_calls:
        reply = message.content or ""
        save_service_agent_trace(
            session,
            context=context,
            user_message=message_text,
            final_action="chat",
            final_reply=reply,
        )
        return {"action": "chat", "reply": reply, "result": {}}

    executions = []
    try:
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            if tool_name not in SERVICE_TOOL_NAMES:
                fail_service_tool_call(
                    session,
                    context=context,
                    tool_name=tool_name,
                    arguments={},
                    error_message="unsupported tool call",
                )

            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                fail_service_tool_call(
                    session,
                    context=context,
                    tool_name=tool_name,
                    arguments={},
                    error_message="tool arguments are invalid json",
                )

            if not isinstance(arguments, dict):
                fail_service_tool_call(
                    session,
                    context=context,
                    tool_name=tool_name,
                    arguments={},
                    error_message="tool arguments must be an object",
                )

            execution = execute_service_tool(
                session,
                context=context,
                tool_name=tool_name,
                arguments=arguments,
            )
            save_service_tool_log(
                session,
                context=context,
                tool_name=tool_name,
                arguments=arguments,
                result=execution["tool_result"],
            )
            executions.append(
                {
                    "tool_call": tool_call,
                    "execution": execution,
                }
            )
    except HTTPException as error:
        save_service_agent_trace(
            session,
            context=context,
            user_message=message_text,
            tool_call_count=len(executions),
            error_message=str(error.detail),
        )
        raise

    messages.append(message)
    for item in executions:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": item["tool_call"].id,
                "content": json.dumps(
                    redact_service_tool_result(item["execution"]["tool_result"]),
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )

    try:
        final_reply = generate_tool_final_answer(messages)
    except Exception:
        save_service_agent_trace(
            session,
            context=context,
            user_message=message_text,
            tool_call_count=len(executions),
            error_message="failed to generate tool result",
        )
        raise HTTPException(status_code=502, detail="failed to generate tool result")

    action = (
        "multiple_tools"
        if len(executions) > 1
        else executions[0]["execution"]["action"]
    )
    result = executions[-1]["execution"]["tool_result"]
    save_service_agent_trace(
        session,
        context=context,
        user_message=message_text,
        final_action=action,
        final_reply=final_reply,
        tool_call_count=len(executions),
    )
    return {"action": action, "reply": final_reply, "result": result}


def confirm_service_request(
    *,
    confirmation_token: str,
    context: OrganizationContext,
    session: Session,
) -> dict:
    token_hash = hash_confirmation_token(confirmation_token)
    confirmation = session.exec(
        select(ServiceRequestConfirmation)
        .where(
            ServiceRequestConfirmation.confirmation_token_hash == token_hash,
            ServiceRequestConfirmation.organization_id == context.organization.id,
            ServiceRequestConfirmation.requester_user_id == context.membership.user_id,
        )
        .with_for_update()
    ).first()

    if confirmation is None:
        raise HTTPException(status_code=404, detail="confirmation not found")

    if confirmation.service_request_id is not None:
        existing_request = session.get(
            ServiceRequest,
            confirmation.service_request_id,
        )
        if existing_request is None:
            raise HTTPException(status_code=409, detail="confirmation is inconsistent")
        return {
            "action": "create_service_request",
            "reply": "该确认已处理，返回原申请单。",
            "result": {
                "created": False,
                "service_request": build_service_request_response(existing_request),
            },
        }

    expires_at = confirmation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="confirmation has expired")

    catalog_item = session.exec(
        select(ServiceCatalogItem).where(
            ServiceCatalogItem.id == confirmation.service_catalog_item_id,
            ServiceCatalogItem.organization_id == context.organization.id,
            ServiceCatalogItem.is_active.is_(True),
        )
    ).first()
    if catalog_item is None:
        raise HTTPException(
            status_code=409,
            detail="service catalog item is no longer available",
        )

    request = ServiceRequest(
        organization_id=context.organization.id,
        requester_user_id=context.membership.user_id,
        service_catalog_item_id=catalog_item.id,
        title=confirmation.title,
        description=confirmation.description,
        status=ServiceRequestStatus.PENDING.value,
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
    confirmation.service_request_id = request.id
    confirmation.confirmed_at = datetime.now(timezone.utc)
    session.add(confirmation)
    session.commit()
    session.refresh(request)

    return {
        "action": "create_service_request",
        "reply": "申请单已创建，当前状态为待审批。",
        "result": {
            "created": True,
            "service_request": build_service_request_response(request),
        },
    }
