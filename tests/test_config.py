import pytest

from app.config import parse_cors_origins, validate_config


def test_validate_config_rejects_unknown_environment():
    with pytest.raises(
        RuntimeError,
        match="APP_ENV must be one of",
    ):
        validate_config(
            app_env="staging",
            database_url="sqlite://",
            secret_key="test-secret",
            deepseek_api_key=None,
            openai_api_key=None,
        )


def test_validate_config_requires_core_values():
    with pytest.raises(
        RuntimeError,
        match="DATABASE_URL, SECRET_KEY",
    ):
        validate_config(
            app_env="test",
            database_url=None,
            secret_key=" ",
            deepseek_api_key=None,
            openai_api_key=None,
        )


def test_production_config_requires_model_keys():
    with pytest.raises(
        RuntimeError,
        match="DEEPSEEK_API_KEY, OPENAI_API_KEY",
    ):
        validate_config(
            app_env="production",
            database_url="postgresql://test",
            secret_key="production-secret-key-at-least-32-bytes",
            deepseek_api_key=None,
            openai_api_key=None,
        )


@pytest.mark.parametrize(
    ("database_url", "secret_key", "deepseek_api_key", "openai_api_key", "message"),
    [
        (
            "sqlite:///workbrain.db",
            "production-secret-key-at-least-32-bytes",
            "deepseek-key",
            "openai-key",
            "production DATABASE_URL must use PostgreSQL",
        ),
        (
            "postgresql+psycopg://workbrain@postgres/workbrain",
            "short-secret",
            "deepseek-key",
            "openai-key",
            "production SECRET_KEY must contain at least 32 characters",
        ),
        (
            "postgresql+psycopg://workbrain:replace-with-password@postgres/workbrain",
            "production-secret-key-at-least-32-bytes",
            "deepseek-key",
            "openai-key",
            "DATABASE_URL must not use an example placeholder",
        ),
        (
            "postgresql+psycopg://workbrain@postgres/workbrain",
            "replace-with-at-least-32-random-characters",
            "deepseek-key",
            "openai-key",
            "SECRET_KEY must not use an example placeholder",
        ),
        (
            "postgresql+psycopg://workbrain@postgres/workbrain",
            "production-secret-key-at-least-32-bytes",
            "replace-with-your-deepseek-api-key",
            "openai-key",
            "DEEPSEEK_API_KEY must not use an example placeholder",
        ),
        (
            "postgresql+psycopg://workbrain@postgres/workbrain",
            "production-secret-key-at-least-32-bytes",
            "deepseek-key",
            "replace-with-your-openai-api-key",
            "OPENAI_API_KEY must not use an example placeholder",
        ),
    ],
)
def test_production_config_rejects_unsafe_values(
    database_url,
    secret_key,
    deepseek_api_key,
    openai_api_key,
    message,
):
    with pytest.raises(RuntimeError, match=message):
        validate_config(
            app_env="production",
            database_url=database_url,
            secret_key=secret_key,
            deepseek_api_key=deepseek_api_key,
            openai_api_key=openai_api_key,
        )


def test_production_config_accepts_explicit_secure_values():
    validate_config(
        app_env="production",
        database_url="postgresql+psycopg://workbrain@postgres/workbrain",
        secret_key="production-secret-key-at-least-32-bytes",
        deepseek_api_key="deepseek-key",
        openai_api_key="openai-key",
    )


def test_test_config_allows_fake_or_missing_model_keys():
    validate_config(
        app_env="test",
        database_url="sqlite://",
        secret_key="test-secret",
        deepseek_api_key=None,
        openai_api_key=None,
    )


def test_parse_cors_origins_normalizes_an_explicit_allowlist():
    assert parse_cors_origins(
        "https://workbrain.example.com/, https://admin.example.com",
        app_env="production",
    ) == [
        "https://workbrain.example.com",
        "https://admin.example.com",
    ]


def test_production_cors_rejects_a_wildcard_origin():
    with pytest.raises(
        RuntimeError,
        match="production CORS_ORIGINS must not contain a wildcard",
    ):
        parse_cors_origins("*", app_env="production")
