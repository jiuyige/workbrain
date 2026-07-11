from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import create_access_token, get_current_user, get_password_hash, verify_password
from app.database import get_session
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


@router.post("/register")
def register(request: RegisterRequest, session: Session = Depends(get_session)):
    statement = select(User).where(User.username == request.username)
    existing_user = session.exec(statement).first()

    if existing_user is not None:
        raise HTTPException(status_code=400, detail="username already exists")

    user = User(
        username=request.username,
        hashed_password=get_password_hash(request.password),
    )

    session.add(user)
    session.commit()
    session.refresh(user)

    return {
        "message": "register success",
        "id": user.id,
        "username": user.username,
    }


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, session: Session = Depends(get_session)):
    statement = select(User).where(User.username == request.username)
    user = session.exec(statement).first()

    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")

    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="invalid username or password")

    access_token = create_access_token(data={"sub": user.username})

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
    }


@router.get("")
def list_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()

    return {
        "users": [
            {"id": user.id, "username": user.username}
            for user in users
        ]
    }