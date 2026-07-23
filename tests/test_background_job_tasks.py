import pytest
from celery.exceptions import Retry
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import document_processing as processing_module
from app import tasks as task_module
from app.models import (
    BackgroundJob,
    BackgroundJobStatus,
    Document,
    DocumentChunk,
    DocumentProcessLog,
    DocumentStatus,
    KnowledgeBase,
    Organization,
    User,
)


@pytest.fixture
def task_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(task_module, "engine", engine)

    yield engine

    SQLModel.metadata.drop_all(engine)


def create_queued_job(engine) -> int:
    with Session(engine) as session:
        user = User(
            username="task-lifecycle-user",
            hashed_password="hashed-password",
        )
        organization = Organization(
            name="Task Lifecycle Organization",
            slug="task-lifecycle-organization",
        )
        session.add_all([user, organization])
        session.commit()
        session.refresh(user)
        session.refresh(organization)

        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type="example",
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        return job.id


def create_document_job(
    engine,
    file_path: str,
    *,
    job_type: str = "document_processing",
) -> tuple[int, int]:
    with Session(engine) as session:
        user = User(
            username="document-task-user",
            hashed_password="hashed-password",
        )
        organization = Organization(
            name="Document Task Organization",
            slug="document-task-organization",
        )
        session.add_all([user, organization])
        session.flush()

        knowledge_base = KnowledgeBase(
            organization_id=organization.id,
            created_by_user_id=user.id,
            name="Document Task Knowledge Base",
        )
        session.add(knowledge_base)
        session.flush()

        document = Document(
            owner_id=user.id,
            organization_id=organization.id,
            knowledge_base_id=knowledge_base.id,
            original_filename="worker.md",
            stored_filename="worker.md",
            file_path=file_path,
            content_type="text/markdown",
        )
        job = BackgroundJob(
            organization_id=organization.id,
            created_by_user_id=user.id,
            job_type=job_type,
        )
        session.add_all([document, job])
        session.commit()
        session.refresh(document)
        session.refresh(job)

        return document.id, job.id


def test_example_task_succeeds_and_records_lifecycle(task_engine):
    job_id = create_queued_job(task_engine)

    result = task_module.run_example_job.run(
        job_id,
        False,
    )

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert result["status"] == BackgroundJobStatus.SUCCEEDED.value
        assert job.status == BackgroundJobStatus.SUCCEEDED.value
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.error_message is None
        assert job.attempt_count == 1
        assert job.next_retry_at is None


def test_example_task_failure_saves_safe_error(
    task_engine,
    monkeypatch,
):
    job_id = create_queued_job(task_engine)

    def raise_sensitive_error(should_fail):
        raise RuntimeError("SECRET_KEY=do-not-store-this-value")

    monkeypatch.setattr(
        task_module,
        "perform_example_work",
        raise_sensitive_error,
    )

    with pytest.raises(
        RuntimeError,
        match="example task failed",
    ):
        task_module.run_example_job.run(
            job_id,
            False,
        )

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert job.status == BackgroundJobStatus.FAILED.value
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.error_message == "example task failed"
        assert "do-not-store-this-value" not in job.error_message


def test_completed_example_task_is_not_executed_twice(
    task_engine,
    monkeypatch,
):
    job_id = create_queued_job(task_engine)
    execution_count = 0

    def count_execution(should_fail):
        nonlocal execution_count
        execution_count += 1
        return "example task completed"

    monkeypatch.setattr(
        task_module,
        "perform_example_work",
        count_execution,
    )

    first_result = task_module.run_example_job.run(
        job_id,
        False,
    )

    with Session(task_engine) as session:
        first_finished_at = session.get(
            BackgroundJob,
            job_id,
        ).finished_at

    second_result = task_module.run_example_job.run(
        job_id,
        False,
    )

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert execution_count == 1
        assert first_result["status"] == (BackgroundJobStatus.SUCCEEDED.value)
        assert second_result["status"] == (BackgroundJobStatus.SUCCEEDED.value)
        assert job.finished_at == first_finished_at


