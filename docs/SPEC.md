# AskDB: Specification (v1)

## 1. Summary
AskDB is a read-only, ask-and-answer web app for non-technical business staff. A user asks a question in plain English about a SQLite database. They get back a written answer, a result table and a plain-English account of how the answer was worked out. Follow-up questions refine earlier answers in the same thread.

## 2. Decisions from the interview
| Area | Decision |
|---|---|
| Database engine | SQLite only |
| Data access | Server-side file path or `sqlite:///` URL, opened live (not a snapshot). Multiple databases are registered; the user picks one per thread. |
| Scale assumption | Under 30 tables and under 1M rows per database. The full schema description and table DDL go in every prompt. |
| Semantics | Admin-curated schema YAML in the format of `data/cloudmetrics.yaml` (section 4.8): connection fields, a free-text `description` carrying grain, joins, metric definitions, NULL conventions and date handling, and `tables` with column descriptions |
| LLM | Claude via the Anthropic API (tool-use loop) |
| Stack | Python FastAPI backend, React + Vite frontend |
| Auth | Local users in an app SQLite DB with `user` and `admin` roles. One shared read-only DB connection per registered database. |
| Ambiguity | The model asks a clarifying question; if the user skips it, the model states its assumption and answers |
| Follow-ups | Thread-based. The model sees prior questions, SQL and result summaries. |
| Result limit | 1,000 rows, with a visible truncation notice |
| Transport | Spinner, then the full response (no streaming) |
| Trust UI | Plain-English steps, a collapsible "Show query" SQL block and an assumptions banner |
| Cost limits | None in v1 |
| Prompt injection | Ignored in v1 (accepted risk, see section 10) |
| Extras | CSV export of the displayed table (up to 1,000 rows) |

Not selected: self-check second pass, thumbs up/down feedback, golden-question tests, mobile-first layout, starter questions. They are listed in section 11 as future work.

## 3. Users and roles
- **User**: asks questions, views their own threads, exports CSV.
- **Admin**: everything a user can do, plus managing users, databases and schema YAML, and viewing the audit log.
- First admin is created by a bootstrap CLI command or environment variables on first run.

## 4. Functional requirements

### 4.1 Asking
1. A chat thread layout with a thread sidebar, a database picker (chosen when the thread is created; locked afterward) and a question box at the bottom.
2. Each turn shows:
   - A plain-English answer.
   - A result table (sortable columns, up to 1,000 rows, truncation notice if capped).
   - An assumptions banner (resolved date ranges, status filters, metric definitions used, interpretations).
   - A "How I got this" panel with numbered plain-English steps and a collapsed "Show query" SQL block.
   - A "Download CSV" button.
3. The request is a single POST. The UI shows a spinner until the full response arrives.
4. A turn takes at most N tool-loop steps (default 8) and an overall wall-clock cap (default 60s). If either is exceeded the user gets a plain failure message.

### 4.2 Follow-ups
- The model receives for each prior turn: the question, the final SQL, the answer text, and a result summary (column names, row count, up to 5 sample rows).
- Context is capped at the last 10 turns. Older turns are dropped, with a note in the prompt that earlier history was omitted.
- Follow-ups such as "Now just show the West region" are answered by rewriting the previous SQL, not by filtering the displayed table.

### 4.3 Ambiguity and unanswerable questions
- If a question has two or more plausible readings (for example "revenue", which could mean paid invoices or MRR), the model returns a clarifying question with 2-4 clickable options plus "Just pick the most likely". Picking that option, or typing a new question instead, makes the model state its assumption and answer.
- If the data cannot answer the question (for example "how are customers feeling?"), the model says so plainly, names what the database does contain, and suggests 2-3 askable rephrasings.
- Out-of-scope requests (writing data, forecasts, advice, cross-source joins) get a polite refusal that says what AskDB can do.

