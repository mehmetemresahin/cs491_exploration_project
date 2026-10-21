import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# MOCK491_DATA_DIR lets tests and experiments point at a throwaway directory.
DATA_DIR = Path(os.environ.get("MOCK491_DATA_DIR", ROOT / "data"))
BRONZE_DIR = DATA_DIR / "bronze"
MOCK_DIR = DATA_DIR / "mock"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

# Report section 6.4: extractions below this confidence go to the human review queue.
HITL_CONFIDENCE_THRESHOLD = 0.85

# Text-to-SQL model (genbi/llm.py). "auto" uses a local Ollama server when one is running and
# never a paid API; "anthropic" must be chosen explicitly. "none" disables the model.
LLM_PROVIDER = os.environ.get("MOCK491_LLM", "auto")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("MOCK491_OLLAMA_MODEL", "qwen2.5-coder:7b")
ANTHROPIC_MODEL = os.environ.get("MOCK491_ANTHROPIC_MODEL", "claude-opus-5-5")
