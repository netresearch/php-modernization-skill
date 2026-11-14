#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Standalone PHP project introspection — agent-harness cheap first-touch.

Emits a project-profile JSON that captures archetype, PHP version, tooling
boolean fingerprints, the config file each tool uses, the coding-standard tool
(PHP-CS-Fixer or PHPCS), source and test directories, the project's own
commands (Composer scripts, Makefile targets, DDEV, CI files), PSR-4 autoload
mapping and baseline presence — without running any subprocess except
`php --version` to detect the runtime. Files are read, never executed.

Always exits 0 (informational, never fails). Output goes to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Sibling-import the shared module. PEP 723 scripts launched via `uv run`
# don't add their own directory to sys.path, so we add it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    FRACTOR_CONFIG_CANDIDATES,
    LINTER_PACKAGES,
    PHP_CS_FIXER_CANDIDATES,
    PHPCS_CONFIG_CANDIDATES,
    PHPUNIT_CONFIG_CANDIDATES,
    SCHEMA_VERSION,
    SKILL_ID,
    ci_files,
    coding_standard,
    composer_dep_mentions,
    composer_scripts,
    detect_archetype,
    first_existing,
    makefile,
    php_version_constraint,
    read_composer_json,
    source_dirs,
)

PHPSTAN_BASELINE_CANDIDATES: tuple[str, ...] = (
    "phpstan-baseline.neon",
    "Build/phpstan-baseline.neon",
    "Build/phpstan/phpstan-baseline.neon",
)
# Same lists and order as verify_php_project.py.
PHPSTAN_CONFIG_CANDIDATES: tuple[str, ...] = (
    "phpstan.neon",
    "phpstan.neon.dist",
    "Build/phpstan.neon",
    "Build/phpstan/phpstan.neon",
)
RECTOR_CONFIG_CANDIDATES: tuple[str, ...] = (
    "rector.php",
    "Build/rector.php",
    "Build/rector/rector.php",
)
PSALM_BASELINE_CANDIDATES: tuple[str, ...] = (
    "psalm-baseline.xml",
    "Build/psalm-baseline.xml",
)


_PHP_VERSION_RE = re.compile(r"PHP\s+(\d+\.\d+\.\d+)")


