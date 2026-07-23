from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_requires_secrets_instead_of_hard_coding_them():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "workbrain123" not in compose
    assert "${POSTGRES_PASSWORD:?" in compose
    assert "${DATABASE_URL:?" in compose
    assert "${SECRET_KEY:?" in compose
    assert "${DEEPSEEK_API_KEY:?" in compose
    assert "${OPENAI_API_KEY:?" in compose


def test_backend_image_runs_as_a_non_root_user():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()

    assert "USER workbrain" in dockerfile


def test_compose_enables_durable_storage_for_stateful_services():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "--appendonly" in compose
    assert "--appendfsync" in compose
    assert "name: workbrain_postgres_data" in compose
    assert "name: workbrain_redis_data" in compose
    assert "name: workbrain_uploads_data" in compose
    assert "postgres_data:/var/lib/postgresql/data" in compose
    assert "redis_data:/data" in compose


def test_compose_prepares_the_shared_upload_volume_for_non_root_services():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "uploads-init:" in compose
    assert 'user: "0:0"' in compose
    assert "chown -R 1000:1000 /app/uploads" in compose
    assert compose.count("uploads_data:/app/uploads") == 3
    assert compose.count("condition: service_completed_successfully") >= 2


def test_compose_runs_migrations_before_api_and_worker_start():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "migrate:" in compose
    assert '["alembic", "upgrade", "head"]' in compose
    assert compose.count("condition: service_completed_successfully") == 4


def test_frontend_image_serves_the_spa_and_proxies_api_requests():
    dockerfile = (PROJECT_ROOT / "frontend" / "Dockerfile").read_text()
    nginx_config = (PROJECT_ROOT / "frontend" / "nginx.conf").read_text()

    assert "npm run build" in dockerfile
    assert "COPY --from=build /app/dist /usr/share/nginx/html" in dockerfile
    assert "try_files $uri $uri/ /index.html" in nginx_config
    assert "proxy_pass http://api:8000/" in nginx_config
    assert (
        "proxy_set_header X-Forwarded-Proto $workbrain_forwarded_proto" in nginx_config
    )


def test_compose_exposes_the_frontend_through_a_persistent_caddy_gateway():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()
    caddyfile = (PROJECT_ROOT / "Caddyfile").read_text()

    assert "frontend:" in compose
    assert "gateway:" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "caddy_data:/data" in compose
    assert "caddy_config:/config" in compose
    assert "{$SITE_ADDRESS:http://localhost}" in caddyfile
    assert "reverse_proxy frontend:80" in caddyfile


def test_compose_healthchecks_cover_public_and_background_services():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "http://127.0.0.1:8000/health/ready" in compose
    assert "celery@$$HOSTNAME" in compose
    assert "http://127.0.0.1:2019/config/" in compose
    assert "api:\n        condition: service_healthy" in compose
    assert "SQL_ECHO: ${SQL_ECHO:-false}" in compose


def test_production_compose_only_publishes_the_gateway():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()
    development_compose = (PROJECT_ROOT / "docker-compose.dev.yml").read_text()

    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose
    assert '"8000:8000"' not in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert '"127.0.0.1:5432:5432"' in development_compose
    assert '"127.0.0.1:6379:6379"' in development_compose
    assert '"127.0.0.1:8000:8000"' in development_compose


def test_production_smoke_script_covers_the_deployed_business_path():
    smoke_script = (PROJECT_ROOT / "scripts" / "production_smoke.py").read_text()

    for path in (
        "/health/ready",
        "/users/register",
        "/users/login",
        "/organizations",
        "/knowledge-bases",
        "/service-catalog/items",
        "/service-requests",
        "/jobs/example",
    ):
        assert path in smoke_script

    assert "secrets.token_hex" in smoke_script
    assert "poll_job_until_finished" in smoke_script
    assert 'if __name__ == "__main__"' in smoke_script


def test_ci_covers_the_complete_backend_frontend_and_container_artifacts():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    for backend_gate in (
        "requirements-mcp-demo.txt",
        "ruff check",
        "ruff format --check",
        "--ignore=tests/test_pgvector_integration.py",
        "tests/test_pgvector_integration.py",
        "alembic check",
    ):
        assert backend_gate in workflow

    for frontend_gate in (
        "actions/setup-node",
        "npm ci",
        "npm run test",
        "npm run lint",
        "npm run build",
    ):
        assert frontend_gate in workflow

    assert "docker build --tag workbrain-api-ci ." in workflow
    assert "docker build --tag workbrain-frontend-ci ./frontend" in workflow
    assert "docker compose config --quiet" in workflow


def test_local_and_secret_artifacts_are_excluded_from_publish_contexts():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text()
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text()
    frontend_gitignore = (PROJECT_ROOT / "frontend" / ".gitignore").read_text()

    for local_artifact in (
        ".idea/",
        ".ruff_cache/",
        ".env",
        "uploads/",
    ):
        assert local_artifact in gitignore

    for docker_secret_or_artifact in (
        ".env",
        ".idea",
        ".ruff_cache",
        "uploads",
        "frontend/node_modules",
        "frontend/dist",
    ):
        assert docker_secret_or_artifact in dockerignore

    assert ".env*" in frontend_gitignore
    assert "!.env.example" in frontend_gitignore
