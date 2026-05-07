"""Central configuration for the OCPM artifact."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "bpi2017"
RESULTS_DIR = PROJECT_ROOT / "results"


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration loaded from environment."""

    openai_api_key: str = ""
    openai_base_url: str = ""  # Custom endpoint (OpenAI-compatible)
    gemini_api_key: str = ""
    gemini_base_url: str = ""  # Custom endpoint for Gemini
    llm_provider: str = "openai"  # "openai" or "gemini"
    # Defaults below match the thesis evaluation (gpt-5.5, 600s timeout); see results/run_manifest.json.
    llm_model: str = "gpt-5.5"
    temperature: float = 0.0
    max_tokens: int = 4096
    task_timeout_s: int = 600
    runs_per_task: int = 3
    data_path: Path = field(default_factory=lambda: DATA_DIR)

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> Config:
        if dotenv_path:
            load_dotenv(dotenv_path)
        else:
            load_dotenv(PROJECT_ROOT / ".env")

        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_base_url=os.getenv("GEMINI_BASE_URL", ""),
            llm_provider=os.getenv("LLM_PROVIDER", "openai"),
            llm_model=os.getenv("LLM_MODEL", "gpt-5.5"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            task_timeout_s=int(os.getenv("TASK_TIMEOUT_S", "600")),
            runs_per_task=int(os.getenv("RUNS_PER_TASK", "3")),
            data_path=Path(os.getenv("DATA_PATH", str(DATA_DIR))),
        )


# ── Acceptance thresholds (FROZEN PRE-EXECUTION per Method.tex §3.4.2) ──
# These define what counts as a "passing" answer per task category.
# Set before any results were available; do not adjust post-hoc.
ACCEPTANCE_THRESHOLDS = {
    # Category A (closed): correctness must be >= 1 (partial or full match)
    # and traceability >= 1 (at least some chain visible).
    "A_correctness_min": 1,
    "A_traceability_min": 1,
    # Category B/C (open): mean of factual_alignment + analytical_depth +
    # evidence_grounding must be >= 5.0; traceability >= 1.
    "B_mean_min": 5.0,
    "C_mean_min": 5.0,
    "BC_traceability_min": 1,
}
