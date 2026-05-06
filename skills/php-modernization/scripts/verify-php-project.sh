#!/usr/bin/env bash
# Backward-compatible wrapper. Delegates to verify_php_project.py.
# Usage: verify-php-project.sh [project-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${1:-.}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: 'uv' is required to run the verifier (install: https://docs.astral.sh/uv/)" >&2
    echo "       Falls back to direct python3 invocation if available..." >&2
    if command -v python3 >/dev/null 2>&1; then
        exec python3 "$SCRIPT_DIR/verify_php_project.py" --root "$PROJECT_DIR" --format json
    fi
    exit 1
fi

exec uv run "$SCRIPT_DIR/verify_php_project.py" --root "$PROJECT_DIR" --format json
