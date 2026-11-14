# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Shared helpers for php-modernization skill scripts.

Used by both verify_php_project.py and introspect.py.
Stdlib-only — no third-party dependencies.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.1.0"
SKILL_ID = "php-modernization"
# The skill's SKILL.md sits next to scripts/ in the repository, in the
# Composer install and in both release archives.
SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
UNKNOWN_VERSION = "unknown"


def _frontmatter_lines(skill_md: Path) -> list[str]:
    """Return the non-blank, non-comment lines of the first frontmatter block.

    Empty when the file is missing or unreadable or has no frontmatter.
    """
    try:
        lines = skill_md.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    if not lines or lines[0].strip() != "---":
        return []
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.strip() and not line.lstrip().startswith("#"):
            block.append(line)
    return block


def read_skill_version(skill_md: Path = SKILL_MD) -> str:
    """Return ``metadata.version`` from the SKILL.md frontmatter.

    The release bump rewrites that line, so the reports follow it without a
    second copy of the version. Returns ``UNKNOWN_VERSION`` when the file is
    missing or unreadable, or when its frontmatter has no ``metadata.version``;
    the verifier still runs then. Only a ``version:`` directly under
    ``metadata:`` counts.
    """
    in_metadata = False
    child_indent: int | None = None
    for line in _frontmatter_lines(skill_md):
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


# ---------------------------------------------------------------------------
# Project tooling — read from files only; nothing here runs project code.
# ---------------------------------------------------------------------------

# Root first, then Build/ — the same list and the same order as PM-04/PM-05/
# PM-06/PM-24/PM-30 in checkpoints.yaml. A TYPO3 extension that keeps its build
# tooling under Build/ carries the config at Build/.php-cs-fixer.php; with a
# root-only list this verifier reported PM-04 as failed for a project that has
# one, while the YAML checkpoint passed.
PHP_CS_FIXER_CANDIDATES: tuple[str, ...] = (
    ".php-cs-fixer.php",
    ".php-cs-fixer.dist.php",
    "Build/.php-cs-fixer.php",
    "Build/.php-cs-fixer.dist.php",
)
# Same order as PM-01 in checkpoints.yaml and PHPStan's own precedence.
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
# Root first, then Build/. PHPCS itself looks for .phpcs.xml, phpcs.xml,
# .phpcs.xml.dist and phpcs.xml.dist in the working directory.
PHPCS_CONFIG_CANDIDATES: tuple[str, ...] = (
    ".phpcs.xml",
    "phpcs.xml",
    ".phpcs.xml.dist",
    "phpcs.xml.dist",
    "Build/phpcs.xml",
    "Build/phpcs.xml.dist",
    "Build/.phpcs.xml",
    "Build/.phpcs.xml.dist",
)
PHPUNIT_CONFIG_CANDIDATES: tuple[str, ...] = (
    "phpunit.xml",
    "phpunit.xml.dist",
    "phpunit.dist.xml",
    "Build/phpunit.xml",
    "Build/phpunit.xml.dist",
    # Unit tests only: a functional suite usually needs a database.
    "Build/phpunit/UnitTests.xml",
)
FRACTOR_CONFIG_CANDIDATES: tuple[str, ...] = (
    "fractor.php",
    "Build/fractor.php",
    "Build/fractor/fractor.php",
)
# Composer package name → tool. The lint tools are alternatives to `php -l`.
LINTER_PACKAGES: tuple[str, ...] = (
    "php-parallel-lint/php-parallel-lint",
    "overtrue/phplint",
)
CI_FILE_CANDIDATES: tuple[str, ...] = (
    ".gitlab-ci.yml",
    "Jenkinsfile",
    ".travis.yml",
    "bitbucket-pipelines.yml",
)
_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.:/-]*)\s*:(?!=)", re.MULTILINE)


