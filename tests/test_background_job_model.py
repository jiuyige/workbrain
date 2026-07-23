from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import (
    BackgroundJob,
    BackgroundJobStatus,
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


def create_job_parents(session: Session):
    user = User(
        username="background-job-user",
        hashed_password="hashed-password",
    )
    organization = Organization(
        name="Background Job Organization",
        slug="background-job-organization",
    )

    session.add_all([user, organization])
    session.commit()
    session.refresh(user)
    session.refresh(organization)

    return user, organization


def test_background_job_defaults_to_queued():
    with Session(engine) as session:
        user, organization = create_job_parents(session)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
        )

        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.id is not None
        assert job.status == BackgroundJobStatus.QUEUED.value
        assert job.started_at is None
        assert job.finished_at is None
        assert job.error_message is None
        assert job.attempt_count == 0
        assert job.next_retry_at is None


@pytest.mark.parametrize(
    ("status", "has_started", "has_finished", "error_message"),
    [
        (BackgroundJobStatus.RUNNING.value, True, False, None),
        (BackgroundJobStatus.SUCCEEDED.value, True, True, None),
        (BackgroundJobStatus.FAILED.value, True, True, "example failure"),
        (BackgroundJobStatus.CANCELLED.value, False, True, None),
    ],
)
def test_background_job_accepts_valid_lifecycle(
    status,
    has_started,
    has_finished,
    error_message,
):
    with Session(engine) as session:
        user, organization = create_job_parents(session)
        now = datetime.now(timezone.utc)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            status=status,
            created_at=now,
            started_at=now if has_started else None,
            finished_at=now if has_finished else None,
            error_message=error_message,
        )

        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.status == status


def test_background_job_rejects_unknown_status():
    with Session(engine) as session:
        user, organization = create_job_parents(session)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            status="paused",
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()


def test_failed_background_job_requires_error_message():
    with Session(engine) as session:
        user, organization = create_job_parents(session)
        now = datetime.now(timezone.utc)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            status=BackgroundJobStatus.FAILED.value,
            created_at=now,
            started_at=now,
            finished_at=now,
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()


def test_non_failed_background_job_rejects_error_message():
    with Session(engine) as session:
        user, organization = create_job_parents(session)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            error_message="unexpected error",
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()


def test_succeeded_background_job_requires_finished_at():
    with Session(engine) as session:
        user, organization = create_job_parents(session)
        now = datetime.now(timezone.utc)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            status=BackgroundJobStatus.SUCCEEDED.value,
            created_at=now,
            started_at=now,
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()


def test_background_job_rejects_blank_job_type():
    with Session(engine) as session:
        user, organization = create_job_parents(session)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="   ",
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()


def test_background_job_rejects_negative_attempt_count():
    with Session(engine) as session:
        user, organization = create_job_parents(session)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            attempt_count=-1,
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()


def test_non_queued_background_job_rejects_next_retry_at():
    with Session(engine) as session:
        user, organization = create_job_parents(session)
        now = datetime.now(timezone.utc)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
            status=BackgroundJobStatus.RUNNING.value,
            started_at=now,
            next_retry_at=now,
        )
        session.add(job)

        with pytest.raises(IntegrityError):
            session.commit()
