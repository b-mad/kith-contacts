# Kith Contacts — Requirements

| Field | Value |
| --- | --- |
| Version | 1.20 |
| Status | Baselined |
| Owner | Bryan Madsen (product owner) |
| Last updated | 2026-10-06 |
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
| [Dex](https://getdex.com/blog/personal-crm-list/) | "How we met" context; keep-in-touch reminders | C-08, C-15–C-17, S-11 |
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
| C-01 | Create, view, edit and archive a contact. Only a display name is required. The card shows the first and last name and nickname wherever they differ from the display name. | Must | 1 |
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
| C-15 | Keep-in-touch cadence per contact (every 2 weeks, month, 3 months, 6 months or year; off by default), set on the card or for a selection. Due = last interaction (meeting, call, email or message) + cadence (ADR-0016). | Should | 7 |
| C-16 | Snooze a keep-in-touch reminder to a date; logging an interaction clears the snooze. | Should | 7 |
| C-17 | After Email, Call or Compose from the app, offer one-click logging of that interaction. | Could | 7 |
| C-18 | Optional LinkedIn profile per contact, entered as a profile URL or name and stored as `https://www.linkedin.com/in/<name>`; a LinkedIn action on the card and search preview opens it in a new tab; CSV import (including LinkedIn's Connections export), vCard and JSON carry it (ADR-0018). | Should | 8 |
| C-19 | Zero or more postal addresses per contact, each with a label (home, work…), street, city, state or region, postal code and country. The country is stored with its ISO 3166-1 code and the state as its ISO 3166-2 code where recognised; an address with a state but no country takes the instance's home country when the state belongs to it. Shown on the card, editable on the form, searchable by city, state, postal code and country, and carried by CSV, vCard and JSON import and export (ADR-0021). | Should | 10 |
| C-20 | Optional birthday per contact, with or without the year, stored as `YYYY-MM-DD` or `--MM-DD`; typed or imported dates are read in common forms (ISO, month names, slashed dates in the instance's order); shown on the card with the age; carried by CSV, vCard and JSON (ADR-0022). | Should | 11 |
| C-21 | Reconnect lists birthdays in the next 14 days, today first, with the age they turn; 29 February falls on 28 February in other years (ADR-0022). | Should | 11 |
| C-22 | Each address is placed from offline data when saved: latitude, longitude, IANA time zone and how precisely it was placed (ZIP, city, state, country), US ZIP first; existing addresses are placed at start-up (ADR-0023). | Should | 12 |
| C-23 | The card, search preview and search results show a contact's local time and time zone (from their first placed address), how far ahead or behind the viewer it is, and whether it is a good time to reach them (working hours, edges of the day, night or weekend) in words, not color alone (ADR-0023). | Should | 12 |

### Search and discovery

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| S-01 | One search box matches across name, email, company, title, team, manager name, "works on", notes, tags and list names — and, from Phase 4, custom field values and activity summaries (ADR-0012). | Must | 2 |
| S-02 | Results rank by relevance and show the matching context (e.g. "team: Data Platform · manager: Maria Lopez"), with the matched words highlighted (ADR-0017). | Must | 2 |
| S-03 | Prefix and typo-tolerant matching ("lab res", "Mria"). | Must | 2 |
| S-04 | Filters: contact type, company, team, manager, tag, list; combinable. | Must | 2 |
| S-05 | Results update as you type (< 200 ms). | Must | 2 |
| S-06 | Org view: pick a manager and browse reports, up and down the chain. | Should | 3 |
| S-07 | Saved searches (e.g. "Vendors tagged HL7"). | Could | 4 |
| S-08 | Natural-language or semantic search ("the person who helped with the FDA submission"), using a local model; results show the text that matched (ADR-0013). | Could | 5 |
| S-09 | Filter by recent interaction (contacted in the last 7, 30, 90 or 365 days, from the activity log; notes don't count) and sort by last contact; results show the last contact date (ADR-0014). | Should | 5 |
| S-10 | Time phrases in the search box ("recently", "last week", "in September", "since June 1", "yesterday") limit results to people with an interaction in that period, newest first, showing that interaction; "met", "called", "emailed", "messaged" narrow the kind (ADR-0014). | Could | 5 |
| S-11 | **Reconnect** page and a "Due to reconnect" filter: overdue contacts first (most overdue at the top), then those due within 7 days; the count shows in the navigation; Log and Snooze offer Undo; search results mark overdue contacts, not by color alone (ADR-0016, ADR-0017). | Should | 7 |
| S-12 | Command palette (Ctrl/⌘ + K): jump to a person, list, tag or saved search, or run a common action (add a contact, Reconnect, Present, theme); presenting mode applies (ADR-0017). | Should | 6 |
| S-13 | **Map** view of any search, list, tag or selection: states shaded by how many contacts are there, zooming to clustered points at ZIP or city level; home, work or all addresses; a count of contacts that could not be placed; offline — no map tiles or other outside requests; presenting mode applies (ADR-0023). | Should | 12 |
| S-14 | "Near" filter: contacts within a chosen number of miles of a city, ZIP code or another contact (ADR-0023). | Could | 12 |

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
| M-05 | Teams group chat link for selected contacts (`users=a@x.example,b@y.example`). | Could | 3 |
| M-06 | **Directions** links: from the device's location to a contact (card and selection of one), from one selected contact to another, or a route through 3–11 selected contacts; opens Google Maps, or Apple Maps when the instance prefers it (routes always open in Google Maps) (ADR-0023). | Should | 12 |

### Data in and out

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| D-01 | Import contacts from CSV with column mapping and preview. | Should | 3 |
| D-02 | Import and export vCard (.vcf). | Should | 3 |
| D-03 | Export all data (contacts, tags, lists) to CSV and JSON. The JSON export includes each contact's photo, so importing it into another instance restores them (ADR-0026). | Must | 3 |
| D-04 | One-click backup and restore of the instance's database (`pg_dump` / `pg_restore`). | Must | 3 |
| D-05 | Optional directory sync from Microsoft Graph or Slack to prefill employees (title, manager, team). | Could | 5 |
| D-06 | In-app import help: an information icon on the import pages opens a help page explaining the column mapping (column in the file → field), what each field holds, and where the columns of a Google Contacts, Outlook or LinkedIn export go (ADR-0020). | Should | 3 |
| D-07 | Review an import before it runs (ADR-0026): the preview is paged (25 rows) with a filter for ready rows, possible duplicates and errors; every valid row has a checkbox, with select this page, all, none and ready rows only, and ticks are kept across pages; only ticked rows are imported (ready rows start ticked, duplicates do not). A possible duplicate is compared field by field with the contact it matches, or the earlier row of the file: a full match says there is nothing new, otherwise a detail view lists each field that is different, only in the file or only in the stored contact. Import never changes a stored contact; a ticked duplicate is added as a new contact and can be merged afterwards (C-12). | Should | 3 |

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
| I-09 | Move or copy a contact between instances via export/import (vCard or JSON). JSON keeps extra fields, activity, lists, photo, the keep-in-touch cadence and snooze, and private flags; a whole-instance JSON export carries photos too. | Could | 4 |
| I-10 | Container deployment: one Compose file runs PostgreSQL and up to two instances (Work, Personal) built from the app image. Each instance's database and role are created automatically on first start (I-02 unchanged); passwords are generated then and kept in Docker volumes; the database has no published port; instances listen on 127.0.0.1 only and restart with Docker. | Must | 9 |
| I-11 | Before applying migrations to a production instance that already has a schema, the app takes a backup (`…_before-upgrade.dump`) and refuses to migrate if the backup fails. | Must | 9 |
| I-12 | A new container instance with an empty database restores the newest backup already in its backup folder on first start, so moving to a new computer is copying one folder. | Should | 9 |
| I-13 | Double-click Start and Stop for macOS and Windows: Start checks Docker Desktop is installed and running, asks first-run questions, starts the stack, waits until it is healthy and opens the browser. A plain-language install guide covers install, update, backups, moving computers and troubleshooting. | Should | 9 |
| I-14 | The running app version is shown in Settings and returned by `/healthz`. | Should | 9 |

**Standard instance set**

| Instance | Purpose | Database | Port | `APP_ENV` |
| --- | --- | --- | --- | --- |
| business-prod | Work contacts | `contacts_business_prod` | 5170 | production |
| personal-prod | Friends, family, personal services | `contacts_personal_prod` | 5171 | production |
| dev | Building and testing features | `contacts_dev` | 5180 | development |
| test | Automated tests | created and dropped per run | — | test |

### Appearance

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| A-01 | Theme mode is System, Light or Dark; System follows the operating system and updates when it changes. Default: System (ADR-0015). | Must | 6 |
| A-02 | Three palettes — Harbor (default), Sage, Clay — each with a light and a dark version. | Must | 6 |
| A-03 | Theme mode and palette are saved per instance and applied by the server, with no flash of the wrong theme and no JavaScript required. | Must | 6 |
| A-04 | Every palette in both modes meets WCAG 2.2 AA: text 4.5:1; field borders, focus rings and icons 3:1; an automated test checks every pair. | Must | 6 |
| A-05 | Density: Comfortable or Compact. | Could | 6 |
| A-06 | Honors the operating system's reduce-motion and increase-contrast settings. | Should | 6 |

### Privacy while presenting

| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| P-01 | Presenting mode: a header button and ⇧P turn it on and off; a persistent bar shows while it is on; it covers every instance in the browser and turns off when the browser closes (configurable) (ADR-0016). | Should | 7 |
| P-02 | While presenting, private data is never sent to the browser: notes, activity summaries, personal emails and phones, private extra fields, private tags, lists and contacts. | Must | 7 |
| P-03 | Tags, lists, contacts and extra fields can be marked private; Settings chooses which built-in fields are hidden and which email/phone labels count as personal. | Should | 7 |
| P-04 | Search while presenting still matches hidden fields but never quotes them; private contacts are left out, with a count. | Should | 7 |
| P-05 | Import preview, duplicate merge, backup restore, exports and the JSON API do not expose private data while presenting. | Should | 7 |
| P-06 | Copy emails and Compose use work addresses only while presenting and say how many were left out. | Should | 7 |
| P-07 | Per-instance presenting view: work details, names and companies only, or a lock screen. | Could | 7 |
| P-08 | A contact type can be marked private: while presenting, every contact of that type is withheld like a private contact, and the type itself is hidden (ADR-0022). | Should | 11 |

## 5. Non-functional requirements

| ID | Area | Requirement |
| --- | --- | --- |
| N-01 | Hosting | PostgreSQL runs locally in Docker; each app instance starts with one command and serves at `http://localhost:<port>`. Binds to 127.0.0.1 by default; LAN access is opt-in. A container install runs PostgreSQL and the instances together with Docker Desktop (I-10, ADR-0019). |
| N-02 | Platforms | Runs on macOS, Windows and Linux with Docker Desktop; works in current Chrome, Edge, Safari and Firefox. |
| N-03 | Performance | Search returns in < 200 ms and pages load in < 1 s with 10,000 contacts per instance. |
| N-04 | Privacy | No telemetry, no third-party calls at runtime; all assets bundled. Database port 5432 is not exposed beyond localhost. The search-by-meaning model is downloaded once by the user (`make model`), verified, and loaded from disk (ADR-0013). In a container install the model is downloaded when the image is built (ADR-0019). Links the user clicks (Teams, LinkedIn, Google or Apple Maps directions) send their contents only on that click (ADR-0023). |
| N-05 | Security | One database user per instance with rights only to its own database; credentials in env files excluded from git. Optional UI passcode per instance. Validate and escape all input; CSRF protection on writes. |
| N-06 | Durability | Nightly `pg_dump` per production instance, 14-day retention, stored in a local folder outside Docker volumes; restore tested in CI. Container installs write backups to a host folder through a bind mount (ADR-0019). |
| N-07 | Clipboard | Copy uses the browser Clipboard API (works on `localhost` as a secure context); a fallback shows the text to copy manually. |
| N-08 | Email hand-off | `mailto:` links stay under ~2,000 characters; above that the app falls back to Copy emails and says why. |
| N-09 | Usability | Keyboard-first: `/` focuses search, arrow keys move, space selects, `c` copies emails, Ctrl/⌘ + K opens the command palette and `?` lists every shortcut. Readable at 200% zoom; meets WCAG 2.2 Level AA, including contrast in every theme (A-04), visible focus and 24 × 24 px minimum targets; buttons and fields are at least 40 px tall (44 px at phone width) (ADR-0015, ADR-0017). |
| N-10 | Maintainability | Typed Python (type hints checked by mypy, Pydantic models), versioned migrations, ≥ 80% test coverage overall and on search and list logic. |
| N-11 | Portability | Full export to open formats (CSV, JSON, vCard) per instance so data is never locked in. |
| N-12 | Identity | The product is named **Kith Contacts**. The name is used for everything a person sees or downloads (pages, launchers, messages, install guide, bundle zip, image title) and for the Compose project `kith-contacts`, the `~/KithContacts` data folder, the program folder, the image, the Python package, the JSON export format `kith-contacts/1` (import also accepts `contacts-app/1`) and the model cache `~/.cache/kith-contacts/`. "Kith" alone appears only in running text after the full name. Moving an existing install is the I-12 restore from its backups (ADR-0024). |
| N-13 | Open source | The source is published under the Apache License 2.0 (ADR-0025). The repository carries `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES` (every bundled font, library, outline and data set, and the downloaded model, with its licence and required attribution), `SECURITY.md`, `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`, and the install zip carries the licence files. It contains no secrets, no real personal data and no real addresses (`.example` domains only), in the files or in the published history. A test fails when a bundled asset has no notice. |

## 6. Data model

| Table | Key fields | Notes |
| --- | --- | --- |
| `contact_type` | id, name (unique), sort_order | Per-instance list seeded from `CONTACT_TYPES` (C-05, I-08). |
| `contact` | id, display_name\*, first_name, last_name, nickname, contact_type_id → contact_type, company, title, team, department, location, manager_id → contact, works_on, notes, slack_handle, slack_url, teams_url, pronunciation, is_favorite, archived_at, created_at, updated_at | \* required. `manager_id` nullable; no self-reference; cycles rejected in app logic. |
| `contact_email` | id, contact_id, email, label, is_primary | Unique (contact_id, lower(email)); at most one primary per contact. |
| `contact_photo` | contact_id, content_type, data, updated_at | Phase 3. ≤ 512 px, EXIF stripped; stored in the database so backups include it (ADR-0011). |
| `contact_phone` | id, contact_id, number, label | Stored as E.164 when parseable, using the instance's `PHONE_REGION` (ADR-0008). |
| `contact` (Phase 11 column) | birthday | Phase 11 (C-20, ADR-0022). `YYYY-MM-DD`, or `--MM-DD` without a year. |
| `contact_type` (Phase 11 column) | is_private | Phase 11 (P-08, ADR-0022). |
| `contact_address` (Phase 12 columns) | latitude, longitude, time_zone, place_precision | Phase 12 (C-22, ADR-0023). From offline data; `place_precision` ∈ zip, city, state, country, none. |
| `contact_address` | id, contact_id, label, street, city, region, postal_code, country, country_code | Phase 10 (C-19, ADR-0021). `country_code` is ISO 3166-1 alpha-2; `region` is the ISO 3166-2 subdivision code (without the country prefix) when recognised. |
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
| `semantic_doc` | contact_id, model, doc_hash, stale, embedded_at | Phase 5 (S-08). One row per indexed contact (ADR-0013). |
| `semantic_chunk` | id, contact_id, source, text, vector (bytea) | Phase 5 (S-08). Derived data; not exported; dropped when anonymizing. |
| `app_setting` | key (primary key), value, updated_at | Phase 6 (A-03, ADR-0015). Per-instance preferences: theme, palette, density; Phase 7 adds presenting options. |
| `contact` (Phase 7 columns) | kit_interval, kit_started_on, kit_snoozed_until, is_private | Phase 7 (C-15, C-16, P-03, ADR-0016). Due date is computed, not stored. |
| `contact` (Phase 8 column) | linkedin_url | Phase 8 (C-18, ADR-0018). Canonical `https://www.linkedin.com/in/<name>`. |
| `tag`, `contact_list`, `custom_field` (Phase 7) | is_private | Phase 7 (P-03, ADR-0016). |
| `contact.search_vector` | Weighted tsvector: name (A); team, company, manager, tags (B); title, department, works_on, lists, emails, custom fields (C); notes, location, activities, address city, region, postal code and country (D) | Maintained by the application (`app/search.py`, ADR-0010); GIN index; plus `pg_trgm` GIN index on names. |

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
| 3 — Daily-driver ✅ | Production instances; org view, import/export, backups | S-06, T-03–T-04, C-09, M-05, D-01–D-04, D-06, N-06, I-06–I-08 | 1–2 weeks |
| 4 — Depth ✅ | Power-user features | C-11–C-13, S-07, T-05, L-05 (list tags), I-09 | 1–2 weeks |
| 5 — Smart | Semantic search, recent interactions and directory sync | S-08–S-10, D-05 | 2+ weeks |
| 6 — Look and feel ✅ | Theme modes, three palettes, accessibility pass, layout refresh, command palette | A-01–A-06, N-09, S-12 | 8–10 days |
| 7 — Relationships and privacy ✅ | Keep-in-touch reminders and presenting mode | C-15–C-17, S-11, P-01–P-07 | ~8 days |
| 8 — Profiles | LinkedIn profile link on every card | C-18 | 1 day |
| 9 — Containers | Container deployment, safer upgrades, double-click install for Windows and Mac | I-10–I-14 | 3–4 days |
| 10 — Places | Postal addresses, groundwork for a contact map and time zones | C-19 | 2 days |
| 11 — Birthdays and private types | Birthdays with reminders; private contact types | C-20, C-21, P-08 | 1–2 days |
| 12 — Map and local time | Offline map, local time, near search, directions | C-22, C-23, S-13, S-14, M-06 | 4–5 days |
| 13 — Name ✅ | Rename to Kith Contacts everywhere for the public release; one-time move of the owner's install through backup and restore | N-12 | 1–2 days |
| 14 — Open source release | LICENSE and notices, project files, README for strangers, clean sample data, rewritten author addresses, name and policy checks | N-13 | 2–3 days |

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

- Search by meaning (S-08): a local embedding model (`all-MiniLM-L6-v2`, ONNX), vectors stored in the instance database and compared in the app; a background task keeps them current (ADR-0013).
- Find people by when you last interacted: a Contacted filter, a Last contact column and sort, and time phrases in the search box (S-09, S-10, ADR-0014).
- Optional Microsoft Graph / Slack directory sync with review before overwrite (D-05).

**Done when (S-08):** with the model installed, "the person who helped with the FDA submission" lists the contact whose notes mention the 510(k) submission, with that note shown as the reason; the app runs normally when the model is absent.

### Phase 6 — Look and feel

- `app/static/tokens.css` with every color as a token, written once per palette with `light-dark()`; `app.css` uses tokens only; contrast fixes for the dark primary button, field borders, `color-scheme`, dark tag tints (ADR-0015).
- `app_setting` table; Settings › Appearance (theme, palette, density); header theme switch that works without JavaScript; `<html data-theme data-palette data-density>` rendered by the server.
- Sage and Clay palettes; vendored Atkinson Hyperlegible Next; reduced motion and increased contrast; instance header stripe and chip (I-03).
- Layout refresh: card list + preview pane, filter chips, highlighted matches; command palette (Ctrl/⌘ + K) and `?` shortcut list (ADR-0017).

**Done when:** with the OS in dark mode, System renders dark and Light renders light with no flash on reload, even with JavaScript off; business-prod and personal-prod keep different palettes across a backup and restore; the contrast test and axe-core pass for all six palette-and-mode pairs.

### Phase 7 — Relationships and privacy

- Keep-in-touch cadence and snooze on the card and in bulk; Reconnect page with a nav count; log prompt after Email, Call or Compose (ADR-0016).
- Presenting mode: ⇧P and header button, bar, session cookie for all instances; allowlist-based presentable view in `app/privacy.py`; private flags and Settings › Privacy and presenting; search, Copy/Compose, raw-data pages and the API respect it.

**Done when:** a contact with a monthly cadence and a call logged 40 days ago appears on Reconnect as overdue by about 10 days, and logging a call removes it; with presenting on, a marker string seeded into every private field appears in no page, fragment or API response.

### Phase 8 — Profiles

- `contact.linkedin_url` (migration 0009); profile URL or name normalised on save; LinkedIn action on the card and preview; edit form field; duplicate merge, anonymised copies, CSV/vCard/JSON export and import, including LinkedIn's own Connections export (ADR-0018).

**Done when:** importing LinkedIn's `Connections.csv` fills profile links for those people, and the card's LinkedIn action opens `https://www.linkedin.com/in/<name>` in a new tab.

### Phase 9 — Containers

- `Dockerfile` (Python 3.12 on Debian trixie, PostgreSQL 17 client, model fetched at build time) and `compose.yaml` (PostgreSQL, one-shot `secrets` and `setup`, `work` and `personal` instances by profile) (ADR-0019).
- Before-upgrade backup for production instances; restore-on-empty for new container instances.
- Start and Stop launchers for macOS (`.command`) and Windows (`.bat` + PowerShell); `~/KithContacts/settings.env` and `~/KithContacts/Backups/`.
- `make image`, `make container-test`, `make bundle`; `docs/install-guide.md`, shipped as `Start here.html`.

**Done when:** on a computer with only Docker Desktop installed, unzipping the bundle and double-clicking Start opens a working instance at `http://localhost:5170`; stopping and starting keeps the data; a newer version applies its migrations after a before-upgrade backup; copying `~/KithContacts` to another computer and starting there brings the contacts back.

### Phase 10 — Places

- `contact_address` (migration 0010) with country and state normalised on save (`pycountry`); address rows on the edit form; addresses on the card; presenting mode withholds personal-labelled addresses, and all of them when location is hidden; search document gains address city, region, postal code and country.
- Import reads Google's per-value labels, skips fax numbers, splits `:::` cells, and maps Google, Outlook and hand-made address columns; vCard `ADR`, CSV and JSON export and import carry addresses; duplicate merge and anonymised copies handle them (ADR-0021).

**Done when:** importing a Google Contacts export gives each person their addresses with labels, a two-letter country code and a state code; a card shows them; searching a city finds the people there; presenting hides home addresses.

### Phase 11 — Birthdays and private types

- `contact.birthday` and `contact_type.is_private` (migration 0011). Birthday on the form, card and preview; imported from Google, Outlook, vCard, CSV and JSON; exported to all three; presenting treats it as personal.
- Reconnect lists birthdays in the next 14 days.
- Private contact types: a toggle on Settings › Contact types and Settings › Privacy; presenting withholds their contacts and hides the type (ADR-0022).

**Done when:** importing a Google export fills birthdays (with and without years); Reconnect shows those coming up in the next two weeks; marking the import's type private hides all of its contacts while presenting.

### Phase 12 — Map and local time

- Place lookup from offline data (`zipcodes`; GeoNames cities extract in `app/data/`), migration 0012, start-up fill for existing addresses.
- Local time, time zone and good-time-to-reach on the card, preview and search results.
- `/map` for any search, list, tag or selection: vendored Leaflet, markercluster and state/country outlines; no tiles.
- Near filter (miles from a city, ZIP or contact); directions and routes to Google Maps or Apple Maps (Settings › Maps).

**Done when:** a Google export's contacts appear on the map by state and, zoomed in, by town; a western-Kansas contact shows Mountain time and an Olathe contact Central; two selected contacts open Google Maps driving directions between them; the browser makes no request outside the app while using the map.

## 9. Open questions

- [x] Build language → Python (ADR-0004).
- [x] Slack or Teams → both are used; both actions on every card (ADR-0007).
- [x] Backup location → local folder for now, `~/ContactsBackups/<instance>` (ADR-0007).
- [x] Default mail client → both are used; the user chooses Outlook or Gmail when copying or composing (ADR-0009).
- [ ] Is any contact data subject to company data-handling policy? Affects where the business instance may run.
- [ ] Is a directory export (Outlook / Entra ID CSV) available to seed the business instance in Phase 3?
- [x] Contact map and time-zone offsets → offline ZIP and city data (`zipcodes`, GeoNames extract) and a tile-free map (ADR-0023).
- [ ] Is "Kith Contacts" clear to use? Check GitHub repository availability and search USPTO software classes 9 and 42 before the first public release (ADR-0024).
- [x] Which open-source licence for the public release? Apache-2.0 (ADR-0025, accepted 2026-10-05).
- [ ] Before the first push (ADR-0025 steps 5 to 7, owner only): rewrite the author address on a fresh clone, confirm the `axe-playwright-python` licence and the employer's outside-work policy, and turn on GitHub secret scanning, Dependabot alerts, private vulnerability reporting and branch protection.

## 10. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Data entry burden | High | Quick-add form; CSV/vCard import (Phase 3); directory sync (Phase 5) |
| Working in the wrong instance | Medium | Instance name and color band; seed/reset blocked in production (I-03, I-05); a different palette per instance (A-02) |
| Database lost or corrupted | High | Nightly `pg_dump` outside Docker (N-06); open-format export (N-11) |
| Docker Desktop not running | Medium | PostgreSQL container `restart: unless-stopped`; start Docker at login |
| Org data goes stale | Medium | "Last verified" date; archive instead of delete |
| Customer/vendor personal data on a laptop | Medium | Local-only, per-instance DB roles, disk encryption, optional passcode (N-05) |
| Private details seen while sharing a screen | Medium | Presenting mode withholds them on the server (P-01–P-07) |

## Change log

| Version | 1.20 |
| --- | --- | --- | --- |
| 1.20 | 2026-10-06 | D-07 import review added (Phase 3): paged preview, choose rows with select all / individual, and a field-by-field comparison of each possible duplicate. D-03 and I-09 clarified: the whole-instance JSON export carries photos (JSON imports may be up to 64 MB; CSV and vCard stay 5 MB). | 0026 |
| 1.19 | 2026-10-06 | Clarified how the install zip (I-13) is published: a tag workflow builds it with `make bundle` and attaches it, with a checksum, to a GitHub Release; the zip is not committed to git. No requirement added or removed. | 0025 |
| 1.18 | 2026-10-05 | ADR-0025 accepted; N-13 implemented in the repository: `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, an About section in Settings, licence files in the install zip, a README for strangers, `.example` sample data and tests that fail on an unlisted asset or a real address. Phase 14 stays open until the owner-only steps (history rewrite, name and policy checks, GitHub settings) are done. | 0025 |
| 1.17 | 2026-10-05 | N-13 added in a new Phase 14: publish as open source under the Apache License 2.0 with third-party notices, project files and a clean history. Proposed. | 0025 |
| 1.16 | 2026-10-05 | N-12 added in a new Phase 13: the product is named Kith Contacts everywhere (UI, launchers, bundle, Compose project, data folder, export format, model cache) for the public open-source release; the owner's install moves once through backup and restore (I-12). Delivered. | 0024 |
| 1.15 | 2026-10-04 | C-22 place lookup, C-23 local time, S-13 map, S-14 near filter and M-06 directions added in a new Phase 12. Data model gains place columns on `contact_address`. N-04 clarified (links the user clicks). Open question on map data closed. | 0023 |
| 1.14 | 2026-10-04 | C-20 birthdays, C-21 birthday reminders on Reconnect and P-08 private contact types added in a new Phase 11. Data model gains `contact.birthday` and `contact_type.is_private`. Clarified P-02 (birthdays are personal) and D-01, D-02, D-03, I-09 (birthdays included). | 0022 |
| 1.13 | 2026-10-04 | C-19 postal addresses added in a new Phase 10 — Places. Data model gains `contact_address`. Clarified D-01 (Google's per-value email and phone labels, fax numbers skipped, `:::` cells split, address columns), D-02, D-03 and I-09 (addresses included). | 0021 |
| 1.12 | 2026-10-04 | D-06 in-app import help added (Phase 3). Clarified D-01: Google Contacts' current export columns (Organization Name, Organization Title, Organization Department, Address 1 - City) are recognised, and a row with a company but no person's name uses the company as display name. | 0020 |
| 1.11.1 | 2026-10-04 | Clarified C-01: the card and search preview show the first and last name and nickname when they differ from the display name. No requirement added or removed. | — |
| 1.11 | 2026-10-04 | Phase 9 — Containers added: I-10 container deployment, I-11 backup before upgrade, I-12 restore on first start, I-13 double-click start for macOS and Windows with an install guide, I-14 version shown. N-01, N-04 and N-06 clarified for container installs. | 0019 |
| 1.10 | 2026-10-03 | C-18 LinkedIn profile link added in a new Phase 8 — Profiles. Data model gains contact.linkedin_url. | 0018 |
| 1.9.1 | 2026-10-03 | Phases 6 and 7 delivered. Clarified I-09: a JSON copy also carries the keep-in-touch cadence and snooze (C-15, C-16) and private flags (P-03). No requirement added or removed. | 0016, 0017 |
| 1.9 | 2026-10-03 | S-12 command palette added to Phase 6; S-02 highlights matched words; S-11 adds Undo on Reconnect and an overdue marker in results; N-09 adds `?`, Ctrl/⌘ + K and 40/44 px controls. | 0017 |
| 1.8 | 2026-10-03 | Phase 7 added: keep-in-touch reminders (C-15–C-17, S-11) and presenting mode (P-01–P-07). Data model gains kit_* and is_private columns. | 0016 |
| 1.7 | 2026-10-03 | Phase 6 added: theme modes and palettes (A-01–A-06); N-09 reworded to WCAG 2.2 Level AA. Data model gains app_setting. | 0015 |
| 1.6 | 2026-10-03 | S-09 (recent-interaction filter, last-contact sort) and S-10 (time phrases in search) added after "who have I interacted with recently" found no one. | 0014 |
| 1.5 | 2026-10-03 | S-08 search by meaning designed and delivered: local model, in-process vectors instead of pgvector; N-04 clarified for the one-time model download. Data model gains semantic_doc, semantic_chunk. | 0013 |
| 1.4 | 2026-09-24 | Phase 4 delivered. S-01 clarified: custom fields and activity summaries are searchable. Data model gains custom_field, activity, saved_search, list_tag, duplicate_dismissal, contact_merge. | 0012 |
| 1.3 | 2026-09-24 | Phase 3 delivered. L-05 list tags moved to Phase 4. Photos stored in the database. Backup tool, daily auto-backup and import/export formats decided. | 0011 |
| 1.2.1 | 2026-09-24 | Phase 2 delivered. Clarified: search document maintained by the application rather than triggers. | 0010 |
| 1.2 | 2026-09-24 | M-02 and M-03 changed: choose Outlook or Gmail when copying or composing to several contacts. C-14 added: company dropdown with add-new and a default for new employees. | 0009 |
| 1.1.1 | 2026-09-24 | Phase 1 delivered. Clarified: phone numbers normalized to E.164 using the instance's `PHONE_REGION`; Slack/Teams links must be https. No requirement added or removed. | 0008 |
| 1.1 | 2026-09-24 | PostgreSQL replaces SQLite; instances (I-01–I-09) added; Python stack chosen; Slack + Teams both required on cards (C-04); backups to local folder (I-06, N-06); contact types configurable per instance (C-05). | 0003, 0004, 0005, 0007 |
| 1.0 | 2026-09-24 | Initial requirements baseline. | 0002 |
