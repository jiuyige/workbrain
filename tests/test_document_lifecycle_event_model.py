from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import (
    DocumentLifecycleAction,
    DocumentLifecycleEvent,
    Organization,
    User,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def create_event_parents(session: Session) -> tuple[User, Organization]:
    user = User(
        username="document-lifecycle-user",
        hashed_password="hashed-password",
    )
    organization = Organization(
        name="Document Lifecycle Organization",
        slug="document-lifecycle-organization",
    )
    session.add_all([user, organization])
    session.commit()
    session.refresh(user)
    session.refresh(organization)
    return user, organization


def test_document_lifecycle_event_records_publish_transition():
    with Session(engine) as session:
        user, organization = create_event_parents(session)
        event = DocumentLifecycleEvent(
            organization_id=organization.id,
            document_id=42,
            actor_user_id=user.id,
            action=DocumentLifecycleAction.PUBLISH.value,
            from_status="ready",
            to_status="published",
            document_version=2,
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        assert event.id is not None
        assert event.created_at is not None
        assert event.document_version == 2


@pytest.mark.parametrize(
    ("action", "from_status", "to_status", "document_version"),
    [
        ("delete", "published", "archived", 1),
        ("publish", "uploaded", "published", 1),
        ("archive", "ready", "archived", 1),
        ("publish", "ready", "published", 0),
    ],
)
def test_document_lifecycle_event_rejects_invalid_transition(
    action,
    from_status,
    to_status,
    document_version,
):
    with Session(engine) as session:
        user, organization = create_event_parents(session)
        session.add(
            DocumentLifecycleEvent(
                organization_id=organization.id,
                document_id=42,
                actor_user_id=user.id,
                action=action,
                from_status=from_status,
                to_status=to_status,
                document_version=document_version,
                created_at=datetime.now(timezone.utc),
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()
