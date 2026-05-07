# OCPM Multi-Agent vs Single-Agent LLM Assistant

Reproducibility artifact for the master's thesis **"Multi-Agent AI for Root-Cause and Bottleneck Analysis in Object-Centric Process Mining: A Comparative Study Against a Single-Agent LLM Assistant"** (Department of Computer and Systems Sciences, Stockholm University, 2026).

## What this is

A complete evaluation harness comparing two architectures for AI-assisted object-centric process mining (OCPM) on the **BPI Challenge 2017** event log (OCEL 2.0):

- **Single-agent baseline**: one LLM instance plans, executes tools, and synthesises in a single conversational turn
- **Multi-agent design**: planner-analyst-synthesizer roles communicate via explicit message passing

Both architectures call the same 12-tool OCPM toolkit (built on `pm4py`) and are evaluated on a 12-task set spanning bottleneck identification, root-cause hypothesis, and integrated analysis.

## What's in this repository

| Path | Content |
|---|---|
| `src/` | OCPM tool layer + assistant architectures (single-agent baseline, planner-analyst-synthesizer) |
| `scripts/` | Helper scripts (run, score, audit, translate) |
| `tests/` | Unit tests for tool layer |
| `results/runs/` | 72 raw run traces (12 tasks × 2 architectures × 3 replications) |
| `results/scores/` | Rubric scoring CSVs + inter-rater agreement data |
| `results/analysis/` | Aggregated descriptive statistics + failure-pattern scan |
| `pyproject.toml` | Python project metadata + dependencies |
| `.env.example` | Environment variable template (no secrets) |
| `DATA.md` | How to obtain BPI Challenge 2017 OCEL 2.0 |

## What's NOT in this repository

- **Raw event-log data** (`data/`, ~680 MB): the BPI Challenge 2017 log is publicly archived. See `DATA.md` for retrieval.
- **API keys / `.env`**: copy `.env.example` to `.env` and add your own keys.
- **Backup directories**: intermediate experimental backups are excluded.

## Quick start

```bash
# 1. Clone
git clone https://github.com/yang2632/ocpm-multi-agent-llm.git
cd ocpm-multi-agent-llm

# 2. Install
pip install uv
uv sync

# 3. Get the BPI 2017 OCEL 2.0 data (see DATA.md)

# 4. Configure API keys
cp .env.example .env
# edit .env with your OPENAI_API_KEY (or GEMINI_API_KEY)

# 5. Run a single task on a single architecture
uv run python run.py --task A1 --mode single_agent --runs 1

# 6. Run the full 72-run evaluation
uv run python run.py --all --modes single_agent multi_agent --runs 3

# 7. Score the runs (interactive rubric scoring)
uv run python score_interactive.py

# 8. Compute descriptive statistics
uv run python -m src.eval.analysis
```

## Requirements

- Python ≥ 3.10
- `pm4py` ≥ 2.7
- An OpenAI-compatible API key (e.g. for `gpt-5.5`) — set in `.env`
- ~1 GB disk for the event-log data (downloaded separately)

## Reproducibility

All execution parameters are recorded in each run's JSON trace:

- Task ID, architecture mode, replication index
- Full tool-call sequence with arguments and return summaries
- Intermediate planner/analyst/synthesizer messages
- Final answer string + wall-clock latency
- LLM model + temperature + decoding parameters

The 72 traces in `results/runs/` are the exact runs analysed in the thesis.

## How the thesis uses this artifact

The thesis reports **descriptive statistics** (means, standard deviations, mean differences) on rubric-scored quality dimensions plus operational cost ratios (latency, tool calls). It complements the quantitative comparison with a qualitative thematic analysis of the 36 multi-agent runs, identifying three recurring patterns: tool-exploration overhead, synthesis under partial data, and graceful degradation.

> **Note on the analysis script**: `src/eval/analysis.py` also emits exploratory Wilcoxon signed-rank and Cliff's delta values into `stats.json`. These are retained for transparency but are **not** reported in the thesis, because at the actual unit of analysis (4 tasks per category × 3 replications, where replications share within-task variance) the strict independence and symmetric-distribution assumptions underlying paired non-parametric tests do not cleanly hold. The thesis therefore relies on descriptive comparison + cost ratios + qualitative themes as the primary analytic frame.

## Citation

If you use this artifact, please cite the thesis:

```bibtex
@mastersthesis{yu2026ocpm,
  author = {Yu, Yang},
  title  = {Multi-Agent AI for Root-Cause and Bottleneck Analysis in Object-Centric Process Mining:
            A Comparative Study Against a Single-Agent LLM Assistant},
  school = {Stockholm University, Department of Computer and Systems Sciences},
  year   = {2026}
}
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

The BPI Challenge 2017 event log referenced by this artifact is published under the 4TU.ResearchData terms (DOI: `10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b`).

## Acknowledgements

Master's thesis supervised by **Martin "Moj" Duneld** at the Department of Computer and Systems Sciences, Stockholm University.

Built on:
- [`pm4py`](https://pm4py.fit.fraunhofer.de/) — process mining for Python (Berti, van Zelst, van der Aalst, 2019)
- BPI Challenge 2017 — Business Process Intelligence Challenge dataset (4TU.ResearchData)
- OCEL 2.0 specification (Berti et al., 2024)

---

For questions, open an issue or contact the author.