### 4.4 Failures and empty results
- SQL errors are retried automatically, up to 2 times, silently. The model sees the error text.
- After the retries are used up, or on a zero-row result, the user sees a plain message and suggested rephrasings. A zero-row result is reported as "no matching rows" and is not presented as zero unless the query was an aggregate.
- Raw errors are never shown to users. They are kept in the audit log.

### 4.5 Dates
- The app resolves relative dates against the configured IANA timezone (a global setting) and "today", or an admin-set per-database **as-of date** override for snapshot datasets (a database setting, not part of the YAML). Quarters and years follow the YAML's `calendar.fiscal_year_start_month`.
- The resolved range always appears in the assumptions banner, for example: "yesterday = 2026-10-27 (Asia/Kolkata)".
- Date formats are declared in the YAML through the column `type` (`DATE`, `DATETIME`) and the date-handling section of the `description` (for example ISO text `YYYY-MM-DD`, with the matching `strftime` and `julianday` patterns). There is no per-column `date_format` key in v1; any non-ISO storage must be explained in the description. The model must use SQLite date functions that match the declared format.
- The description should also say where the data ends. A relative period outside the data range is clarified with the user instead of silently returning no rows.

### 4.6 CSV export
- Exports exactly the displayed table (at most 1,000 rows), produced by the backend from a re-run of the stored SQL.
- Cells beginning with `=`, `+`, `-` or `@` are prefixed with `'` to prevent spreadsheet formula injection.
- Each export is recorded in the audit log.

### 4.7 Admin area
1. **Users**: create, disable, reset password, set role.
2. **Databases**: register by path or `sqlite:///` URL, with a display name.
   - A database can also be registered from its schema YAML: `name`, `display_name` and `path` (after `${ENV_VAR}` expansion) create the registry entry. When both a registration and a YAML are supplied, the YAML `path` must resolve to the same file as the registration, otherwise validation fails.
   - The path must resolve under an admin-configured allow-listed directory.
   - The file must exist, open with `mode=ro` and look like a SQLite database.
   - Re-validation runs on every use.
3. **Schema YAML** per database:
   - Upload, validate against a JSON Schema and show a diff against the live database. The diff flags tables and columns in the YAML that are missing from the DB, and DB tables and columns with no description (a column without a `description` is allowed but flagged).   - In-browser editing with validation.
   - Version history with rollback.
   - The introspection view shows sample values per column to help the admin write descriptions.
4. **Audit log**: filter by user, database, date and status.
5. **Settings**: timezone, as-of date override, Anthropic model name, step and time caps.

### 4.8 Schema YAML format
The reference file is `data/cloudmetrics.yaml`. Abridged:
```yaml
name: cloudmetrics
display_name: CloudMetrics SaaS Analytics
path: ${CLOUDMETRICS_DB_PATH}      # opened read-only (mode=ro)

calendar:
  fiscal_year_start_month: 1       # calendar year

description: |
  Free text sent verbatim to the model: what the data is, the grain of each
  table, how tables join, metric definitions (MRR, revenue, churn rate, ...),
  status conventions and NULLs, SQLite date handling, and which table answers what.

tables:
  - name: subscriptions
    description: Customer subscriptions to plans. A customer may have several over time.
    columns:
      - { name: subscription_id, type: INTEGER, primary_key: true, description: "Unique subscription identifier" }
      - { name: customer_id,     type: INTEGER, references: customers.customer_id }
      - { name: end_date,        type: DATE,    description: "NULL while ongoing (active, trial, paused)" }
      - { name: status,          type: TEXT,    description: "active, churned, trial, paused" }
```
Keys:
| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Stable identifier for the database. |
| `display_name` | yes | Name shown in the database picker. |
| `path` | yes | File path or `sqlite:///` URL. `${ENV_VAR}` is expanded at load time; the result is checked against the allow-listed directory (section 4.7). |
| `calendar.fiscal_year_start_month` | no | 1-12, default 1. Used when resolving quarters and years. |
| `description` | yes | Free text sent verbatim to the model. All business rules live here. |
| `tables[].name`, `tables[].description` | yes | Table name and what one row represents. |
| `tables[].columns[].name`, `.type` | yes | Column name and declared type (`INTEGER`, `TEXT`, `REAL`, `DATE`, `DATETIME`). |
| `tables[].columns[].primary_key` | no | Boolean. |
| `tables[].columns[].references` | no | `table.column`. Both must exist in the YAML. |
| `tables[].columns[].description` | no | Plain-English meaning, including allowed values and NULL behaviour. |

