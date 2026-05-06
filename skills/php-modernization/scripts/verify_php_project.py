#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PHP modernization verifier — agent-harness primary discovery tool.

Implements a curated subset of the mechanical checkpoints (PM-XX IDs) defined
in checkpoints.yaml — the ones that benefit from a structured Python evaluator
(JSON+SARIF output, archetype detection, agent_actions[]). The full checkpoint
catalog (including LLM reviews) is in checkpoints.yaml; this verifier does not
read or parse that file dynamically. Checkpoint IDs are deliberately mirrored
so that findings cross-reference cleanly.

Emits stable JSON 1.0.0 or SARIF 2.1.0. Exit code: 0 on pass/warn, 1 on fail.
The JSON schema is a public contract; checkpoint IDs are never renumbered.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Sibling-import the shared module. PEP 723 scripts launched via `uv run`
# don't add their own directory to sys.path, so we add it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    SCHEMA_VERSION,
    SKILL_ID,
    SKILL_VERSION,
    composer_dep_mentions,
    detect_archetype,
    php_version_constraint,
    read_composer_json,
    text_contains,
)

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URI = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"

DEFAULT_CACHE_PATH = Path(".build/php-modernization/last-run.json")
ARTIFACT_DIR = Path(".build/php-modernization")

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
PHP_CS_FIXER_CANDIDATES: tuple[str, ...] = (
    ".php-cs-fixer.php",
    ".php-cs-fixer.dist.php",
)
PHPSTAN_BASELINE_CANDIDATES: tuple[str, ...] = (
    "phpstan-baseline.neon",
    "Build/phpstan-baseline.neon",
    "Build/phpstan/phpstan-baseline.neon",
)

PHPSTAN_LEVEL_RE = re.compile(r"^[\t ]*level:[\t ]*(?P<level>\S+)", re.MULTILINE)

SUBPROCESS_TIMEOUT_SECONDS = 300


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Check:
    """One mechanical checkpoint result."""

    id: str
    category: str
    severity: str  # error | warning | info
    status: str  # pass | fail | skipped
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class AgentAction:
    """A concrete next-step the orchestrating agent should consider."""

    action: str  # edit_file | run_orchestrator | read_reference
    checkpoint: str
    target: str
    operation: str
    rationale: str
    confirm_required: bool = False


@dataclass
class ToolRun:
    """Outcome of a subprocess invocation against the project."""

    tool: str
    status: str  # pass | fail | skipped | timeout | error
    exit_code: int | None
    command: str
    artifact: str | None = None


@dataclass
class Tooling:
    phpstan: dict[str, Any]
    rector: dict[str, Any]
    php_cs_fixer: dict[str, Any]
    phpat: dict[str, Any]
    infection: dict[str, Any]
    composer_audit_supported: bool


@dataclass
class Environment:
    php_version_constraint: str
    php_runtime: str
    composer_json: bool
    composer_lock: bool


@dataclass
class Summary:
    status: str  # pass | warn | fail
    errors: int
    warnings: int
    info: int


@dataclass
class Report:
    schema_version: str
    skill: str
    skill_version: str
    generated_at: str
    project_root: str
    archetype: str
    summary: Summary
    environment: Environment
    tooling: Tooling
    checks: list[Check]
    agent_actions: list[AgentAction]
    tool_runs: list[ToolRun]


# ---------------------------------------------------------------------------
# Pure helpers — no IO except via Path arguments
# ---------------------------------------------------------------------------


def find_first_existing(root: Path, candidates: Iterable[str]) -> Path | None:
    for rel in candidates:
        p = root / rel
        if p.is_file():
            return p
    return None


