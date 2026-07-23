from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.database import get_session
from app.models import (
    LEGACY_KNOWLEDGE_BASE_ID,
    LEGACY_KNOWLEDGE_BASE_NAME,
    LEGACY_ORGANIZATION_ID,
    LEGACY_ORGANIZATION_NAME,
    LEGACY_ORGANIZATION_SLUG,
    KnowledgeBase,
    Membership,
    MembershipRole,
    Organization,
    User,
)

router = APIRouter(prefix="/users", tags=["users"])


class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


@router.post("/register")
def register(
    request: RegisterRequest,
    session: Session = Depends(get_session),
):
    statement = select(User).where(User.username == request.username)
    existing_user = session.exec(statement).first()

    if existing_user is not None:
        raise HTTPException(
            status_code=400,
            detail="username already exists",
        )

    legacy_organization = session.get(
        Organization,
        LEGACY_ORGANIZATION_ID,
    )

    if legacy_organization is None:
        legacy_organization = Organization(
            id=LEGACY_ORGANIZATION_ID,
            name=LEGACY_ORGANIZATION_NAME,
            slug=LEGACY_ORGANIZATION_SLUG,
        )
        session.add(legacy_organization)

    user = User(
        username=request.username,
        hashed_password=get_password_hash(request.password),
    )
    session.add(user)

    try:
        session.flush()

        legacy_knowledge_base = session.get(
            KnowledgeBase,
            LEGACY_KNOWLEDGE_BASE_ID,
        )

        if legacy_knowledge_base is None:
            legacy_knowledge_base = KnowledgeBase(
                id=LEGACY_KNOWLEDGE_BASE_ID,
                organization_id=LEGACY_ORGANIZATION_ID,
                created_by_user_id=user.id,
                name=LEGACY_KNOWLEDGE_BASE_NAME,
            )
            session.add(legacy_knowledge_base)

        membership = Membership(
            organization_id=LEGACY_ORGANIZATION_ID,
            user_id=user.id,
            role=MembershipRole.MEMBER.value,
        )
        session.add(membership)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="registration could not be completed",
        ) from error

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
def list_users(
    current_user: User = Depends(get_current_user),
):
    return {
        "users": [
            {
                "id": current_user.id,
                "username": current_user.username,
            }
        ]
    }
