import json

from fastapi import HTTPException
from sqlmodel import Session, select

from app.llm import generate_tool_final_answer, plan_with_tools
from app.models import AgentTrace, Todo, ToolCallLog, User

TOOL_POLICIES = {
    "create_todo": {
        "risk_level": "safe",
        "description": "创建待办",
    },
    "list_todos": {
        "risk_level": "safe",
        "description": "查询待办列表",
    },
    "mark_todo_done": {
        "risk_level": "safe",
        "description": "标记待办完成",
    },
    "request_delete_todo_confirmation": {
        "risk_level": "confirm",
        "description": "请求删除待办确认",
    },
}


def get_tool_policy(tool_name: str) -> dict:
    policy = TOOL_POLICIES.get(tool_name)

    if policy is None:
        raise HTTPException(status_code=502, detail="unsupported tool call")

    return policy


def ensure_tool_allowed(tool_name: str):
    policy = get_tool_policy(tool_name)

    if policy["risk_level"] == "blocked":
        raise HTTPException(status_code=403, detail="tool is blocked")

    return policy


def save_tool_call_log(
    session: Session,
    owner_id: int,
    tool_name: str,
    arguments: dict,
    result: dict | None = None,
    error_message: str | None = None,
):
    log = ToolCallLog(
        owner_id=owner_id,
        tool_name=tool_name,
        arguments_json=json.dumps(arguments, ensure_ascii=False),
        result_json=json.dumps(result or {}, ensure_ascii=False),
        is_success=error_message is None,
        error_message=error_message,
    )

    session.add(log)
    session.commit()


def fail_tool_call(
    session: Session,
    owner_id: int,
    tool_name: str,
    arguments: dict,
    error_message: str,
    status_code: int = 502,
):
    save_tool_call_log(
        session=session,
        owner_id=owner_id,
        tool_name=tool_name,
        arguments=arguments,
        error_message=error_message,
    )
    raise HTTPException(status_code=status_code, detail=error_message)


def execute_todo_tool(
    session: Session,
    current_user: User,
    tool_name: str,
    arguments: dict,
) -> dict:
    if tool_name == "create_todo":
        title = arguments.get("title", "").strip()
        priority = arguments.get("priority", "medium")

        if title == "":
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments=arguments,
                error_message="todo title is empty",
            )

        if priority not in ["low", "medium", "high"]:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments=arguments,
                error_message="invalid todo priority",
            )

        todo = Todo(
            owner_id=current_user.id,
            title=title,
            priority=priority,
        )

        session.add(todo)
        session.commit()
        session.refresh(todo)

        todo_data = {
            "id": todo.id,
            "title": todo.title,
            "priority": todo.priority,
            "is_done": todo.is_done,
        }

        return {
            "action": "create_todo",
            "tool_result": todo_data,
            "todo_response": todo_data,
        }

    if tool_name == "list_todos":
        statement = (
            select(Todo)
            .where(Todo.owner_id == current_user.id)
            .order_by(Todo.created_at.desc())
        )
        todos = session.exec(statement).all()

        tool_result = {
            "todos": [
                {
                    "id": todo.id,
                    "title": todo.title,
                    "priority": todo.priority,
                    "is_done": todo.is_done,
                }
                for todo in todos
            ]
        }

        return {
            "action": "list_todos",
            "tool_result": tool_result,
            "todo_response": None,
        }

    if tool_name == "mark_todo_done":
        todo_id = arguments.get("todo_id")

        if todo_id is None:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments=arguments,
                error_message="todo_id is required",
            )

        statement = select(Todo).where(
            Todo.id == todo_id,
            Todo.owner_id == current_user.id,
        )
        todo = session.exec(statement).first()

        if todo is None:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments=arguments,
                error_message="todo not found",
                status_code=404,
            )

        todo.is_done = True
        session.add(todo)
        session.commit()
        session.refresh(todo)

        todo_data = {
            "id": todo.id,
            "title": todo.title,
            "priority": todo.priority,
            "is_done": todo.is_done,
        }

        return {
            "action": "mark_todo_done",
            "tool_result": todo_data,
            "todo_response": todo_data,
        }

    if tool_name == "request_delete_todo_confirmation":
        todo_id = arguments.get("todo_id")

        if todo_id is None:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments=arguments,
                error_message="todo_id is required",
            )

        statement = select(Todo).where(
            Todo.id == todo_id,
            Todo.owner_id == current_user.id,
        )
        todo = session.exec(statement).first()

        if todo is None:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments=arguments,
                error_message="todo not found",
                status_code=404,
            )

        todo_data = {
            "id": todo.id,
            "title": todo.title,
            "priority": todo.priority,
            "is_done": todo.is_done,
        }

        tool_result = {
            "requires_confirmation": True,
            "confirmation_action": "delete_todo",
            "confirm_endpoint": f"DELETE /todos/{todo.id}",
            "todo": todo_data,
        }

        tool_result = {
            "requires_confirmation": True,
            "confirmation_action": "delete_todo",
            "confirm_endpoint": f"DELETE /todos/{todo.id}",
            "todo": todo_data,
        }

        return {
            "action": "confirm_delete_todo",
            "tool_result": tool_result,
            "todo_response": todo_data,
        }

    fail_tool_call(
        session=session,
        owner_id=current_user.id,
        tool_name=tool_name,
        arguments=arguments,
        error_message="unsupported tool call",
    )


