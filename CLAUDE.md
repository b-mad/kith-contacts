# Instructions for coding agents

This file is read automatically by Claude Code and is the contract for any
agent (or person) changing this repository. `AGENTS.md` points here.

## 1. Read before you change anything

1. **`docs/requirements.md`** — the source of truth for behavior. Find the
   requirement IDs (e.g. `C-07`, `S-03`, `I-02`) your task touches and the
   phase they belong to (§8).
2. **`docs/adr/README.md`** and every ADR it lists for the area you are
   touching. Accepted ADRs are binding.
3. The existing tests for the area (`grep -rn 'req("C-07")' tests/`).

If the task is not covered by a requirement, or conflicts with a requirement
or an accepted ADR: **stop and say so**. Propose either a requirement change
or a new ADR (see §3). Do not silently implement behavior that is not in the
requirements, and do not silently deviate from an ADR.

## 2. How to work

- Work in phase order. Do not build features from a later phase unless asked.
- Test first where practical: add or update a failing test tagged with the
  requirement ID, then implement until it passes.
  ```python
  @pytest.mark.req("C-07")
  def test_manager_cycle_is_rejected(client): ...
  ```
- Tests use real PostgreSQL (never mock the database) — ADR-0006.
- Keep changes small and focused; one requirement or fix per commit when possible.
- Schema changes: edit `app/models.py` **and** add an Alembic migration in
  `migrations/versions/` (`make migration m="describe change"`), then review
  the generated file by hand. Migrations must upgrade and downgrade cleanly.
- Never commit secrets. Instance env files (`instances/*.env`) are git-ignored;
  only `instances/example.env` is tracked.
- No runtime calls to third-party services and no CDN assets (N-04). Vendor
  JavaScript into `app/static/vendor/`.
- Seed/reset/destructive commands must refuse to run when `APP_ENV=production` (I-05).
- Keep routes thin: validation in `app/schemas.py`, rules in `app/contacts.py` (or a
  sibling module per area). Every form POST includes `{{ m.csrf() }}`; templates must
  not use inline `style=` or inline `<script>` (blocked by the CSP).
- Any write that changes a contact's name, team, company, title, department, works-on,
  notes, location, manager, emails, tags, list memberships, custom fields or activities
  must call `app.search.refresh_search` for every affected contact (ADR-0010); it also
  marks them for re-embedding (search by meaning, ADR-0013). Changing what goes into the
  search document needs a new migration that rebuilds it.
- Anything that deletes or overwrites data (restore, reset, copy) must take a backup
  first or refuse in production (I-05, ADR-0011). The one exception is merging
  duplicates, which stores a JSON snapshot of the removed contact in `contact_merge`
  instead (ADR-0012). Uploaded files must be closed after reading
  (`await upload.close()`); use Starlette's `UploadFile` for `isinstance` checks.
- Search by meaning (ADR-0013): the app never downloads anything; the model comes from
  `make model` (pinned revision, SHA-256 checked). Tests use `tests/fake_embedder.py`;
  real-model checks are marked `@pytest.mark.model` and run with `make test-model`.
  Anything that copies data for others to see (exports, anonymized copies) must not
  include `semantic_chunk` text or vectors.
- Presenting mode (ADR-0016): anything that shows contact data must go through
  `contacts.to_out` (which redacts) or check `app.privacy.presenting()`. A new field on
  `ContactOut` must be classified in `app/privacy.py`; a new page is covered automatically
  by the canary test in `tests/test_presenting.py`, which must keep passing.
- Browser-only behavior (clipboard, compose links, live search) is tested with
  Playwright in `tests/e2e/`; run `make e2e`.
- Type everything; `mypy --strict` must pass. Prefer small pure functions that
  are easy to unit test.

## 3. When requirements or decisions change

Follow ADR-0002:

| Change | Do this |
| --- | --- |
| Wording clarification only | Edit `docs/requirements.md`, add a change-log row, patch version. |
| New/changed/withdrawn requirement, phase move, new technology | Copy `docs/adr/template.md` to the next number, fill it in (Status: Proposed), update `docs/requirements.md` (version + change-log row naming the ADR), update the ADR index. Ask the product owner to accept before implementing Must-level changes. |

Never renumber or reuse requirement IDs. Withdrawn requirements stay in the
table marked **Withdrawn (ADR-NNNN)**.

## 4. Definition of done (run before every commit)

```bash
make check      # ruff format --check, ruff lint, mypy --strict, pytest + coverage >= 80%
make trace      # shows which requirement IDs have tests
```

A change is done only when:

