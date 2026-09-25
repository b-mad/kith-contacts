# Contact Manager — Requirements

| Field | Value |
| --- | --- |
| Version | 1.4 |
| Status | Baselined |
| Owner | Bryan Madsen (product owner) |
| Last updated | 2026-09-24 |
| Change process | [ADR-0002](adr/0002-requirements-as-versioned-source-of-truth.md) |

> **This file is the source of truth for what the application must do.**
> Every code change must trace to one or more requirement IDs below. Changes to
> this file follow ADR-0002: clarifications are edited in place and logged in the
> [Change log](#change-log); anything that adds, removes, re-scopes or
> re-prioritizes a requirement needs a new ADR in `docs/adr/`.
> Requirement IDs are permanent — never renumber or reuse them. A dropped
> requirement is marked **Withdrawn (ADR-NNNN)**, not deleted.

## 1. Overview

Build a locally hosted, browser-based contact manager that lets a product
manager find the right person by context — team, manager, project, topic,
tag — even when the name is forgotten.

**Problem.** A PM works across employees, customers and vendors. Names fade;
context sticks ("the data engineer on Maria's team who owns the lab-results
pipeline"). Standard address books search by name, so recall fails at the
moment of need.

**Goals**

- Find a person in under 15 seconds from partial context (team, manager, project, tag, company, notes).
- Group people into project lists that carry context over time.
- Go from a selected group to a drafted email (or Slack/Teams message) in two clicks.
- Keep all data local, private and backed up, in separate instances for business, personal and development use.

**Non-goals (v1)**

- Multi-user sharing, cloud sync or mobile apps.
- Sending email from the app — it hands off to the user's mail client.
- Full sales CRM features (deal pipelines, forecasting).

**Success metrics**

| Metric | Target |
| --- | --- |
| Context search finds the intended person in top 5 results | ≥ 90% of searches |
| Time from "who was that?" to contact card | < 15 s |
| Time from project list to email draft with all recipients | < 10 s |
| Contacts with at least one context field (team, manager, project or tag) | ≥ 80% |

## 2. Market research summary

No public tool combines org-context search (team, manager, project) with
personal lists and local hosting. Features adopted from existing products:

| Source | Adopted idea | Requirement(s) |
| --- | --- | --- |
| [Sift](https://www.justsift.com/integrating-sift/with-microsoft-teams) | Search by attribute "even when you don't know someone's name" | S-01–S-03 |
| [Microsoft 365 profile card](https://support.microsoft.com/en-gb/office/profile-cards-in-microsoft-365-e80f931f-5fc4-4a59-ba6e-c1e35a85b501) | Manager and reporting chain on the card; private notes | C-07, C-08, S-06 |
| [Google Contacts labels](https://support.google.com/contacts/answer/30970) | Email a whole group | L-01–L-04, M-02 |
| [Dex](https://getdex.com/blog/personal-crm-list/) | "How we met" context; keep-in-touch reminders (future) | C-08 |
| [Monica](https://github.com/monicahq/monica) | Labels, favorites, custom fields, activity log, self-hosting | T-01, C-10, C-11, C-13 |
| Sift / M365 | Photo and name pronunciation as memory cues | C-09 |

## 3. Personas and user stories

| Persona | Relationship | What the PM usually remembers |
| --- | --- | --- |
| Internal employee | Same company | Team, manager, what they work on, a meeting or project |
| Customer | External, buys from us | Company, role, account/project, last conversation |
| Vendor | External, we buy from them | Company, product/service provided, contract or integration |

1. **US-1 Recall by context** — I type "lab results pipeline Maria" and see the engineer on Maria's team who owns that work.
2. **US-2 Browse the org** — I open a manager and see their direct reports.
3. **US-3 Project list** — I create "Q4 LIS integration" and add the vendor PM, two engineers and the customer sponsor, each with a role note.
4. **US-4 Tag discovery** — I click tag `HL7` and see everyone tagged `HL7` or related tags.
5. **US-5 Start a conversation** — I select five people, click **Copy emails**, and paste into Outlook; or click **Open in mail** for a `mailto:` draft.
6. **US-6 Reach on chat** — From a card I click Slack or Teams to open a direct message.
7. **US-7 Capture fast** — After a meeting I add a person with only a name fragment, company and a note.

## 4. Functional requirements

Priority uses MoSCoW (Must / Should / Could). Phase maps to §8.

### Contacts

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| C-01 | Create, view, edit and archive a contact. Only a display name is required. | Must | 1 |
| C-02 | Zero or more email addresses per contact, each with a label (work, personal) and one marked primary. | Must | 1 |
| C-03 | Zero or more phone numbers per contact, each with a label. | Must | 1 |
| C-04 | Optional Slack handle and Slack DM link; optional Microsoft Teams chat link (`https://teams.microsoft.com/l/chat/0/0?users=<email>`), generated from the primary email when blank. Both Slack and Teams actions are shown on every card. | Must | 1 |
| C-05 | Contact type is one of Employee, Customer, Vendor by default; the list is configurable per instance (e.g. Family, Friend for a personal instance). | Must | 1 |
| C-06 | Organization fields: company, title, team, department, location. | Must | 1 |
| C-07 | Manager link to another contact; card shows manager and direct reports. Manager cycles are rejected. | Must | 1 |
| C-08 | "Works on" free-text field plus a notes field (how we met, memory cues). | Must | 1 |
| C-09 | Optional photo and name-pronunciation text as memory aids. | Should | 3 |
| C-10 | Mark contact as favorite. | Should | 2 |
| C-11 | Custom fields (key/value) per contact. | Could | 4 |
| C-12 | Detect and merge likely duplicates (same email or similar name + company). | Should | 4 |
| C-13 | Activity log: dated interaction notes (meeting, call, email). | Could | 4 |
| C-14 | Company is chosen from a dropdown of existing companies, with "+ Add new company…"; a new name matching an existing one (ignoring case) reuses its spelling. A new Employee defaults to the home company (`HOME_COMPANY`, else the most common Employee company) (ADR-0009). | Must | 2 |

### Search and discovery

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| S-01 | One search box matches across name, email, company, title, team, manager name, "works on", notes, tags and list names — and, from Phase 4, custom field values and activity summaries (ADR-0012). | Must | 2 |
| S-02 | Results rank by relevance and show the matching context (e.g. "team: Data Platform · manager: Maria Lopez"). | Must | 2 |
| S-03 | Prefix and typo-tolerant matching ("lab res", "Mria"). | Must | 2 |
| S-04 | Filters: contact type, company, team, manager, tag, list; combinable. | Must | 2 |
| S-05 | Results update as you type (< 200 ms). | Must | 2 |
| S-06 | Org view: pick a manager and browse reports, up and down the chain. | Should | 3 |
| S-07 | Saved searches (e.g. "Vendors tagged HL7"). | Could | 4 |
| S-08 | Natural-language or semantic search ("the person who helped with the FDA submission"). | Could | 5 |

### Tags

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| T-01 | Add and remove any number of free-form tags per contact, with autocomplete from existing tags. | Must | 2 |
| T-02 | Click a tag to list every contact with it. | Must | 2 |
| T-03 | "Related contacts" on a card: others ranked by shared tags, team, company and lists. | Should | 3 |
| T-04 | Tag management: rename, merge, delete, optional color. | Should | 3 |
| T-05 | Related tags: tags that frequently co-occur, shown beside a tag's results. | Could | 4 |

### Project lists

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| L-01 | Create, rename, describe and archive lists (e.g. per project). | Must | 2 |
| L-02 | Add or remove contacts from a list, from the card, search results or bulk selection. A contact can be in many lists. | Must | 2 |
| L-03 | Per-membership role note ("customer sponsor", "vendor PM"). | Should | 2 |
| L-04 | List view shows members with type, company, role and contact methods. | Must | 2 |
| L-05 | Lists can carry tags and a status (active / archived). Status delivered in Phase 2; list tags moved to Phase 4 (ADR-0011). | Could | 4 |

### Communication

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| M-01 | Multi-select contacts in any view (search, list, tag, org). | Must | 2 |
| M-02 | **Copy emails**: copies primary emails of selected contacts to the clipboard, skipping contacts without email and saying how many were skipped. With more than one contact the user chooses **Outlook** (semicolon-separated) or **Gmail** (comma-separated); the last choice is remembered (ADR-0009). | Must | 2 |
| M-03 | **Compose**: opens a new message to the selected recipients in **Gmail**, **Outlook on the web** or the **default mail app** (`mailto:`), with a To / Cc choice (ADR-0009). | Should | 2 |
| M-04 | One-click Slack DM, Teams chat, `tel:` and `mailto:` on each card. | Must | 1 |
| M-05 | Teams group chat link for selected contacts (`users=a@x.com,b@y.com`). | Could | 3 |

### Data in and out

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| D-01 | Import contacts from CSV with column mapping and preview. | Should | 3 |
| D-02 | Import and export vCard (.vcf). | Should | 3 |
| D-03 | Export all data (contacts, tags, lists) to CSV and JSON. | Must | 3 |
| D-04 | One-click backup and restore of the instance's database (`pg_dump` / `pg_restore`). | Must | 3 |
| D-05 | Optional directory sync from Microsoft Graph or Slack to prefill employees (title, manager, team). | Could | 5 |

### Instances and environments

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| I-01 | All instance-specific settings come from an env file; no code changes to add an instance. | Must | 0 |
| I-02 | Each instance uses its own database and database user; one instance cannot read another's data. | Must | 0 |
| I-03 | Header shows instance name and color; production and development look clearly different. | Must | 1 |
| I-04 | Migrations run automatically on start, per instance; a production instance refuses to start if a migration fails. | Must | 0 |
| I-05 | Seed and reset commands are blocked when `APP_ENV=production`. | Must | 1 |
| I-06 | Nightly `pg_dump` per production instance with 14-day retention to a local folder (`BACKUP_DIR`); restore command per instance. | Must | 3 |
| I-07 | Copy a production database into dev (optionally anonymized) to reproduce issues. | Should | 3 |
| I-08 | Contact types are configurable per instance from the settings page. | Should | 3 |
| I-09 | Move or copy a contact between instances via export/import (vCard or JSON). | Could | 4 |

**Standard instance set**

| Instance | Purpose | Database | Port | `APP_ENV` |
| --- | --- | --- | --- | --- |
| business-prod | Work contacts | `contacts_business_prod` | 5170 | production |
| personal-prod | Friends, family, personal services | `contacts_personal_prod` | 5171 | production |
| dev | Building and testing features | `contacts_dev` | 5180 | development |
| test | Automated tests | created and dropped per run | — | test |

## 5. Non-functional requirements

| ID | Area | Requirement |
| --- | --- | --- |
| N-01 | Hosting | PostgreSQL runs locally in Docker; each app instance starts with one command and serves at `http://localhost:<port>`. Binds to 127.0.0.1 by default; LAN access is opt-in. |
| N-02 | Platforms | Runs on macOS, Windows and Linux with Docker Desktop; works in current Chrome, Edge, Safari and Firefox. |
| N-03 | Performance | Search returns in < 200 ms and pages load in < 1 s with 10,000 contacts per instance. |
| N-04 | Privacy | No telemetry, no third-party calls at runtime; all assets bundled. Database port 5432 is not exposed beyond localhost. |
| N-05 | Security | One database user per instance with rights only to its own database; credentials in env files excluded from git. Optional UI passcode per instance. Validate and escape all input; CSRF protection on writes. |
| N-06 | Durability | Nightly `pg_dump` per production instance, 14-day retention, stored in a local folder outside Docker volumes; restore tested in CI. |
| N-07 | Clipboard | Copy uses the browser Clipboard API (works on `localhost` as a secure context); a fallback shows the text to copy manually. |
| N-08 | Email hand-off | `mailto:` links stay under ~2,000 characters; above that the app falls back to Copy emails and says why. |
| N-09 | Usability | Keyboard-first: `/` focuses search, arrow keys move, space selects, `c` copies emails. Readable at 200% zoom; meets WCAG 2.2 AA contrast. |
| N-10 | Maintainability | Typed Python (type hints checked by mypy, Pydantic models), versioned migrations, ≥ 80% test coverage overall and on search and list logic. |
| N-11 | Portability | Full export to open formats (CSV, JSON, vCard) per instance so data is never locked in. |

## 6. Data model

| Table | Key fields | Notes |
| --- | --- | --- |
| `contact_type` | id, name (unique), sort_order | Per-instance list seeded from `CONTACT_TYPES` (C-05, I-08). |
| `contact` | id, display_name\*, first_name, last_name, nickname, contact_type_id → contact_type, company, title, team, department, location, manager_id → contact, works_on, notes, slack_handle, slack_url, teams_url, pronunciation, is_favorite, archived_at, created_at, updated_at | \* required. `manager_id` nullable; no self-reference; cycles rejected in app logic. |
| `contact_email` | id, contact_id, email, label, is_primary | Unique (contact_id, lower(email)); at most one primary per contact. |
| `contact_photo` | contact_id, content_type, data, updated_at | Phase 3. ≤ 512 px, EXIF stripped; stored in the database so backups include it (ADR-0011). |
| `contact_phone` | id, contact_id, number, label | Stored as E.164 when parseable, using the instance's `PHONE_REGION` (ADR-0008). |
| `tag` | id, name (unique, case-insensitive), color | Phase 2. |
| `contact_tag` | contact_id, tag_id | Phase 2. Composite key. |
| `contact_list` | id, name, description, status, created_at | Phase 2. The "project list". |
| `list_member` | list_id, contact_id, role_note, added_at | Phase 2. Composite key. |
| `custom_field` | id, contact_id, name, value, sort_order | Phase 4 (C-11). Unique (contact_id, lower(name)). |
| `activity` | id, contact_id, kind, occurred_on, summary, created_at | Phase 4 (C-13). kind ∈ meeting, call, email, message, note. |
| `saved_search` | id, name (unique, case-insensitive), query, created_at | Phase 4 (S-07). `query` is a whitelisted query string. |
| `list_tag` | list_id, tag_id | Phase 4 (L-05). Composite key. |
| `duplicate_dismissal` | contact_a, contact_b | Phase 4 (C-12). Pairs marked "not a duplicate"; a < b. |
| `contact_merge` | id, kept_id, merged_name, snapshot (jsonb), merged_at | Phase 4 (C-12). Snapshot of each contact removed by a merge. |
| `contact.search_vector` | Weighted tsvector: name (A); team, company, manager, tags (B); title, department, works_on, lists, emails, custom fields (C); notes, location, activities (D) | Maintained by the application (`app/search.py`, ADR-0010); GIN index; plus `pg_trgm` GIN index on names. |

Each instance has its own database, so no table carries an instance column.

## 7. Architecture

Decisions are recorded as ADRs — see [docs/adr/README.md](adr/README.md).

- **Data store:** PostgreSQL 17 with `pg_trgm` (ADR-0003).
- **Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 + psycopg 3, Alembic, Pydantic, Jinja + HTMX + Alpine.js, pytest + Playwright, `uv` (ADR-0004).
- **Instances:** one PostgreSQL server, one database + role per instance, one env file per instance (ADR-0005).
- **Quality:** tests run against real PostgreSQL; CI gates every change (ADR-0006).

## 8. Implementation phases

| Phase | Goal | Requirements | Estimate |
| --- | --- | --- | --- |
| 0 — Foundation ✅ | Repo, PostgreSQL, instance config; dev instance on localhost | N-01, N-02, N-10, I-01, I-02, I-04 | 3–4 days |
| 1 — Contact core ✅ | Store and edit rich contacts | C-01–C-08, M-04, I-03, I-05 | 1 week |
| 2 — Find and act (MVP) ✅ | Context search, tags, lists, copy emails | S-01–S-05, T-01–T-02, L-01–L-04, M-01–M-03, C-10, C-14 | 2 weeks |
| 3 — Daily-driver ✅ | Production instances; org view, import/export, backups | S-06, T-03–T-04, C-09, M-05, D-01–D-04, N-06, I-06–I-08 | 1–2 weeks |
| 4 — Depth ✅ | Power-user features | C-11–C-13, S-07, T-05, L-05 (list tags), I-09 | 1–2 weeks |
| 5 — Smart | Semantic search and directory sync | S-08, D-05 | 2+ weeks |

### Phase 0 — Foundation

- Repo layout: `app/`, `migrations/`, `instances/` (git-ignored env files + committed `example.env`), `docker-compose.db.yml`, `run.sh`.
- PostgreSQL 17 in Docker with `pg_trgm`; a bootstrap script creates a database and dedicated role per instance.
- Config loader reads the instance env file; the app refuses to start if required settings are missing.
- Migrations run on start; first migration creates the Phase 1 tables.
- Dev instance with hot reload; test database created and dropped by the test runner.
- CI: lint, type check, tests against a throwaway PostgreSQL, Playwright smoke test.

**Done when:** `./run.sh dev` serves `http://localhost:5180` with an empty contact list; a second instance from another env file runs side by side on its own port and database; CI passes.

### Phase 1 — Contact core

- REST API: `GET/POST /api/contacts`, `GET/PATCH/DELETE /api/contacts/{id}` (delete = archive), nested emails and phones.
- Contact form and card with all fields, `mailto:`, `tel:`, Slack and Teams links; manager and direct reports as links.
- Contact list page with sort and a type filter.
- Seed script (~50 sample contacts), blocked in production.

**Done when:** a vendor with no email or phone and an employee with two emails and a manager can be created; the manager's card lists the employee as a direct report; manager cycles are rejected.

### Phase 2 — Find and act (MVP)

- Weighted `search_vector` + GIN index (maintained by the app, ADR-0010); `pg_trgm` index on names; `GET /api/search?q=&type=&tag=&list=&company=&team=&manager=`.
- Ranking with `ts_rank`; `pg_trgm` similarity fallback; each hit returns the matched fields.
- Global search bar with instant results and filter chips; tags with autocomplete; lists with role notes.
- Multi-select with a sticky action bar: Copy emails (Outlook or Gmail), Compose (Gmail, Outlook on the web, mail app), Add to list, Add tag.
- Company dropdown with “+ Add new company…”; new employees default to the home company (C-14).

**Done when:** with seed data, "data platform maria" puts the right engineer in the top 3; selecting 5 list members (1 without email) copies 4 addresses and reports "1 skipped".

### Phase 3 — Daily-driver

- `business-prod` and `personal-prod` instances live; nightly `pg_dump` with 14-day retention to a local folder; restore; prod → dev copy.
- Org view; related contacts; tag and contact-type admin; CSV / vCard / JSON import-export; photo and pronunciation; Teams group chat.

**Done when:** both production instances run at once with no shared data; a 500-row CSV imports in under 10 s; a restored backup reproduces every contact, tag and list.

### Phase 4 — Depth

- Custom fields in the contact form; activity log on the card; duplicate finder and side-by-side merge; saved searches as chips; related tags beside a tag's results; tags on lists; per-contact JSON export and JSON import for moving people between instances (ADR-0012).

**Done when:** two contacts sharing an email appear on the duplicates page and merge into one that keeps every email, tag, list and activity; "met at HIMSS" finds a person by an activity note; a contact exported from `dev` imports into another instance with its custom fields and activities.

### Phase 5 — Smart

- Local semantic search with `pgvector` and a local embedding model; optional Microsoft Graph / Slack directory sync with review before overwrite.

## 9. Open questions

- [x] Build language → Python (ADR-0004).
- [x] Slack or Teams → both are used; both actions on every card (ADR-0007).
- [x] Backup location → local folder for now, `~/ContactsBackups/<instance>` (ADR-0007).
- [x] Default mail client → both are used; the user chooses Outlook or Gmail when copying or composing (ADR-0009).
- [ ] Is any contact data subject to company data-handling policy? Affects where the business instance may run.
- [ ] Is a directory export (Outlook / Entra ID CSV) available to seed the business instance in Phase 3?

## 10. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Data entry burden | High | Quick-add form; CSV/vCard import (Phase 3); directory sync (Phase 5) |
| Working in the wrong instance | Medium | Instance name and color band; seed/reset blocked in production (I-03, I-05) |
| Database lost or corrupted | High | Nightly `pg_dump` outside Docker (N-06); open-format export (N-11) |
| Docker Desktop not running | Medium | PostgreSQL container `restart: unless-stopped`; start Docker at login |
| Org data goes stale | Medium | "Last verified" date; archive instead of delete |
| Customer/vendor personal data on a laptop | Medium | Local-only, per-instance DB roles, disk encryption, optional passcode (N-05) |

## Change log

| Version | Date | Change | ADR |
| --- | --- | --- | --- |
| 1.4 | 2026-09-24 | Phase 4 delivered. S-01 clarified: custom fields and activity summaries are searchable. Data model gains custom_field, activity, saved_search, list_tag, duplicate_dismissal, contact_merge. | 0012 |
| 1.3 | 2026-09-24 | Phase 3 delivered. L-05 list tags moved to Phase 4. Photos stored in the database. Backup tool, daily auto-backup and import/export formats decided. | 0011 |
| 1.2.1 | 2026-09-24 | Phase 2 delivered. Clarified: search document maintained by the application rather than triggers. | 0010 |
| 1.2 | 2026-09-24 | M-02 and M-03 changed: choose Outlook or Gmail when copying or composing to several contacts. C-14 added: company dropdown with add-new and a default for new employees. | 0009 |
| 1.1.1 | 2026-09-24 | Phase 1 delivered. Clarified: phone numbers normalized to E.164 using the instance's `PHONE_REGION`; Slack/Teams links must be https. No requirement added or removed. | 0008 |
| 1.1 | 2026-09-24 | PostgreSQL replaces SQLite; instances (I-01–I-09) added; Python stack chosen; Slack + Teams both required on cards (C-04); backups to local folder (I-06, N-06); contact types configurable per instance (C-05). | 0003, 0004, 0005, 0007 |
| 1.0 | 2026-09-24 | Initial requirements baseline. | 0002 |