Rules:
- Unknown keys are rejected. There are no `metrics`, `glossary`, `date_format` or `hidden` keys: metric definitions and date handling are written in the `description`, and every table and column listed is visible to the model and queryable by every user.
- What the model sees of the schema is exactly the `description` (verbatim) and the `tables`, rendered as `CREATE TABLE` DDL with the table and column descriptions as comments. `name`, `display_name`, `path` and `calendar` are not rendered, although the date context in the system prompt uses `calendar`.
- Tables or columns that exist in the database but are not listed in the YAML are not shown to the model. This is a documentation choice, not an access control: the SQL executor does not block them (section 5.3).

## 5. Architecture

### 5.1 Components
- **Frontend (React + Vite)**: chat UI, admin UI, login.
- **Backend (FastAPI)**: auth, thread API, query orchestration, admin API.
- **App DB (SQLite, separate file)**: users, sessions, threads, turns, databases registry, YAML versions, audit log. Contains no target-database result rows.
- **Target DBs (SQLite files)**: touched only through the read-only query executor.
- **Anthropic API**: SQL generation and answer writing.

### 5.2 Orchestration (per question)
1. Build the system prompt: role, rules, timezone and today's date, and the schema section: the YAML `description` verbatim, followed by the `tables` as `CREATE TABLE` DDL with descriptions as comments.
2. Run a tool-use loop with these tools:
   - `run_sql(sql)`: returns column names, the row count, and up to 50 sample rows for the model to inspect.
   - `ask_clarification(question, options)`: ends the turn.
3. The final structured response contains the answer text, the plain-English steps, the assumptions list and the final SQL.
4. The backend re-runs the final SQL for the display table (up to 1,000 rows). Numbers in the answer must come from the query output, not from the model's own arithmetic. Aggregates are computed in SQL.
5. Persist the turn (question, SQL, answer, steps, assumptions, row count, duration, tokens). Result rows are not stored. A past thread re-runs the stored SQL when reopened, and the UI marks the data as "refreshed now" (the answer text may then differ from the current rows; this is flagged with a note).

### 5.3 Read-only and safety (deliberately light, as chosen)
1. Open the target DB with URI `file:...?mode=ro`. This is the primary guarantee that data cannot change.
2. Accept only a single statement beginning with `SELECT` or `WITH`. Reject multiple statements, `ATTACH`, `DETACH`, `PRAGMA` and `load_extension`.
3. Install a progress handler that aborts queries after 10 seconds (configurable). This keeps a runaway query or accidental cartesian join from hanging the server.
4. Apply a hard row cap of 1,000 when displaying.
5. SQLite specifics: set `busy_timeout`; handle `SQLITE_BUSY` by returning a friendly "database is busy, try again" message; open one connection per query (no sharing across threads).
6. Known limit: every table and column in the database is queryable by every user in v1. There is no per-table or per-column restriction and no SQLite authorizer. The backend process itself holds read access to the full DB file.

### 5.4 Auth
- Passwords hashed with argon2 or bcrypt. HTTP-only, same-site session cookie. CSRF protection on mutating routes.
- Login rate limiting.
- The Anthropic API key and secrets live in environment variables only.