def run_todo_agent(
    message_text: str,
    current_user: User,
    session: Session,
) -> dict:

    try:
        message, messages = plan_with_tools(message_text)
    except RuntimeError as error:
        save_agent_trace(
            session=session,
            owner_id=current_user.id,
            user_message=message_text,
            error_message=str(error),
        )
        raise HTTPException(status_code=500, detail=str(error))
    except Exception:
        save_agent_trace(
            session=session,
            owner_id=current_user.id,
            user_message=message_text,
            error_message="failed to call llm provider",
        )
        raise HTTPException(status_code=502, detail="failed to call llm provider")

    if not message.tool_calls:
        reply = message.content or ""

        save_agent_trace(
            session=session,
            owner_id=current_user.id,
            user_message=message_text,
            final_action="chat",
            final_reply=reply,
            tool_call_count=0,
        )

        return {
            "action": "chat",
            "reply": reply,
            "todo": None,
        }

    executions = []
    todo_response = None

    for tool_call in message.tool_calls:
        tool_name = tool_call.function.name

        try:
            policy = ensure_tool_allowed(tool_name)
        except HTTPException as error:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments={},
                error_message=str(error.detail),
                status_code=error.status_code,
            )

        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            fail_tool_call(
                session=session,
                owner_id=current_user.id,
                tool_name=tool_name,
                arguments={},
                error_message="tool arguments are invalid json",
            )

        execution = execute_todo_tool(
            session=session,
            current_user=current_user,
            tool_name=tool_name,
            arguments=arguments,
        )

        execution["risk_level"] = policy["risk_level"]

        save_tool_call_log(
            session=session,
            owner_id=current_user.id,
            tool_name=tool_name,
            arguments=arguments,
            result={
                "risk_level": execution["risk_level"],
                "tool_result": execution["tool_result"],
            },
        )

        executions.append(
            {
                "tool_call": tool_call,
                "execution": execution,
            }
        )

        if execution["todo_response"] is not None:
            todo_response = execution["todo_response"]

    messages.append(message)

    for item in executions:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": item["tool_call"].id,
                "content": json.dumps(
                    item["execution"]["tool_result"],
                    ensure_ascii=False,
                ),
            }
        )

    final_reply = generate_tool_final_answer(messages)

    action = (
        "multiple_tools"
        if len(executions) > 1
        else executions[0]["execution"]["action"]
    )

    save_agent_trace(
        session=session,
        owner_id=current_user.id,
        user_message=message_text,
        final_action=action,
        final_reply=final_reply,
        tool_call_count=len(executions),
    )

    return {
        "action": action,
        "reply": final_reply,
        "todo": todo_response,
    }


def save_agent_trace(
    session: Session,
    owner_id: int,
    user_message: str,
    final_action: str = "",
    final_reply: str = "",
    tool_call_count: int = 0,
    error_message: str | None = None,
):
    trace = AgentTrace(
        owner_id=owner_id,
        user_message=user_message,
        final_action=final_action,
        final_reply=final_reply,
        tool_call_count=tool_call_count,
        is_success=error_message is None,
        error_message=error_message,
    )

    session.add(trace)
    session.commit()

    return trace
