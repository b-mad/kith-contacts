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
| `app/api.py` | JSON API (`/api/...`); writes require `application/json` |
| `app/web.py` | Server-rendered pages and forms; POSTs need the CSRF token |
| `app/static/js/app.js` | Small vanilla JS enhancements (manager picker, form rows) |
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
make trace PHASE=1           # requirement coverage up to a phase
make migration m="add tags"  # new Alembic migration
```
