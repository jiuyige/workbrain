import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
main = import_module("app.rag_evaluation").main


if __name__ == "__main__":
    main()