def _detect_php_runtime() -> str:
    """Return the installed PHP runtime version, or "unknown" if php missing.

    Uses ``php --version`` (faster and more conventional than ``php -r``)
    and parses the leading line, e.g. ``PHP 8.4.5 (cli) (built: ...)``.
    Returns ``"unknown"`` if php is missing, the call fails, or the output
    does not match the expected pattern (e.g. heavily-customised builds).
    """
    php = shutil.which("php")
    if not php:
        return "unknown"
    try:
        completed = subprocess.run(
            [php, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"
    out = (completed.stdout or "").strip()
    if not out:
        return "unknown"
    first_line = out.splitlines()[0]
    match = _PHP_VERSION_RE.search(first_line)
    return match.group(1) if match else "unknown"


def _autoload_psr4(composer: dict[str, Any] | None) -> dict[str, Any]:
    if not composer:
        return {}
    autoload = composer.get("autoload") or {}
    if not isinstance(autoload, dict):
        return {}
    psr4 = autoload.get("psr-4") or {}
    if isinstance(psr4, dict):
        return dict(psr4)
    return {}


def _has_baseline(root: Path, candidates: tuple[str, ...]) -> bool:
    return any((root / rel).is_file() for rel in candidates)


def build_profile(root: Path) -> dict[str, Any]:
    """Build the project-profile dict for a given root."""
    composer = read_composer_json(root)
    archetype = detect_archetype(root)

    tooling = {
        "phpstan": composer_dep_mentions(root, "phpstan"),
        "rector": composer_dep_mentions(root, "rector/rector"),
        "php_cs_fixer": composer_dep_mentions(root, "php-cs-fixer"),
        "phpat": composer_dep_mentions(root, "phpat"),
        "infection": composer_dep_mentions(root, "infection"),
        "psalm": composer_dep_mentions(root, "vimeo/psalm"),
        "phpcs": composer_dep_mentions(root, "squizlabs/php_codesniffer")
        or first_existing(root, PHPCS_CONFIG_CANDIDATES) is not None,
        "fractor": composer_dep_mentions(root, "a9f/fractor")
        or composer_dep_mentions(root, "a9f/typo3-fractor"),
        "phpunit": composer_dep_mentions(root, "phpunit/phpunit")
        or first_existing(root, PHPUNIT_CONFIG_CANDIDATES) is not None,
        "php_linter": any(composer_dep_mentions(root, pkg) for pkg in LINTER_PACKAGES),
        "composer_audit_supported": (root / "composer.lock").is_file()
        and (
            shutil.which("composer") is not None
            or (root / "vendor/bin/composer").is_file()
        ),
    }

    baselines = {
        "phpstan": _has_baseline(root, PHPSTAN_BASELINE_CANDIDATES),
        "psalm": _has_baseline(root, PSALM_BASELINE_CANDIDATES),
    }

    php_cs_fixer_config = first_existing(root, PHP_CS_FIXER_CANDIDATES)
    config_files = {
        "phpstan": first_existing(root, PHPSTAN_CONFIG_CANDIDATES),
        "rector": first_existing(root, RECTOR_CONFIG_CANDIDATES),
        "php_cs_fixer": php_cs_fixer_config,
        "phpcs": first_existing(root, PHPCS_CONFIG_CANDIDATES),
        "phpunit": first_existing(root, PHPUNIT_CONFIG_CANDIDATES),
        "fractor": first_existing(root, FRACTOR_CONFIG_CANDIDATES),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL_ID,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_root": str(root.resolve()),
        "archetype": archetype,
        "php_version_constraint": php_version_constraint(composer),
        "php_runtime": _detect_php_runtime(),
        "tooling": tooling,
        "config_files": config_files,
        "coding_standard": coding_standard(root, php_cs_fixer_config),
        "source_dirs": source_dirs(root, composer),
        "project_commands": {
            "composer_scripts": composer_scripts(composer),
            "makefile": makefile(root),
            "ddev": (root / ".ddev" / "config.yaml").is_file(),
            "ci_files": ci_files(root),
        },
        "autoload_psr4": _autoload_psr4(composer),
        "baselines": baselines,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="introspect",
        description="Cheap, fast PHP project introspection (php-modernization skill).",
    )
    parser.add_argument(
        "--root", default=".", help="Project root (default: current directory)"
    )
    parser.add_argument(
        "--format",
        choices=("json",),
        default="json",
        help="Output format (default: json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.stderr.write(f"warning: --root {args.root!r} is not a directory\n")
        # Even on bad root, emit a profile so callers always get JSON.
        profile = {
            "schema_version": SCHEMA_VERSION,
            "skill": SKILL_ID,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project_root": str(root),
            "archetype": "unknown",
            "php_version_constraint": "unknown",
            "php_runtime": "unknown",
            "tooling": {
                "phpstan": False,
                "rector": False,
                "php_cs_fixer": False,
                "phpat": False,
                "infection": False,
                "psalm": False,
                "phpcs": False,
                "fractor": False,
                "phpunit": False,
                "php_linter": False,
                "composer_audit_supported": False,
            },
            "config_files": {
                "phpstan": None,
                "rector": None,
                "php_cs_fixer": None,
                "phpcs": None,
                "phpunit": None,
                "fractor": None,
            },
            "coding_standard": "none",
            "source_dirs": {"src": [], "tests": []},
            "project_commands": {
                "composer_scripts": [],
                "makefile": None,
                "ddev": False,
                "ci_files": [],
            },
            "autoload_psr4": {},
            "baselines": {"phpstan": False, "psalm": False},
        }
    else:
        profile = build_profile(root)

    sys.stdout.write(json.dumps(profile, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
