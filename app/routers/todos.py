from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models import Todo, User

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("")
def list_todos(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = (
        select(Todo)
        .where(Todo.owner_id == current_user.id)
        .order_by(Todo.created_at.desc())
    )
    todos = session.exec(statement).all()

    return {
        "todos": [
            {
                "id": todo.id,
                "title": todo.title,
                "priority": todo.priority,
                "is_done": todo.is_done,
                "created_at": todo.created_at,
            }
            for todo in todos
        ]
    }


@router.patch("/{todo_id}/done")
def mark_todo_done(
    todo_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Todo).where(
        Todo.id == todo_id,
        Todo.owner_id == current_user.id,
    )
    todo = session.exec(statement).first()

    if todo is None:
        raise HTTPException(status_code=404, detail="todo not found")

    todo.is_done = True

    session.add(todo)
    session.commit()
    session.refresh(todo)

    return {
        "message": "todo marked as done",
        "todo": {
            "id": todo.id,
            "title": todo.title,
            "priority": todo.priority,
            "is_done": todo.is_done,
        },
    }


@router.delete("/{todo_id}")
def delete_todo(
    todo_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    statement = select(Todo).where(
        Todo.id == todo_id,
        Todo.owner_id == current_user.id,
    )
    todo = session.exec(statement).first()

    if todo is None:
        raise HTTPException(status_code=404, detail="todo not found")

    session.delete(todo)
    session.commit()

    return {"message": "todo deleted"}