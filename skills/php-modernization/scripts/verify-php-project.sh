#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
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
    # The scripts need Python 3.11 or later (datetime.UTC, tomllib); an older
    # python3 would die on an ImportError, so it is not a fallback.
    if command -v python3 >/dev/null 2>&1 \
        && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        exec python3 "$TARGET" "${ARGS[@]}"
    fi
    echo "ERROR: this tool needs 'uv' (install: https://docs.astral.sh/uv/) or python3 3.11 or later" >&2
    exit 1
fi

exec uv run "$TARGET" "${ARGS[@]}"
