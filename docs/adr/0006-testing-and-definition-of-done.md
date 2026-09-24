# ADR-0006: Testing strategy and definition of done

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** N-10

## Context

Most code will be written by AI agents. Tests are the main guard against
regressions and against code that drifts from the requirements. Search and
isolation behavior are PostgreSQL-specific, so mocks would hide real bugs.

## Decision

**Test layers**

| Layer | Tool | Scope | Database |
| --- | --- | --- | --- |
| Unit | pytest | Pure functions (config parsing, link builders, ranking helpers) | none |
| Integration | pytest + FastAPI `TestClient` | API routes, models, migrations, isolation | real PostgreSQL, fresh database per test session, rolled-back transaction per test |
| End-to-end | Playwright for Python (`-m e2e`) | One test per user story once its UI exists | real PostgreSQL |

**Rules**

- Test-first where practical: write or update the failing test, then the code.
- Never mock the database. The test suite creates a throwaway database, runs every migration, and drops it afterwards.
- Every requirement test carries `@pytest.mark.req("<ID>")`.
- Migrations are tested: upgrade to head, downgrade to base, upgrade again; models and migrations must not drift (autogenerate diff is empty).
- Coverage ≥ 80% overall (enforced by `pytest --cov-fail-under=80`).

**Definition of done** for any change:

1. `make check` passes locally: Ruff format check, Ruff lint, mypy strict, full pytest suite with coverage.
2. New behavior has tests tagged with requirement IDs; bug fixes have a regression test.
3. `docs/requirements.md` and ADRs updated if behavior or decisions changed (ADR-0002).
4. Commit message follows Conventional Commits and names requirement IDs.
5. CI (GitHub Actions, PostgreSQL service container) is green.

## Consequences

- Contributors need PostgreSQL available locally (`make db-up`) to run tests; the suite fails fast with a clear message if it is not.
- Slightly slower tests than mocks, in exchange for testing real search and isolation behavior.
