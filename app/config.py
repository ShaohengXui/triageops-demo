"""Central configuration.

Everything is driven by environment variables with safe defaults so the project
runs offline out of the box (LLM_PROVIDER=mock).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience, not a requirement
    pass


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"
LOG_DIR = ROOT / "logs"
DB_PATH = DATA_DIR / "triageops.db"
EVAL_CASES_PATH = DATA_DIR / "eval_cases.json"


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.70"))
    max_tool_calls: int = int(os.getenv("MAX_TOOL_CALLS", "6"))


SETTINGS = Settings()


def ensure_dirs() -> None:
    for path in (DATA_DIR, DOCS_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
