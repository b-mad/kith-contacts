# Contributing to Kith Contacts

Thank you for helping. This is a small project run by one person, so small, focused changes
that start from an issue or a requirement are easiest to review.

## Licence of contributions

Kith Contacts is licensed under the [Apache License 2.0](LICENSE). By sending a contribution you
agree it is licensed under the same terms (section 5 of the licence). There is no separate
agreement to sign. Do not send code you do not have the right to share.

## How the project works

- [docs/requirements.md](docs/requirements.md) is the source of truth for what the app must do.
  Every change traces to a requirement ID.
- A change that adds, removes or re-scopes a requirement, or changes a decision, needs a short
  architecture decision record in [docs/adr/](docs/adr/README.md) first
  (see [ADR-0002](docs/adr/0002-requirements-as-versioned-source-of-truth.md)).
- Tests come first, and each is tagged with the requirement it covers:
  `@pytest.mark.req("C-07")`.

[CLAUDE.md](CLAUDE.md) has the full rules, including the project map. They apply to people and
to AI coding assistants alike.

## Set up

```bash
make install        # dependencies + git hooks
make db-up          # PostgreSQL 17 (Docker); the tests need a real database
```

## Definition of done

Run this before every commit and read the output:

```bash
make check      # ruff format --check, ruff lint, mypy --strict, pytest with coverage >= 80%
make trace      # shows which requirement IDs have tests
```

A change is done only when:

1. `make check` passes.
2. New behaviour has tests tagged `@pytest.mark.req("<ID>")`; a bug fix has a regression test.
3. The requirements and ADRs are updated if behaviour or a decision changed.
4. The commit message follows Conventional Commits and names the IDs, for example
   `feat(contacts): reject manager cycles [C-07]`.
5. A change to the `Dockerfile`, `compose.yaml` or `scripts/container.py` also passes
   `make container-test`.
6. A new bundled font, library, outline or data set has an entry in
   [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES) (a test checks this).

Never skip, disable or delete a failing test to get a green run.

## Keep real data out

Use made-up people and `.example` addresses (for example `ada@lovelace.example`) in tests, docs and
sample data. Never commit real contacts, backups, `.env` files or screenshots that show them.

## Pull requests

Fill in the pull request template. Describe what changed and why, and name the requirement IDs.
By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
