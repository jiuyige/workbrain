import importlib
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.models import (
    Document,
    DocumentChunk,
    DocumentProcessLog,
    DocumentStatus,
    User,
)
from main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


@pytest.mark.parametrize(
    ("app_env", "expected_create_calls"),
    [
        ("development", 1),
        ("production", 0),
    ],
)
def test_startup_table_creation_depends_on_environment(
    monkeypatch,
    app_env,
    expected_create_calls,
):
    main_module = importlib.import_module("app.main")
    create_calls = []

    monkeypatch.setattr(main_module, "APP_ENV", app_env)
    monkeypatch.setattr(
        main_module,
        "create_db_and_tables",
        lambda: create_calls.append("called"),
    )

    main_module.on_startup()

    assert len(create_calls) == expected_create_calls


def _patch_if_present(monkeypatch, module_name, name, value):
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, name, value, raising=False)


def _tool_call(name, arguments):
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        ),
    )


def _fake_plan_with_tools(message):
    messages = [{"role": "user", "content": message}]

    if "哪些待办" in message or "查询" in message:
        tool_calls = [_tool_call("list_todos", {})]
    elif "完成" in message:
        todo_id = int(re.search(r"\d+", message).group())
        tool_calls = [_tool_call("mark_todo_done", {"todo_id": todo_id})]
    elif "删除" in message:
        todo_id = int(re.search(r"\d+", message).group())
        tool_calls = [
            _tool_call("request_delete_todo_confirmation", {"todo_id": todo_id})
        ]
    elif "创建" in message or "待办" in message:
        title = message.split("：", 1)[-1]
        tool_calls = [_tool_call("create_todo", {"title": title, "priority": "medium"})]
    else:
        tool_calls = []

    return SimpleNamespace(content="普通聊天回复", tool_calls=tool_calls), messages


def _fake_generate_answer(message, history=None):
    return {
        "answer": f"测试回复：{message}",
        "model": "deepseek-test",
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 1,
        "estimated_cost_usd": 0,
        "finish_reason": "stop",
    }


def _fake_analyze_text(text):
    return {
        "summary": "测试摘要",
        "tasks": ["复习 FastAPI", "上传简历"],
        "priority": "medium",
    }


def _fake_final_answer(messages):
    return "工具执行完成"


def _install_llm_fakes(monkeypatch):
    patches = [
        ("app.routers.chat", "generate_answer", _fake_generate_answer),
        ("app.routers.chat", "analyze_text", _fake_analyze_text),
        ("app.agent", "plan_with_tools", _fake_plan_with_tools),
        ("app.agent", "generate_tool_final_answer", _fake_final_answer),
    ]

    for module_name, name, value in patches:
        _patch_if_present(monkeypatch, module_name, name, value)


def _assert_ok(response, label):
    assert response.status_code < 400, (
        f"{label} failed: status={response.status_code}, body={response.text}"
    )


def _register_and_login():
    username = "regression_user"
    password = "regression_password"

    register_response = client.post(
        "/users/register",
        json={"username": username, "password": password},
    )
    _assert_ok(register_response, "register")

    login_response = client.post(
        "/users/login",
        json={"username": username, "password": password},
    )
    _assert_ok(login_response, "login")

    token = login_response.json().get("access_token")
    assert token, f"login response has no access_token: {login_response.text}"
    return {"Authorization": f"Bearer {token}"}


def test_register_and_login_remain_public():
    username = "public_contract_user"
    password = "public_contract_password"

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
    assert login_response.json()["token_type"] == "bearer"
    assert login_response.json()["access_token"]


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/users/me", None),
        ("GET", "/documents", None),
        ("GET", "/documents/process-logs", None),
        ("POST", "/rag/ask", {"question": "test"}),
        ("GET", "/rag/logs", None),
        ("GET", "/todos", None),
        ("POST", "/assistant/tools", {"message": "test"}),
        ("GET", "/assistant/tool-logs", None),
        ("GET", "/assistant/traces", None),
    ],
)
def test_protected_endpoints_require_authentication(method, path, json_body):
    request_kwargs = {}

    if json_body is not None:
        request_kwargs["json"] = json_body

    response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401