def test_document_task_builds_ready_document(
    task_engine,
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "worker.md"
    file_path.write_text("# WorkBrain\n\n企业知识库内容。", encoding="utf-8")
    document_id, job_id = create_document_job(task_engine, str(file_path))

    monkeypatch.setattr(
        processing_module,
        "generate_embedding",
        lambda _text: [0.1, 0.2],
    )

    result = task_module.process_document_job.run(job_id, document_id)

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)
        document = session.get(Document, document_id)
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        logs = session.exec(
            select(DocumentProcessLog).where(
                DocumentProcessLog.document_id == document_id
            )
        ).all()

        assert result["status"] == BackgroundJobStatus.SUCCEEDED.value
        assert result["document_id"] == document_id
        assert job.status == BackgroundJobStatus.SUCCEEDED.value
        assert document.status == DocumentStatus.READY.value
        assert document.is_extracted is True
        assert document.extracted_text.startswith("# WorkBrain")
        assert len(chunks) == 1
        assert chunks[0].is_embedded is True
        assert chunks[0].embedding_vector == [0.1, 0.2]
        assert chunks[0].organization_id == document.organization_id
        assert chunks[0].knowledge_base_id == document.knowledge_base_id
        assert chunks[0].document_version == document.version
        assert chunks[0].status == DocumentStatus.READY.value
        assert len(logs) == 1
        assert logs[0].is_success is True
        assert logs[0].organization_id == document.organization_id


@pytest.mark.parametrize(
    ("retry_number", "expected_countdown"),
    [
        (0, 5),
        (1, 10),
        (2, 20),
    ],
)
def test_document_task_failure_preserves_old_ready_data_and_backs_off(
    task_engine,
    monkeypatch,
    tmp_path,
    retry_number,
    expected_countdown,
):
    file_path = tmp_path / "retry.md"
    file_path.write_text("这是新内容。", encoding="utf-8")
    document_id, job_id = create_document_job(task_engine, str(file_path))

    with Session(task_engine) as session:
        document = session.get(Document, document_id)
        document.extracted_text = "这是旧内容。"
        document.is_extracted = True
        document.status = DocumentStatus.READY.value
        session.add(document)
        session.add(
            DocumentChunk(
                owner_id=document.owner_id,
                organization_id=document.organization_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                document_version=document.version,
                status=DocumentStatus.READY.value,
                chunk_index=0,
                content="这是旧内容。",
                char_count=6,
                embedding_vector=[0.3, 0.4],
                is_embedded=True,
            )
        )
        session.commit()

    def fail_with_sensitive_error(_text):
        raise RuntimeError("OPENAI_API_KEY=do-not-store-this-value")

    monkeypatch.setattr(
        processing_module,
        "generate_embedding",
        fail_with_sensitive_error,
    )

    retry_request = {}

    def fake_retry(*, exc, countdown):
        retry_request["exc"] = exc
        retry_request["countdown"] = countdown
        raise Retry(exc=exc, when=countdown)

    monkeypatch.setattr(
        task_module.process_document_job,
        "retry",
        fake_retry,
    )

    task_module.process_document_job.push_request(retries=retry_number)
    try:
        with pytest.raises(Retry):
            task_module.process_document_job.run(job_id, document_id)
    finally:
        task_module.process_document_job.pop_request()

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)
        document = session.get(Document, document_id)
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        log = session.exec(
            select(DocumentProcessLog).where(
                DocumentProcessLog.document_id == document_id
            )
        ).one()

        assert job.status == BackgroundJobStatus.QUEUED.value
        assert job.attempt_count == 1
        assert job.next_retry_at is not None
        assert job.started_at is None
        assert job.finished_at is None
        assert job.error_message is None
        assert retry_request["countdown"] == expected_countdown
        assert str(retry_request["exc"]) == "failed to create embedding"
        assert "do-not-store-this-value" not in str(retry_request["exc"])
        assert document.status == DocumentStatus.READY.value
        assert document.extracted_text == "这是旧内容。"
        assert len(chunks) == 1
        assert chunks[0].content == "这是旧内容。"
        assert log.is_success is False
        assert log.error_message == "failed to create embedding"