def detect_php_runtime() -> str:
    php = shutil.which("php")
    if not php:
        return "unknown"
    try:
        completed = subprocess.run(
            [php, "-r", "echo PHP_VERSION;"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"
    out = (completed.stdout or "").strip()
    return out if out else "unknown"


def parse_phpstan_level(text: str) -> str | None:
    """Return the raw level token from a phpstan.neon body, or None."""
    m = PHPSTAN_LEVEL_RE.search(text)
    if not m:
        return None
    return m.group("level").strip()


def phpstan_level_meets_threshold(level_token: str | None) -> bool:
    if level_token is None:
        return False
    if level_token in {"max", "10"}:
        return True
    if level_token.isdigit():
        return int(level_token) >= 9
    return False


def composer_has_script(
    composer: dict[str, Any] | None, names: Iterable[str]
) -> str | None:
    if not composer:
        return None
    scripts = composer.get("scripts") or {}
    if not isinstance(scripts, dict):
        return None
    for name in names:
        if name in scripts:
            return name
    return None


def find_in_files(root: Path, files: Iterable[str], needle: str) -> Path | None:
    for rel in files:
        p = root / rel
        if p.is_file() and text_contains(p, needle):
            return p
    return None


def has_phpstan_binary(root: Path) -> Path | None:
    for rel in ("vendor/bin/phpstan", ".Build/bin/phpstan"):
        p = root / rel
        if p.is_file():
            return p
    return None


def has_php_cs_fixer_binary(root: Path) -> Path | None:
    for rel in ("vendor/bin/php-cs-fixer", ".Build/bin/php-cs-fixer"):
        p = root / rel
        if p.is_file():
            return p
    return None


def has_rector_binary(root: Path) -> Path | None:
    for rel in ("vendor/bin/rector", ".Build/bin/rector"):
        p = root / rel
        if p.is_file():
            return p
    return None


def has_infection_binary(root: Path) -> Path | None:
    for rel in ("vendor/bin/infection", ".Build/bin/infection"):
        p = root / rel
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Mechanical checks
# ---------------------------------------------------------------------------


def check_pm01(root: Path) -> tuple[Check, Path | None]:
    config = find_first_existing(root, PHPSTAN_CONFIG_CANDIDATES)
    if config is not None:
        return (
            Check(
                id="PM-01",
                category="phpstan",
                severity="error",
                status="pass",
                message=f"PHPStan configuration found at {config.relative_to(root)}",
                evidence=[str(config.relative_to(root))],
            ),
            config,
        )
    return (
        Check(
            id="PM-01",
            category="phpstan",
            severity="error",
            status="fail",
            message="PHPStan configuration is missing",
            evidence=list(PHPSTAN_CONFIG_CANDIDATES),
        ),
        None,
    )


def check_pm02(root: Path, config: Path | None) -> tuple[Check, str | None]:
    if config is None:
        return (
            Check(
                id="PM-02",
                category="phpstan",
                severity="error",
                status="skipped",
                message="PHPStan configuration not found; level cannot be evaluated",
            ),
            None,
        )
    try:
        body = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        body = ""
    level = parse_phpstan_level(body)
    if phpstan_level_meets_threshold(level):
        return (
            Check(
                id="PM-02",
                category="phpstan",
                severity="error",
                status="pass",
                message=f"PHPStan level is '{level}' (>= 9 / max)",
                evidence=[str(config.relative_to(root))],
            ),
            level,
        )
    return (
        Check(
            id="PM-02",
            category="phpstan",
            severity="error",
            status="fail",
            message=f"PHPStan level '{level or 'unset'}' is below the required 9/max",
            evidence=[str(config.relative_to(root))],
        ),
        level,
    )


def check_pm03(root: Path, config: Path | None) -> Check:
    if config is None:
        return Check(
            id="PM-03",
            category="phpstan",
            severity="warning",
            status="skipped",
            message="PHPStan configuration not found",
        )
    if text_contains(config, "treatPhpDocTypesAsCertain: false"):
        return Check(
            id="PM-03",
            category="phpstan",
            severity="warning",
            status="pass",
            message="treatPhpDocTypesAsCertain is set to false",
            evidence=[str(config.relative_to(root))],
        )
    return Check(
        id="PM-03",
        category="phpstan",
        severity="warning",
        status="fail",
        message="treatPhpDocTypesAsCertain: false is missing — PHPDoc types are trusted over runtime",
        evidence=[str(config.relative_to(root))],
    )


def check_pm04(root: Path) -> tuple[Check, Path | None]:
    config = find_first_existing(root, PHP_CS_FIXER_CANDIDATES)
    if config is not None:
        return (
            Check(
                id="PM-04",
                category="php-cs-fixer",
                severity="error",
                status="pass",
                message=f"PHP-CS-Fixer config found at {config.relative_to(root)}",
                evidence=[str(config.relative_to(root))],
            ),
            config,
        )
    return (
        Check(
            id="PM-04",
            category="php-cs-fixer",
            severity="error",
            status="fail",
            message="PHP-CS-Fixer configuration is missing",
            evidence=list(PHP_CS_FIXER_CANDIDATES),
        ),
        None,
    )


def check_pm05(root: Path, config: Path | None) -> Check:
    if config is None:
        return Check(
            id="PM-05",
            category="php-cs-fixer",
            severity="error",
            status="skipped",
            message="PHP-CS-Fixer configuration not found",
        )
    if text_contains(config, "@PER-CS"):
        return Check(
            id="PM-05",
            category="php-cs-fixer",
            severity="error",
            status="pass",
            message="@PER-CS ruleset is enabled",
            evidence=[str(config.relative_to(root))],
        )
    return Check(
        id="PM-05",
        category="php-cs-fixer",
        severity="error",
        status="fail",
        message="@PER-CS ruleset is not present in PHP-CS-Fixer config",
        evidence=[str(config.relative_to(root))],
    )


def check_pm09(root: Path) -> tuple[Check, Path | None]:
    config = find_first_existing(root, RECTOR_CONFIG_CANDIDATES)
    if config is not None:
        return (
            Check(
                id="PM-09",
                category="rector",
                severity="warning",
                status="pass",
                message=f"Rector config found at {config.relative_to(root)}",
                evidence=[str(config.relative_to(root))],
            ),
            config,
        )
    return (
        Check(
            id="PM-09",
            category="rector",
            severity="warning",
            status="fail",
            message="Rector configuration is missing",
            evidence=list(RECTOR_CONFIG_CANDIDATES),
        ),
        None,
    )


def check_pm13(composer: dict[str, Any] | None) -> Check:
    found = composer_has_script(composer, ("cs:fix", "fix:cs", "php:cs:fix"))
    if found:
        return Check(
            id="PM-13",
            category="composer",
            severity="warning",
            status="pass",
            message=f"composer script '{found}' is defined",
            evidence=["composer.json"],
        )
    return Check(
        id="PM-13",
        category="composer",
        severity="warning",
        status="fail",
        message="No coding-standards fix script (cs:fix/fix:cs/php:cs:fix) found in composer.json",
        evidence=["composer.json"],
    )


def check_pm14(composer: dict[str, Any] | None) -> Check:
    found = composer_has_script(composer, ("phpstan", "analyse", "analyze"))
    if found:
        return Check(
            id="PM-14",
            category="composer",
            severity="warning",
            status="pass",
            message=f"composer script '{found}' is defined",
            evidence=["composer.json"],
        )
    return Check(
        id="PM-14",
        category="composer",
        severity="warning",
        status="fail",
        message="No PHPStan script (phpstan/analyse/analyze) found in composer.json",
        evidence=["composer.json"],
    )


def check_pm15(composer: dict[str, Any] | None) -> Check:
    found = composer_has_script(composer, ("rector", "refactor"))
    if found:
        return Check(
            id="PM-15",
            category="composer",
            severity="info",
            status="pass",
            message=f"composer script '{found}' is defined",
            evidence=["composer.json"],
        )
    return Check(
        id="PM-15",
        category="composer",
        severity="info",
        status="fail",
        message="No Rector script (rector/refactor) found in composer.json",
        evidence=["composer.json"],
    )


def check_pm16(root: Path) -> Check:
    if has_phpstan_binary(root) is not None or composer_dep_mentions(root, "phpstan"):
        return Check(
            id="PM-16",
            category="dependencies",
            severity="warning",
            status="pass",
            message="PHPStan is available (binary or composer dependency)",
        )
    return Check(
        id="PM-16",
        category="dependencies",
        severity="warning",
        status="fail",
        message="PHPStan is not available — neither binary nor composer dependency detected",
    )


def check_pm17(root: Path) -> Check:
    if has_php_cs_fixer_binary(root) is not None or composer_dep_mentions(
        root, "php-cs-fixer"
    ):
        return Check(
            id="PM-17",
            category="dependencies",
            severity="warning",
            status="pass",
            message="PHP-CS-Fixer is available (binary or composer dependency)",
        )
    return Check(
        id="PM-17",
        category="dependencies",
        severity="warning",
        status="fail",
        message="PHP-CS-Fixer is not available — neither binary nor composer dependency detected",
    )


def check_pm19(composer: dict[str, Any] | None) -> Check:
    if not composer:
        return Check(
            id="PM-19",
            category="composer",
            severity="error",
            status="fail",
            message="composer.json is missing or unparseable",
            evidence=["composer.json"],
        )
    autoload = composer.get("autoload") or {}
    psr4 = autoload.get("psr-4") if isinstance(autoload, dict) else None
    if isinstance(psr4, dict) and psr4:
        return Check(
            id="PM-19",
            category="composer",
            severity="error",
            status="pass",
            message=f"PSR-4 autoload defined ({len(psr4)} namespace mapping(s))",
            evidence=["composer.json"],
        )
    return Check(
        id="PM-19",
        category="composer",
        severity="error",
        status="fail",
        message="composer.json autoload.psr-4 is missing or empty",
        evidence=["composer.json"],
    )


def check_pm25(root: Path) -> Check:
    if composer_dep_mentions(root, "phpat"):
        return Check(
            id="PM-25",
            category="architecture",
            severity="info",
            status="pass",
            message="phpat is referenced in composer dependencies",
        )
    return Check(
        id="PM-25",
        category="architecture",
        severity="info",
        status="fail",
        message="phpat is not configured — architecture tests recommended",
    )


def check_pm53(root: Path, config: Path | None, level: str | None) -> Check:
    if config is None:
        return Check(
            id="PM-53",
            category="phpstan",
            severity="warning",
            status="skipped",
            message="PHPStan configuration not found",
        )
    if level in {"max", "10"}:
        return Check(
            id="PM-53",
            category="phpstan",
            severity="warning",
            status="pass",
            message=f"PHPStan level is '{level}' (max)",
            evidence=[str(config.relative_to(root))],
        )
    return Check(
        id="PM-53",
        category="phpstan",
        severity="warning",
        status="fail",
        message=f"PHPStan level is '{level or 'unset'}' — recommend 10/max",
        evidence=[str(config.relative_to(root))],
    )


# ---------------------------------------------------------------------------
# Action generation
# ---------------------------------------------------------------------------


_ACTION_BY_CHECKPOINT: dict[str, dict[str, Any]] = {
    "PM-01": {
        "action": "edit_file",
        "target": "phpstan.neon",
        "operation": "create_phpstan_config",
        "rationale": "PHPStan must be configured (phpstan.neon or phpstan.neon.dist)",
        "confirm_required": False,
    },
    "PM-02": {
        "action": "edit_file",
        "target": "phpstan.neon",
        "operation": "raise_level_to_max",
        "rationale": "PHPStan level must be 9 or higher (or max) for strict typing",
        "confirm_required": False,
    },
    "PM-03": {
        "action": "edit_file",
        "target": "phpstan.neon",
        "operation": "set_treat_phpdoc_types_as_certain_false",
        "rationale": "treatPhpDocTypesAsCertain: false ensures PHPStan does not trust PHPDoc over runtime",
        "confirm_required": False,
    },
    "PM-04": {
        "action": "edit_file",
        "target": ".php-cs-fixer.dist.php",
        "operation": "create_php_cs_fixer_config",
        "rationale": "PHP-CS-Fixer must be configured to enforce coding standards",
        "confirm_required": False,
    },
    "PM-05": {
        "action": "edit_file",
        "target": ".php-cs-fixer.dist.php",
        "operation": "add_per_cs_ruleset",
        "rationale": "@PER-CS is the active PER coding-style ruleset replacing @PSR12",
        "confirm_required": False,
    },
    "PM-09": {
        "action": "edit_file",
        "target": "rector.php",
        "operation": "create_rector_config",
        "rationale": "Rector enables automated refactoring for PHP version upgrades",
        "confirm_required": False,
    },
    "PM-13": {
        "action": "edit_file",
        "target": "composer.json",
        "operation": "add_cs_fix_script",
        "rationale": "Coding-standards fix script makes the toolchain runnable via composer",
        "confirm_required": False,
    },
    "PM-14": {
        "action": "edit_file",
        "target": "composer.json",
        "operation": "add_phpstan_script",
        "rationale": "PHPStan script makes static analysis runnable via composer",
        "confirm_required": False,
    },
    "PM-15": {
        "action": "edit_file",
        "target": "composer.json",
        "operation": "add_rector_script",
        "rationale": "Rector script makes automated refactoring runnable via composer",
        "confirm_required": False,
    },
    "PM-16": {
        "action": "edit_file",
        "target": "composer.json",
        "operation": "require_dev_phpstan",
        "rationale": "Add phpstan/phpstan to require-dev or rely on a transitive CI package",
        "confirm_required": False,
    },
    "PM-17": {
        "action": "edit_file",
        "target": "composer.json",
        "operation": "require_dev_php_cs_fixer",
        "rationale": "Add friendsofphp/php-cs-fixer to require-dev or rely on a transitive CI package",
        "confirm_required": False,
    },
    "PM-19": {
        "action": "edit_file",
        "target": "composer.json",
        "operation": "add_psr4_autoload",
        "rationale": "PSR-4 autoload is required for class loading",
        "confirm_required": True,
    },
    "PM-25": {
        "action": "read_reference",
        "target": "skills/php-modernization/references/static-analysis-tools.md",
        "operation": "introduce_phpat",
        "rationale": "phpat enforces architectural rules in CI",
        "confirm_required": False,
    },
    "PM-53": {
        "action": "edit_file",
        "target": "phpstan.neon",
        "operation": "set_level_max",
        "rationale": "Level 10/max provides full strict typing",
        "confirm_required": False,
    },
}


def build_actions(checks: Iterable[Check], tooling: Tooling) -> list[AgentAction]:
    out: list[AgentAction] = []
    for c in checks:
        if c.status != "fail":
            continue
        spec = _ACTION_BY_CHECKPOINT.get(c.id)
        if spec is None:
            continue
        target = spec["target"]
        if c.id in {"PM-02", "PM-03", "PM-53"} and tooling.phpstan.get("config_file"):
            target = tooling.phpstan["config_file"]
        elif c.id in {"PM-04", "PM-05"} and tooling.php_cs_fixer.get("config_file"):
            target = tooling.php_cs_fixer["config_file"]
        elif c.id == "PM-09" and tooling.rector.get("config_file"):
            target = tooling.rector["config_file"]
        out.append(
            AgentAction(
                action=spec["action"],
                checkpoint=c.id,
                target=target,
                operation=spec["operation"],
                rationale=spec["rationale"],
                confirm_required=bool(spec["confirm_required"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Optional toolchain runs (skipped under --no-tools)
# ---------------------------------------------------------------------------


def _ensure_artifact_dir(root: Path) -> Path:
    target = root / ARTIFACT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_phpstan(root: Path) -> ToolRun | None:
    binary = has_phpstan_binary(root)
    if binary is None:
        return None
    cmd = [str(binary), "analyse", "--no-progress", "--error-format=json"]
    artifact = _ensure_artifact_dir(root) / "phpstan.json"
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ToolRun(
            tool="phpstan",
            status="timeout",
            exit_code=None,
            command=" ".join(cmd),
            artifact=None,
        )
    except OSError:
        return ToolRun(
            tool="phpstan",
            status="error",
            exit_code=None,
            command=" ".join(cmd),
            artifact=None,
        )
    try:
        artifact.write_text(completed.stdout or "", encoding="utf-8")
    except OSError:
        pass
    status = "pass" if completed.returncode == 0 else "fail"
    return ToolRun(
        tool="phpstan",
        status=status,
        exit_code=completed.returncode,
        command=" ".join(cmd),
        artifact=str(artifact.relative_to(root)),
    )


def run_composer_audit(root: Path) -> ToolRun | None:
    if not (root / "composer.lock").is_file():
        return None
    composer_cmd: list[str] | None = None
    on_path = shutil.which("composer")
    if on_path:
        composer_cmd = [on_path]
    else:
        vendored = root / "vendor" / "bin" / "composer"
        if vendored.is_file():
            composer_cmd = [str(vendored)]
    if composer_cmd is None:
        return None
    cmd = composer_cmd + ["audit", "--locked", "--format=json"]
    artifact = _ensure_artifact_dir(root) / "composer-audit.json"
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ToolRun(
            tool="composer-audit",
            status="timeout",
            exit_code=None,
            command=" ".join(cmd),
            artifact=None,
        )
    except OSError:
        return ToolRun(
            tool="composer-audit",
            status="error",
            exit_code=None,
            command=" ".join(cmd),
            artifact=None,
        )
    try:
        artifact.write_text(completed.stdout or "", encoding="utf-8")
    except OSError:
        pass
    # composer audit exits non-zero when vulnerabilities are found.
    status = "pass" if completed.returncode == 0 else "fail"
    return ToolRun(
        tool="composer-audit",
        status=status,
        exit_code=completed.returncode,
        command=" ".join(cmd),
        artifact=str(artifact.relative_to(root)),
    )


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


CACHE_INVALIDATION_FILES: tuple[str, ...] = (
    "composer.json",
    "composer.lock",
    "phpstan.neon",
    "phpstan.neon.dist",
    "Build/phpstan.neon",
    "Build/phpstan/phpstan.neon",
    "rector.php",
    ".php-cs-fixer.php",
    ".php-cs-fixer.dist.php",
)


def cache_signature(root: Path) -> dict[str, float]:
    sig: dict[str, float] = {}
    for rel in CACHE_INVALIDATION_FILES:
        p = root / rel
        if p.is_file():
            try:
                sig[rel] = p.stat().st_mtime
            except OSError:
                continue
    return sig


def cache_load(
    cache_path: Path,
    expected_signature: dict[str, float],
    expected_flags: dict[str, Any],
) -> dict[str, Any] | None:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("signature") != expected_signature:
        return None
    if payload.get("flags") != expected_flags:
        return None
    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    return report


def cache_store(
    cache_path: Path,
    signature: dict[str, float],
    flags: dict[str, Any],
    report: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"signature": signature, "flags": flags, "report": report}
    try:
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        # Cache is best-effort; never block the verifier on cache writes.
        pass


# ---------------------------------------------------------------------------
# Verifier orchestration
# ---------------------------------------------------------------------------


def evaluate(root: Path, *, run_tools: bool) -> Report:
    archetype = detect_archetype(root)
    composer = read_composer_json(root)
    php_constraint = php_version_constraint(composer)
    php_runtime = detect_php_runtime()

    check_01, phpstan_cfg = check_pm01(root)
    check_02, phpstan_level = check_pm02(root, phpstan_cfg)
    check_03 = check_pm03(root, phpstan_cfg)
    check_04, phpcs_cfg = check_pm04(root)
    check_05 = check_pm05(root, phpcs_cfg)
    check_09, rector_cfg = check_pm09(root)
    check_13 = check_pm13(composer)
    check_14 = check_pm14(composer)
    check_15 = check_pm15(composer)
    check_16 = check_pm16(root)
    check_17 = check_pm17(root)
    check_19 = check_pm19(composer)
    check_25 = check_pm25(root)
    check_53 = check_pm53(root, phpstan_cfg, phpstan_level)

    checks: list[Check] = [
        check_01,
        check_02,
        check_03,
        check_04,
        check_05,
        check_09,
        check_13,
        check_14,
        check_15,
        check_16,
        check_17,
        check_19,
        check_25,
        check_53,
    ]

    baseline = find_first_existing(root, PHPSTAN_BASELINE_CANDIDATES)
    tooling = Tooling(
        phpstan={
            "configured": phpstan_cfg is not None,
            "config_file": str(phpstan_cfg.relative_to(root)) if phpstan_cfg else None,
            "level": phpstan_level,
            "baseline": str(baseline.relative_to(root)) if baseline else None,
        },
        rector={
            "configured": rector_cfg is not None,
            "config_file": str(rector_cfg.relative_to(root)) if rector_cfg else None,
        },
        php_cs_fixer={
            "configured": phpcs_cfg is not None,
            "config_file": str(phpcs_cfg.relative_to(root)) if phpcs_cfg else None,
            "ruleset_includes_per_cs": (
                bool(phpcs_cfg) and text_contains(phpcs_cfg, "@PER-CS")  # type: ignore[arg-type]
            ),
        },
        phpat={"configured": composer_dep_mentions(root, "phpat")},
        infection={
            "configured": (root / "infection.json").is_file()
            or (root / "infection.json5").is_file()
        },
        composer_audit_supported=(root / "composer.lock").is_file()
        and (
            shutil.which("composer") is not None
            or (root / "vendor/bin/composer").is_file()
        ),
    )

    environment = Environment(
        php_version_constraint=php_constraint,
        php_runtime=php_runtime,
        composer_json=(root / "composer.json").is_file(),
        composer_lock=(root / "composer.lock").is_file(),
    )

    actions = build_actions(checks, tooling)

    tool_runs: list[ToolRun] = []
    if run_tools:
        for runner in (run_phpstan, run_composer_audit):
            result = runner(root)
            if result is not None:
                tool_runs.append(result)

    summary = build_summary(checks)

    return Report(
        schema_version=SCHEMA_VERSION,
        skill=SKILL_ID,
        skill_version=SKILL_VERSION,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        project_root=str(root.resolve()),
        archetype=archetype,
        summary=summary,
        environment=environment,
        tooling=tooling,
        checks=checks,
        agent_actions=actions,
        tool_runs=tool_runs,
    )


def build_summary(checks: Iterable[Check]) -> Summary:
    errors = warnings = info = 0
    for c in checks:
        if c.status != "fail":
            continue
        if c.severity == "error":
            errors += 1
        elif c.severity == "warning":
            warnings += 1
        elif c.severity == "info":
            info += 1
    if errors > 0:
        status = "fail"
    elif warnings > 0:
        status = "warn"
    else:
        status = "pass"
    return Summary(status=status, errors=errors, warnings=warnings, info=info)


# ---------------------------------------------------------------------------
# Output adapters
# ---------------------------------------------------------------------------


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def report_to_dict(report: Report) -> dict[str, Any]:
    return asdict(report)


def filter_to_checkpoint(
    report_dict: dict[str, Any], checkpoint_id: str
) -> dict[str, Any]:
    filtered = dict(report_dict)
    filtered["checks"] = [
        c for c in report_dict.get("checks", []) if c.get("id") == checkpoint_id
    ]
    filtered["agent_actions"] = [
        a
        for a in report_dict.get("agent_actions", [])
        if a.get("checkpoint") == checkpoint_id
    ]
    return filtered


def summarize(report_dict: dict[str, Any]) -> dict[str, Any]:
    summarized = dict(report_dict)
    failed = [c for c in report_dict.get("checks", []) if c.get("status") == "fail"]
    failed.sort(
        key=lambda c: (
            _SEVERITY_ORDER.get(c.get("severity", "info"), 9),
            c.get("id", ""),
        )
    )
    summarized["checks"] = failed[:3]
    summarized["agent_actions"] = report_dict.get("agent_actions", [])[:3]
    summarized["tool_runs"] = []
    return summarized


_SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


def to_sarif(report: Report) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    seen_rules: set[str] = set()
    for c in report.checks:
        if c.id in seen_rules:
            continue
        seen_rules.add(c.id)
        rules.append(
            {
                "id": c.id,
                "name": c.id.replace("-", "_"),
                "shortDescription": {"text": c.id},
                "fullDescription": {"text": c.message},
                "defaultConfiguration": {"level": _SARIF_LEVEL.get(c.severity, "note")},
                "properties": {
                    "category": c.category,
                    "skill": SKILL_ID,
                    "skillVersion": SKILL_VERSION,
                },
            }
        )
    results: list[dict[str, Any]] = []
    for c in report.checks:
        if c.status != "fail":
            continue
        primary_uri = c.evidence[0] if c.evidence else "."
        results.append(
            {
                "ruleId": c.id,
                "level": _SARIF_LEVEL.get(c.severity, "note"),
                "message": {"text": c.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": primary_uri},
                        }
                    }
                ],
            }
        )
    return {
        "$schema": SARIF_SCHEMA_URI,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "php-modernization-verifier",
                        "version": SKILL_VERSION,
                        "informationUri": "https://github.com/netresearch/php-modernization-skill",
                        "rules": rules,
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": report.summary.status != "fail",
                        "endTimeUtc": report.generated_at,
                    }
                ],
            }
        ],
    }


