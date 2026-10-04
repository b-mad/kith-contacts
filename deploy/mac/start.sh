#!/bin/bash
# Start Contact Manager on a Mac (I-13, ADR-0019).
# Run by double-clicking "Start Contact Manager.command"; also works from a terminal.
set -u

PROGRAM="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$HOME/Contact Manager"
SETTINGS="$DATA/settings.env"
PROJECT="contact-manager"
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"

say() { printf '%s\n' "$*"; }
finish() {
  echo
  read -r -p "Press Return to close this window. " _
  exit "$1"
}
setting() { # value of KEY in settings.env, without quotes
  sed -n "s/^$1=//p" "$SETTINGS" 2>/dev/null | tail -1 | sed 's/^"\(.*\)"$/\1/'
}
clean() { # a name safe for settings.env: no quotes, $, backslashes or backticks; 40 characters
  local value="$1"
  value="${value//[\"\$\\\`]/}"
  value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  value="${value:0:40}"
  printf '%s' "${value:-$2}"
}

first_start() {
  say ""
  say "First start: two quick questions."
  say ""
  say "Which contact books do you want?"
  say "  1  Work      (colleagues, customers, vendors)"
  say "  2  Personal  (family, friends, services)"
  say "  3  Both"
  read -r -p "Type 1, 2 or 3 and press Return [1]: " pick
  case "$pick" in
    2) profiles="personal" ;;
    3) profiles="work,personal" ;;
    *) profiles="work" ;;
  esac
  work_name="Work"
  personal_name="Personal"
  if [[ "$profiles" == *work* ]]; then
    read -r -p "Name for your work contact book [Work]: " answer
    work_name="$(clean "$answer" "Work")"
  fi
  if [[ "$profiles" == *personal* ]]; then
    read -r -p "Name for your personal contact book [Personal]: " answer
    personal_name="$(clean "$answer" "Personal")"
  fi
  region="$(defaults read -g AppleLocale 2>/dev/null | sed -n 's/^[a-z]*_\([A-Z][A-Z]\).*/\1/p')"
  mkdir -p "$DATA"
  cat > "$SETTINGS" <<EOF
# Contact Manager settings. Change a value, then double-click "Start Contact Manager" again.
# No passwords are kept here.

# Contact books to run: work, personal, or work,personal
COMPOSE_PROFILES=$profiles

WORK_NAME="$work_name"
WORK_COLOR="#1f6feb"
WORK_TYPES="Employee,Customer,Vendor"
WORK_PORT=5170

PERSONAL_NAME="$personal_name"
PERSONAL_COLOR="#8250df"
PERSONAL_TYPES="Family,Friend,Service provider"
PERSONAL_PORT=5171

# Country for phone numbers typed without a +code (two letters, e.g. US, GB, CA)
PHONE_REGION=${region:-US}
EOF
  say ""
  say "Saved your answers in $SETTINGS"
}

say "Contact Manager"
say "==============="

# 1. Docker Desktop installed?
if ! command -v docker >/dev/null 2>&1; then
  say ""
  say "Docker Desktop is not installed yet. It is free and runs Contact Manager."
  say "Opening the download page. Install it (step 1 in 'Start here'), then try again."
  open "https://www.docker.com/products/docker-desktop/"
  finish 1
fi

# 2. Docker Desktop running?
if ! docker info >/dev/null 2>&1; then
  say ""
  say "Starting Docker Desktop. This can take a minute..."
  if ! open -a Docker 2>/dev/null; then
    say "Could not open Docker Desktop. Open it from your Applications folder, then try again."
    finish 1
  fi
  for _ in $(seq 1 90); do
    docker info >/dev/null 2>&1 && break
    printf '.'
    sleep 2
  done
  echo
  if ! docker info >/dev/null 2>&1; then
    say "Docker Desktop did not finish starting within 3 minutes."
    say "Open Docker Desktop, wait until it shows 'Engine running', then try again."
    finish 1
  fi
fi

# 3. Settings (first start only) and folders
[ -f "$SETTINGS" ] || first_start
mkdir -p "$DATA/Backups/work" "$DATA/Backups/personal"

# 4. Build and start
APP_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$PROGRAM/pyproject.toml" | head -1)"
export APP_VERSION
export CONTACTS_BACKUPS="$DATA/Backups"
# Run the app as you: Docker Desktop lets only the folder's owner write your backups there.
if [ "$(id -u)" != "0" ]; then
  APP_UID="$(id -u)"
  APP_GID="$(id -g)"
  export APP_UID APP_GID
fi
say ""
say "Starting Contact Manager $APP_VERSION."
say "The first start, and the first start after an update, take 5 to 10 minutes."
if ! docker compose --project-name "$PROJECT" --env-file "$SETTINGS" -f "$PROGRAM/compose.yaml" \
    up -d --build --remove-orphans --wait --wait-timeout 300; then
  say ""
  say "Contact Manager could not start. Look at the last lines above:"
  say " - 'port is already allocated' or 'address already in use': another program uses the"
  say "   port. Close it, or change WORK_PORT / PERSONAL_PORT in $SETTINGS."
  say " - 'failed to resolve' or 'network': check the internet connection and try again."
  say " - anything else: see 'Something went wrong' in Start here."
  finish 1
fi

# 5. Open the contact books
profiles="$(setting COMPOSE_PROFILES)"
say ""
if [[ "$profiles" == *work* ]]; then
  url="http://localhost:$(setting WORK_PORT)"
  say "$(setting WORK_NAME): $url"
  open "$url"
fi
if [[ "$profiles" == *personal* ]]; then
  url="http://localhost:$(setting PERSONAL_PORT)"
  say "$(setting PERSONAL_NAME): $url"
  open "$url"
fi
say ""
say "Contact Manager is running. Bookmark the page in your browser."
say "It keeps running in Docker Desktop, also after a restart, until you use Stop Contact Manager."
say "Backups are saved daily in $DATA/Backups"
finish 0
