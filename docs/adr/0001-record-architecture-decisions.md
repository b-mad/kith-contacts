# ADR-0001: Record architecture decisions

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** none

## Context

The application will be built largely with AI coding agents over several
phases. Agents and future maintainers need to know not only what was decided
but why, so they do not undo deliberate choices or re-litigate settled ones.

## Decision

Keep lightweight Architecture Decision Records (Michael Nygard format, with a
"Requirements changes" table) in `docs/adr/`, numbered sequentially, one
decision per file. The index and the process live in `docs/adr/README.md`.

## Consequences

- Every significant decision has a short, reviewable record next to the code.
- Accepted ADRs are immutable; change happens by superseding, so history is preserved.
- Agents are instructed (in `CLAUDE.md`) to read relevant ADRs before changing code and to propose a new ADR rather than silently deviating.
