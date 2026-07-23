import argparse
import json
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

from app.config import RAG_MIN_SCORE
from app.document_parser import split_text_into_chunks
from app.rag import (
    LEXICAL_RELEVANCE_THRESHOLD,
    MIN_LEXICAL_MATCH_COUNT,
    search_chunks,
)

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "evals" / "rag_retrieval_cases.json"
)
CHUNK_SELECTION_POLICY = [
    "top3_recall",
    "rejection_accuracy",
    "answer_accuracy",
    "shorter_average_context",
    "top1_recall",
]


@dataclass
class EvaluationChunk:
    id: str
    document_id: str
    chunk_index: int
    content: str
    embedding_json: str


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as dataset_file:
        dataset = json.load(dataset_file)

    _validate_dataset(dataset)
    return dataset


def _validate_dataset(dataset: dict[str, Any]) -> None:
    if dataset.get("version") != 1:
        raise ValueError("unsupported RAG evaluation dataset version")

    if not isinstance(dataset.get("top_k"), int) or dataset["top_k"] <= 0:
        raise ValueError("top_k must be a positive integer")

    chunks = dataset.get("chunks")
    cases = dataset.get("cases")
    if not chunks or not cases:
        raise ValueError("RAG evaluation dataset requires chunks and cases")

    chunk_ids = [chunk["id"] for chunk in chunks]
    case_ids = [case["id"] for case in cases]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("chunk ids must be unique")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case ids must be unique")

    embedding_dimensions = {len(chunk["embedding"]) for chunk in chunks} | {
        len(case["query_embedding"]) for case in cases
    }
    if len(embedding_dimensions) != 1:
        raise ValueError("all evaluation embeddings must have the same dimension")

    known_chunk_ids = set(chunk_ids)
    for case in cases:
        expected_chunk_id = case["expected_chunk_id"]
        if expected_chunk_id is not None and expected_chunk_id not in known_chunk_ids:
            raise ValueError(f"case {case['id']} references an unknown expected chunk")


def evaluate_dataset(
    dataset: dict[str, Any],
    *,
    top_k: int | None = None,
    min_score: float = RAG_MIN_SCORE,
) -> dict[str, Any]:
    chunks = [
        EvaluationChunk(
            id=chunk["id"],
            document_id=chunk["document_id"],
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            embedding_json=json.dumps(chunk["embedding"]),
        )
        for chunk in dataset["chunks"]
    ]
    selected_top_k = top_k if top_k is not None else dataset["top_k"]
    if selected_top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    results = []
    reciprocal_rank_total = 0.0
    retrieval_hits = 0
    rejection_hits = 0
    answerable_count = 0
    unanswerable_count = 0

    for case in dataset["cases"]:
        retrieved = search_chunks(
            query_embedding=case["query_embedding"],
            chunks=chunks,
            top_k=selected_top_k,
            query=case["question"],
        )
        grounded = [
            item
            for item in retrieved
            if item["lexical_score"] >= LEXICAL_RELEVANCE_THRESHOLD
            and item["lexical_match_count"] >= MIN_LEXICAL_MATCH_COUNT
            and item["rank_score"] >= min_score
        ]
        retrieved_ids = [item["chunk_id"] for item in grounded]
        expected_chunk_id = case["expected_chunk_id"]

        if expected_chunk_id is None:
            unanswerable_count += 1
            passed = not grounded
            rejection_hits += int(passed)
            reciprocal_rank = None
        else:
            answerable_count += 1
            passed = expected_chunk_id in retrieved_ids
            retrieval_hits += int(passed)
            reciprocal_rank = (
                1.0 / (retrieved_ids.index(expected_chunk_id) + 1) if passed else 0.0
            )
            reciprocal_rank_total += reciprocal_rank

        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_chunk_id": expected_chunk_id,
                "retrieved_chunk_ids": retrieved_ids,
                "reciprocal_rank": reciprocal_rank,
                "passed": passed,
            }
        )

    case_count = len(results)
    passed_count = sum(result["passed"] for result in results)
    return {
        "dataset_version": dataset["version"],
        "case_count": case_count,
        "answerable_count": answerable_count,
        "unanswerable_count": unanswerable_count,
        "top_k": selected_top_k,
        "min_score": min_score,
        "lexical_relevance_threshold": LEXICAL_RELEVANCE_THRESHOLD,
        "min_lexical_match_count": MIN_LEXICAL_MATCH_COUNT,
        "recall_at_k": round(retrieval_hits / answerable_count, 4),
        "mean_reciprocal_rank": round(
            reciprocal_rank_total / answerable_count,
            4,
        ),
        "rejection_accuracy": round(rejection_hits / unanswerable_count, 4),
        "pass_rate": round(passed_count / case_count, 4),
        "results": results,
    }


