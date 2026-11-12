# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Shared helpers for php-modernization skill scripts.

Used by both verify_php_project.py and introspect.py.
Stdlib-only — no third-party dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
SKILL_ID = "php-modernization"
# The skill's SKILL.md sits next to scripts/ in the repository, in the
# Composer install and in both release archives.
SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
UNKNOWN_VERSION = "unknown"


def read_skill_version(skill_md: Path = SKILL_MD) -> str:
    """Return ``metadata.version`` from the SKILL.md frontmatter.

    The release bump rewrites that line, so the reports follow it without a
    second copy of the version. Returns ``UNKNOWN_VERSION`` when the file is
    missing or unreadable, or when its frontmatter has no ``metadata.version``;
    the verifier still runs then. Only a ``version:`` directly under
    ``metadata:`` counts.
    """
    try:
        lines = skill_md.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return UNKNOWN_VERSION
    if not lines or lines[0].strip() != "---":
        return UNKNOWN_VERSION
    in_metadata = False
    child_indent: int | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            in_metadata = line.split("#", 1)[0].strip() == "metadata:"
            child_indent = None
            continue
        if not in_metadata:
            continue
        # The first key under metadata: sets the indentation of its direct
        # children; a version: nested deeper belongs to another mapping.
        indent = len(line) - len(line.lstrip())
        if child_indent is None:
            child_indent = indent
        key, sep, value = line.strip().partition(":")
        if indent == child_indent and sep and key == "version":
            value = value.split(" #", 1)[0].strip().strip("\"'").strip()
            return value or UNKNOWN_VERSION
    return UNKNOWN_VERSION


SKILL_VERSION = read_skill_version()


def detect_archetype(root: Path) -> str:
    """Classify a PHP project root by archetype.

    Returns one of: typo3-extension, symfony-app, monorepo-package,
    generic-composer, unknown.

    The ``generic-composer`` fallback recognises plain Composer libraries
    that lack framework markers but still declare a PSR-4 autoload mapping
    or carry a top-level ``src/`` directory. This matches typical SDK and
    library shapes (e.g. ``netresearch/sdk-api-central-station``) where
    requiring both ``src/`` and ``tests/`` would produce false ``unknown``
    classifications.
    """
    if (root / "ext_emconf.php").is_file():
        return "typo3-extension"
    if (root / "Configuration" / "Services.yaml").is_file():
        return "typo3-extension"
    if (root / "bin" / "console").is_file() and (
        root / "config" / "bundles.php"
    ).is_file():
        return "symfony-app"
    packages_dir = root / "packages"
    if packages_dir.is_dir():
        nested = sum(
            1
            for child in packages_dir.iterdir()
            if child.is_dir() and (child / "composer.json").is_file()
        )
        if nested >= 2:
            return "monorepo-package"
    if (root / "composer.json").is_file():
        if (root / "src").is_dir():
            return "generic-composer"
        composer = read_composer_json(root)
        if composer is not None:
            autoload = composer.get("autoload") or {}
            if isinstance(autoload, dict):
                psr4 = autoload.get("psr-4")
                if isinstance(psr4, dict) and psr4:
                    return "generic-composer"
    return "unknown"


def read_composer_json(root: Path) -> dict[str, Any] | None:
    """Parse composer.json at the project root, or None if missing/invalid.

    A file that parses to something other than a JSON object is invalid too:
    every caller reads it with ``.get``.
    """
    p = root / "composer.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def php_version_constraint(composer: dict[str, Any] | None) -> str:
    """Resolve the declared PHP version constraint.

    Priority: config.platform.php (composer's runtime override) → require.php
    → "unknown".
    """
    if not composer:
        return "unknown"
    config = composer.get("config") or {}
    if isinstance(config, dict):
        platform = config.get("platform") or {}
        if isinstance(platform, dict) and "php" in platform:
            return str(platform["php"])
    require = composer.get("require") or {}
    if isinstance(require, dict) and "php" in require:
        return str(require["php"])
    return "unknown"


def text_contains(path: Path, needle: str) -> bool:
    """True if the file at `path` contains `needle` (best-effort, never raises)."""
    try:
        return needle in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def composer_dep_mentions(root: Path, needle: str) -> bool:
    """True if `needle` appears in composer.json or composer.lock."""
    for rel in ("composer.json", "composer.lock"):
        p = root / rel
        if p.is_file() and text_contains(p, needle):
            return True
    return False
