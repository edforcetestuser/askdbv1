# AskDB: Implementation Plan

Tracks progress against `docs/SPEC.md` (the source of truth). Update this file in the same change that completes a step.

## Status
| # | Slice | Depends on | Status |
|---|---|---|---|
| 1 | Scaffold + read-only SQL executor | none | [x] |
| 2 | Schema YAML loader and prompt builder | 1 | [ ] |
| 3 | Orchestrator with a stubbed LLM | 2 | [ ] |
| 4 | Real Anthropic client + validation harness | 3 | [ ] |
| 5 | App DB, auth, user and database admin APIs | 1, 2 | [ ] |
| 6 | Threads, ask endpoint, follow-ups, audit log, CSV | 3, 5 | [ ] |
| 7 | Frontend chat UI | 6 | [ ] |
| 8 | Schema admin and audit viewer | 2, 5, 6, 7 | [ ] |

## Context
The repo has a spec (`docs/SPEC.md`), a sample DB (`data/cloudmetrics.db`), its schema YAML (`data/cloudmetrics.yaml`) and a 29-case validation set (`data/cloudmetrics_eval.yaml`). This plan breaks v1 into thin vertical slices. Each ships something runnable and testable, and they are ordered so the riskiest guarantee (read-only SQL) lands first and the eval set can score answer quality early.

Every slice follows `CLAUDE.md`:
- Tests come with the change, using a stubbed LLM. The real API is used only manually.
- Run `uv run pytest` and `uv run ruff check .` before calling a slice done.
- Safety-related changes need tests that try `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `PRAGMA` and multi-statement input, and assert the DB file is unchanged.
- Update this file in the same change.

The schema YAML format is defined in SPEC 4.8 and follows `data/cloudmetrics.yaml`.

## Slices

### 1. Scaffold + read-only SQL executor
- **Goal:** `uv` project, config from env vars, and the safe query path every later slice uses: single `SELECT`/`WITH` check, `mode=ro` connection per query, 10s progress-handler timeout, 1,000-row cap, `busy_timeout` and a friendly busy error. Create this file's progress tracking; correct the Commands table in `CLAUDE.md`.
- **Files:** `pyproject.toml`, `src/askdb/config.py`, `src/askdb/sql_guard.py`, `src/askdb/executor.py`, `src/askdb/errors.py`, `tests/conftest.py`, `tests/test_config.py`, `tests/test_sql_guard.py`, `tests/test_executor.py`, `docs/PLAN.md`, `CLAUDE.md`.
- **Verify:**
  - Parametrised tests for `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `DETACH`, `PRAGMA`, `load_extension` and multi-statement input. Each is rejected and the DB file hash is unchanged (run on a temp copy of `cloudmetrics.db`).
  - A deliberate cross-join aborts within the timeout.
  - A query returning more than 1,000 rows is truncated with a flag.
  - A `WITH` query works.
- **Depends on:** none.

### 2. Schema YAML loader and prompt builder
- **Goal:** Load and validate a database's YAML in the `cloudmetrics.yaml` format (SPEC 4.8). Render the system prompt: role, rules, today and timezone (using `calendar.fiscal_year_start_month`), as-of date, then the schema section, which is the `description` verbatim followed by the `tables` as `CREATE TABLE` DDL with the table and column descriptions as comments.
- **Files:** `src/askdb/schema_config.py` (typed models for the YAML), `src/askdb/schema.json` (JSON Schema, unknown keys rejected), `src/askdb/prompt.py`, `tests/test_schema_config.py`, `tests/test_prompt.py`.
- **Verify:**
  - `data/cloudmetrics.yaml` loads unchanged and `${CLOUDMETRICS_DB_PATH}` expands.
  - A missing required key, an unknown key (including the retired `metrics`, `glossary`, `date_format` and `hidden`), a bad `type` and a `references` target that is not in the YAML each fail with a readable error.
  - A golden-string test covers the rendered schema section: description verbatim, DDL with `PRIMARY KEY`, `REFERENCES` and comments, and no `name`, `display_name`, `path` or `calendar` in the schema section.
  - Every table and column in `cloudmetrics.yaml` appears in the rendered DDL.
- **Depends on:** 1.
- **Note from slice 1:** `Settings` in `config.py` is the one place env vars are read; add new settings as fields with a `from_env` entry instead of reading `os.environ` elsewhere.

