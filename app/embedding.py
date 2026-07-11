import json

from openai import OpenAI

from app.config import (
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_DIMENSIONS,
    OPENAI_EMBEDDING_MODEL,
)

client = OpenAI(api_key=OPENAI_API_KEY)


def generate_embedding(text: str) -> list[float]:
    if OPENAI_API_KEY is None:
        raise RuntimeError("OPENAI_API_KEY is not set")

    response = client.embeddings.create(
        input=text,
        model=OPENAI_EMBEDDING_MODEL,
        dimensions=OPENAI_EMBEDDING_DIMENSIONS,
    )

    return response.data[0].embedding


def embedding_to_json(embedding: list[float]) -> str:
    return json.dumps(embedding)
