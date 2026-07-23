from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app.background_jobs import (
    claim_background_job,
    mark_background_job_failed,
    mark_background_job_queued_for_retry,
    mark_background_job_succeeded,
)
from app.celery_app import celery_app
from app.config import (
    DOCUMENT_PROCESSING_MAX_RETRIES,
    DOCUMENT_PROCESSING_RETRY_BASE_SECONDS,
)
from app.database import engine
from app.document_processing import (
    DOCUMENT_PROCESSING_JOB_TYPE,
    DOCUMENT_PROCESSING_TASK_ERROR,
    DOCUMENT_PROCESSING_TASK_NAME,
    INVALID_DOCUMENT_PROCESSING_JOB_ERROR,
    DocumentProcessingError,
    process_document_record,
)
from app.models import BackgroundJobStatus, Document

EXAMPLE_TASK_ERROR_MESSAGE = "example task failed"


def perform_example_work(
    should_fail: bool,
) -> str:
    if should_fail:
        raise RuntimeError(EXAMPLE_TASK_ERROR_MESSAGE)

    return "example task completed"


@celery_app.task(name="workbrain.run_example_job")
def run_example_job(
    job_id: int,
    should_fail: bool = False,
):
    with Session(engine) as session:
        claim = claim_background_job(
            session,
            job_id,
        )
        job = claim.job

        if job is None:
            return {
                "job_id": job_id,
                "status": "missing",
            }

        if not claim.acquired:
            return {
                "job_id": job_id,
                "status": job.status,
            }

        try:
            result = perform_example_work(should_fail)
        except Exception:
            failed_job = mark_background_job_failed(
                session,
                job_id,
                safe_error_message=EXAMPLE_TASK_ERROR_MESSAGE,
            )

            if (
                failed_job is not None
                and failed_job.status == BackgroundJobStatus.CANCELLED.value
            ):
                return {
                    "job_id": job_id,
                    "status": failed_job.status,
                }

            raise RuntimeError(EXAMPLE_TASK_ERROR_MESSAGE) from None

        succeeded_job = mark_background_job_succeeded(
            session,
            job_id,
        )

        return {
            "job_id": job_id,
            "status": succeeded_job.status,
            "result": result,
        }


def fail_document_processing_job(
    session: Session,
    job_id: int,
    safe_error_message: str,
):
    failed_job = mark_background_job_failed(
        session,
        job_id,
        safe_error_message=safe_error_message,
    )

    if (
        failed_job is not None
        and failed_job.status == BackgroundJobStatus.CANCELLED.value
    ):
        return {
            "job_id": job_id,
            "status": failed_job.status,
        }

    raise RuntimeError(safe_error_message) from None


def retry_document_processing_job(
    task,
    session: Session,
    job_id: int,
    safe_error_message: str,
):
    if task.request.retries >= DOCUMENT_PROCESSING_MAX_RETRIES:
        return fail_document_processing_job(
            session,
            job_id,
            safe_error_message,
        )

    countdown = DOCUMENT_PROCESSING_RETRY_BASE_SECONDS * (2**task.request.retries)
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=countdown)
    queued_job = mark_background_job_queued_for_retry(
        session,
        job_id,
        next_retry_at=retry_at,
    )

    if (
        queued_job is not None
        and queued_job.status == BackgroundJobStatus.CANCELLED.value
    ):
        return {
            "job_id": job_id,
            "status": queued_job.status,
        }

    raise task.retry(
        exc=RuntimeError(safe_error_message),
        countdown=countdown,
    )


@celery_app.task(
    bind=True,
    name=DOCUMENT_PROCESSING_TASK_NAME,
    max_retries=DOCUMENT_PROCESSING_MAX_RETRIES,
)
def process_document_job(
    self,
    job_id: int,
    document_id: int,
):
    with Session(engine) as session:
        claim = claim_background_job(session, job_id)
        job = claim.job

        if job is None:
            return {
                "job_id": job_id,
                "document_id": document_id,
                "status": "missing",
            }

        if not claim.acquired:
            return {
                "job_id": job_id,
                "document_id": document_id,
                "status": job.status,
            }

        document = session.get(Document, document_id)

        if (
            job.job_type != DOCUMENT_PROCESSING_JOB_TYPE
            or document is None
            or document.organization_id != job.organization_id
            or document.owner_id != job.created_by_user_id
        ):
            return fail_document_processing_job(
                session,
                job_id,
                INVALID_DOCUMENT_PROCESSING_JOB_ERROR,
            )

        try:
            result = process_document_record(session, document)
        except DocumentProcessingError as error:
            if error.status_code >= 500:
                return retry_document_processing_job(
                    self,
                    session,
                    job_id,
                    error.detail,
                )

            return fail_document_processing_job(
                session,
                job_id,
                error.detail,
            )
        except Exception:
            return retry_document_processing_job(
                self,
                session,
                job_id,
                DOCUMENT_PROCESSING_TASK_ERROR,
            )

        succeeded_job = mark_background_job_succeeded(session, job_id)

        return {
            "job_id": job_id,
            "document_id": document_id,
            "status": succeeded_job.status,
            "chunk_count": result.chunk_count,
            "embedded_count": result.embedded_count,
            "process_log_id": result.process_log_id,
        }