### 3. Orchestrator with a stubbed LLM
- **Goal:** The tool-use loop with `run_sql` (columns, row count, up to 50 sample rows) and `ask_clarification` (ends the turn). Up to 2 silent SQL-error retries. 8-step and 60s caps with a plain failure message. The structured final response (answer, steps, assumptions, SQL). The backend re-runs the final SQL for the display table. Zero-row and unanswerable or out-of-scope outcomes are handled.
- **Files:** `src/askdb/llm.py` (client protocol plus scripted stub), `src/askdb/orchestrator.py`, `src/askdb/models.py`, `tests/test_orchestrator.py`.
- **Verify:** Scripted-stub tests for:
  - happy path
  - SQL error then recovery
  - retries exhausted (the user message hides the raw error, which is recorded for the audit log)
  - step cap
  - time cap (fake clock)
  - clarification turn
  - zero rows reported as "no matching rows" unless the query is an aggregate
  - display table re-run capped at 1,000 rows
- **Depends on:** 2.
- **Note from slice 1:** `run_query` raises `QueryError` subclasses (`askdb/errors.py`). `user_message` is safe to show; `detail` is the raw SQLite text, which goes to the model for retries and to the audit log, never to the user. A result carries up to `row_cap` rows plus `truncated`; take the first 50 rows for the model's sample.

### 4. Real Anthropic client + validation harness
- **Goal:** The Claude adapter for the tool-use loop (model name from config, token counts captured) and the eval runner that scores `cloudmetrics_eval.yaml`.
  - A case passes if the final SQL's result set equals `expected_sql`'s.
  - `clarification` and `declined` cases check the outcome type.
  - Follow-up cases seed `conversation`.
  - `today` is injectable.
- **Files:** `src/askdb/anthropic_client.py`, `tests/validation/runner.py`, `tests/validation/test_cloudmetrics.py`, a `real_llm` pytest marker or env flag.
- **Verify:**
  - The default run uses an oracle stub that returns each case's `expected_sql` and must pass 100%. That proves the harness, and that every expected SQL runs through the guard.
  - Result-set comparison is unit-tested (row order, float tolerance).
  - Manual: the user sets `ANTHROPIC_API_KEY` and runs with the real-LLM flag to get a per-category pass rate. Never read `.env` files.
- **Depends on:** 3.

### 5. App DB, auth, user and database admin APIs
- **Goal:** The app SQLite DB and migrations. argon2 or bcrypt login, HTTP-only same-site session cookie, CSRF on mutating routes, login rate limit, `/api/me`. Bootstrap admin from CLI or env. Admin user management (create, disable, reset password, set role). Database registry (`name`, `display_name`, `path`, `as_of_date`) limited to an allow-listed directory and re-validated on every use. Registration works by path, or from a schema YAML whose `name`, `display_name` and `path` create the entry; a YAML `path` that resolves to a different file than the registration is refused. `GET /api/databases`.
- **Files:** `src/askdb/main.py`, `src/askdb/appdb.py`, `src/askdb/auth.py`, `src/askdb/api/auth.py`, `src/askdb/api/admin_users.py`, `src/askdb/api/databases.py`, tests per module.
- **Verify:** FastAPI `TestClient`:
  - login and logout
  - wrong password
  - a disabled user is blocked
  - the rate limit trips
  - a mutating request without a CSRF token is refused
  - a `user` gets 403 on admin routes
  - a path outside the allow-list (including `..` traversal) is refused
  - a non-SQLite file is refused
  - registering from `data/cloudmetrics.yaml` (with `CLOUDMETRICS_DB_PATH` set) creates the entry, and a YAML path that differs from the registered path is refused
- **Depends on:** 1, 2 (YAML loader).
- **Note from slice 1:** `run_query` and `connect_readonly` take a filesystem path, so the registry must turn a `sqlite:///` URL into a path first. `mode=ro` never creates a missing file, so a bad path fails at open instead of making an empty database.

### 6. Threads, ask endpoint, follow-ups, audit log, CSV
- **Goal:** `POST /api/threads`, `GET /api/threads[/{id}]`, `POST /api/threads/{id}/ask`, `GET /api/turns/{id}/csv`.
  - Turns are persisted without result rows.
  - Follow-up context is the last 10 turns (question, SQL, answer, result summary), with an "earlier history omitted" note.
  - Reopening a thread re-runs the stored SQL and flags refreshed data.
  - Dates resolved against the timezone, the as-of override and the YAML calendar appear in the assumptions.
  - Every ask, failure and export is audited.
  - CSV is regenerated from the stored SQL, prefixes cells starting with `=`, `+`, `-` or `@` with `'`.
