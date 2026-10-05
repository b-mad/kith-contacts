# ADR-0024: Name the product Kith Contacts, everywhere

- **Status:** Accepted (2026-10-05)
- **Date:** 2026-10-05
- **Deciders:** Bryan Madsen
- **Requirements affected:** N-12 added (Phase 13); no existing requirement changes meaning
- **Supersedes:** none. Accepted ADRs (0015, 0016, 0019 and others) keep the old name as history.

## Context

The product is called "Contact Manager", which describes what it is but is not a name: it
cannot be searched for, distinguished from other contact managers, or owned. The source is
going to be published in a public GitHub repository as open source, so the name now also
has to work as a repository, package and image name and should not collide with existing
software.

Candidates were checked on 2026-10-05 against PyPI, npm and web search results for trademark
listings and app stores:

- **Inkling:** `inkling` is taken on PyPI (a "coming soon" placeholder) and npm; INKLING
  trademarks are held by Inkling, Inc. and Inkling Systems, Inc.; an AI model on Hugging Face
  carries the name.
- **Cairn:** taken on PyPI and npm; trademarks held by Cairn Applications, Inc.; an Android
  app and a startup use the name.
- **Hearth:** taken on PyPI and npm; "Hearth AI" appears to be a relationship and network
  product, i.e. the same space.
- **Tether:** taken on npm; trademarks held by Tether LLC and Tether Global Inc; search
  results are dominated by cryptocurrency.
- **Kith:** `kith` is taken on PyPI and npm by unrelated projects; no software contact
  manager of that name turned up; KITH is a well-known apparel brand (a different industry,
  but it crowds search results).

Limits of this check: GitHub repository search was not available, the trademark results were
read as listings and not as filings, and none of this is legal clearance.

The old name is in the UI, the launchers, the start and stop scripts, the bundle, the image
label, the documents, and in names that sit under the data: the Compose project
`contact-manager` (it names the Docker volumes `contact-manager_pgdata`, `_db-secrets`,
`_work-instance`, `_personal-instance`), the `~/ContactManager` folder (`settings.env` and
the backups), the JSON export format `contacts-app/1` and the model cache
`~/.cache/contacts-app/`.

Nobody but the product owner runs the application yet, so these can change now at the cost of
one move of his own install, and not later when others have data under them. Docker cannot
rename a volume, so a renamed Compose project starts each instance with an empty database. That
is not a loss: a new container instance with an empty database restores the newest backup in
its backup folder (I-12, ADR-0019), which is exactly how moving to a new computer already works.

## Options considered

Name:

1. **Keep "Contact Manager"** — no work, but generic and unsearchable.
2. **Inkling** — fits the context-clue idea, but INKLING is already registered by software
   companies and is crowded on both registries.
3. **Kith alone** — short and warm, but KITH search results are apparel.
4. **Kith Contacts** — the descriptor separates it from the apparel brand, makes it findable
   ("kith contacts"), and `kith-contacts` is free on PyPI and npm. Chosen.
5. **Cairn, Hearth, Tether** — more direct overlaps with software and trademark owners (above).

Scope of the rename:

- **A. Rename everything, with a one-time move of the owner's install through the existing
  backup and restore (I-11, I-12).** No migration code, and the public repository carries no
  leftover names. Chosen.
- **B. Rename only what people see; keep the Compose project, data folder, export format
  and model cache.** Avoids the one-time move, but leaves the old name in a public repository
  for good, and only protects installs that do not exist.
- **C. Leave all technical names** — still shows "Contact Manager" to everyone.

## Decision

The product is named **Kith Contacts** and the old name is removed everywhere it is not
history. Pages, launchers, messages, the install guide, the bundle zip and the image title use
the full name; "Kith" alone appears only in running text after the full name. The public
repository is `kith-contacts`.

| Was | Becomes |
| --- | --- |
| Pages, header, Settings and import-help text, `app/container.py` messages | "Kith Contacts" |
| `Start/Stop Contact Manager` (`.command`, `.bat`) and every message in `deploy/` and `scripts/` | `Start/Stop Kith Contacts` |
| `Contact-Manager-<version>.zip`, folder `ContactManager-<version>` | `Kith-Contacts-<version>.zip`, folder `KithContacts-<version>` |
| Compose project `contact-manager` (volumes `contact-manager_*`), tests' `contact-manager-test` | `kith-contacts` (volumes `kith-contacts_*`), `kith-contacts-test` |
| Image `contact-manager:<version>`, `LABEL` title, `make image`, `probe-mounts.sh` | `kith-contacts:<version>` and the same places |
| Data folder `~/ContactManager` (`settings.env`, `Backups/`) | `~/KithContacts` |
| `name = "contacts-app"` in `pyproject.toml` | `kith-contacts` (lock file regenerated) |
| JSON export format `contacts-app/1` | `kith-contacts/1`; import accepts both |
| Model cache `~/.cache/contacts-app/` | `~/.cache/kith-contacts/` (`make model` once more for development) |
| Install guide, operations guide, README, title of `docs/requirements.md` | the new name |

Not changed: applied migrations (their text is history), the text of accepted ADRs, and git
history.

### Moving the existing install (once)

Documented in the operations guide and done by the owner:

1. In the old install, stop making changes, then back up each instance (Settings, or let the
   hourly check run) and stop it with `Stop Contact Manager`.
2. Copy `~/ContactManager` to `~/KithContacts` (the old folder stays as it is).
3. Unzip the new version and start it. Each instance finds its new database empty and restores
   the newest backup (I-12).
4. Check the contacts, photos, lists and activity. Only then remove the old Compose project's
   volumes, the old image and `~/ContactManager`. Until then the old install still works:
   start the previous version's folder.

Changes made after the backup in step 1 are not carried across, so step 1 comes first.

## Consequences

- The product, repository, package, image, folders and export format all carry one name, and
  the public repository has no leftover identifiers.
- The product owner makes one move of his own install, about ten minutes. The old install is
  untouched until he removes it, so it is also the rollback.
- Exports written before the change still import, because import accepts `contacts-app/1`.
  Exports written after it say `kith-contacts/1`; an older build would not read them.
- A rename gets harder once other people have installs. Doing it before the first public
  release is the reason for doing all of it now.
- Not cleared: this ADR is not a trademark clearance. A USPTO search in software classes 9
  and 42, and a check that the GitHub repository name is free, should happen before the
  first public release.
- Follow-up outside this ADR: the repository has no `LICENSE` file; choose a licence (its own
  ADR) before publishing.
- Tests: tag a check `@pytest.mark.req("N-12")` that no template, launcher, script or doc shows
  the old name or old identifiers, except the old export format accepted on import, the
  transition steps in the operations guide, migrations and accepted ADRs. Update
  `tests/test_deploy.py` and `scripts/container_test.py` for the new names. Run
  `make check` and `make container-test`, and rehearse the move on a copy of the real backups
  before deleting anything.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| N-12 | Added: the product is named Kith Contacts everywhere; moving an existing install is the I-12 restore (Phase 13) | — |
