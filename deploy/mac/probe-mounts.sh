#!/bin/bash
# Diagnose "Cannot write backups": can a Contact Manager container write to a folder shared
# from this computer? (ADR-0019; works on macOS and Linux with Docker.)
#
#   bash deploy/mac/probe-mounts.sh            # from the program or repository folder
#
# Tries every combination the install uses: where the folder is, which user the app runs as,
# who created the folder (this computer, a container, or Docker itself because it was missing),
# whether it is shared on its own (as the install shares each contact
# book's backup folder) or inside a shared parent, and the hardening options the contact
# books run with. Prints one
# line per combination and a verdict. Creates only throw-away folders and removes them.
set -u

PROGRAM="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$PROGRAM/pyproject.toml" | head -1)"
IMG="contact-manager:${VERSION:-dev}"
ME="$(id -u):$(id -g)"
HARDENED="--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true"
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running: start Docker Desktop and try again."
  exit 1
fi
if ! docker image inspect "$IMG" >/dev/null 2>&1; then
  echo "Image $IMG not found: double-click Start Contact Manager once (it builds it), then try again."
  exit 1
fi

TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/cm-probe.XXXXXX")"
HOME_BASE="$HOME/Contact Manager/.probe"
LOCATIONS="$TMP_BASE|$HOME_BASE|/tmp/cm-probe-$$"
failures=0
results=""

probe_location() {
  local base="$1"
  rm -rf "$base"
  if ! mkdir -p "$base/made-on-host"; then
    echo "  cannot create $base on this computer"
    return
  fi
  # the install's setup step: root in the container makes the folder and hands it to the app user
  docker run --rm --user 0 -v "$base:/b" --entrypoint sh "$IMG" -c \
    "mkdir -p /b/made-in-container && chown $ME /b/made-in-container" >/dev/null 2>&1
  local user flags name dir verdict
  for user in "$ME" "10001:10001"; do
    for flags in "plain" "hardened"; do
      local opts=""
      [ "$flags" = "hardened" ] && opts="$HARDENED"
      # shellcheck disable=SC2086
      out="$(docker run --rm --user "$user" $opts -v "$base:/b" --entrypoint sh "$IMG" -c '
        for d in made-on-host made-in-container; do
          if [ -d "/b/$d" ] && touch "/b/$d/.probe-$$" 2>/dev/null; then echo "$d OK"; rm -f "/b/$d/.probe-$$"
          else echo "$d FAIL $(ls -lnd "/b/$d" 2>&1)"; fi
        done' 2>&1)"
      # the install shares each backup folder on its own, so the app writes at the top of the share
      for d in made-on-host made-in-container; do
        # shellcheck disable=SC2086
        out="$out
$(docker run --rm --user "$user" $opts -v "$base/$d:/b" --entrypoint sh "$IMG" -c '
          if touch "/b/.probe-$$" 2>/dev/null; then echo "'"$d"'-shared-alone OK"; rm -f "/b/.probe-$$"
          else echo "'"$d"'-shared-alone FAIL $(ls -lnd /b 2>&1)"; fi' 2>&1)"
      done
      # a share whose folder does not exist yet: Docker creates it
      # shellcheck disable=SC2086
      out="$out
$(docker run --rm --user "$user" $opts -v "$base/made-by-docker-$user-$flags:/b" --entrypoint sh "$IMG" -c '
        if touch "/b/.probe-$$" 2>/dev/null; then echo "made-by-docker-shared-alone OK"; rm -f "/b/.probe-$$"
        else echo "made-by-docker-shared-alone FAIL $(ls -lnd /b 2>&1)"; fi' 2>&1)"
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        name="${line%% *}"
        verdict="$(echo "$line" | cut -d' ' -f2)"
        printf '  %-8s %-11s %-9s %-30s %s\n' "$verdict" "$user" "$flags" "$name" \
          "$( [ "$verdict" = OK ] || echo "${line#* FAIL }")"
        if [ "$verdict" != OK ]; then
          failures=$((failures + 1))
          results="$results\n  $base ($name) as $user, $flags"
        fi
      done <<< "$out"
    done
  done
  for d in made-on-host made-in-container; do
    echo "  on this computer, $d: $(ls -lnd "$base/$d" 2>/dev/null | awk '{print $1, "owner " $3 ":" $4}')"
  done
  rm -rf "$base"
}

echo "Contact Manager: shared-folder probe ($IMG, you are $ME)"
echo "Docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null), $(docker info --format '{{.OperatingSystem}}' 2>/dev/null)"
IFS='|' read -r -a bases <<< "$LOCATIONS"
for base in "${bases[@]}"; do
  echo ""
  echo "Folder: $base"
  printf '  %-8s %-11s %-9s %-30s %s\n' "RESULT" "USER" "OPTIONS" "FOLDER (MADE BY, HOW SHARED)" "WHAT THE CONTAINER SEES"
  probe_location "$base"
done
rmdir "$HOME/Contact Manager" 2>/dev/null || true

echo ""
if [ "$failures" -eq 0 ]; then
  echo "Verdict: containers can write to shared folders here. A backup problem lies elsewhere;"
  echo "send this output and the 'Cannot write backups' message to whoever gave you Contact Manager."
else
  echo "Verdict: $failures combination(s) cannot write:"
  printf '%b\n' "$results"
  echo "Send this output to whoever gave you Contact Manager."
fi
