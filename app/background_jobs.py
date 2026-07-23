from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, update
from sqlmodel import Session

from app.models import BackgroundJob, BackgroundJobStatus

TERMINAL_JOB_STATUSES = {
    BackgroundJobStatus.SUCCEEDED.value,
    BackgroundJobStatus.FAILED.value,
    BackgroundJobStatus.CANCELLED.value,
}


@dataclass(frozen=True)
class BackgroundJobClaim:
    job: BackgroundJob | None
    acquired: bool


def claim_background_job(
    session: Session,
    job_id: int,
) -> BackgroundJobClaim:
    claimed_at = datetime.now(timezone.utc)
    result = session.exec(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == BackgroundJobStatus.QUEUED.value,
            or_(
                BackgroundJob.next_retry_at.is_(None),
                BackgroundJob.next_retry_at <= claimed_at,
            ),
        )
        .values(
            status=BackgroundJobStatus.RUNNING.value,
            started_at=claimed_at,
            finished_at=None,
            error_message=None,
            next_retry_at=None,
            attempt_count=BackgroundJob.attempt_count + 1,
        )
    )
    session.commit()
    session.expire_all()

    return BackgroundJobClaim(
        job=session.get(BackgroundJob, job_id),
        acquired=result.rowcount == 1,
    )


def mark_background_job_running(
    session: Session,
    job_id: int,
) -> BackgroundJob | None:
    return claim_background_job(session, job_id).job


def mark_background_job_queued_for_retry(
    session: Session,
    job_id: int,
    *,
    next_retry_at: datetime,
) -> BackgroundJob | None:
    job = session.get(BackgroundJob, job_id)

    if job is None:
        return None

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    if job.status != BackgroundJobStatus.RUNNING.value:
        raise RuntimeError("background job must be running before retrying")

    job.status = BackgroundJobStatus.QUEUED.value
    job.started_at = None
    job.finished_at = None
    job.error_message = None
    job.next_retry_at = next_retry_at

    session.add(job)
    session.commit()
    session.refresh(job)

    return job


def mark_background_job_succeeded(
    session: Session,
    job_id: int,
) -> BackgroundJob | None:
    job = session.get(BackgroundJob, job_id)

    if job is None:
        return None

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    if job.status != BackgroundJobStatus.RUNNING.value:
        raise RuntimeError("background job must be running before succeeding")

    job.status = BackgroundJobStatus.SUCCEEDED.value
    job.finished_at = datetime.now(timezone.utc)
    job.error_message = None
    job.next_retry_at = None

    session.add(job)
    session.commit()
    session.refresh(job)

    return job


def mark_background_job_failed(
    session: Session,
    job_id: int,
    *,
    safe_error_message: str,
) -> BackgroundJob | None:
    job = session.get(BackgroundJob, job_id)

    if job is None:
        return None

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    if job.status != BackgroundJobStatus.RUNNING.value:
        raise RuntimeError("background job must be running before failing")

    normalized_error = safe_error_message.strip()

    if not normalized_error:
        normalized_error = "background job failed"

    job.status = BackgroundJobStatus.FAILED.value
    job.finished_at = datetime.now(timezone.utc)
    job.error_message = normalized_error[:1000]
    job.next_retry_at = None

    session.add(job)
    session.commit()
    session.refresh(job)

    return job


def mark_background_job_dispatch_failed(
    session: Session,
    job_id: int,
    *,
    safe_error_message: str,
) -> BackgroundJob | None:
    job = session.get(BackgroundJob, job_id)

    if job is None:
        return None

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    if job.status != BackgroundJobStatus.QUEUED.value:
        raise RuntimeError("only a queued background job can fail dispatch")

    normalized_error = safe_error_message.strip()

    if not normalized_error:
        normalized_error = "background job could not be queued"

    failed_at = datetime.now(timezone.utc)
    job.status = BackgroundJobStatus.FAILED.value
    job.started_at = failed_at
    job.finished_at = failed_at
    job.error_message = normalized_error[:1000]
    job.next_retry_at = None

    session.add(job)
    session.commit()
    session.refresh(job)

    return job
