"""Central configuration for the OCPM artifact."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "bpi2017"
RESULTS_DIR = PROJECT_ROOT / "results"

# ── Dataset registry ──────────────────────────────────────────────
# Each key selects an OCEL 2.0 log + display name (used in the injected log
# profile). Path may be a directory (run.py picks the first OCEL file) or a
# file. BPI 2017 stays the default; Order Management is the second dataset.
DATASETS: dict[str, dict[str, object]] = {
    "bpi2017": {
        "path": PROJECT_ROOT / "data" / "bpi2017",
        "display_name": "BPI Challenge 2017 (loan application)",
    },
    "order_management": {
        "path": PROJECT_ROOT / "data" / "order_management",
        "display_name": "Order Management (ocel-standard.org, OCEL 2.0)",
    },
}


def dataset_path(key: str) -> Path:
    if key not in DATASETS:
        raise ValueError(f"Unknown dataset '{key}'. Known: {list(DATASETS)}")
    return Path(DATASETS[key]["path"])  # type: ignore[arg-type]


def dataset_display_name(key: str) -> str:
    entry = DATASETS.get(key, {})
    return str(entry.get("display_name", key))


# ── Dataset-isolated results paths (single source of truth) ───────
# BPI 2017 keeps the legacy flat layout (results/{runs,scores,analysis}) so the
# existing thesis results and their paths are unchanged. Every other dataset is
# isolated under results/<dataset>/{runs,scores,analysis}. All scoring/analysis
# scripts MUST route through these helpers so BPI and OM never collide.
def active_dataset() -> str:
    """Active dataset from the DATASET env var (loads .env first)."""
    load_dotenv(PROJECT_ROOT / ".env")
    return os.getenv("DATASET", "bpi2017")


def dataset_results_dir(dataset: str | None = None) -> Path:
    ds = dataset or active_dataset()
    return RESULTS_DIR if ds == "bpi2017" else RESULTS_DIR / ds


def runs_dir(dataset: str | None = None) -> Path:
    return dataset_results_dir(dataset) / "runs"


def scores_dir(dataset: str | None = None) -> Path:
    return dataset_results_dir(dataset) / "scores"


def analysis_dir(dataset: str | None = None) -> Path:
    return dataset_results_dir(dataset) / "analysis"


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
    dataset: str = "bpi2017"
    data_path: Path = field(default_factory=lambda: DATA_DIR)

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> Config:
        if dotenv_path:
            load_dotenv(dotenv_path)
        else:
            load_dotenv(PROJECT_ROOT / ".env")

        dataset = os.getenv("DATASET", "bpi2017")
        # DATA_PATH (if set) wins; otherwise derive the path from the dataset key.
        default_path = str(dataset_path(dataset)) if dataset in DATASETS else str(DATA_DIR)
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
            dataset=dataset,
            data_path=Path(os.getenv("DATA_PATH", default_path)),
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
