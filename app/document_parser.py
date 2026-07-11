from pathlib import Path


def extract_text_from_file(file_path: str) -> str:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError("file not found")

    suffix = path.suffix.lower()

    if suffix not in [".txt", ".md"]:
        raise ValueError("unsupported file type")

    return path.read_text(encoding="utf-8")


def split_text_into_chunks(
    text: str,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start = end - overlap

    return chunks