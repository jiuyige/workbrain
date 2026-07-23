import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models import Membership, MembershipRole, Organization, User

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def create_membership_parents(session: Session):
    user = User(
        username="membership-user",
        hashed_password="hashed-password",
    )
    first_organization = Organization(
        name="First Organization",
        slug="first-organization",
    )
    second_organization = Organization(
        name="Second Organization",
        slug="second-organization",
    )

    session.add_all(
        [
            user,
            first_organization,
            second_organization,
        ]
    )
    session.commit()

    session.refresh(user)
    session.refresh(first_organization)
    session.refresh(second_organization)

    return user, first_organization, second_organization


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.MEMBER.value,
        MembershipRole.APPROVER.value,
        MembershipRole.ADMIN.value,
    ],
)
def test_membership_accepts_fixed_roles(role):
    with Session(engine) as session:
        user, organization, _ = create_membership_parents(session)

        membership = Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=role,
        )

        session.add(membership)
        session.commit()
        session.refresh(membership)

        assert membership.id is not None
        assert membership.role == role
        assert membership.is_active is True


def test_same_user_can_join_two_organizations():
    with Session(engine) as session:
        user, first_organization, second_organization = create_membership_parents(
            session
        )

        session.add_all(
            [
                Membership(
                    organization_id=first_organization.id,
                    user_id=user.id,
                    role=MembershipRole.ADMIN.value,
                ),
                Membership(
                    organization_id=second_organization.id,
                    user_id=user.id,
                    role=MembershipRole.MEMBER.value,
                ),
            ]
        )
        session.commit()

        memberships = session.exec(
            select(Membership).where(Membership.user_id == user.id)
        ).all()

        assert len(memberships) == 2
        assert {membership.organization_id for membership in memberships} == {
            first_organization.id,
            second_organization.id,
        }


def test_same_user_cannot_join_same_organization_twice():
    with Session(engine) as session:
        user, organization, _ = create_membership_parents(session)

        first_membership = Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=MembershipRole.MEMBER.value,
        )
        session.add(first_membership)
        session.commit()

        duplicate_membership = Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=MembershipRole.ADMIN.value,
        )
        session.add(duplicate_membership)

        with pytest.raises(IntegrityError):
            session.commit()


def test_membership_rejects_unknown_role():
    with Session(engine) as session:
        user, organization, _ = create_membership_parents(session)

        membership = Membership(
            organization_id=organization.id,
            user_id=user.id,
            role="owner",
        )
        session.add(membership)

        with pytest.raises(IntegrityError):
            session.commit()
