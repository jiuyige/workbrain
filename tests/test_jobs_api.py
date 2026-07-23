from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.context import ORGANIZATION_ID_HEADER
from app.database import get_session
from app.models import BackgroundJob, User
from app.routers import jobs as jobs_router
from main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    with Session(engine) as session:
        yield session


@pytest.fixture
def client():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    previous_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    if previous_override is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous_override


def register_and_login(
    client: TestClient,
    username: str,
) -> dict[str, str]:
    password = "background-job-api-password"

    register_response = client.post(
        "/users/register",
        json={
            "username": username,
            "password": password,
        },
    )
    assert register_response.status_code == 200

    login_response = client.post(
        "/users/login",
        json={
            "username": username,
            "password": password,
        },
    )
    assert login_response.status_code == 200

    return {"Authorization": (f"Bearer {login_response.json()['access_token']}")}


def create_organization_context(
    client: TestClient,
    *,
    username: str,
    name: str,
    slug: str,
):
    headers = register_and_login(client, username)

    response = client.post(
        "/organizations",
        headers=headers,
        json={
            "name": name,
            "slug": slug,
        },
    )
    assert response.status_code == 201

    organization = response.json()
    headers[ORGANIZATION_ID_HEADER] = str(organization["id"])

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).one()
        user_id = user.id

    return headers, organization["id"], user_id


def create_background_job(
    *,
    organization_id: int,
    created_by_user_id: int,
    job_type: str,
    created_at: datetime,
    attempt_count: int = 0,
    next_retry_at: datetime | None = None,
) -> int:
    with Session(engine) as session:
        job = BackgroundJob(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            job_type=job_type,
            created_at=created_at,
            attempt_count=attempt_count,
            next_retry_at=next_retry_at,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        return job.id


def test_jobs_require_authentication(client):
    response = client.get(
        "/jobs",
        headers={ORGANIZATION_ID_HEADER: "1"},
    )

    assert response.status_code == 401


def test_list_jobs_only_returns_current_organization_with_pagination(client):
    first_headers, first_organization_id, first_user_id = create_organization_context(
        client,
        username="first-job-user",
        name="First Job Organization",
        slug="first-job-organization",
    )
    _, second_organization_id, second_user_id = create_organization_context(
        client,
        username="second-job-user",
        name="Second Job Organization",
        slug="second-job-organization",
    )

    now = datetime.now(timezone.utc)

    create_background_job(
        organization_id=first_organization_id,
        created_by_user_id=first_user_id,
        job_type="first-job",
        created_at=now,
    )
    create_background_job(
        organization_id=first_organization_id,
        created_by_user_id=first_user_id,
        job_type="second-job",
        created_at=now + timedelta(seconds=1),
    )
    create_background_job(
        organization_id=first_organization_id,
        created_by_user_id=first_user_id,
        job_type="third-job",
        created_at=now + timedelta(seconds=2),
    )
    create_background_job(
        organization_id=second_organization_id,
        created_by_user_id=second_user_id,
        job_type="hidden-job",
        created_at=now + timedelta(seconds=3),
    )

    response = client.get(
        "/jobs?offset=1&limit=2",
        headers=first_headers,
    )

    assert response.status_code == 200

    payload = response.json()

    assert [job["job_type"] for job in payload["jobs"]] == [
        "second-job",
        "first-job",
    ]
    assert payload["pagination"] == {
        "offset": 1,
        "limit": 2,
        "total": 3,
        "returned": 2,
    }
    assert all(job["job_type"] != "hidden-job" for job in payload["jobs"])


def test_read_job_hides_other_organization_resources(client):
    first_headers, first_organization_id, first_user_id = create_organization_context(
        client,
        username="job-owner",
        name="Job Owner Organization",
        slug="job-owner-organization",
    )
    second_headers, _, _ = create_organization_context(
        client,
        username="job-outsider",
        name="Job Outsider Organization",
        slug="job-outsider-organization",
    )

    job_id = create_background_job(
        organization_id=first_organization_id,
        created_by_user_id=first_user_id,
        job_type="private-job",
        created_at=datetime.now(timezone.utc),
    )

    own_response = client.get(
        f"/jobs/{job_id}",
        headers=first_headers,
    )
    cross_organization_response = client.get(
        f"/jobs/{job_id}",
        headers=second_headers,
    )
    missing_response = client.get(
        "/jobs/999999",
        headers=first_headers,
    )

    assert own_response.status_code == 200
    assert own_response.json()["id"] == job_id
    assert own_response.json()["job_type"] == "private-job"
    assert own_response.json()["status"] == "queued"
    assert own_response.json()["attempt_count"] == 0
    assert own_response.json()["next_retry_at"] is None

    assert cross_organization_response.status_code == 404
    assert missing_response.status_code == 404
    assert cross_organization_response.json()["message"] == ("background job not found")
    assert missing_response.json()["message"] == ("background job not found")


def test_read_job_exposes_retry_progress(client):
    headers, organization_id, user_id = create_organization_context(
        client,
        username="retry-progress-user",
        name="Retry Progress Organization",
        slug="retry-progress-organization",
    )
    next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    job_id = create_background_job(
        organization_id=organization_id,
        created_by_user_id=user_id,
        job_type="document_processing",
        created_at=datetime.now(timezone.utc),
        attempt_count=2,
        next_retry_at=next_retry_at,
    )

    response = client.get(
        f"/jobs/{job_id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["attempt_count"] == 2
    returned_retry_at = datetime.fromisoformat(response.json()["next_retry_at"])
    assert returned_retry_at.replace(tzinfo=timezone.utc) == next_retry_at


@pytest.mark.parametrize(
    ("case_name", "query_string"),
    [
        ("negative-offset", "offset=-1&limit=20"),
        ("zero-limit", "offset=0&limit=0"),
        ("oversized-limit", "offset=0&limit=101"),
    ],
)
def test_list_jobs_rejects_invalid_pagination(
    client,
    case_name,
    query_string,
):
    headers, _, _ = create_organization_context(
        client,
        username=f"pagination-user-{case_name}",
        name="Pagination Organization",
        slug=f"pagination-organization-{case_name}",
    )

    response = client.get(
        f"/jobs?{query_string}",
        headers=headers,
    )

    assert response.status_code == 422


def test_create_example_job_queues_celery_task(
    client,
    monkeypatch,
):
    headers, organization_id, user_id = create_organization_context(
        client,
        username="example-job-user",
        name="Example Job Organization",
        slug="example-job-organization",
    )
    dispatched_task = {}

    def fake_apply_async(*, args, task_id):
        dispatched_task["args"] = args
        dispatched_task["task_id"] = task_id

    monkeypatch.setattr(
        jobs_router.run_example_job,
        "apply_async",
        fake_apply_async,
    )

    response = client.post(
        "/jobs/example",
        headers=headers,
        json={"should_fail": True},
    )

    assert response.status_code == 202

    payload = response.json()

    assert payload["job_type"] == "example"
    assert payload["status"] == "queued"
    assert "celery_task_id" not in payload

    with Session(engine) as session:
        job = session.get(
            BackgroundJob,
            payload["id"],
        )

        assert job.organization_id == organization_id
        assert job.created_by_user_id == user_id
        assert job.celery_task_id == (dispatched_task["task_id"])

    assert dispatched_task["args"] == [
        payload["id"],
        True,
    ]
