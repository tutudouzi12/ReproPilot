#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
if [ -f "$ROOT/backend.env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ROOT/backend.env"
  set +a
fi
cd "$ROOT/docker-sandbox"
exec python3 run.py
