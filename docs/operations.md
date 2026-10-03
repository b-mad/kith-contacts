# Operations: backups, restores and copies

All commands run from the project folder. `I=` names an instance (`instances/<name>.env`).

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
    <string>cd ~/code/contacts-app &amp;&amp; make backup I=business-prod</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardErrorPath</key><string>/tmp/contacts-backup.err</string>
</dict></plist>
```

Load it once with `launchctl load ~/Library/LaunchAgents/com.contacts.backup.business.plist`.

## Import and export (D-01 – D-03)

Settings → Export offers CSV (spreadsheets), vCard (Outlook / Google / Apple
Contacts) and JSON (complete, including lists, roles and tags). Settings → Import
accepts CSV (Outlook and Google export columns are recognised) or vCard, shows a
preview with duplicate warnings, and can put everyone imported into a list.

## Search by meaning (S-08 — ADR-0013)

| Task | Command |
| --- | --- |
| Install the model once (≈90 MB, shared by all instances) | `make model` |
| Install it from a folder (no internet / blocked site) | `make model FROM=~/Downloads/all-MiniLM-L6-v2` |
| Embed every contact now (otherwise the running app does it) | `make reindex I=business-prod` |
| Check it with the real model | `make test-model` |

- The model is saved in `~/.cache/contacts-app/models/all-MiniLM-L6-v2` and checked
  against pinned SHA-256 checksums. After installing it, restart running instances.
- A running instance embeds new and changed contacts in the background within seconds.
  Settings → Search by meaning shows progress and has **Re-check all contacts**.
- Turn it off for one instance with `SEMANTIC_SEARCH=off` in its env file.
- Embeddings live in the instance database (so backups include them) but are never
  exported, and an anonymized copy to dev rebuilds them from the anonymized text.
