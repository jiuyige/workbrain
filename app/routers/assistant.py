import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.agent import run_todo_agent
from app.auth import get_current_user
from app.context import OrganizationContext, get_current_organization_context
from app.database import get_session
from app.llm import plan_assistant_action
from app.models import AgentTrace, Todo, ToolCallLog, User
from app.service_agent import confirm_service_request, run_service_request_agent

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantRequest(BaseModel):
    message: str


class AssistantResponse(BaseModel):
    action: str
    reply: str
    todo: dict | None = None


class ServiceAssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ServiceConfirmationRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=200)


@router.post("", response_model=AssistantResponse)
def assistant(
    request: AssistantRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        plan = plan_assistant_action(request.message)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="llm returned invalid json")
    except Exception:
        raise HTTPException(status_code=502, detail="failed to call llm provider")

    action = plan.get("action")
    priority = plan.get("priority")
    reply = plan.get("reply", "")

    if action not in ["create_todo", "chat"]:
        raise HTTPException(status_code=502, detail="llm returned invalid action")

    if priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=502, detail="llm returned invalid priority")

    if action == "chat":
        return {
            "action": "chat",
            "reply": reply,
            "todo": None,
        }

    todo_title = plan.get("todo_title", "").strip()

    if todo_title == "":
        raise HTTPException(status_code=502, detail="llm returned empty todo title")

    todo = Todo(
        owner_id=current_user.id,
        title=todo_title,
        priority=priority,
    )

    session.add(todo)
    session.commit()
    session.refresh(todo)

    return {
        "action": "create_todo",
        "reply": reply,
        "todo": {
            "id": todo.id,
            "title": todo.title,
            "priority": todo.priority,
            "is_done": todo.is_done,
        },
    }


@router.post("/tools", response_model=AssistantResponse)
def assistant_with_tools(
    request: AssistantRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return run_todo_agent(
        message_text=request.message,
        current_user=current_user,
        session=session,
    )


@router.post("/service-tools")
def assistant_with_service_tools(
    request: ServiceAssistantRequest,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    return run_service_request_agent(
        message_text=request.message,
        context=context,
        session=session,
    )


@router.post("/service-tools/confirm")
def confirm_assistant_service_request(
    request: ServiceConfirmationRequest,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    return confirm_service_request(
        confirmation_token=request.confirmation_token,
        context=context,
        session=session,
    )


def load_json_or_empty(value: str) -> dict:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


@router.get("/tool-logs")
def list_tool_call_logs(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = (
        select(ToolCallLog)
        .where(ToolCallLog.owner_id == current_user.id)
        .order_by(ToolCallLog.created_at.desc())
    )
    logs = session.exec(statement).all()

    return {
        "logs": [
            {
                "id": log.id,
                "tool_name": log.tool_name,
                "arguments": load_json_or_empty(log.arguments_json),
                "result": load_json_or_empty(log.result_json),
                "is_success": log.is_success,
                "error_message": log.error_message,
                "created_at": log.created_at,
            }
            for log in logs
        ]
    }


@router.get("/traces")
def list_agent_traces(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = (
        select(AgentTrace)
        .where(AgentTrace.owner_id == current_user.id)
        .order_by(AgentTrace.created_at.desc())
    )
    traces = session.exec(statement).all()

    return {
        "traces": [
            {
                "id": trace.id,
                "user_message": trace.user_message,
                "final_action": trace.final_action,
                "final_reply": trace.final_reply,
                "tool_call_count": trace.tool_call_count,
                "is_success": trace.is_success,
                "error_message": trace.error_message,
                "created_at": trace.created_at,
            }
            for trace in traces
        ]
    }
