import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import KnowledgeBase, Organization, User

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def create_parents(session: Session):
    user = User(
        username="knowledge-base-model-user",
        hashed_password="hashed-password",
    )
    first_organization = Organization(
        name="First Knowledge Organization",
        slug="first-knowledge-organization",
    )
    second_organization = Organization(
        name="Second Knowledge Organization",
        slug="second-knowledge-organization",
    )
    session.add_all([user, first_organization, second_organization])
    session.commit()
    session.refresh(user)
    session.refresh(first_organization)
    session.refresh(second_organization)

    return user, first_organization, second_organization


def test_knowledge_base_can_be_saved():
    with Session(engine) as session:
        user, organization, _ = create_parents(session)
        knowledge_base = KnowledgeBase(
            organization_id=organization.id,
            created_by_user_id=user.id,
            name="IT Support",
            description="Internal IT support knowledge.",
        )

        session.add(knowledge_base)
        session.commit()
        session.refresh(knowledge_base)

        assert knowledge_base.id is not None
        assert knowledge_base.name == "IT Support"
        assert knowledge_base.created_at is not None
        assert knowledge_base.updated_at is not None


def test_knowledge_base_name_must_be_unique_inside_organization():
    with Session(engine) as session:
        user, organization, _ = create_parents(session)
        session.add(
            KnowledgeBase(
                organization_id=organization.id,
                created_by_user_id=user.id,
                name="Shared Name",
            )
        )
        session.commit()

        session.add(
            KnowledgeBase(
                organization_id=organization.id,
                created_by_user_id=user.id,
                name="Shared Name",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_two_organizations_can_use_same_knowledge_base_name():
    with Session(engine) as session:
        user, first_organization, second_organization = create_parents(session)
        session.add_all(
            [
                KnowledgeBase(
                    organization_id=first_organization.id,
                    created_by_user_id=user.id,
                    name="Company Handbook",
                ),
                KnowledgeBase(
                    organization_id=second_organization.id,
                    created_by_user_id=user.id,
                    name="Company Handbook",
                ),
            ]
        )

        session.commit()


def test_knowledge_base_rejects_blank_name():
    with Session(engine) as session:
        user, organization, _ = create_parents(session)
        session.add(
            KnowledgeBase(
                organization_id=organization.id,
                created_by_user_id=user.id,
                name="   ",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()