1. `make check` passes — **run it and read the output; do not claim success without running it**.
2. New behavior has tests tagged `@pytest.mark.req("<ID>")`; bug fixes have a regression test.
3. Requirements / ADRs are updated if behavior or a decision changed.
4. The commit message follows Conventional Commits and names the IDs, e.g.
   `feat(contacts): reject manager cycles [C-07]`.

If PostgreSQL is not running, start it with `make db-up` (Docker) — tests
cannot pass without it. Report test failures honestly; never skip, xfail or
delete a failing test to get a green run unless the requirement was withdrawn.

## 5. Project map

| Path | What |
| --- | --- |
| `app/config.py` | Instance settings loaded from the env file (I-01) |
| `app/db.py` | Engine and session factory |
| `app/models.py` | SQLAlchemy models (data model §6) |
| `app/schemas.py` | Pydantic input/output models and validation rules |
| `app/contacts.py` | Contact business logic — routes stay thin and call this |
| `app/links.py` | Pure helpers for mailto/tel/Slack/Teams links and phone format |
| `app/search.py` | Context search, filters, match context, and `refresh_search` (ADR-0010) |
| `app/tags.py`, `app/lists.py` | Tags (incl. related tags, T-05) and project lists (incl. list tags, L-05) |
| `app/web_lists.py` | Pages for lists and tags |
| `app/backup.py`, `scripts/backup.py` | pg_dump/pg_restore backups, retention, restore, copy-to-dev (ADR-0011) |
| `app/exchange.py`, `app/vcard.py` | CSV/JSON/vCard export; CSV/vCard/JSON import with preview (JSON carries fields, activity, lists and photo between instances, I-09) |
| `app/org.py`, `app/related.py` | Org chart and related-contacts scoring |
| `app/contact_types.py`, `app/photos.py` | Type admin; photo validation/resizing |
| `app/web_admin.py` | Settings, backups, import/export, org, tag/type admin, photo routes |
| `app/activity.py` | Activity log: add/delete dated interactions (C-13) |
| `app/duplicates.py` | Duplicate detection, dismissals and merge with snapshot (C-12) |
| `app/saved_searches.py` | Saved searches: whitelisted query strings (S-07) |
| `app/web_depth.py` | Phase 4 pages: duplicates/merge, saved searches |
| `app/embedder.py` | Local ONNX embedding model loader (S-08) |
| `app/semantic.py` | Search by meaning: chunks, indexing, in-memory vectors, ranking (ADR-0013) |
| `scripts/semantic.py` | `make model` (verified download) and `make reindex` |
| `app/timephrase.py` | Time phrases in the search box ("recently", "last week") → period filter (S-10, ADR-0014) |
| `app/appearance.py` | Theme, palette and density per instance in `app_setting`; contrast helpers (A-01 to A-06, ADR-0015) |
| `app/keep_in_touch.py`, `app/web_kit.py` | Keep-in-touch cadence, due dates, snooze; Reconnect page (C-15 to C-17, S-11, ADR-0016) |
| `app/privacy.py` | Presenting mode: session-level filtering of private records, allowlist redaction of contacts, blocked pages (P-01 to P-07, ADR-0016) |
| `app/web_privacy.py` | `POST /presenting`, Settings › Privacy and presenting, private flags |
| `app/api.py` | JSON API (`/api/...`); writes require `application/json` |
| `app/web.py` | Server-rendered pages and forms; POSTs need the CSRF token |
| `app/static/js/app.js` | Vanilla JS: live search, selection + action bar (copy/compose for Outlook or Gmail), search preview pane and keyboard moves (↑ ↓, space, c), pickers, form rows, ⇧P |
| `app/migrate.py` | Runs Alembic on start-up; fails fast (I-04) |
| `app/main.py` | FastAPI app factory, routes, templates |
| `app/templates/` | Jinja templates (HTMX/Alpine for interactivity) |
| `migrations/` | Alembic migrations |
| `scripts/bootstrap_instance.py` | Creates an instance's database, role and env file (I-02) |
| `scripts/req_trace.py` | Requirement → test traceability report |
| `scripts/seed.py` | Sample data for dev instances; refuses production (I-05) |
| `tests/` | pytest suite; `conftest.py` creates a throwaway database |
| `docs/requirements.md` | Requirements (source of truth) |
| `docs/adr/` | Architecture decision records |

## 6. Common commands

```bash
make install                 # uv sync + pre-commit hooks
make db-up                   # start PostgreSQL in Docker
make instance NAME=dev PORT=5180 ENV=development
./run.sh dev                 # run an instance
make check                   # everything CI runs
make test                    # tests only
make seed I=dev              # sample contacts (dev only)
make trace PHASE=5           # requirement coverage up to a phase
make migration m="add tags"  # new Alembic migration
make model                   # install the search-by-meaning model once
make test-model              # tests with the real model
```
