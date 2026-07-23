import json
from pathlib import Path

from app.rag_evaluation import (
    evaluate_chunk_sizes,
    evaluate_dataset,
    load_dataset,
    run_parameter_experiments,
    select_chunk_configuration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "evals" / "rag_retrieval_cases.json"


def test_rag_evaluation_dataset_has_stable_answerable_and_unanswerable_cases():
    dataset = load_dataset(DATASET_PATH)

    assert dataset["version"] == 1
    assert dataset["top_k"] == 3
    assert len(dataset["chunks"]) >= 5

    case_ids = [case["id"] for case in dataset["cases"]]
    assert len(case_ids) == len(set(case_ids))
    assert sum(case["expected_chunk_id"] is not None for case in dataset["cases"]) >= 6
    assert sum(case["expected_chunk_id"] is None for case in dataset["cases"]) >= 3


def test_rag_evaluation_reaches_the_checked_in_baseline():
    dataset = load_dataset(DATASET_PATH)

    report = evaluate_dataset(dataset)

    assert report["case_count"] == len(dataset["cases"])
    assert report["answerable_count"] >= 6
    assert report["unanswerable_count"] >= 3
    assert report["recall_at_k"] == 1.0
    assert report["mean_reciprocal_rank"] >= 0.8
    assert report["rejection_accuracy"] == 1.0
    assert report["pass_rate"] == 1.0
    assert all(result["passed"] for result in report["results"])


def test_rag_evaluation_report_is_json_serializable():
    report = evaluate_dataset(load_dataset(DATASET_PATH))

    serialized = json.dumps(report, ensure_ascii=False)

    assert '"recall_at_k": 1.0' in serialized
    assert "VPN" in serialized


def test_parameter_experiment_selects_the_best_balanced_configuration():
    dataset = load_dataset(DATASET_PATH)

    experiment = run_parameter_experiments(
        dataset,
        top_k_values=[1, 3, 5],
        min_score_values=[0.3, 0.45, 0.7],
    )

    assert len(experiment["retrieval_experiments"]) == 9
    assert experiment["recommended_configuration"] == {
        "top_k": 3,
        "min_score": 0.45,
    }
    assert experiment["recommended_metrics"]["recall_at_k"] == 1.0
    assert experiment["recommended_metrics"]["rejection_accuracy"] == 1.0
    assert experiment["recommended_metrics"]["pass_rate"] == 1.0

    low_top_k = next(
        result
        for result in experiment["retrieval_experiments"]
        if result["top_k"] == 1 and result["min_score"] == 0.45
    )
    assert low_top_k["recall_at_k"] < 1.0


def test_chunk_size_experiment_uses_the_real_chunking_function():
    dataset = load_dataset(DATASET_PATH)

    results = evaluate_chunk_sizes(dataset, chunk_sizes=[200, 500, 800])

    assert [result["chunk_size"] for result in results] == [200, 500, 800]
    assert all(result["overlap"] == result["chunk_size"] // 5 for result in results)
    assert all(0.0 <= result["evidence_retention_rate"] <= 1.0 for result in results)
    assert results[0]["chunk_count"] >= results[-1]["chunk_count"]
    assert results[0]["indexed_char_count"] >= results[-1]["source_char_count"]


def test_chunk_selection_prioritizes_context_cost_before_top1_on_a_tie():
    results = [
        {
            "chunk_size": 500,
            "top3_recall": 1.0,
            "rejection_accuracy": 1.0,
            "answer_accuracy": 1.0,
            "average_context_chars": 1249.8,
            "top1_recall": 0.8846,
        },
        {
            "chunk_size": 800,
            "top3_recall": 1.0,
            "rejection_accuracy": 1.0,
            "answer_accuracy": 1.0,
            "average_context_chars": 2109.3,
            "top1_recall": 0.9231,
        },
    ]

    selected = select_chunk_configuration(results)

    assert selected["chunk_size"] == 500


def test_chunk_selection_never_trades_recall_for_a_shorter_context():
    results = [
        {
            "chunk_size": 200,
            "top3_recall": 0.9615,
            "rejection_accuracy": 1.0,
            "answer_accuracy": 1.0,
            "average_context_chars": 484.4,
            "top1_recall": 0.9231,
        },
        {
            "chunk_size": 500,
            "top3_recall": 1.0,
            "rejection_accuracy": 1.0,
            "answer_accuracy": 1.0,
            "average_context_chars": 1249.8,
            "top1_recall": 0.8846,
        },
    ]

    selected = select_chunk_configuration(results)

    assert selected["chunk_size"] == 500
