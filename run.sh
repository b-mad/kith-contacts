#!/usr/bin/env bash
# Start one instance:  ./run.sh <instance>   (reads instances/<instance>.env)
set -euo pipefail

cd "$(dirname "$0")"

if [[ $# -ne 1 ]]; then
  echo "usage: ./run.sh <instance>" >&2
  echo "available instances:" >&2
  ls instances/*.env 2>/dev/null | grep -v example.env | xargs -n1 basename 2>/dev/null \
    | sed 's/\.env$//; s/^/  /' >&2 || true
  exit 2
fi

env_file="instances/$1.env"
if [[ ! -f "$env_file" ]]; then
  echo "error: $env_file not found. Create it with: make instance NAME=$1 PORT=<port> ENV=<env>" >&2
  exit 2
fi

export INSTANCE_ENV_FILE="$env_file"
exec uv run python -m app
