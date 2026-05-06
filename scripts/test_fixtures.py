#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Regression-test runner for verifier output against synthetic project fixtures.

Runs ``skills/php-modernization/scripts/verify_php_project.py`` against each
fixture under ``fixtures/`` with deterministic flags (``--no-tools --no-cache``),
applies a normalization pass to scrub fields that vary per environment, and
diffs the result against ``<fixture>/expected/verifier.json``.

Use ``--update`` to regenerate the golden snapshots when verifier output
legitimately changes (e.g. a new check is added or skill_version bumps).

Designed to be invoked via uv:

    uv run scripts/test_fixtures.py
    uv run scripts/test_fixtures.py --update
    uv run scripts/test_fixtures.py --fixture generic-composer-minimal

Stdlib only. Exits 0 if all fixtures pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"
VERIFIER = (
    REPO_ROOT / "skills" / "php-modernization" / "scripts" / "verify_php_project.py"
)
NORMALIZED = "<NORMALIZED>"

# Fields whose values vary per run/host. Replaced with NORMALIZED placeholder.
TOP_LEVEL_VOLATILE_FIELDS: tuple[str, ...] = (
    "generated_at",
    "project_root",
)
ENVIRONMENT_VOLATILE_FIELDS: tuple[str, ...] = ("php_runtime",)


def discover_fixtures() -> list[Path]:
    """Return all fixture directories (those containing a composer.json)."""
    if not FIXTURES_DIR.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(FIXTURES_DIR.iterdir()):
        if not child.is_dir():
            continue
        if (child / "composer.json").is_file():
            out.append(child)
    return out


def run_verifier(fixture: Path) -> dict[str, Any]:
    """Invoke the verifier on a fixture and return the parsed JSON output."""
    cmd = [
        "uv",
        "run",
        str(VERIFIER),
        "--root",
        str(fixture),
        "--format",
        "json",
        "--no-tools",
        "--no-cache",
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    # Verifier exit codes: 0 pass/warn, 1 fail. Both produce valid JSON. Other
    # codes (2 = bad args) are harness errors and should propagate.
    if completed.returncode not in (0, 1):
        sys.stderr.write(
            f"verifier failed for {fixture.name}: exit {completed.returncode}\n"
            f"stderr: {completed.stderr}\n"
        )
        raise SystemExit(2)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"verifier emitted invalid JSON for {fixture.name}: {exc}\n"
            f"stdout: {completed.stdout[:500]}\n"
        )
        raise SystemExit(2) from exc


def normalize(report: dict[str, Any]) -> dict[str, Any]:
    """Scrub volatile fields and impose a stable ordering on collections.

    Idempotent: applying twice yields the same result.
    """
    out: dict[str, Any] = dict(report)

    # Scrub top-level volatile fields.
    for key in TOP_LEVEL_VOLATILE_FIELDS:
        if key in out:
            out[key] = NORMALIZED

    # Scrub environment.php_runtime (varies per CI runner / local install).
    env = out.get("environment")
    if isinstance(env, dict):
        env = dict(env)
        for key in ENVIRONMENT_VOLATILE_FIELDS:
            if key in env:
                env[key] = NORMALIZED
        out["environment"] = env

    # tool_runs[] is non-deterministic (subprocess data, paths, exit codes).
    # The fixtures run with --no-tools so this should already be empty, but we
    # drop it for safety in case a future verifier emits something here.
    out["tool_runs"] = []

    # Stable ordering for the collections an agent might re-emit in any order.
    checks = out.get("checks")
    if isinstance(checks, list):
        out["checks"] = sorted(
            checks, key=lambda c: c.get("id", "") if isinstance(c, dict) else ""
        )
    actions = out.get("agent_actions")
    if isinstance(actions, list):
        out["agent_actions"] = sorted(
            actions,
            key=lambda a: a.get("checkpoint", "") if isinstance(a, dict) else "",
        )

    return out


def serialize(d: dict[str, Any]) -> str:
    """Stable, pretty-printed JSON for diffing."""
    return json.dumps(d, sort_keys=True, indent=2) + "\n"


def diff_text(expected: str, actual: str, expected_label: str) -> list[str]:
    return list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=expected_label,
            tofile="actual",
            n=3,
        )
    )


def expected_path(fixture: Path) -> Path:
    return fixture / "expected" / "verifier.json"


def update_snapshot(fixture: Path) -> None:
    actual = run_verifier(fixture)
    normalized = normalize(actual)
    target = expected_path(fixture)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize(normalized), encoding="utf-8")


def check_fixture(fixture: Path) -> tuple[bool, list[str]]:
    """Return (passed, diff_lines)."""
    target = expected_path(fixture)
    if not target.is_file():
        return False, [
            f"missing snapshot: {target.relative_to(REPO_ROOT)}\n",
            "  run with --update to generate it\n",
        ]
    actual = normalize(run_verifier(fixture))
    try:
        expected_raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [
            f"snapshot is not valid JSON: {target.relative_to(REPO_ROOT)}\n",
            f"  {exc.__class__.__name__}: {exc}\n",
            "  run with --update to regenerate it\n",
        ]
    expected = normalize(expected_raw)  # idempotent — protects hand-edits
    actual_text = serialize(actual)
    expected_text = serialize(expected)
    if actual_text == expected_text:
        return True, []
    return False, diff_text(
        expected_text,
        actual_text,
        str(target.relative_to(REPO_ROOT)),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="test_fixtures",
        description="Verifier regression tests against fixture snapshots.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate fixture snapshots instead of diffing.",
    )
    parser.add_argument(
        "--fixture",
        metavar="NAME",
        help="Run only the fixture with this directory name.",
    )
    return parser.parse_args(argv)


def select_fixtures(name: str | None) -> list[Path]:
    all_fixtures = discover_fixtures()
    if name is None:
        return all_fixtures
    matched = [f for f in all_fixtures if f.name == name]
    if not matched:
        available = ", ".join(f.name for f in all_fixtures) or "(none)"
        sys.stderr.write(f"no fixture named {name!r} (available: {available})\n")
        raise SystemExit(2)
    return matched


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))

    if not VERIFIER.is_file():
        sys.stderr.write(f"verifier not found at {VERIFIER}\n")
        return 2

    fixtures = select_fixtures(args.fixture)
    if not fixtures:
        sys.stderr.write("no fixtures discovered under fixtures/\n")
        return 2

    if args.update:
        for fixture in fixtures:
            update_snapshot(fixture)
            rel = fixture.relative_to(REPO_ROOT)
            sys.stdout.write(f"{rel}\tUPDATED\n")
        return 0

    name_width = max(len(str(f.relative_to(REPO_ROOT))) for f in fixtures)
    name_width = max(name_width, 40)
    failed: list[tuple[Path, list[str]]] = []
    passed_count = 0

    for fixture in fixtures:
        rel = fixture.relative_to(REPO_ROOT)
        ok, diff = check_fixture(fixture)
        if ok:
            sys.stdout.write(f"{str(rel).ljust(name_width)} PASS\n")
            passed_count += 1
        else:
            sys.stdout.write(f"{str(rel).ljust(name_width)} FAIL\n")
            for line in diff:
                sys.stdout.write("  " + line)
            if diff and not diff[-1].endswith("\n"):
                sys.stdout.write("\n")
            failed.append((fixture, diff))

    sys.stdout.write("\n")
    total = len(fixtures)
    sys.stdout.write(f"{passed_count}/{total} fixtures pass.\n")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
