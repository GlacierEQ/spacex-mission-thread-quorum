# AGENTS.md — spacex-mission-thread-quorum

**Company:** GlacierEQ
**Domain:** Autonomous Systems Engineering

## Quick Rules
- **Test command:** `PYTHONPATH=src pytest tests/ -v`
- **Lint:** `ruff check src/ tests/`
- **No drive-by edits** — load the skill first.

## Architecture
- `src/spacex_mission_thread_quorum/core.py` — Domain logic (Autonomous Systems Engineering)
- `tests/` — Verified test suite
- `.github/workflows/ci.yml` — Enforced CI pipeline