## 6. Data model (app DB)
`users(id, email, password_hash, role, disabled, created_at)`,
`databases(id, name, display_name, path, as_of_date, created_at)`,
`schema_versions(id, database_id, yaml_text, created_by, created_at)`,
`threads(id, user_id, database_id, title, created_at)`,
`turns(id, thread_id, question, sql, answer, steps_json, assumptions_json, row_count, truncated, status, error_detail, duration_ms, input_tokens, output_tokens, created_at)`,
`audit_events(id, user_id, kind, detail_json, created_at)`.
A thread's database is fixed, so replacing or removing a database leaves old threads readable. A deleted database marks its threads "data source removed".

## 7. API (sketch)
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me`
- `GET /api/databases`
- `POST /api/threads`, `GET /api/threads`, `GET /api/threads/{id}`
- `POST /api/threads/{id}/ask` returns a turn (or a clarification)
- `GET /api/turns/{id}/csv`
- Admin: `/api/admin/users`, `/api/admin/databases`, `/api/admin/databases/{id}/schema` (GET, PUT, validate, diff, versions, rollback), `/api/admin/audit`

## 8. Non-functional requirements
- Typical question answered in 5-20 seconds. A hard cap of 60 seconds.
- Desktop-first responsive layout. Mobile is not a requirement.
- Accessibility: keyboard-operable, labelled controls, tables with header semantics.
- Config via environment variables: API key, model name, app DB path, allowed DB directory, timezone, caps.
- Single-process deployment (uvicorn) behind a reverse proxy over HTTPS.

## 9. Testing and acceptance
- **Read-only safety**: automated tests attempt `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `PRAGMA` and multi-statement input. Each must fail and the DB file hash must be unchanged.
- **Timeout**: a deliberate cross-join aborts within the configured time and the server stays responsive.
- **Orchestration**: the sample database `data/cloudmetrics.db` with the validation set `data/cloudmetrics_eval.yaml` (29 cases: totals and trends, rankings, filters, comparisons, a follow-up, clarifications and non-data requests). A case passes when the final SQL's result set equals its `expected_sql`'s; clarification and declined cases check the outcome type. Empty results and error retries are covered by scripted-stub tests. The set runs against a stubbed LLM in CI (an oracle stub that returns each `expected_sql`), and against the real API manually.
- **Dates**: "yesterday", "this quarter vs last", with timezone and as-of override.
- **Admin**: YAML validation errors, diff display, rollback.
- **Acceptance**: a user can ask a question, get the three outputs, ask a follow-up, and export CSV. An admin can register a DB, upload YAML, and see the audit log.

## 10. Risks and accepted tradeoffs
- **Wrong answers presented as fact (desirable-not-required)**: mitigated only by the metric definitions in the schema description, the assumptions banner, visible SQL and numbers sourced from SQL output. There is no second verification pass in v1.
- **Prompt injection via cell values**: ignored in v1. The sample rows returned to the model could contain instructions. Worst case is a misleading answer, because the read-only connection prevents writes and every table is already readable by all users.
- **No cost limits**: a heavy user or a tool loop could run up API spend. The only brakes are the step cap and the 60s turn cap.
- **Data leaves the network**: question text, schema, glossary and sample rows are sent to the Anthropic API. This needs sign-off for sensitive data.
- **Light SQLite protection**: it relies on `mode=ro`, the statement check and the timeout. There is no per-table or per-column restriction. A bug in the statement check is bounded by `mode=ro`.
- **Live-DB contention**: a writer process may hold locks. WAL mode is recommended on the source DB; the app cannot set it.
- **Stale threads**: reopening an old thread re-runs SQL, so numbers may differ from the saved answer.
- **YAML burden**: answer quality depends on the admin writing a good `description` (metric definitions, join paths, NULL and date conventions). It is free text, so nothing checks it beyond the diff against the live schema.
## 11. Out of scope (v1) and future work
- Out of scope: writing or editing data, saved dashboards, scheduled reports, forecasting and advice, combining databases or other sources in one query, charts.
- Future: second-pass answer verification, thumbs up/down feedback, golden-question regression suite, starter questions, per-user permissions, hiding tables and columns, SSO, cost and rate limits, response streaming, prompt-injection hardening, non-SQLite engines.
