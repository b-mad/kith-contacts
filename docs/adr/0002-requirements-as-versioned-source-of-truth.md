# ADR-0002: Requirements as a versioned source of truth

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** all (governance)

## Context

Requirements were first drafted in a shared Claude Doc for stakeholder
review. Code will be written by agents that need a single, current,
machine-readable copy, and requirements will change as the product is used.
Without a process, the doc, the code and the tests drift apart.

## Options considered

1. **Shared doc only** — easy for stakeholders; invisible to agents and CI; no link to code history.
2. **Issue tracker only** — good for work items; poor as a single readable baseline.
3. **Markdown in the repo, changed through ADRs** — versioned with the code, reviewable in diffs, readable by agents.

## Decision

`docs/requirements.md` in this repository is the **source of truth**. The
shared doc is a stakeholder-friendly view and is refreshed from the repo
when requirements change.

Change rules:

| Change type | Examples | What is required |
| --- | --- | --- |
| Clarification | Typo, wording that does not change meaning, added example | Edit in place; add a change-log row; patch version (1.1 → 1.1.1) |
| Minor | New Should/Could requirement; phase moved; acceptance detail tightened | New ADR; update requirements; minor version (1.1 → 1.2) |
| Major | Must requirement added, withdrawn or re-scoped; goal or non-goal changed; data store or stack changed | New ADR approved by the product owner before code; minor or major version (1.x → 2.0 when the MVP scope changes) |

Traceability rules:

- Requirement IDs (`C-01`, `S-03`, `I-02`, …) are permanent. Never renumber or reuse; a dropped requirement is marked **Withdrawn (ADR-NNNN)**.
- New IDs take the next number in their group.
- Commit messages and pull requests name the requirement IDs they implement (`feat(contacts): add manager picker [C-07]`).
- Tests that verify a requirement carry `@pytest.mark.req("C-07")`; `make trace` reports which requirements have tests.
- A phase is complete only when every Must requirement in it has at least one passing test marked with its ID.

## Consequences

- Requirement history is visible in `git log docs/requirements.md` and the ADR index.
- Agents always read one file; conflicts between code and requirements are resolved by changing one of them explicitly, never silently.
- Small overhead per change (one ADR), accepted as the price of traceability.
