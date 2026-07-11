from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select


import json


from app.config import CHAT_HISTORY_MAX_CHARS
from app.auth import get_current_user
from app.database import get_session
from app.llm import analyze_text, generate_answer
from app.models import ChatMessage, LLMCallLog, Todo, User

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class AnalyzeRequest(BaseModel):
    text: str


class TodoResponse(BaseModel):
    id: int
    title: str
    priority: str
    is_done: bool


class AnalyzeResponse(BaseModel):
    summary: str
    priority: str
    todos: list[TodoResponse]


class UsageResponse(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    estimated_cost_usd: float


class ChatResponse(BaseModel):
    answer: str
    usage: UsageResponse
    finish_reason: str | None = None
    history_message_count: int




def build_history_messages(recent_messages: list[ChatMessage]) -> list[dict]:
    history = []
    used_chars = 0

    for message in reversed(recent_messages):
        user_content = message.user_message
        assistant_content = message.assistant_message

        message_chars = len(user_content) + len(assistant_content)

        if used_chars + message_chars > CHAT_HISTORY_MAX_CHARS:
            break

        history.append(
            {
                "role": "user",
                "content": user_content,
            }
        )
        history.append(
            {
                "role": "assistant",
                "content": assistant_content,
            }
        )

        used_chars += message_chars

    return history

@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    history_statement = (
        select(ChatMessage)
        .where(ChatMessage.owner_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(5)
    )
    recent_messages = session.exec(history_statement).all()

    history = build_history_messages(recent_messages)

    try:
        result = generate_answer(request.message, history=history)
        answer = result["answer"]
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error))

    chat_message = ChatMessage(
        owner_id=current_user.id,
        user_message=request.message,
        assistant_message=answer,
    )
    
    llm_call_log = LLMCallLog(
        owner_id=current_user.id,
        model=result["model"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        total_tokens=result["total_tokens"],
        prompt_cache_hit_tokens=result["prompt_cache_hit_tokens"],
        prompt_cache_miss_tokens=result["prompt_cache_miss_tokens"],
        estimated_cost_usd=result["estimated_cost_usd"],
    )

    session.add(chat_message)
    session.add(llm_call_log)
    session.commit()

    session.add(chat_message)
    llm_call_log = LLMCallLog(
    owner_id=current_user.id,
    model=result["model"],
    input_tokens=result["input_tokens"],
    output_tokens=result["output_tokens"],
    total_tokens=result["total_tokens"],
    prompt_cache_hit_tokens=result["prompt_cache_hit_tokens"],
    prompt_cache_miss_tokens=result["prompt_cache_miss_tokens"],
    estimated_cost_usd=result["estimated_cost_usd"],
)

    return {
        "answer": answer,
        "usage": {
            "model": result["model"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "total_tokens": result["total_tokens"],
            "prompt_cache_hit_tokens": result["prompt_cache_hit_tokens"],
            "prompt_cache_miss_tokens": result["prompt_cache_miss_tokens"],
            "estimated_cost_usd": result["estimated_cost_usd"],
        },
        "finish_reason": result["finish_reason"],
        "history_message_count": len(history),
    }

@router.get("/usage")
def get_chat_usage(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(LLMCallLog).where(LLMCallLog.owner_id == current_user.id)
    logs = session.exec(statement).all()

    return {
        "calls": len(logs),
        "input_tokens": sum(log.input_tokens for log in logs),
        "output_tokens": sum(log.output_tokens for log in logs),
        "total_tokens": sum(log.total_tokens for log in logs),
        "prompt_cache_hit_tokens": sum(log.prompt_cache_hit_tokens for log in logs),
        "prompt_cache_miss_tokens": sum(log.prompt_cache_miss_tokens for log in logs),
        "estimated_cost_usd": round(
            sum(log.estimated_cost_usd for log in logs),
            6,
        ),
    }


@router.get("/history")
def get_chat_history(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = (
        select(ChatMessage)
        .where(ChatMessage.owner_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
    )
    messages = session.exec(statement).all()

    return {
        "messages": [
            {
                "id": message.id,
                "user_message": message.user_message,
                "assistant_message": message.assistant_message,
                "created_at": message.created_at,
            }
            for message in messages
        ]
    }


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        result = analyze_text(request.text)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="llm returned invalid json")
    except Exception:
        raise HTTPException(status_code=502, detail="failed to call llm provider")

    priority = result.get("priority")

    if priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=502, detail="llm returned invalid priority")

    todos = []
    
    for task in result.get("tasks", []):
        todo = Todo(
            owner_id=current_user.id,
            title=task,
            priority=priority,
        )
        session.add(todo)
        todos.append(todo)

    session.commit()

    for todo in todos:
        session.refresh(todo)

    return {
        "summary": result.get("summary", ""),
        "priority": priority,
        "todos": [
            {
                "id": todo.id,
                "title": todo.title,
                "priority": todo.priority,
                "is_done": todo.is_done,
            }
            for todo in todos
        ],
    }