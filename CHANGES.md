2026-05-04: single_agent.txt scaffolded with tool list + decomposition hint to equalize prompt fairness with multi-agent (audit Gap #3, Task 1.4)
2026-05-04: Task 1.5 (config ACCEPTANCE_THRESHOLDS), 1.7 (log_loader validation), 1.8 (multi_agent max_tool_rounds=15 + empty subtask marker) implemented
2026-05-04: Task 1.9 (14-tool pytest smoke tests in tests/test_tools.py)
2026-05-03: Task 2.2 — added rater_interactive.py (independent non-expert rater TUI, seed=99 stratified 6+6+6 sample, mode/run_index hidden, 4 structural dimensions only, output results/scores/rater_scores.csv) and docs/rater_brief.md (1-page bilingual rubric)
2026-05-05: Task 3.1-tool (scripts/mast_coding.py interactive MAST coding)
2026-05-05: Removed scripts/mast_coding.py and mast_coding.csv (reverted to thematic-analysis approach per DSV norm survey)
2026-05-05: Added scripts/scan_failure_patterns.py — one-off scan of 36 multi-agent runs to seed §4.4 inductive thematic analysis. Output saved to results/analysis/failure_patterns_scan.txt (3 candidate themes: Theme A tool exploration overhead 7 runs, Theme B synthesis under partial data 2 runs, Theme C self-acknowledged limitations 29 runs).
