from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.context import (
    OrganizationContext,
    get_current_organization_context,
)
from app.database import get_session
from app.models import BackgroundJob
from app.tasks import run_example_job

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
)


class ExampleJobRequest(BaseModel):
    should_fail: bool = False


class BackgroundJobResponse(BaseModel):
    id: int
    created_by_user_id: int
    job_type: str
    status: str
    error_message: str | None
    attempt_count: int
    next_retry_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PaginationResponse(BaseModel):
    offset: int
    limit: int
    total: int
    returned: int


class BackgroundJobListResponse(BaseModel):
    jobs: list[BackgroundJobResponse]
    pagination: PaginationResponse


def build_background_job_response(
    job: BackgroundJob,
) -> BackgroundJobResponse:
    return BackgroundJobResponse(
        id=job.id,
        created_by_user_id=job.created_by_user_id,
        job_type=job.job_type,
        status=job.status,
        error_message=job.error_message,
        attempt_count=job.attempt_count,
        next_retry_at=job.next_retry_at,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/example",
    response_model=BackgroundJobResponse,
    status_code=202,
)
def create_example_background_job(
    request: ExampleJobRequest,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    task_id = str(uuid4())

    job = BackgroundJob(
        organization_id=context.organization.id,
        created_by_user_id=context.membership.user_id,
        job_type="example",
        celery_task_id=task_id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    run_example_job.apply_async(
        args=[job.id, request.should_fail],
        task_id=task_id,
    )

    return build_background_job_response(job)


@router.get(
    "",
    response_model=BackgroundJobListResponse,
)
def list_background_jobs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    organization_condition = BackgroundJob.organization_id == context.organization.id

    total = session.exec(
        select(func.count()).select_from(BackgroundJob).where(organization_condition)
    ).one()

    jobs = session.exec(
        select(BackgroundJob)
        .where(organization_condition)
        .order_by(
            BackgroundJob.created_at.desc(),
            BackgroundJob.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return BackgroundJobListResponse(
        jobs=[build_background_job_response(job) for job in jobs],
        pagination=PaginationResponse(
            offset=offset,
            limit=limit,
            total=total,
            returned=len(jobs),
        ),
    )


@router.get(
    "/{job_id}",
    response_model=BackgroundJobResponse,
)
def read_background_job(
    job_id: int,
    context: OrganizationContext = Depends(get_current_organization_context),
    session: Session = Depends(get_session),
):
    job = session.exec(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.organization_id == context.organization.id,
        )
    ).first()

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="background job not found",
        )

    return build_background_job_response(job)
