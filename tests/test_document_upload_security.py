from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.models import BackgroundJob, BackgroundJobStatus, Document
from app.routers import documents as document_router
from app.routers.documents import sanitize_upload_filename
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
def client(monkeypatch, tmp_path):
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    previous_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(document_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(document_router, "UPLOAD_MAX_BYTES", 1024)
    monkeypatch.setattr(
        document_router,
        "dispatch_document_processing_job",
        lambda **_kwargs: None,
        raising=False,
    )

    with TestClient(app) as test_client:
        yield test_client

    if previous_override is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous_override


def register_and_login(client: TestClient) -> dict[str, str]:
    username = "secure-upload-user"
    password = "secure-upload-password"
    register_response = client.post(
        "/users/register",
        json={"username": username, "password": password},
    )
    assert register_response.status_code == 200

    login_response = client.post(
        "/users/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200

    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


@pytest.mark.parametrize(
    ("unsafe_name", "safe_name"),
    [
        ("../../payroll.txt", "payroll.txt"),
        (r"..\..\windows.txt", "windows.txt"),
        ("季度\x00报告?.txt", "季度_报告_.txt"),
    ],
)
def test_sanitize_upload_filename_removes_dangerous_parts(
    unsafe_name: str,
    safe_name: str,
):
    assert sanitize_upload_filename(unsafe_name) == safe_name


@pytest.mark.parametrize("filename", [None, "", ".", "..", "../"])
def test_sanitize_upload_filename_rejects_empty_result(filename: str | None):
    with pytest.raises(HTTPException) as raised:
        sanitize_upload_filename(filename)

    assert raised.value.status_code == 400
    assert raised.value.detail == "invalid filename"


def test_upload_rejects_file_larger_than_configured_limit(
    client,
    tmp_path,
    monkeypatch,
):
    headers = register_and_login(client)
    monkeypatch.setattr(document_router, "UPLOAD_MAX_BYTES", 8)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("large.txt", b"123456789", "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["message"] == "file exceeds maximum upload size"
    assert list(tmp_path.iterdir()) == []

    with Session(engine) as session:
        assert session.exec(select(Document)).all() == []


def test_upload_uses_safe_filename_and_preserves_content(client, tmp_path):
    headers = register_and_login(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("../../payroll?.txt", b"safe", "text/plain")},
    )

    assert response.status_code == 202
    assert response.json()["document"]["filename"] == "payroll_.txt"

    with Session(engine) as session:
        document = session.exec(select(Document)).one()

    stored_path = Path(document.file_path)
    assert document.original_filename == "payroll_.txt"
    assert document.stored_filename.endswith("-payroll_.txt")
    assert stored_path.parent == tmp_path
    assert stored_path.read_bytes() == b"safe"


def assert_upload_was_rejected_without_side_effects(
    response,
    tmp_path: Path,
    expected_message: str,
):
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert response.json()["message"] == expected_message
    assert list(tmp_path.iterdir()) == []

    with Session(engine) as session:
        assert session.exec(select(Document)).all() == []


def test_upload_rejects_unsupported_extension(client, tmp_path):
    headers = register_and_login(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("manual.pdf", b"plain text", "text/plain")},
    )

    assert_upload_was_rejected_without_side_effects(
        response,
        tmp_path,
        "unsupported file extension",
    )


def test_upload_rejects_mime_type_that_does_not_match_extension(client, tmp_path):
    headers = register_and_login(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("notes.txt", b"plain text", "application/pdf")},
    )

    assert_upload_was_rejected_without_side_effects(
        response,
        tmp_path,
        "content type does not match file extension",
    )


@pytest.mark.parametrize(
    "binary_content",
    [
        b"%PDF-1.7 fake pdf",
        b"PK\x03\x04fake zip archive",
        b"\xff\xfe\x00\x00invalid utf-8",
        b"text with \x00 control byte",
    ],
)
def test_upload_rejects_binary_content_disguised_as_text(
    client,
    tmp_path,
    binary_content: bytes,
):
    headers = register_and_login(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("disguised.txt", binary_content, "text/plain")},
    )

    assert_upload_was_rejected_without_side_effects(
        response,
        tmp_path,
        "file content does not match text format",
    )


@pytest.mark.parametrize("empty_content", [b"", b" \n\t "])
def test_upload_rejects_empty_text_content(
    client,
    tmp_path,
    empty_content: bytes,
):
    headers = register_and_login(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("empty.md", empty_content, "text/markdown")},
    )

    assert_upload_was_rejected_without_side_effects(
        response,
        tmp_path,
        "file content is empty",
    )


def test_upload_accepts_markdown_and_normalizes_mime_type(client, tmp_path):
    headers = register_and_login(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={
            "file": (
                "guide.md",
                "# WorkBrain\n\n企业知识库。".encode(),
                "text/markdown; charset=utf-8",
            )
        },
    )

    assert response.status_code == 202
    assert response.json()["document"]["content_type"] == "text/markdown"

    with Session(engine) as session:
        document = session.exec(select(Document)).one()

    assert document.content_type == "text/markdown"
    assert (
        Path(document.file_path).read_text(encoding="utf-8").startswith("# WorkBrain")
    )


def test_upload_creates_job_before_dispatching_task(client, tmp_path, monkeypatch):
    headers = register_and_login(client)
    dispatched = {}

    def fake_dispatch_document_processing_job(
        *,
        job_id: int,
        document_id: int,
        task_id: str,
    ):
        with Session(engine) as session:
            assert session.get(BackgroundJob, job_id) is not None
            assert session.get(Document, document_id) is not None

        dispatched.update(
            {
                "job_id": job_id,
                "document_id": document_id,
                "task_id": task_id,
            }
        )

    monkeypatch.setattr(
        document_router,
        "dispatch_document_processing_job",
        fake_dispatch_document_processing_job,
    )

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("queued.txt", b"queued content", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()

    with Session(engine) as session:
        document = session.get(Document, payload["document"]["id"])
        job = session.get(BackgroundJob, payload["job"]["id"])

        assert job.organization_id == document.organization_id
        assert job.created_by_user_id == document.owner_id
        assert job.job_type == "document_processing"
        assert job.status == BackgroundJobStatus.QUEUED.value
        assert job.celery_task_id == dispatched["task_id"]

    assert payload["job"]["status"] == BackgroundJobStatus.QUEUED.value
    assert dispatched["job_id"] == payload["job"]["id"]
    assert dispatched["document_id"] == payload["document"]["id"]


def test_upload_records_safe_failure_when_task_dispatch_fails(
    client,
    tmp_path,
    monkeypatch,
):
    headers = register_and_login(client)

    def fail_dispatch(**_kwargs):
        raise RuntimeError("redis://user:secret-password@private-host")

    monkeypatch.setattr(
        document_router,
        "dispatch_document_processing_job",
        fail_dispatch,
    )

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("dispatch.txt", b"dispatch content", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json()["message"] == "document processing could not be queued"

    with Session(engine) as session:
        document = session.exec(select(Document)).one()
        job = session.exec(select(BackgroundJob)).one()

        assert document.status == "uploaded"
        assert Path(document.file_path).exists()
        assert job.status == BackgroundJobStatus.FAILED.value
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.error_message == "document processing could not be queued"
        assert "secret-password" not in job.error_message