def evaluate_chunk_sizes(
    dataset: dict[str, Any],
    *,
    chunk_sizes: list[int],
) -> list[dict[str, Any]]:
    documents: dict[str, list[str]] = {}
    for chunk in dataset["chunks"]:
        documents.setdefault(chunk["document_id"], []).append(chunk["content"])

    source_documents = ["\n\n".join(parts) for parts in documents.values()]
    evidence_passages = [
        chunk["content"]
        for chunk in dataset["chunks"]
        if not chunk.get("is_distractor", False)
    ]
    source_char_count = sum(len(document) for document in source_documents)
    results = []

    for chunk_size in chunk_sizes:
        overlap = chunk_size // 5
        generated_chunks = [
            chunk
            for document in source_documents
            for chunk in split_text_into_chunks(
                document,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        ]
        retained_evidence_count = sum(
            any(evidence in chunk for chunk in generated_chunks)
            for evidence in evidence_passages
        )
        indexed_char_count = sum(len(chunk) for chunk in generated_chunks)

        results.append(
            {
                "chunk_size": chunk_size,
                "overlap": overlap,
                "source_char_count": source_char_count,
                "chunk_count": len(generated_chunks),
                "indexed_char_count": indexed_char_count,
                "duplication_ratio": round(
                    indexed_char_count / source_char_count,
                    4,
                ),
                "evidence_retention_rate": round(
                    retained_evidence_count / len(evidence_passages),
                    4,
                ),
            }
        )

    return results


def select_chunk_configuration(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    if not results:
        raise ValueError("chunk evaluation results cannot be empty")

    required_metrics = {
        "top3_recall",
        "rejection_accuracy",
        "answer_accuracy",
        "average_context_chars",
        "top1_recall",
    }
    for result in results:
        missing_metrics = required_metrics - result.keys()
        if missing_metrics:
            missing_text = ", ".join(sorted(missing_metrics))
            raise ValueError(f"chunk result is missing metrics: {missing_text}")

    return max(
        results,
        key=lambda result: (
            result["top3_recall"],
            result["rejection_accuracy"],
            result["answer_accuracy"],
            -result["average_context_chars"],
            result["top1_recall"],
        ),
    )


def run_parameter_experiments(
    dataset: dict[str, Any],
    *,
    top_k_values: list[int],
    min_score_values: list[float],
    chunk_sizes: list[int] | None = None,
) -> dict[str, Any]:
    retrieval_experiments = []
    for top_k, min_score in product(top_k_values, min_score_values):
        report = evaluate_dataset(
            dataset,
            top_k=top_k,
            min_score=min_score,
        )
        retrieval_experiments.append(
            {
                key: report[key]
                for key in (
                    "top_k",
                    "min_score",
                    "recall_at_k",
                    "mean_reciprocal_rank",
                    "rejection_accuracy",
                    "pass_rate",
                )
            }
        )

    recommended = max(
        retrieval_experiments,
        key=lambda result: (
            result["pass_rate"],
            result["recall_at_k"],
            result["rejection_accuracy"],
            result["mean_reciprocal_rank"],
            -result["top_k"],
            -abs(result["min_score"] - RAG_MIN_SCORE),
        ),
    )
    selected_chunk_sizes = chunk_sizes or [200, 500, 800]

    return {
        "dataset_version": dataset["version"],
        "retrieval_experiments": retrieval_experiments,
        "recommended_configuration": {
            "top_k": recommended["top_k"],
            "min_score": recommended["min_score"],
        },
        "recommended_metrics": {
            key: recommended[key]
            for key in (
                "recall_at_k",
                "mean_reciprocal_rank",
                "rejection_accuracy",
                "pass_rate",
            )
        },
        "chunking_experiments": evaluate_chunk_sizes(
            dataset,
            chunk_sizes=selected_chunk_sizes,
        ),
        "chunk_selection_policy": CHUNK_SELECTION_POLICY,
        "chunking_conclusion": (
            "The checked-in corpus is too small to select a production chunk size; "
            "keep the current 500/100 default until a larger corpus is evaluated."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic WorkBrain RAG retrieval evaluation."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to a version 1 RAG evaluation dataset.",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-score", type=float, default=RAG_MIN_SCORE)
    args = parser.parse_args(argv)

    report = evaluate_dataset(
        load_dataset(args.dataset),
        top_k=args.top_k,
        min_score=args.min_score,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["pass_rate"] < 1.0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
