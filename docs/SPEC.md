# AskDB: Specification (v1)

## 1. Summary
AskDB is a read-only, ask-and-answer web app for non-technical business staff. A user asks a question in plain English about a SQLite database. They get back a written answer, a result table and a plain-English account of how the answer was worked out. Follow-up questions refine earlier answers in the same thread.

## 2. Decisions from the interview
| Area | Decision |
|---|---|
| Database engine | SQLite only |
| Data access | Server-side file path or `sqlite:///` URL, opened live (not a snapshot). Multiple databases are registered; the user picks one per thread. |
| Scale assumption | Under 30 tables and under 1M rows per database. The full schema and glossary go in every prompt. |
| Semantics | Admin-curated schema YAML (descriptions, metrics, date formats, hidden items) |
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
- If a question has two or more plausible readings (for example "revenue" with two glossary definitions), the model returns a clarifying question with 2-4 clickable options plus "Just pick the most likely". Picking that option, or typing a new question instead, makes the model state its assumption and answer.
- If the data cannot answer the question (for example "how are customers feeling?"), the model says so plainly, names what the database does contain, and suggests 2-3 askable rephrasings.
- Out-of-scope requests (writing data, forecasts, advice, cross-source joins) get a polite refusal that says what AskDB can do.

### 4.4 Failures and empty results
- SQL errors are retried automatically, up to 2 times, silently. The model sees the error text.
- After the retries are used up, or on a zero-row result, the user sees a plain message and suggested rephrasings. A zero-row result is reported as "no matching rows" and is not presented as zero unless the query was an aggregate.
- Raw errors are never shown to users. They are kept in the audit log.

### 4.5 Dates
- The app resolves relative dates against the configured IANA timezone and "today", or an admin-set per-database **as-of date** override for snapshot datasets.
- The resolved range always appears in the assumptions banner, for example: "yesterday = 2026-10-27 (Asia/Kolkata)".
- Date column formats come from the YAML (`date_format`, for example `iso8601_text`, `unix_seconds`, `unix_millis`, `custom: %d/%m/%Y`). The model must use SQLite date functions that match the declared format.

### 4.6 CSV export
- Exports exactly the displayed table (at most 1,000 rows), produced by the backend from a re-run of the stored SQL.
- Hidden columns are never included. Cells beginning with `=`, `+`, `-` or `@` are prefixed with `'` to prevent spreadsheet formula injection.
- Each export is recorded in the audit log.

### 4.7 Admin area
1. **Users**: create, disable, reset password, set role.
2. **Databases**: register by path or `sqlite:///` URL, with a display name.
   - The path must resolve under an admin-configured allow-listed directory.
   - The file must exist, open with `mode=ro` and look like a SQLite database.
   - Re-validation runs on every use.
3. **Schema YAML** per database:
   - Upload, validate against a JSON Schema and show a diff against the live database. The diff flags tables and columns in the YAML that are missing from the DB, and DB items with no description.
   - In-browser editing with validation.
   - Version history with rollback.
   - The introspection view shows sample values per column to help the admin write descriptions.
4. **Audit log**: filter by user, database, date and status.
5. **Settings**: timezone, as-of date override, Anthropic model name, step and time caps.

### 4.8 Schema YAML format
```yaml
version: 1
database:
  description: "Order management data for the retail business"
  timezone: Asia/Kolkata        # optional, overrides global
  as_of_date: null              # optional
tables:
  orders:
    description: "One row per customer order"
    hidden: false
    columns:
      order_date: { description: "Date order was placed", date_format: iso8601_text }
      status:     { description: "pending | shipped | cancelled", hidden: false }
      customer_email: { hidden: true }
metrics:
  revenue: "SUM(order_items.quantity * order_items.unit_price) for orders where status != 'cancelled'"
  active_customer: "A customer with at least one non-cancelled order in the last 90 days"
glossary:
  "West region": "customers.region = 'West'"
```
Rules:
- Unknown keys are rejected.
- A table or column that is hidden is omitted from the prompt and from CSV, and any SQL that references it is rejected (section 5.3).

## 5. Architecture

### 5.1 Components
- **Frontend (React + Vite)**: chat UI, admin UI, login.
- **Backend (FastAPI)**: auth, thread API, query orchestration, admin API.
- **App DB (SQLite, separate file)**: users, sessions, threads, turns, databases registry, YAML versions, audit log. Contains no target-database result rows.
- **Target DBs (SQLite files)**: touched only through the read-only query executor.
- **Anthropic API**: SQL generation and answer writing.

### 5.2 Orchestration (per question)
1. Build the system prompt: role, rules, timezone and today's date, and the schema with descriptions, metrics and date formats (hidden items removed).
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
5. Hidden-table and hidden-column enforcement: use the SQLite authorizer callback, deny-listing only the hidden items. This is the only use of the authorizer; it is not a general lockdown.
6. SQLite specifics: set `busy_timeout`; handle `SQLITE_BUSY` by returning a friendly "database is busy, try again" message; open one connection per query (no sharing across threads).
7. Known limit: the backend process itself holds read access to the full DB file. "Restricted data" is only soft, enforced via YAML hidden items and the authorizer.

### 5.4 Auth
- Passwords hashed with argon2 or bcrypt. HTTP-only, same-site session cookie. CSRF protection on mutating routes.
- Login rate limiting.
- The Anthropic API key and secrets live in environment variables only.

## 6. Data model (app DB)
`users(id, email, password_hash, role, disabled, created_at)`,
`databases(id, name, path, created_at)`,
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
- **Hidden items**: queries referencing hidden columns are rejected, and CSV never contains them.
- **Orchestration**: a fixture database with 15-20 sample questions covering lookups, comparisons, rankings, follow-ups, ambiguity, empty results and unanswerable questions. These run against a stubbed LLM in CI, and optionally against the real API manually.
- **Dates**: "yesterday", "this quarter vs last", with timezone and as-of override.
- **Admin**: YAML validation errors, diff display, rollback.
- **Acceptance**: a user can ask a question, get the three outputs, ask a follow-up, and export CSV. An admin can register a DB, upload YAML, and see the audit log.

## 10. Risks and accepted tradeoffs
- **Wrong answers presented as fact (desirable-not-required)**: mitigated only by the glossary, the assumptions banner, visible SQL and numbers sourced from SQL output. There is no second verification pass in v1.
- **Prompt injection via cell values**: ignored in v1. The sample rows returned to the model could contain instructions. Worst case is a misleading answer or hidden-item leakage in text, because the read-only connection prevents writes.
- **No cost limits**: a heavy user or a tool loop could run up API spend. The only brakes are the step cap and the 60s turn cap.
- **Data leaves the network**: question text, schema, glossary and sample rows are sent to the Anthropic API. This needs sign-off for sensitive data.
- **Light SQLite protection**: it relies on `mode=ro`, the statement check and the timeout. The authorizer is used only for hidden items. A bug in the statement check is bounded by `mode=ro`.
- **Live-DB contention**: a writer process may hold locks. WAL mode is recommended on the source DB; the app cannot set it.
- **Stale threads**: reopening an old thread re-runs SQL, so numbers may differ from the saved answer.
- **YAML burden**: answer quality depends on the admin writing good metrics and date formats.

## 11. Out of scope (v1) and future work
- Out of scope: writing or editing data, saved dashboards, scheduled reports, forecasting and advice, combining databases or other sources in one query, charts.
- Future: second-pass answer verification, thumbs up/down feedback, golden-question regression suite, starter questions, per-user permissions, SSO, cost and rate limits, response streaming, prompt-injection hardening, non-SQLite engines.
