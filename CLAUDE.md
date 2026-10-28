# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## About
AskDB is a read-only web app where non-technical staff ask plain-English questions of a SQLite database.
They get a written answer, a result table and a plain-English account of how it was worked out.

## Source of truth
- `docs/SPEC.md` is the source of truth. If code and spec disagree, the spec wins, or the spec is changed first.
- `docs/PLAN.md` tracks progress. Update it in the same change that completes a step. (It does not exist yet; create it when work starts.)

## Stack
- Backend: Python + FastAPI (single uvicorn process), managed with `uv`.
- Frontend: React + Vite.
- LLM: Claude via the Anthropic API (tool-use loop). Data: SQLite only.

## Commands
The repo has no code or tooling yet. These are the intended commands; correct them here as soon as the scaffolding exists.

| Task | Backend (repo root) | Frontend (`frontend/`) |
|---|---|---|
| Install | `uv sync` | `npm install` |
| Run | `uv run uvicorn askdb.main:app --reload` | `npm run dev` |
| Test | `uv run pytest` (one test: `uv run pytest path::name`) | `npm test` |
| Lint | `uv run ruff check .` | `npm run lint` |

## Folder layout (planned)
- `docs/`: `SPEC.md`, `PLAN.md`, `one-pager.md`
- `src/askdb/`: backend (API, auth, orchestration, read-only SQL executor)
- `frontend/`: React + Vite app
- `tests/`: backend tests; `tests/validation/` runs the eval YAMLs
- `config/`: per-database schema YAMLs and validation cases
- `data/`: sample `cloudmetrics.db`, `cloudmetrics.yaml`, `cloudmetrics_eval.yaml`

## Guardrails
- **Read-only SQL**: open target DBs with `mode=ro`; accept a single `SELECT`/`WITH` only; reject `ATTACH`, `DETACH`, `PRAGMA`, `load_extension`. Never write to a target DB.
- **Row cap and timeout**: display at most 1,000 rows; abort queries after 10s (progress handler); a turn is capped at 8 tool steps and 60s.
- Hidden tables/columns never reach the prompt, the SQL or the CSV.
- Never commit secrets (API keys, passwords, session secrets). Configuration comes from environment variables.
- Never read `.env` files. Ask the user for any value you need.
- Never show raw errors to users; log them to the audit log.

## Conventions
- Every change comes with tests: new behavior gets a test, and a bug fix gets a regression test. Run the backend tests and lint before calling work done.
- Safety-related changes need tests that try `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `PRAGMA` and multi-statement input, and assert the DB file is unchanged.
- Use a stubbed LLM in tests; use the real API only manually.
- SQL is SQLite dialect: `strftime`, `julianday`, `date()`; no `DATE_TRUNC` or `EXTRACT`.