def test_list_users_requires_authentication():
    response = client.get("/users")

    assert response.status_code == 401


def test_full_agent_regression_flow(monkeypatch, tmp_path):
    _install_llm_fakes(monkeypatch)
    _patch_if_present(
        monkeypatch,
        "app.routers.documents",
        "dispatch_document_processing_job",
        lambda **_kwargs: None,
    )
    headers = _register_and_login()

    file_path = tmp_path / "note.txt"
    file_path.write_text("用于回归测试的文档内容", encoding="utf-8")
    with file_path.open("rb") as file:
        upload_response = client.post(
            "/documents",
            headers=headers,
            files={"file": ("note.txt", file, "text/plain")},
        )
    _assert_ok(upload_response, "upload document")

    chat_response = client.post(
        "/chat",
        headers=headers,
        json={"message": "普通聊天测试"},
    )
    _assert_ok(chat_response, "chat")
    assert "answer" in chat_response.json()

    analyze_response = client.post(
        "/chat/analyze",
        headers=headers,
        json={"text": "我明天要复习 FastAPI，还要上传简历。"},
    )
    _assert_ok(analyze_response, "analyze")
    assert analyze_response.json()["todos"]

    create_response = client.post(
        "/assistant/tools",
        headers=headers,
        json={"message": "帮我创建一个待办：回归测试创建待办"},
    )
    _assert_ok(create_response, "assistant create todo")
    todo = create_response.json().get("todo")
    assert todo and todo.get("id"), create_response.text
    todo_id = todo["id"]

    list_response = client.post(
        "/assistant/tools",
        headers=headers,
        json={"message": "我现在有哪些待办？"},
    )
    _assert_ok(list_response, "assistant list todos")

    done_response = client.post(
        "/assistant/tools",
        headers=headers,
        json={"message": f"把 id 为 {todo_id} 的待办标记为完成"},
    )
    _assert_ok(done_response, "assistant mark todo done")
    assert done_response.json()["todo"]["is_done"] is True

    confirm_delete_response = client.post(
        "/assistant/tools",
        headers=headers,
        json={"message": f"删除 id 为 {todo_id} 的待办"},
    )
    _assert_ok(confirm_delete_response, "assistant delete confirmation")
    assert confirm_delete_response.json().get("action") == "confirm_delete_todo"

    logs_response = client.get("/assistant/tool-logs", headers=headers)
    _assert_ok(logs_response, "tool logs")
    assert len(logs_response.json().get("logs", [])) >= 4

    traces_response = client.get("/assistant/traces", headers=headers)
    _assert_ok(traces_response, "agent traces")
    assert len(traces_response.json().get("traces", [])) >= 4


RAG_SOURCE_TEXT = """
WorkBrain 的聊天和 Agent 使用 DeepSeek。
WorkBrain 的文档向量使用 OpenAI 的 text-embedding-3-small。
文档初始切分大小为 500 个字符，重叠 100 个字符。
当前只支持 txt 和 md 文档提取。
删除待办属于危险操作，必须先请求用户确认。
RAG 每次最多返回 3 个相关文档片段。
""".strip()

RAG_ANSWERABLE_CASES = [
    ("K1", "WorkBrain 的聊天和 Agent 使用什么服务？", "DeepSeek"),
    ("K2", "文档向量用什么模型生成？", "text-embedding-3-small"),
    ("K3", "文档切分大小和重叠大小分别是多少？", "500 个字符，重叠 100 个字符"),
    ("K4", "当前支持哪些文档格式？", "txt 和 md"),
    ("K5", "删除待办前需要做什么？", "请求用户确认"),
    ("K6", "RAG 单次最多返回几个文档片段？", "3 个相关文档片段"),
]

RAG_UNANSWERABLE_CASES = [
    ("U1", "上海明天天气怎么样？"),
    ("U2", "WorkBrain 的月费是多少钱？"),
    ("U3", "项目使用 LangChain 吗？"),
]


