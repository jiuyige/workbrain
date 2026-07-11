import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "800"))
CHAT_HISTORY_MAX_CHARS = int(os.getenv("CHAT_HISTORY_MAX_CHARS", "4000"))


OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL",
    "text-embedding-3-small",
)
OPENAI_EMBEDDING_DIMENSIONS = int(
    os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536")
)

RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.45"))


RAG_MAX_DOCUMENT_CHARS = int(
    os.getenv("RAG_MAX_DOCUMENT_CHARS", "20000")
)

RAG_MAX_CHUNKS_PER_DOCUMENT = int(
    os.getenv("RAG_MAX_CHUNKS_PER_DOCUMENT", "50")
)



DEEPSEEK_INPUT_CACHE_HIT_PRICE_PER_1M_USD = float(
    os.getenv("DEEPSEEK_INPUT_CACHE_HIT_PRICE_PER_1M_USD", "0")
)
DEEPSEEK_INPUT_CACHE_MISS_PRICE_PER_1M_USD = float(
    os.getenv("DEEPSEEK_INPUT_CACHE_MISS_PRICE_PER_1M_USD", "0")
)
DEEPSEEK_OUTPUT_PRICE_PER_1M_USD = float(
    os.getenv("DEEPSEEK_OUTPUT_PRICE_PER_1M_USD", "0")
)

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

if DATABASE_URL is None:
    raise RuntimeError("DATABASE_URL is not set")

if SECRET_KEY is None:
    raise RuntimeError("SECRET_KEY is not set")

UPLOAD_DIR.mkdir(exist_ok=True)

ALGORITHM = "HS256"
