import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

VALID_APP_ENVS = {"development", "test", "production"}


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _is_example_placeholder(value: str) -> bool:
    normalized_value = value.strip().lower()
    return normalized_value.startswith("replace-with-") or normalized_value in {
        "changeme",
        "change-me",
    }


def parse_cors_origins(
    value: str | None,
    *,
    app_env: str,
) -> list[str]:
    origins = [
        origin.strip().rstrip("/")
        for origin in (value or "").split(",")
        if origin.strip()
    ]

    if app_env == "production" and "*" in origins:
        raise RuntimeError("production CORS_ORIGINS must not contain a wildcard")

    return list(dict.fromkeys(origins))


def validate_config(
    *,
    app_env: str,
    database_url: str | None,
    secret_key: str | None,
    deepseek_api_key: str | None,
    openai_api_key: str | None,
) -> None:
    if app_env not in VALID_APP_ENVS:
        allowed_values = ", ".join(sorted(VALID_APP_ENVS))
        raise RuntimeError(f"APP_ENV must be one of: {allowed_values}")

    missing_names = []

    if _is_blank(database_url):
        missing_names.append("DATABASE_URL")

    if _is_blank(secret_key):
        missing_names.append("SECRET_KEY")

    if app_env == "production":
        if _is_blank(deepseek_api_key):
            missing_names.append("DEEPSEEK_API_KEY")

        if _is_blank(openai_api_key):
            missing_names.append("OPENAI_API_KEY")

    if missing_names:
        missing_text = ", ".join(missing_names)
        raise RuntimeError(f"Missing required configuration: {missing_text}")

    if app_env != "production":
        return

    if not database_url.lower().startswith("postgresql"):
        raise RuntimeError("production DATABASE_URL must use PostgreSQL")

    if "replace-with-" in database_url.lower():
        raise RuntimeError("DATABASE_URL must not use an example placeholder")

    if len(secret_key.strip()) < 32:
        raise RuntimeError("production SECRET_KEY must contain at least 32 characters")

    if _is_example_placeholder(secret_key):
        raise RuntimeError("SECRET_KEY must not use an example placeholder")

    if _is_example_placeholder(deepseek_api_key):
        raise RuntimeError("DEEPSEEK_API_KEY must not use an example placeholder")

    if _is_example_placeholder(openai_api_key):
        raise RuntimeError("OPENAI_API_KEY must not use an example placeholder")


APP_ENV = os.getenv("APP_ENV", "development").lower()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"
CORS_ORIGINS = parse_cors_origins(
    os.getenv("CORS_ORIGINS"),
    app_env=APP_ENV,
)
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com",
)
DEEPSEEK_MODEL = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-v4-flash",
)
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "800"))
CHAT_HISTORY_MAX_CHARS = int(os.getenv("CHAT_HISTORY_MAX_CHARS", "4000"))

DEEPSEEK_INPUT_CACHE_HIT_PRICE_PER_1M_USD = float(
    os.getenv(
        "DEEPSEEK_INPUT_CACHE_HIT_PRICE_PER_1M_USD",
        "0",
    )
)
DEEPSEEK_INPUT_CACHE_MISS_PRICE_PER_1M_USD = float(
    os.getenv(
        "DEEPSEEK_INPUT_CACHE_MISS_PRICE_PER_1M_USD",
        "0",
    )
)
DEEPSEEK_OUTPUT_PRICE_PER_1M_USD = float(
    os.getenv(
        "DEEPSEEK_OUTPUT_PRICE_PER_1M_USD",
        "0",
    )
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL",
    "text-embedding-3-small",
)
OPENAI_EMBEDDING_DIMENSIONS = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))

RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.45"))
RAG_MAX_DOCUMENT_CHARS = int(os.getenv("RAG_MAX_DOCUMENT_CHARS", "20000"))
RAG_MAX_CHUNKS_PER_DOCUMENT = int(os.getenv("RAG_MAX_CHUNKS_PER_DOCUMENT", "50"))

CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    "redis://localhost:6379/0",
)
CELERY_RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND",
    "redis://localhost:6379/1",
)
DOCUMENT_PROCESSING_MAX_RETRIES = int(os.getenv("DOCUMENT_PROCESSING_MAX_RETRIES", "3"))
DOCUMENT_PROCESSING_RETRY_BASE_SECONDS = int(
    os.getenv("DOCUMENT_PROCESSING_RETRY_BASE_SECONDS", "5")
)

validate_config(
    app_env=APP_ENV,
    database_url=DATABASE_URL,
    secret_key=SECRET_KEY,
    deepseek_api_key=DEEPSEEK_API_KEY,
    openai_api_key=OPENAI_API_KEY,
)

UPLOAD_DIR.mkdir(exist_ok=True)

ALGORITHM = "HS256"
