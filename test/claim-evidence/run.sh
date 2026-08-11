#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR/backend"
python3 -m pytest -q tests/test_claim_evidence.py

cd "$ROOT_DIR/frontend"
npm run lint
npm run build
