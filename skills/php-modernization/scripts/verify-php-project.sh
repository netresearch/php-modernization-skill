#!/usr/bin/env bash
# Backward-compatible wrapper. Delegates to verify_php_project.py (default)
# or introspect.py (when first arg is "introspect").
#
# Usage:
#   verify-php-project.sh [project-dir]              # full verifier
#   verify-php-project.sh introspect [project-dir]   # cheap introspection
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Subcommand dispatch — first argument decides target script.
SUBCOMMAND="verify"
if [[ $# -gt 0 && "$1" == "introspect" ]]; then
    SUBCOMMAND="introspect"
    shift
fi

PROJECT_DIR="${1:-.}"

case "$SUBCOMMAND" in
    introspect)
        TARGET="$SCRIPT_DIR/introspect.py"
        ARGS=(--root "$PROJECT_DIR" --format json)
        ;;
    verify)
        TARGET="$SCRIPT_DIR/verify_php_project.py"
        ARGS=(--root "$PROJECT_DIR" --format json)
        ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: 'uv' is required to run this tool (install: https://docs.astral.sh/uv/)" >&2
    echo "       Falls back to direct python3 invocation if available..." >&2
    if command -v python3 >/dev/null 2>&1; then
        exec python3 "$TARGET" "${ARGS[@]}"
    fi
    exit 1
fi

exec uv run "$TARGET" "${ARGS[@]}"