def _seed_rag_chunks():
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()
        document = Document(
            owner_id=user.id,
            status=DocumentStatus.PUBLISHED.value,
            original_filename="rag-test-source.md",
            stored_filename="rag-test-source.md",
            file_path="rag-test-source.md",
        )
        session.add(document)
        session.commit()
        session.refresh(document)

        source_chunk = DocumentChunk(
            owner_id=user.id,
            document_id=document.id,
            status=DocumentStatus.PUBLISHED.value,
            chunk_index=0,
            content=RAG_SOURCE_TEXT,
            char_count=len(RAG_SOURCE_TEXT),
            embedding_json=json.dumps([0.3, 0.9539392014]),
            is_embedded=True,
        )
        semantic_distractor = DocumentChunk(
            owner_id=user.id,
            document_id=document.id,
            status=DocumentStatus.PUBLISHED.value,
            chunk_index=1,
            content="RAG 学习笔记：先把文档内容读出来，再考虑向量库。",
            char_count=28,
            embedding_json=json.dumps([1.0, 0.0]),
            is_embedded=True,
        )
        session.add(source_chunk)
        session.add(semantic_distractor)
        session.commit()
        session.refresh(source_chunk)
        return source_chunk.id


def _install_rag_fakes(monkeypatch):
    _patch_if_present(
        monkeypatch,
        "app.routers.rag",
        "generate_embedding",
        lambda _question: [1.0, 0.0],
    )


def test_rag_answerable_cases_are_grounded_and_logged(monkeypatch):
    headers = _register_and_login()
    source_chunk_id = _seed_rag_chunks()
    _install_rag_fakes(monkeypatch)

    expected_answers = {
        question: answer_fragment
        for _, question, answer_fragment in RAG_ANSWERABLE_CASES
    }

    def fake_answer_with_documents(question, context):
        assert RAG_SOURCE_TEXT in context
        return f"{expected_answers[question]} [S1]"

    _patch_if_present(
        monkeypatch,
        "app.routers.rag",
        "answer_with_documents",
        fake_answer_with_documents,
    )

    for case_id, question, answer_fragment in RAG_ANSWERABLE_CASES:
        response = client.post("/rag/ask", headers=headers, json={"question": question})
        _assert_ok(response, case_id)
        payload = response.json()

        assert answer_fragment in payload["answer"]
        assert "[S1]" in payload["answer"]
        assert payload["sources"][0]["reference"] == "[S1]"
        assert payload["sources"][0]["chunk_id"] == source_chunk_id
        assert payload["retrieval"]["matched_count"] >= 1

    logs_response = client.get("/rag/logs", headers=headers)
    _assert_ok(logs_response, "rag logs")
    logs = logs_response.json()
    assert len(logs) == len(RAG_ANSWERABLE_CASES)
    assert all(log["used_llm"] is True for log in logs)
    assert all(log["source_chunk_ids"] == [source_chunk_id] for log in logs)


def test_rag_unanswerable_cases_do_not_call_the_llm_or_return_sources(monkeypatch):
    headers = _register_and_login()
    _seed_rag_chunks()
    _install_rag_fakes(monkeypatch)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("LLM must not be called for an unanswerable question")

    _patch_if_present(
        monkeypatch,
        "app.routers.rag",
        "answer_with_documents",
        fail_if_called,
    )

    for case_id, question in RAG_UNANSWERABLE_CASES:
        response = client.post("/rag/ask", headers=headers, json={"question": question})
        _assert_ok(response, case_id)
        payload = response.json()

        assert payload["answer"] == "资料库中没有足够相关的内容，暂时无法回答这个问题。"
        assert payload["sources"] == []
        assert payload["retrieval"]["matched_count"] == 0

    logs_response = client.get("/rag/logs", headers=headers)
    _assert_ok(logs_response, "rag logs")
    logs = logs_response.json()
    assert len(logs) == len(RAG_UNANSWERABLE_CASES)
    assert all(log["used_llm"] is False for log in logs)
    assert all(log["source_chunk_ids"] == [] for log in logs)