- **Files:** `src/askdb/api/threads.py`, `src/askdb/api/csv_export.py`, `src/askdb/audit.py`, additions to `orchestrator.py` and `prompt.py`, `tests/test_threads_api.py`, `tests/test_csv.py`.
- **Verify:** End-to-end through `TestClient` with the stub:
  - ask, then a follow-up (the stub asserts it received the prior SQL)
  - the 11th turn drops the oldest
  - users cannot read another user's thread or CSV
  - formula-injection cells are prefixed
  - audit rows are written
  - no raw error reaches a response body
  - the eval case `mrr_by_plan_followup_industry` runs through the API path
- **Depends on:** 3, 5.

### 7. Frontend chat UI
- **Goal:** Vite + React app with login, thread sidebar, database picker (locked once the thread exists) and a question box with spinner. Each turn shows the answer, a sortable table with truncation notice, the assumptions banner, numbered "How I got this" steps and a collapsed "Show query". It also handles clickable clarification options plus "Just pick the most likely", failure and empty-result messages with rephrasings, and "Download CSV".
- **Files:** `frontend/package.json`, `frontend/vite.config.ts` (dev proxy to FastAPI), `frontend/src/**` (api client, Login, ThreadList, Chat, TurnView, ResultTable), component tests.
- **Verify:**
  - `npm test` with a mocked API covering each turn state: answer, clarification, failure, zero rows, truncated.
  - `npm run lint`.
  - Keyboard-only walkthrough and header semantics on the table.
  - Manual run of the backend (stub mode) plus `npm run dev`: log in, ask, follow up, download CSV.
- **Depends on:** 6.

### 8. Schema admin and audit viewer
- **Goal:** The remaining admin area.
  - Backend: schema YAML GET/PUT/validate/diff/versions/rollback (the diff flags YAML tables and columns missing from the DB, and DB tables and columns with no description), column sample-value introspection, settings (global timezone, per-database as-of date, model name, step and time caps), and audit log queries with filters.
  - Frontend: admin screens for users, databases, YAML editor with validation errors and diff, version history and audit log.
  - If this is too big for one session, split it into backend then UI.
- **Files:** `src/askdb/api/admin_schema.py`, `api/admin_settings.py`, `api/admin_audit.py`, `src/askdb/schema_diff.py`, `frontend/src/admin/**`, tests.
- **Verify:**
  - Invalid YAML gives line-level errors.
  - The diff runs against `cloudmetrics.db`: `data/cloudmetrics.yaml` shows no missing items, and removing a column from the DB copy or the YAML shows the expected flag.
  - Save then rollback restores the earlier text.
  - A new version takes effect on the next ask.
  - The audit log filters by user, database, date and status.
  - Non-admins are refused.
  - Frontend tests cover the editor and diff views.
  - Final acceptance pass from SPEC section 9: as admin, register `cloudmetrics.db`, upload its YAML and see the audit log; as user, ask, follow up and export CSV.
- **Depends on:** 2, 5, 6, 7.

## Dependency order
1 → 2 → 3 → 4, with 5 branching off 2 (it needs the YAML loader for registration). Then 6 (needs 3 and 5) → 7 → 8. Slice 4 can run any time after 3, since the eval harness is independent of the web layers.

## Risks (from SPEC section 10)
| Risk | Accepted tradeoff | Limited by |
|---|---|---|
| Wrong answers presented as fact | No second verification pass in v1 | Metric definitions in the schema description, assumptions banner, visible SQL, numbers taken from SQL output |
| Prompt injection via cell values | Ignored in v1; worst case a misleading answer, since every table is already readable by all users | `mode=ro` prevents writes |
| No cost limits | A heavy user or a tool loop can run up API spend | 8-step cap and 60s turn cap |
| Data leaves the network | Question, schema description, table DDL and sample rows go to the Anthropic API | Needs sign-off for sensitive data |
| Light SQLite protection | No general lockdown and no per-table or per-column restriction; every user can query everything | `mode=ro`, statement check, timeout |
| Live-DB contention | A writer may hold locks; the DB is opened live, not as a snapshot | `busy_timeout`, friendly busy message; WAL on the source DB is recommended |
| Stale threads | Reopening re-runs SQL, so numbers may differ from the saved answer | "Refreshed now" marker and a note |
| YAML burden | Answer quality depends on the admin writing a good free-text `description` (metrics, joins, NULL and date conventions) | Upload diff flags missing descriptions; nothing checks the description text itself |
Build-time watch items:
- Real-LLM quality on the eval set can only be measured manually in slice 4. Budget a prompt-tuning pass there rather than in later slices.
- Slice 8 is the largest. Split it if a session runs long.