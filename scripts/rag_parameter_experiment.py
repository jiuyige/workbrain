import json
import sys
from importlib import import_module
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
evaluation = import_module("app.rag_evaluation")


def main() -> None:
    dataset = evaluation.load_dataset(evaluation.DEFAULT_DATASET_PATH)
    report = evaluation.run_parameter_experiments(
        dataset,
        top_k_values=[1, 3, 5],
        min_score_values=[0.3, 0.45, 0.7],
        chunk_sizes=[200, 500, 800],
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
