# ADR-0019: Run production instances in containers, with double-click start for Windows and Mac

- **Status:** Accepted (2026-10-04)
- **Date:** 2026-10-04
- **Deciders:** Bryan Madsen
- **Requirements affected:** I-10, I-11, I-12, I-13, I-14 added (Phase 9); N-01, N-02, N-04, N-06 clarified

## Context

Running an instance today needs developer tools: uv and Python on the host, `make instance`
to create the database and env file, `./run.sh <instance>` in a terminal that must stay
open, and a hand-written launchd job for nightly backups (docs/operations.md). Only
PostgreSQL runs in Docker (`docker-compose.db.yml`). That suits the developer's own Mac,
but:

- production instances stop when the terminal closes, and nothing restarts them;
- an upgrade applies migrations on start (I-04) with no backup taken first, so a bad
  release can only be undone from the last nightly backup;
- other people with Windows or Mac computers and little technical knowledge cannot set up
  their own copy;
- search by meaning is unavailable on Intel Macs because onnxruntime has no build for them
  (ADR-0013).

The product owner asked for container-based production deployment and for instructions a
non-technical Windows or Mac user can follow, and chose (2026-10-04) to have each person
build the image on their own computer rather than download a published one, and to move
the existing business-prod and personal-prod instances into containers.

## Options considered

1. **Pre-built image in a registry (GitHub Container Registry)** — fastest first start and
   one-click updates; needs a hosted repository, and the image is public unless users sign
   in to the registry, which non-technical users cannot be expected to do.
2. **Build the image on the user's computer from a zip** — no hosting and nothing public;
   the first start takes several minutes and needs internet access to Debian, PyPI and
   Hugging Face (for the search model). Updates are a new zip.
3. **Ship the image as a file in the zip (`docker load`)** — works offline, but a separate
   large download per processor type and a clumsy update path.
4. **Keep the host install and add installers (Homebrew/winget scripts)** — no Docker for
   the app, but Python, uv, PostgreSQL client tools and the model differ per operating
   system, which is exactly what makes setup hard today.

## Decision

Option 2, designed so option 1 can be switched on later by changing only the image name in
`compose.yaml`.

- **Image** (`Dockerfile`): `python:3.12-slim-trixie`, dependencies from `uv.lock` with
  `uv sync --frozen --no-dev`, PostgreSQL 17 client tools from Debian (so backups and
  restores run inside the container with `BACKUP_TOOL=local`), and the search-by-meaning
  model downloaded at build time by `scripts.semantic model` with the pinned checksums. If
  the model cannot be downloaded the build continues and search by meaning stays off; the
  running app still never downloads anything (N-04). The app runs as an unprivileged user,
  and the image has a health check on `/healthz`.
- **Stack** (`compose.yaml`, project `contact-manager`): PostgreSQL 17 (`postgres:17-trixie`)
  on an internal network with no published port; two optional instances, `work` and
  `personal`, selected with Compose profiles and published on `127.0.0.1` only (ports 5170
  and 5171 by default); two one-shot services: `secrets` generates the database admin
  password into a Docker volume before PostgreSQL first starts, and `setup` creates each
  instance's database and role idempotently (I-02 unchanged) and writes that instance's
  connection URL into a volume only that instance mounts. Passwords are never written to
  files the user sees. Instances restart with Docker (`restart: unless-stopped`), run with a
  read-only root filesystem, no added capabilities and `no-new-privileges`, and logs rotate
  at 3 × 10 MB.
- **Backups** stay outside Docker (N-06): each instance writes to
  `~/Contact Manager/Backups/<instance>` on the host through a bind mount. The existing
  hourly check keeps a daily backup while Docker runs, replacing the launchd job.
- **Before-upgrade backup (I-11):** when a production instance with an existing schema has
  pending migrations, it takes `<instance>_<time>_before-upgrade.dump` first and refuses to
  migrate if that backup fails. This applies to `./run.sh` too.
- **Moving to a new computer (I-12):** when a container instance's database is brand new
  (no schema yet) and its backup folder already holds backups, it restores the newest one
  before migrating. No safety backup is taken in that case because the database is empty
  (the one exception to the "back up before overwriting" rule).
- **Settings for people** live in `~/Contact Manager/settings.env` (names, colors, contact
  types, ports, which instances to run); it holds no passwords. The home folder is used
  instead of Documents to avoid the macOS Documents permission prompt and Windows OneDrive
  redirection.
- **Launchers (I-13):** `Start Contact Manager.command` and `Stop Contact Manager.command`
  for macOS, `Start Contact Manager.bat` and `Stop Contact Manager.bat` for Windows
  (PowerShell does the work). Start checks Docker Desktop is installed and running (and
  starts it), asks on first run which contact books to create and what to call them,
  builds and starts the stack, waits until it is healthy and opens the browser. Updating is
  unzipping the new version and starting it.
- **Version (I-14):** `pyproject.toml` holds the app version; `/healthz` and Settings show it
  and the image is tagged with it.
- **Bundle:** `make bundle` writes `dist/Contact-Manager-<version>.zip` with the launchers at
  the top, a plain-language `Start here.html` guide, and the program files in `program/`.
  `make container-test` builds the image and exercises the whole stack on spare ports.

## Consequences

- Production instances survive restarts, upgrades are reversible, and a non-technical user
  can install with Docker Desktop and two double-clicks. Intel Macs get search by meaning,
  because the container runs Linux.
- Docker Desktop becomes a requirement for container installs. Its licence is free for
  personal use and organisations under 250 employees and USD 10 million revenue; larger
  organisations need a paid subscription. Windows needs Windows 10 22H2 or Windows 11 23H2
  or later with virtualization turned on; Mac needs one of the three newest macOS versions.
- The launchers are not code-signed, so macOS and Windows warn the first time; the guide
  shows how to allow them.
- The first start needs internet access to Docker Hub, Debian, PyPI and Hugging Face; later
  starts do not.
- Development is unchanged: uv, `./run.sh`, `docker-compose.db.yml` and `make check` stay.
- Access from other computers on the network is still out of scope: it needs the optional
  passcode (N-05) and HTTPS first.
- More than two instances in one install needs a third service in `compose.yaml`.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| I-10 | Added (Must, Phase 9): container deployment. | — |
| I-11 | Added (Must, Phase 9): backup before migrating a production instance. | — |
| I-12 | Added (Should, Phase 9): a new container instance restores the newest backup in its folder. | — |
| I-13 | Added (Should, Phase 9): double-click start and stop for macOS and Windows, and a plain-language install guide. | — |
| I-14 | Added (Should, Phase 9): the running version is shown in Settings and `/healthz`. | — |
| N-01 | Clarified: containers are a second way to run an instance. | PostgreSQL runs locally in Docker; each app instance starts with one command and serves at `http://localhost:<port>`. Binds to 127.0.0.1 by default; LAN access is opt-in. |
| N-04 | Clarified: in a container install, the model is downloaded when the image is built. | — |
| N-06 | Clarified: container installs keep backups in a host folder through a bind mount. | — |