def test_delete_document_removes_related_chunks(tmp_path):
    headers = _register_and_login()

    file_path = tmp_path / "remove-me.txt"
    file_path.write_text("temporary document", encoding="utf-8")

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        document = Document(
            owner_id=user.id,
            original_filename="remove-me.txt",
            stored_filename="remove-me.txt",
            file_path=str(file_path),
        )
        session.add(document)
        session.commit()
        session.refresh(document)

        for index in range(2):
            session.add(
                DocumentChunk(
                    owner_id=user.id,
                    document_id=document.id,
                    chunk_index=index,
                    content=f"chunk {index}",
                    char_count=7,
                    embedding_json=json.dumps([0.1, 0.2]),
                    is_embedded=True,
                )
            )

        session.commit()
        document_id = document.id

    response = client.delete(f"/documents/{document_id}", headers=headers)
    _assert_ok(response, "delete document")
    assert response.json()["deleted_chunk_count"] == 2

    with Session(engine) as session:
        assert session.get(Document, document_id) is None

        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert chunks == []


def test_list_documents_reports_rag_readiness():
    headers = _register_and_login()

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        pending_document = Document(
            owner_id=user.id,
            original_filename="pending.md",
            stored_filename="pending.md",
            file_path="pending.md",
        )
        ready_document = Document(
            owner_id=user.id,
            status=DocumentStatus.PUBLISHED.value,
            original_filename="ready.md",
            stored_filename="ready.md",
            file_path="ready.md",
            is_extracted=True,
        )
        session.add(pending_document)
        session.add(ready_document)
        session.commit()
        session.refresh(pending_document)
        session.refresh(ready_document)

        session.add(
            DocumentChunk(
                owner_id=user.id,
                document_id=ready_document.id,
                status=DocumentStatus.PUBLISHED.value,
                chunk_index=0,
                content="已完成向量化的测试内容",
                char_count=11,
                embedding_json=json.dumps([0.1, 0.2]),
                is_embedded=True,
            )
        )
        session.commit()

        pending_id = pending_document.id
        ready_id = ready_document.id

    response = client.get("/documents", headers=headers)
    _assert_ok(response, "list documents")

    documents = {document["id"]: document for document in response.json()["documents"]}

    assert documents[pending_id]["is_ready_for_rag"] is False
    assert documents[pending_id]["chunk_count"] == 0

    assert documents[ready_id]["is_ready_for_rag"] is True
    assert documents[ready_id]["chunk_count"] == 1
    assert documents[ready_id]["embedded_chunk_count"] == 1