def to_junit(report: Report) -> str:
    """Render the report as JUnit XML 2.x.

    Mapping:
    - severity=error   → <failure type="error">
    - severity=warning → <failure type="warning">
    - status=skipped   → <skipped/>
    Uncategorised checks (status=pass) are still emitted as passing testcases.

    Suite-level attribute semantics match the emitted children:
    - ``failures`` = total count of <failure> elements (every failed check
      regardless of severity, since all failures are rendered as <failure>).
    - ``errors``   = 0 — we never emit <error> children. JUnit reserves
      <error> for unexpected runtime crashes; assertion failures are
      <failure>. Severity is preserved on the failure's ``type`` attribute.
    - ``tests``    = total checks. ``skipped`` = count of skipped checks.
    """
    checks = report.checks
    failure_count = sum(1 for c in checks if c.status == "fail")
    error_count = 0  # we never emit <error>; assertion-style failures use <failure>
    skipped_count = sum(1 for c in checks if c.status == "skipped")
    total = len(checks)

    testsuites = ET.Element(
        "testsuites",
        {
            "name": "php-modernization",
            "tests": str(total),
            "failures": str(failure_count),
            "errors": str(error_count),
            "time": "0",
        },
    )
    testsuite = ET.SubElement(
        testsuites,
        "testsuite",
        {
            "name": "checks",
            "tests": str(total),
            "failures": str(failure_count),
            "errors": str(error_count),
            "skipped": str(skipped_count),
            "time": "0",
            "timestamp": report.generated_at,
        },
    )
    for c in checks:
        # name combines id with truncated message; classname carries the category.
        msg = c.message or ""
        truncated = msg[:80]
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            {
                "classname": f"php-modernization.{c.category}",
                "name": f"{c.id}: {truncated}",
                "time": "0",
            },
        )
        if c.status == "skipped":
            ET.SubElement(testcase, "skipped")
        elif c.status == "fail":
            failure = ET.SubElement(
                testcase,
                "failure",
                {"type": c.severity, "message": msg},
            )
            if c.evidence:
                failure.text = "\n".join(c.evidence)

    # Pretty-print for human readability; ElementTree.indent is stdlib (3.9+).
    ET.indent(testsuites, space="  ")
    body = ET.tostring(testsuites, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify_php_project",
        description="Mechanical PHP modernization verifier (php-modernization skill).",
    )
    parser.add_argument(
        "--root", default=".", help="Project root (default: current directory)"
    )
    parser.add_argument(
        "--format",
        choices=("json", "sarif", "junit"),
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Emit only header + counts + top-3 actions (compact for agent context)",
    )
    parser.add_argument(
        "--check",
        metavar="PM-XX",
        help="Drill into a single checkpoint (filters checks[] and agent_actions[])",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Skip subprocess tool invocations (phpstan, composer audit) — fast static-only mode",
    )
    parser.add_argument(
        "--cache-file",
        default=str(DEFAULT_CACHE_PATH),
        help=f"Cache file location (default: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the cache (always re-evaluate)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.stderr.write(f"error: --root {args.root!r} is not a directory\n")
        return 2

    cache_path = (
        root / args.cache_file
        if not os.path.isabs(args.cache_file)
        else Path(args.cache_file)
    )
    flags = {"no_tools": bool(args.no_tools)}
    signature = cache_signature(root)

    report_dict: dict[str, Any] | None = None
    if not args.no_cache:
        report_dict = cache_load(cache_path, signature, flags)

    if report_dict is None:
        report = evaluate(root, run_tools=not args.no_tools)
        report_dict = report_to_dict(report)
        if not args.no_cache:
            cache_store(cache_path, signature, flags, report_dict)

    if args.check:
        report_dict = filter_to_checkpoint(report_dict, args.check)
    if args.summary:
        report_dict = summarize(report_dict)

    if args.format == "sarif":
        # SARIF emission uses the typed Report; rebuild from dict for fidelity.
        report = _report_from_dict(report_dict)
        sys.stdout.write(json.dumps(to_sarif(report), indent=2) + "\n")
    elif args.format == "junit":
        report = _report_from_dict(report_dict)
        sys.stdout.write(to_junit(report))
    else:
        sys.stdout.write(json.dumps(report_dict, indent=2) + "\n")

    status = report_dict.get("summary", {}).get("status", "fail")
    return 1 if status == "fail" else 0


def _report_from_dict(d: dict[str, Any]) -> Report:
    summary = d.get("summary") or {}
    env = d.get("environment") or {}
    tooling = d.get("tooling") or {}
    return Report(
        schema_version=d.get("schema_version", SCHEMA_VERSION),
        skill=d.get("skill", SKILL_ID),
        skill_version=d.get("skill_version", SKILL_VERSION),
        generated_at=d.get("generated_at", ""),
        project_root=d.get("project_root", ""),
        archetype=d.get("archetype", "unknown"),
        summary=Summary(
            status=summary.get("status", "fail"),
            errors=int(summary.get("errors", 0)),
            warnings=int(summary.get("warnings", 0)),
            info=int(summary.get("info", 0)),
        ),
        environment=Environment(
            php_version_constraint=env.get("php_version_constraint", "unknown"),
            php_runtime=env.get("php_runtime", "unknown"),
            composer_json=bool(env.get("composer_json", False)),
            composer_lock=bool(env.get("composer_lock", False)),
        ),
        tooling=Tooling(
            phpstan=tooling.get("phpstan", {}),
            rector=tooling.get("rector", {}),
            php_cs_fixer=tooling.get("php_cs_fixer", {}),
            phpat=tooling.get("phpat", {}),
            infection=tooling.get("infection", {}),
            composer_audit_supported=bool(
                tooling.get("composer_audit_supported", False)
            ),
        ),
        checks=[Check(**c) for c in d.get("checks", [])],
        agent_actions=[AgentAction(**a) for a in d.get("agent_actions", [])],
        tool_runs=[ToolRun(**t) for t in d.get("tool_runs", [])],
    )


if __name__ == "__main__":
    sys.exit(main())
