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
SKILL_VERSION = "1.17.0"


def detect_archetype(root: Path) -> str:
    """Classify a PHP project root by archetype.

    Returns one of: typo3-extension, symfony-app, monorepo-package,
    generic-composer, unknown.
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
    if (
        (root / "composer.json").is_file()
        and (root / "src").is_dir()
        and (root / "tests").is_dir()
    ):
        return "generic-composer"
    return "unknown"


def read_composer_json(root: Path) -> dict[str, Any] | None:
    """Parse composer.json at the project root, or None if missing/invalid."""
    p = root / "composer.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


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