def test_process_document_builds_ready_rag_document(monkeypatch, tmp_path):
    headers = _register_and_login()

    file_path = tmp_path / "process.md"
    file_path.write_text("WorkBrain 使用 DeepSeek。", encoding="utf-8")

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        document = Document(
            owner_id=user.id,
            original_filename="process.md",
            stored_filename="process.md",
            file_path=str(file_path),
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = document.id

    _patch_if_present(
        monkeypatch,
        "app.document_processing",
        "generate_embedding",
        lambda _text: [0.1, 0.2],
    )

    response = client.post(
        f"/documents/{document_id}/process",
        headers=headers,
    )
    _assert_ok(response, "process document")

    assert response.json()["is_ready_for_publish"] is True
    assert response.json()["is_ready_for_rag"] is False

    with Session(engine) as session:
        document = session.get(Document, document_id)
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()

        assert document.is_extracted is True
        assert document.status == DocumentStatus.READY.value
        assert len(chunks) == 1
        assert chunks[0].is_embedded is True
        assert chunks[0].embedding_vector == [0.1, 0.2]
        assert chunks[0].organization_id == document.organization_id
        assert chunks[0].knowledge_base_id == document.knowledge_base_id
        assert chunks[0].document_version == document.version
        assert chunks[0].status == DocumentStatus.READY.value

    logs_response = client.get(
        "/documents/process-logs",
        headers=headers,
    )
    _assert_ok(logs_response, "list process logs")

    logs = logs_response.json()["logs"]
    assert len(logs) == 1

    log = logs[0]
    assert log["id"] == response.json()["process_log_id"]
    assert log["document_id"] == document_id
    assert log["is_success"] is True
    assert log["text_char_count"] == len("WorkBrain 使用 DeepSeek。")
    assert log["chunk_count"] == 1
    assert log["embedded_count"] == 1
    assert log["total_latency_ms"] >= 0
    assert log["error_message"] is None


def test_process_document_keeps_old_data_on_failure_and_can_retry(
    monkeypatch,
    tmp_path,
):
    headers = _register_and_login()

    file_path = tmp_path / "retry.md"
    file_path.write_text("这是新的文档内容。", encoding="utf-8")

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        document = Document(
            owner_id=user.id,
            original_filename="retry.md",
            stored_filename="retry.md",
            file_path=str(file_path),
            extracted_text="这是旧的文档内容。",
            is_extracted=True,
        )
        session.add(document)
        session.commit()
        session.refresh(document)

        session.add(
            DocumentChunk(
                owner_id=user.id,
                document_id=document.id,
                chunk_index=0,
                content="这是旧的文档内容。",
                char_count=10,
                embedding_json=json.dumps([0.3, 0.4]),
                is_embedded=True,
            )
        )
        session.commit()
        document_id = document.id

    attempts = {"count": 0}

    def flaky_embedding(_text):
        attempts["count"] += 1

        if attempts["count"] == 1:
            raise Exception("temporary embedding failure")

        return [0.8, 0.9]

    _patch_if_present(
        monkeypatch,
        "app.document_processing",
        "generate_embedding",
        flaky_embedding,
    )

    failed_response = client.post(
        f"/documents/{document_id}/process",
        headers=headers,
    )
    assert failed_response.status_code == 502

    failed_logs_response = client.get(
        "/documents/process-logs",
        headers=headers,
    )
    _assert_ok(failed_logs_response, "list failed process logs")

    failed_logs = failed_logs_response.json()["logs"]
    assert len(failed_logs) == 1

    failed_log = failed_logs[0]
    assert failed_log["document_id"] == document_id
    assert failed_log["is_success"] is False
    assert failed_log["chunk_count"] == 1
    assert failed_log["embedded_count"] == 0
    assert failed_log["error_message"] == "failed to create embedding"

    with Session(engine) as session:
        document = session.get(Document, document_id)
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()

        assert document.extracted_text == "这是旧的文档内容。"
        assert len(chunks) == 1
        assert chunks[0].content == "这是旧的文档内容。"

    retry_response = client.post(
        f"/documents/{document_id}/process",
        headers=headers,
    )
    _assert_ok(retry_response, "retry process document")

    with Session(engine) as session:
        document = session.get(Document, document_id)
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()

        assert document.extracted_text == "这是新的文档内容。"
        assert len(chunks) == 1
        assert chunks[0].content == "这是新的文档内容。"
        assert chunks[0].is_embedded is True

    retry_logs_response = client.get(
        "/documents/process-logs",
        headers=headers,
    )
    _assert_ok(retry_logs_response, "list retry process logs")

    retry_logs = retry_logs_response.json()["logs"]
    assert len(retry_logs) == 2

    success_logs = [log for log in retry_logs if log["is_success"] is True]
    failure_logs = [log for log in retry_logs if log["is_success"] is False]

    assert len(success_logs) == 1
    assert len(failure_logs) == 1
    assert success_logs[0]["embedded_count"] == 1
    assert success_logs[0]["error_message"] is None
    assert failure_logs[0]["error_message"] == "failed to create embedding"


def test_process_document_checks_budget_before_embedding(
    monkeypatch,
    tmp_path,
):
    headers = _register_and_login()

    file_path = tmp_path / "large.md"
    file_path.write_text("A" * 1000, encoding="utf-8")

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        document = Document(
            owner_id=user.id,
            original_filename="large.md",
            stored_filename="large.md",
            file_path=str(file_path),
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = document.id

    embedding_calls = {"count": 0}

    def fake_embedding(_text):
        embedding_calls["count"] += 1
        return [0.1, 0.2]

    _patch_if_present(
        monkeypatch,
        "app.document_processing",
        "generate_embedding",
        fake_embedding,
    )

    _patch_if_present(
        monkeypatch,
        "app.document_processing",
        "RAG_MAX_DOCUMENT_CHARS",
        10,
    )

    response = client.post(
        f"/documents/{document_id}/process",
        headers=headers,
    )

    assert response.status_code == 413
    assert embedding_calls["count"] == 0

    _patch_if_present(
        monkeypatch,
        "app.document_processing",
        "RAG_MAX_DOCUMENT_CHARS",
        2000,
    )
    _patch_if_present(
        monkeypatch,
        "app.document_processing",
        "RAG_MAX_CHUNKS_PER_DOCUMENT",
        1,
    )

    response = client.post(
        f"/documents/{document_id}/process",
        headers=headers,
    )

    assert response.status_code == 413
    assert embedding_calls["count"] == 0


def test_document_process_logs_are_isolated_by_user():
    headers = _register_and_login()

    with Session(engine) as session:
        current_user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        other_user = User(
            username="other_user",
            hashed_password="unused-in-this-test",
        )
        session.add(other_user)
        session.commit()
        session.refresh(other_user)

        current_user_log = DocumentProcessLog(
            owner_id=current_user.id,
            document_id=101,
            is_success=True,
            text_char_count=100,
            chunk_count=1,
            embedded_count=1,
            total_latency_ms=10,
        )
        other_user_log = DocumentProcessLog(
            owner_id=other_user.id,
            document_id=202,
            is_success=False,
            error_message="other user's error",
        )

        session.add(current_user_log)
        session.add(other_user_log)
        session.commit()
        session.refresh(current_user_log)
        session.refresh(other_user_log)

        current_log_id = current_user_log.id
        other_log_id = other_user_log.id

    response = client.get(
        "/documents/process-logs",
        headers=headers,
    )
    _assert_ok(response, "list isolated process logs")

    returned_ids = {log["id"] for log in response.json()["logs"]}

    assert current_log_id in returned_ids
    assert other_log_id not in returned_ids
    assert response.json()["pagination"]["total"] == 1


def test_document_process_logs_support_pagination():
    headers = _register_and_login()

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == "regression_user")
        ).one()

        for index in range(5):
            session.add(
                DocumentProcessLog(
                    owner_id=user.id,
                    document_id=index + 1,
                    is_success=True,
                    text_char_count=100,
                    chunk_count=1,
                    embedded_count=1,
                    total_latency_ms=10,
                )
            )

        session.commit()

    first_response = client.get(
        "/documents/process-logs?offset=0&limit=2",
        headers=headers,
    )
    _assert_ok(first_response, "first process log page")
    first_payload = first_response.json()

    assert len(first_payload["logs"]) == 2
    assert first_payload["pagination"] == {
        "offset": 0,
        "limit": 2,
        "total": 5,
        "returned": 2,
    }

    second_response = client.get(
        "/documents/process-logs?offset=2&limit=2",
        headers=headers,
    )
    _assert_ok(second_response, "second process log page")
    second_payload = second_response.json()

    assert len(second_payload["logs"]) == 2
    assert second_payload["pagination"]["total"] == 5

    first_ids = {log["id"] for log in first_payload["logs"]}
    second_ids = {log["id"] for log in second_payload["logs"]}
    assert first_ids.isdisjoint(second_ids)


def test_document_process_log_pagination_rejects_invalid_values():
    headers = _register_and_login()

    invalid_requests = [
        "/documents/process-logs?offset=-1&limit=20",
        "/documents/process-logs?offset=0&limit=0",
        "/documents/process-logs?offset=0&limit=101",
    ]

    for url in invalid_requests:
        response = client.get(url, headers=headers)
        assert response.status_code == 422