def test_document_task_fails_after_retry_limit(
    task_engine,
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "retry-limit.md"
    file_path.write_text("始终失败。", encoding="utf-8")
    document_id, job_id = create_document_job(task_engine, str(file_path))

    monkeypatch.setattr(
        processing_module,
        "generate_embedding",
        lambda _text: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    task_module.process_document_job.push_request(retries=3)
    try:
        with pytest.raises(RuntimeError, match="failed to create embedding"):
            task_module.process_document_job.run(job_id, document_id)
    finally:
        task_module.process_document_job.pop_request()

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert job.status == BackgroundJobStatus.FAILED.value
        assert job.attempt_count == 1
        assert job.next_retry_at is None
        assert job.error_message == "failed to create embedding"


def test_permanent_document_error_does_not_retry(
    task_engine,
    tmp_path,
):
    missing_path = tmp_path / "missing.md"
    document_id, job_id = create_document_job(task_engine, str(missing_path))

    with pytest.raises(RuntimeError, match="file not found"):
        task_module.process_document_job.run(job_id, document_id)

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert job.status == BackgroundJobStatus.FAILED.value
        assert job.attempt_count == 1
        assert job.next_retry_at is None
        assert job.error_message == "file not found"


def test_running_document_job_is_not_claimed_twice(
    task_engine,
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "already-running.md"
    file_path.write_text("不能重复处理。", encoding="utf-8")
    document_id, job_id = create_document_job(task_engine, str(file_path))

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)
        job.status = BackgroundJobStatus.RUNNING.value
        job.started_at = job.created_at
        job.attempt_count = 1
        session.add(job)
        session.commit()

    def fail_if_called(_session, _document):
        raise AssertionError("a running job must not execute twice")

    monkeypatch.setattr(
        task_module,
        "process_document_record",
        fail_if_called,
    )

    result = task_module.process_document_job.run(job_id, document_id)

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert result["status"] == BackgroundJobStatus.RUNNING.value
        assert job.status == BackgroundJobStatus.RUNNING.value
        assert job.attempt_count == 1


def test_document_job_cannot_run_before_next_retry_at(
    task_engine,
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "wait-for-retry.md"
    file_path.write_text("等待重试时间。", encoding="utf-8")
    document_id, job_id = create_document_job(task_engine, str(file_path))

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)
        job.attempt_count = 1
        job.next_retry_at = job.created_at.replace(year=job.created_at.year + 1)
        session.add(job)
        session.commit()

    def fail_if_called(_session, _document):
        raise AssertionError("a retry must wait until next_retry_at")

    monkeypatch.setattr(
        task_module,
        "process_document_record",
        fail_if_called,
    )

    result = task_module.process_document_job.run(job_id, document_id)

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)

        assert result["status"] == BackgroundJobStatus.QUEUED.value
        assert job.status == BackgroundJobStatus.QUEUED.value
        assert job.attempt_count == 1
        assert job.next_retry_at is not None


def test_completed_document_task_does_not_process_twice(
    task_engine,
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "once.txt"
    file_path.write_text("只处理一次。", encoding="utf-8")
    document_id, job_id = create_document_job(task_engine, str(file_path))
    embedding_calls = 0

    def count_embedding_calls(_text):
        nonlocal embedding_calls
        embedding_calls += 1
        return [0.5, 0.6]

    monkeypatch.setattr(
        processing_module,
        "generate_embedding",
        count_embedding_calls,
    )

    first_result = task_module.process_document_job.run(job_id, document_id)
    second_result = task_module.process_document_job.run(job_id, document_id)

    with Session(task_engine) as session:
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        logs = session.exec(
            select(DocumentProcessLog).where(
                DocumentProcessLog.document_id == document_id
            )
        ).all()

        assert first_result["status"] == BackgroundJobStatus.SUCCEEDED.value
        assert second_result["status"] == BackgroundJobStatus.SUCCEEDED.value
        assert embedding_calls == 1
        assert len(chunks) == 1
        assert len(logs) == 1


def test_document_task_rejects_wrong_job_type(
    task_engine,
    tmp_path,
):
    file_path = tmp_path / "wrong-job.txt"
    file_path.write_text("不能执行。", encoding="utf-8")
    document_id, job_id = create_document_job(
        task_engine,
        str(file_path),
        job_type="example",
    )

    with pytest.raises(RuntimeError, match="document processing job is invalid"):
        task_module.process_document_job.run(job_id, document_id)

    with Session(task_engine) as session:
        job = session.get(BackgroundJob, job_id)
        document = session.get(Document, document_id)

        assert job.status == BackgroundJobStatus.FAILED.value
        assert job.error_message == "document processing job is invalid"
        assert document.status == DocumentStatus.UPLOADED.value
