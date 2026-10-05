# Operations: backups, restores and copies

Two ways to run instances:

- **From the repository** (development, and production until moved): `./run.sh <instance>`,
  PostgreSQL from `docker-compose.db.yml`. The `make` commands below are for this setup;
  `I=` names an instance (`instances/<name>.env`).
- **Container install** (production, and other people's computers — ADR-0019): see
  [Container installs](#container-installs) below and the plain-language
  [install guide](install-guide.md), which ships as `Start here.html` in the zip.

## Backups (D-04, I-06, N-06 — ADR-0011)

| Task | Command |
| --- | --- |
| Back up now (also deletes backups older than the retention period) | `make backup I=business-prod` |
| List backups | `make backups I=business-prod` |
| Restore (stop `./run.sh` for that instance first) | `make restore I=dev FILE=dev_20260924-120000.dump` |
| Restore a production instance | `make restore I=business-prod FILE=… YES=1` |
| Copy production into dev, anonymized | `make copy-to-dev FROM=business-prod TO=dev ANONYMIZE=1` |

- Files go to `BACKUP_DIR` (default `~/ContactsBackups/<instance>`), named `<instance>_<UTC time>.dump`.
- Retention: `BACKUP_RETENTION_DAYS` (default 14). The newest backup is never deleted.
- Every restore first saves the current data as `…_before-restore.dump`.
- The Settings page offers the same: **Back up now**, download, and restore (type the
  instance name to confirm).

### Which pg_dump is used

`BACKUP_TOOL=auto` (default) uses a local `pg_dump` if it is at least as new as the
server (PostgreSQL 17), otherwise runs it inside the Docker container. Nothing extra
needs installing as long as Docker Desktop is running. To use local tools instead:
`brew install libpq && brew link --force libpq`.

### Daily backups

Production instances back themselves up while running: at start-up and then hourly,
if the newest backup is older than 24 hours. For nights when the app is closed, add a
macOS `launchd` job (runs daily at 01:30; adjust the paths):

```xml
<!-- ~/Library/LaunchAgents/com.contacts.backup.business.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.contacts.backup.business</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-lc</string>
    <string>cd ~/code/kith-contacts &amp;&amp; make backup I=business-prod</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardErrorPath</key><string>/tmp/contacts-backup.err</string>
</dict></plist>
```

Load it once with `launchctl load ~/Library/LaunchAgents/com.contacts.backup.business.plist`.

## Import and export (D-01 – D-03)

Settings → Export offers CSV (spreadsheets), vCard (Outlook / Google / Apple
Contacts) and JSON (complete, including lists, roles and tags). Settings → Import
accepts CSV (Outlook and Google export columns are recognised) or vCard, shows a
preview with duplicate warnings, and can put everyone imported into a list. The
information icon on the Import page opens help on the column mapping and on Google,
Outlook and LinkedIn exports (`/import/help`).

## Search by meaning (S-08 — ADR-0013)

| Task | Command |
| --- | --- |
| Install the model once (≈90 MB, shared by all instances) | `make model` |
| Install it from a folder (no internet / blocked site) | `make model FROM=~/Downloads/all-MiniLM-L6-v2` |
| Embed every contact now (otherwise the running app does it) | `make reindex I=business-prod` |
| Check it with the real model | `make test-model` |

- The model is saved in `~/.cache/kith-contacts/models/all-MiniLM-L6-v2` and checked
  against pinned SHA-256 checksums. After installing it, restart running instances.
- A running instance embeds new and changed contacts in the background within seconds.
  Settings → Search by meaning shows progress and has **Re-check all contacts**.
- Turn it off for one instance with `SEMANTIC_SEARCH=off` in its env file.
- Embeddings live in the instance database (so backups include them) but are never
  exported, and an anonymized copy to dev rebuilds them from the anonymized text.

## Container installs

`Start Kith Contacts` (macOS `.command`, Windows `.bat`) runs, from the program folder:

```bash
docker compose --project-name kith-contacts --env-file ~/KithContacts/settings.env \
  -f compose.yaml up -d --build --wait
```

with `APP_VERSION` (from `pyproject.toml`) and `CONTACTS_BACKUPS=~/KithContacts/Backups`
exported. To run the commands below from a terminal, set the same two variables and use the
same flags; `C` stands for that `docker compose …` prefix.

| What | Where |
| --- | --- |
| Settings people may edit (names, colors, contact types, ports, `COMPOSE_PROFILES`) | `~/KithContacts/settings.env` |
| Backups (bind mount, outside Docker — N-06) | `~/KithContacts/Backups/work`, `…/personal` |
| Database | volume `kith-contacts_pgdata` (PostgreSQL 17, no published port) |
| Passwords (generated on first start) | volumes `kith-contacts_db-secrets`, `…_work-instance`, `…_personal-instance` |

| Task | Command |
| --- | --- |
| Back up now / list backups | `C exec work python -m app.container backup` / `… backups` |
| Restore (production needs `--yes`) | `C exec work python -m app.container restore <file> --yes`, then `C restart work` |
| Logs | `C logs -f work` (rotated at 3 × 10 MB) |
| Status | `C ps` — instances report `healthy` from `/healthz` |
| Build and check the whole stack on spare ports | `make container-test` |
| The zip people download | `make bundle` → `dist/Kith-Contacts-<version>.zip` |

What happens on start:

1. `secrets` (one-shot) creates the PostgreSQL admin password if it is missing.
2. `db` starts; `setup` (one-shot) creates or repairs each chosen instance's database and role
   (I-02) and hands each instance its own connection URL, plus its backup folder.
3. Each instance waits for the database, then:
   - **new, empty database and backups in its folder** → restores the newest one (I-12);
   - **production with pending migrations** → takes `…_before-upgrade.dump` first and refuses
     to migrate if that fails (I-11; this applies to `./run.sh` too);
   - migrates (I-04), takes the daily backup if one is due (I-06), and serves on
     `127.0.0.1:<port>`.

### Upgrades and rollback

Updating is unzipping the new version and starting it. If the new version fails to start
because a migration failed, nothing was changed (migrations run in a transaction): start
the previous version's folder again. To undo an upgrade that did complete:

1. Start the previous version's folder. The instance stops with *"Could not migrate…"* because
   the database is newer than that version.
2. Restore the before-upgrade backup with the previous version's image:
   `C run --rm work restore <instance>_<time>_before-upgrade.dump --yes`
3. Start again.

### Moving an instance from `./run.sh` into containers

```bash
make move-to-containers WORK=business-prod PERSONAL=personal-prod
```

takes a fresh backup of each instance, copies it into `~/KithContacts/Backups/work` and
`…/personal`, and writes `~/KithContacts/settings.env` with the same names (so backup file
names match), colors, contact types, ports, home company and phone region. Then:

1. Stop `./run.sh` for those instances (changes made after the backup are not moved).
2. Start the container install (`deploy/mac/start.sh` from the repository, or the zip's
   launcher). Each instance finds its new database empty and restores the copied backup
   (I-12).
3. Check the contacts, then retire the old env files and the launchd job.

<!-- old-name:start -->
### Moving an install from Contact Manager to Kith Contacts (once)

For an install made before the rename (ADR-0024): its data is in `~/ContactManager` and its
Compose project is `contact-manager`. The new version uses a new project and a new folder, so
its databases start empty and each instance restores the newest backup it finds (I-12). The
old install is not touched until the last step, so it is also the way back.

1. In the old version, stop making changes. In **Settings**, **Backups**, back up each
   instance now, and check the new file is in `~/ContactManager/Backups/<instance>`.
2. Stop the old install, which keeps its data and backups (it runs `docker compose stop`, not
   `down`). The old install matters here because it still holds ports 5170 and 5171.
   - If you started it from the zip, double-click `Stop Contact Manager` in the unzipped old
     program folder (`ContactManager-<version>`).
   - If you started it from this repository with `deploy/mac/start.sh`, that script is now
     `Stop Kith Contacts` and looks for the new project, so it would not stop the old one. Run,
     from the repository:
     `export APP_VERSION=1.0.0 CONTACTS_BACKUPS="$HOME/ContactManager/Backups"`, then
     `docker compose --project-name contact-manager --env-file "$HOME/ContactManager/settings.env" -f compose.yaml --profile work --profile personal stop`
     (the service and volume names did not change, so the new `compose.yaml` addresses the old
     project). `docker ps --filter label=com.docker.compose.project=contact-manager` should then
     list nothing.
3. **Copy** the folder `~/ContactManager` to `~/KithContacts` (copy, do not move).
4. Unzip the Kith Contacts version and double-click `Start Kith Contacts`. The first start
   builds the image (5 to 10 minutes); each instance reports
   "New database: restored the newest backup".
5. Check the contact count under Settings, then photos, lists, activity, saved searches and
   keep-in-touch cadences.
6. Only when it is right, remove the old install. This deletes the old database volumes, so be
   sure step 5 is done. From the repository or the new program folder, with the two variables
   from step 2 set (`CONTACTS_BACKUPS` pointing at the old `ContactManager/Backups`):
   `docker compose --project-name contact-manager --env-file "$HOME/ContactManager/settings.env" -f compose.yaml --profile work --profile personal down --volumes`;
   then `docker image rm contact-manager:<version>` and delete `~/ContactManager`.

To go back before step 6, stop Kith Contacts and start the old program folder (if you started
from the repository, repeat the step 2 command with `start` in place of `stop`). Anything
changed in Kith Contacts since step 4 is not in the old install.
<!-- old-name:end -->
