#!/bin/bash
# Stop Kith Contacts on a Mac (I-13, ADR-0019). Your contacts and backups are kept.
set -u

PROGRAM="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$HOME/KithContacts"
SETTINGS="$DATA/settings.env"
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"

finish() {
  echo
  read -r -p "Press Return to close this window. " _
  exit "$1"
}

echo "Stopping Kith Contacts..."
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is not running, so Kith Contacts is already stopped."
  finish 0
fi
if [ ! -f "$SETTINGS" ]; then
  echo "Kith Contacts has not been started on this computer yet."
  finish 0
fi
export CONTACTS_BACKUPS="$DATA/Backups"
export APP_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$PROGRAM/pyproject.toml" | head -1)"
if docker compose --project-name kith-contacts --env-file "$SETTINGS" \
    -f "$PROGRAM/compose.yaml" --profile work --profile personal stop; then
  echo "Stopped. Your contacts and backups are kept; Start Kith Contacts brings them back."
  finish 0
fi
echo "Kith Contacts could not be stopped. Quit Docker Desktop instead."
finish 1
