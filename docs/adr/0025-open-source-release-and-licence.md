# ADR-0025: Publish as open source under the Apache License 2.0

- **Status:** Accepted (2026-10-05)
- **Date:** 2026-10-05
- **Deciders:** Bryan Madsen
- **Requirements affected:** N-13 added (Phase 14); no existing requirement changes meaning
- **Supersedes:** none

## Context

The product owner plans to publish Kith Contacts in a public GitHub repository as open
source (ADR-0024 chose the name). Two things have to be decided before the first push: the
licence, and whether the repository is fit to be public. Both are permanent once the code is
visible, so this ADR records the audit that was run on 2026-10-05 and the checks that remain.

What the audit found:

- **Secrets and personal data:** none. No key or token pattern in the files or in any of the 40
  commits; no `.env`, dump, CSV or vCard file was ever committed (`instances/*.env` is ignored;
  only `instances/example.env` is tracked); no home path or practice name appears in the files of any revision. Sample data uses made-up people at `.example` addresses.
- **Small leaks to clean:** all 40 commits carry the author's practice email address, which would become public with the history. A few tests
  and docs use real-looking domains (`acme.com`, `home.com`, `labco.com`, `x.io`), and
  `scripts/seed.py` names a made-up office "Buford Family Medicine" at "12 Main St", which reads
  as a real business in a real town.
- **Dependency licences:** 51 runtime packages, nearly all MIT, BSD, Apache-2.0, ISC or PSF.
  Exceptions: `psycopg` and `psycopg-binary` (LGPL-3.0), `pycountry` (LGPL-2.1), `certifi` and
  `tqdm` (MPL-2.0). All four are used as separate libraries, which any licence for this code
  permits. No GPL or AGPL package is present, so nothing forces a copyleft licence. Dev-only:
  `axe-playwright-python` reports no licence in its metadata (check upstream before release),
  `pathspec` is MPL-2.0.
- **Bundled assets:** Leaflet (BSD-2-Clause), Leaflet.markercluster (MIT), topojson-client
  (ISC), us-atlas and world-atlas (outlines from US Census and Natural Earth, public domain) and
  the Atkinson Hyperlegible Next font (SIL OFL 1.1) all ship with their licence files. Two do
  not: the city list `app/data/world_cities.tsv.gz` and the `zipcodes` package data both come
  from GeoNames (CC BY 4.0), which requires attribution that the repository does not yet give.
  The search model (`all-MiniLM-L6-v2`) is downloaded, hash-pinned and not committed; its
  upstream licence is Apache-2.0, to be confirmed at the pinned revision and listed in the
  notices because the container image contains it.
- **Project files:** the repository has a pull-request template and a CI workflow, but no
  `LICENSE`, no third-party notices, and no `SECURITY`, `CONTRIBUTING` or `CODE_OF_CONDUCT`
  file. The README's status paragraph still describes Phase 5.

The application keeps data on the user's own computer, makes no runtime calls to third parties
(N-04) and is single-user, so it is a tool people run themselves, not a service others host.

## Options considered

1. **Apache-2.0** — permissive; an explicit patent grant from every contributor; contributions
   come in under the same licence (section 5) without a separate CLA; section 6 says the licence
   grants no rights to the name "Kith Contacts". Cost: redistributors must carry a NOTICE, and
   anyone may fork it closed-source. Chosen.
2. **MIT** — the shortest and most familiar permissive licence, with the same adoption benefits.
   No patent grant and no statement about the name.
3. **AGPL-3.0 or GPL-3.0** — keeps every fork open. For a local single-user tool the network
   clause protects little, many companies (including in healthcare) will not run AGPL software,
   and it lowers the chance of outside contributions.
4. **Stay private** — no exposure, no community, and the work cannot be reused by others.

Authors' history before the first push:

- **Publish the history as it is** — keeps the commit record, exposes the practice email.
- **Rewrite author addresses to a GitHub no-reply address first** (`git filter-repo --mailmap`
  on a fresh clone) — safe now, since nothing is public and no one else has a clone.
  Chosen. Hashes change, so the ADRs and docs must not cite commit hashes.

## Decision

Publish the repository publicly under the **Apache License 2.0**, with copyright held by Bryan
Madsen and the name "Kith Contacts" reserved by a short trademark note in the README. Before the
first push:

1. Add `LICENSE` (Apache-2.0) and `NOTICE`, and a `THIRD_PARTY_NOTICES` file listing every
   bundled font, library, outline and city and ZIP data set, and the downloaded model, with its
   licence and required attribution (GeoNames CC BY 4.0 included). Add an "About" line in
   Settings that points to it.
2. Add `SECURITY.md` (private vulnerability reporting through GitHub, supported version),
   `CONTRIBUTING.md` (the definition of done in `CLAUDE.md`; contributions are licensed under
   Apache-2.0), and `CODE_OF_CONDUCT.md` (Contributor Covenant).
3. Rewrite the README for a stranger: what it is, a screenshot, install, the privacy stance
   (data stays on your computer; no telemetry), and a notice that it is a personal contact
   tool, not validated for regulated health information. Remove the phase status paragraph.
4. Clean the repository: replace real-looking domains in tests and docs with `.example`, and
   rename the made-up office in `scripts/seed.py`.
5. Rewrite the author address on a fresh clone and push that clone, not this one.
6. Check the open items that only the owner can: the repository name `kith-contacts` is free on
   his account, a USPTO search in software classes 9 and 42, the licence of
   `axe-playwright-python`, and his employer's invention-assignment and outside-work policy
   (a written yes if there is any doubt).
7. Turn on GitHub secret scanning with push protection, Dependabot alerts, private
   vulnerability reporting and branch protection for `main`.

## Consequences

- Anyone may use, change and redistribute the code, including in closed products; the project
  keeps the right to its name and gets contributors' patent grants. To forbid closed forks, the
  alternative is AGPL-3.0, at the costs listed above.
- Redistributing the container image or the install zip means shipping `LICENSE`, `NOTICE` and
  the third-party notices with it (the bundle must include them).
- Parts of the code were written with an AI assistant. US copyright protects human authorship,
  so some passages may not be protectable. The licence still applies to everything. This is not
  legal advice.
- Once public, history cannot be reliably withdrawn, so steps 4 and 5 happen first.
- Ongoing: a new bundled asset needs a notice entry in the same change (checked by a test); the
  dependency licence list is re-run before each release.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| N-13 | Added: Apache-2.0 release with notices, project files and a clean history (Phase 14) | — |