def first_existing(root: Path, candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate (relative path) that is a file, or None."""
    for rel in candidates:
        if (root / rel).is_file():
            return rel
    return None


def bin_dirs(root: Path, composer: dict[str, Any] | None) -> list[Path]:
    """Directories that hold the project's Composer binaries.

    ``config.bin-dir`` from composer.json first, then the two layouts the
    skill knows: ``vendor/bin`` and the TYPO3 ``.Build/bin``.
    """
    dirs: list[Path] = []
    config = (composer or {}).get("config")
    if isinstance(config, dict) and isinstance(config.get("bin-dir"), str):
        dirs.append(root / config["bin-dir"])
    for rel in ("vendor/bin", ".Build/bin"):
        candidate = root / rel
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def find_binary(
    root: Path, name: str, composer: dict[str, Any] | None = None
) -> Path | None:
    """Return the project's own binary ``name``, or None."""
    for directory in bin_dirs(root, composer):
        p = directory / name
        if p.is_file():
            return p
    return None


def _autoload_paths(section: Any) -> list[str]:
    paths: list[str] = []
    if not isinstance(section, dict):
        return paths
    for key in ("psr-4", "psr-0"):
        mapping = section.get(key)
        if not isinstance(mapping, dict):
            continue
        for value in mapping.values():
            for entry in value if isinstance(value, list) else [value]:
                if isinstance(entry, str):
                    paths.append(entry)
    classmap = section.get("classmap")
    if isinstance(classmap, list):
        paths.extend(e for e in classmap if isinstance(e, str))
    return paths


def source_dirs(root: Path, composer: dict[str, Any] | None) -> dict[str, list[str]]:
    """Source and test directories from composer.json autoload sections.

    Only directories that exist are returned, normalised without a trailing
    slash. ``""`` and ``"."`` (the package root) become ``"."``. When composer
    declares nothing, the conventional ``src``/``Classes`` and
    ``tests``/``Tests`` directories are used if present.
    """

    def normalise(paths: list[str]) -> list[str]:
        out: list[str] = []
        for p in paths:
            rel = p.strip().rstrip("/") or "."
            if rel not in out and (root / rel).is_dir():
                out.append(rel)
        return out

    composer = composer or {}
    src = normalise(_autoload_paths(composer.get("autoload")))
    tests = normalise(_autoload_paths(composer.get("autoload-dev")))
    if not src:
        src = normalise(["src", "Classes"])
    if not tests:
        tests = normalise(["tests", "Tests"])
    return {"src": src, "tests": tests}


def composer_scripts(composer: dict[str, Any] | None) -> list[str]:
    """Names of the scripts in composer.json, in file order."""
    scripts = (composer or {}).get("scripts")
    if not isinstance(scripts, dict):
        return []
    return [name for name in scripts if isinstance(name, str)]


def makefile(root: Path) -> dict[str, Any] | None:
    """Targets of the top-level Makefile, or None without one.

    Includes are not followed: ``includes`` is true when the Makefile has an
    ``include`` line, and then ``make`` knows more targets than ``targets``
    lists — the agent reads the included files before calling a target absent.
    """
    for name in ("Makefile", "makefile", "GNUmakefile"):
        p = root / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        targets: list[str] = []
        for match in _MAKE_TARGET_RE.finditer(text):
            target = match.group(1)
            if not target.startswith(".") and target not in targets:
                targets.append(target)
        return {
            "file": name,
            "targets": targets,
            "includes": re.search(r"^-?include\s", text, re.MULTILINE) is not None,
        }
    return None


def ci_files(root: Path) -> list[str]:
    found = [rel for rel in CI_FILE_CANDIDATES if (root / rel).is_file()]
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        found.extend(
            str(p.relative_to(root))
            for p in sorted(workflows.iterdir())
            if p.suffix in {".yml", ".yaml"} and p.is_file()
        )
    return found


def coding_standard(root: Path, php_cs_fixer_config: str | None) -> str:
    """Which coding-standard tool the project configures.

    One of ``php-cs-fixer``, ``phpcs``, ``both`` or ``none``. A project picks
    one; the skill uses that one and does not ask for the other.
    """
    phpcs = first_existing(root, PHPCS_CONFIG_CANDIDATES) is not None
    fixer = php_cs_fixer_config is not None
    if fixer and phpcs:
        return "both"
    if fixer:
        return "php-cs-fixer"
    if phpcs:
        return "phpcs"
    return "none"
