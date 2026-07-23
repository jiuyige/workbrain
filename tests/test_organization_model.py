import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import Organization

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def test_organization_can_be_saved():
    organization = Organization(
        name="WorkBrain Technology",
        slug="workbrain",
    )

    with Session(engine) as session:
        session.add(organization)
        session.commit()
        session.refresh(organization)

        assert organization.id is not None
        assert organization.name == "WorkBrain Technology"
        assert organization.slug == "workbrain"
        assert organization.created_at is not None


def test_organization_name_cannot_be_blank():
    organization = Organization(
        name="   ",
        slug="blank-name",
    )

    with Session(engine) as session:
        session.add(organization)

        with pytest.raises(IntegrityError):
            session.commit()


def test_organization_slug_cannot_be_too_short():
    organization = Organization(
        name="Short Slug Organization",
        slug="ab",
    )

    with Session(engine) as session:
        session.add(organization)

        with pytest.raises(IntegrityError):
            session.commit()


def test_organization_slug_must_be_unique():
    first = Organization(
        name="First Organization",
        slug="shared-slug",
    )
    second = Organization(
        name="Second Organization",
        slug="shared-slug",
    )

    with Session(engine) as session:
        session.add(first)
        session.commit()

        session.add(second)

        with pytest.raises(IntegrityError):
            session.commit()
