#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Behaviour tests for the shipped scripts under skills/php-modernization/scripts/.

scripts/test_fixtures.py pins the verifier's JSON report against golden
snapshots. This suite covers what the snapshots do not: the introspector, the
fix-loop orchestrator, the verifier's exit codes, cache and other output formats, and
the Bash wrapper. Every script runs as a subprocess, the way an agent calls it.

Tests that let a script write (the orchestrator's artifacts, the verifier's
cache) run against a copy of a fixture in a temporary directory, so the suite
leaves the repository unchanged.

Stdlib only. Run with ``python3 tests/test_scripts.py``; exits non-zero when a
test fails.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "php-modernization" / "scripts"
FIXTURES = REPO_ROOT / "fixtures"


def run(*args: str | Path, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def run_py(script: str, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, SCRIPTS / script, *args)


class TempProject:
    """Copy of a fixture in a temporary directory, removed afterwards."""

    def __init__(self, fixture: str) -> None:
        self.fixture = fixture

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / self.fixture
        shutil.copytree(
            FIXTURES / self.fixture, root, ignore=shutil.ignore_patterns("expected")
        )
        return root

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()


def fake_tool(root: Path, name: str, exit_code: int) -> Path:
    """Install an executable vendor/bin/<name> that logs its arguments."""
    binary = root / "vendor" / "bin" / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "$(dirname "$0")/{name}.args"\n'
        'echo "{}"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


class IntrospectTest(unittest.TestCase):
    def test_detects_the_archetype_of_each_fixture(self) -> None:
        expected = {
            "generic-composer-minimal": "generic-composer",
            "fully-modern": "generic-composer",
            "symfony-app-minimal": "symfony-app",
            "typo3-extension-minimal": "typo3-extension",
            "monorepo-minimal": "monorepo-package",
        }
        for fixture, archetype in expected.items():
            with self.subTest(fixture=fixture):
                result = run_py("introspect.py", "--root", FIXTURES / fixture)
                self.assertEqual(result.returncode, 0, result.stderr)
                profile = json.loads(result.stdout)
                self.assertEqual(profile["archetype"], archetype)
                self.assertEqual(profile["skill"], "php-modernization")

    def test_psr4_autoload_without_src_is_generic_composer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "composer.json").write_text(
                json.dumps({"autoload": {"psr-4": {"Acme\\": "lib/"}}}),
                encoding="utf-8",
            )
            result = run_py("introspect.py", "--root", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            profile = json.loads(result.stdout)
            self.assertEqual(profile["archetype"], "generic-composer")
            self.assertEqual(profile["autoload_psr4"], {"Acme\\": "lib/"})

    def test_missing_root_still_emits_a_profile_and_exits_zero(self) -> None:
        result = run_py("introspect.py", "--root", REPO_ROOT / "does-not-exist")
        self.assertEqual(result.returncode, 0)
        self.assertIn("is not a directory", result.stderr)
        self.assertEqual(json.loads(result.stdout)["archetype"], "unknown")

    def test_non_object_composer_json_counts_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "composer.json").write_text("[]", encoding="utf-8")
            for script, extra in (
                ("introspect.py", ()),
                ("verify_php_project.py", ("--no-tools", "--no-cache")),
            ):
                with self.subTest(script=script):
                    result = run_py(script, "--root", tmp, *extra)
                    self.assertNotIn("Traceback", result.stderr)
                    json.loads(result.stdout)


class VersionTest(unittest.TestCase):
    def test_reports_carry_the_released_skill_version(self) -> None:
        manifest = REPO_ROOT / ".claude-plugin" / "plugin.json"
        released = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        result = run_py(
            "verify_php_project.py",
            "--root",
            FIXTURES / "fully-modern",
            "--no-tools",
            "--no-cache",
        )
        self.assertEqual(
            json.loads(result.stdout)["skill_version"],
            released,
            "update SKILL_VERSION in scripts/_common.py and regenerate the "
            "snapshots with scripts/test_fixtures.py --update",
        )


class VerifierTest(unittest.TestCase):
    def test_missing_root_exits_two(self) -> None:
        result = run_py("verify_php_project.py", "--root", REPO_ROOT / "does-not-exist")
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not a directory", result.stderr)

    def test_exit_code_follows_the_summary_status(self) -> None:
        for fixture, code in (("fully-modern", 0), ("generic-composer-minimal", 1)):
            with self.subTest(fixture=fixture):
                result = run_py(
                    "verify_php_project.py",
                    "--root",
                    FIXTURES / fixture,
                    "--no-tools",
                    "--no-cache",
                )
                self.assertEqual(result.returncode, code, result.stderr)

    def test_sarif_and_junit_output_parse(self) -> None:
        root = FIXTURES / "generic-composer-minimal"
        base = ("verify_php_project.py", "--root", root, "--no-tools", "--no-cache")
        sarif = json.loads(run_py(*base, "--format", "sarif").stdout)
        self.assertEqual(sarif["version"], "2.1.0")
        junit = run_py(*base, "--format", "junit").stdout
        self.assertTrue(junit.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn("<testsuites", junit)
        self.assertTrue(junit.rstrip().endswith("</testsuites>"))

    def test_check_filters_to_one_checkpoint(self) -> None:
        result = run_py(
            "verify_php_project.py",
            "--root",
            FIXTURES / "generic-composer-minimal",
            "--no-tools",
            "--no-cache",
            "--check",
            "PM-02",
        )
        ids = {c["id"] for c in json.loads(result.stdout)["checks"]}
        self.assertEqual(ids, {"PM-02"})

    def test_cache_is_written_and_reused(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            run_py("verify_php_project.py", "--root", root, "--no-tools")
            cache = root / ".build" / "php-modernization" / "last-run.json"
            self.assertTrue(cache.is_file())
            # Mark the stored report: only a cache hit can print the marker.
            payload = json.loads(cache.read_text(encoding="utf-8"))
            payload["report"]["archetype"] = "from-cache"
            cache.write_text(json.dumps(payload), encoding="utf-8")

            hit = run_py("verify_php_project.py", "--root", root, "--no-tools")
            self.assertEqual(json.loads(hit.stdout)["archetype"], "from-cache")

            bypass = run_py(
                "verify_php_project.py", "--root", root, "--no-tools", "--no-cache"
            )
            self.assertEqual(json.loads(bypass.stdout)["archetype"], "generic-composer")

            # A changed composer.json invalidates the stored report.
            composer = root / "composer.json"
            stat_ = composer.stat()
            os.utime(composer, ns=(stat_.st_atime_ns, stat_.st_mtime_ns + 10**9))
            stale = run_py("verify_php_project.py", "--root", root, "--no-tools")
            self.assertEqual(json.loads(stale.stdout)["archetype"], "generic-composer")

    def test_cache_from_an_older_release_is_not_reused(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            run_py("verify_php_project.py", "--root", root, "--no-tools")
            cache = root / ".build" / "php-modernization" / "last-run.json"
            # A cache written by an earlier release, in the format it used:
            # flags without a version, and the old version in the report.
            payload = json.loads(cache.read_text(encoding="utf-8"))
            payload["flags"] = {"no_tools": True}
            payload["report"]["skill_version"] = "1.17.0"
            cache.write_text(json.dumps(payload), encoding="utf-8")

            result = run_py("verify_php_project.py", "--root", root, "--no-tools")
            self.assertNotEqual(json.loads(result.stdout)["skill_version"], "1.17.0")


class ModernizeLoopTest(unittest.TestCase):
    def test_dry_run_without_tools_reports_them_missing(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            result = run_py("modernize_loop.py", "--root", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            transcript = json.loads(result.stdout)
            self.assertEqual(transcript["mode"], "dry-run")
            status = {r["tool"]: r["status"] for r in transcript["results"]}
            self.assertEqual(
                status,
                {
                    "php-cs-fixer": "missing",
                    "rector": "missing",
                    "phpstan": "missing",
                    "infection-diff": "skipped",
                },
            )
            actions = {a["tool"] for a in transcript["next_actions"]}
            self.assertEqual(actions, {"php-cs-fixer", "rector", "phpstan"})

    def test_dry_run_passes_dry_run_flags_and_fails_on_findings(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            fake_tool(root, "php-cs-fixer", exit_code=8)
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "rector,php-cs-fixer"
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            bin_dir = root / "vendor" / "bin"
            self.assertIn("--dry-run", (bin_dir / "rector.args").read_text().split())
            self.assertIn(
                "--dry-run", (bin_dir / "php-cs-fixer.args").read_text().split()
            )
            status = {
                r["tool"]: r["status"] for r in json.loads(result.stdout)["results"]
            }
            self.assertEqual(status, {"rector": "pass", "php-cs-fixer": "fail"})
            self.assertTrue(
                (root / ".build" / "php-modernization" / "rector.json").is_file()
            )

    def test_apply_without_confirm_exits_two_and_runs_nothing(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            result = run_py("modernize_loop.py", "--root", root, "--mode", "apply")
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires --confirm", result.stderr)
            self.assertFalse((root / "vendor" / "bin" / "rector.args").exists())

    def test_apply_with_confirm_runs_without_dry_run(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--mode",
                "apply",
                "--confirm",
                "--tools",
                "rector",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (root / "vendor" / "bin" / "rector.args").read_text().split()
            self.assertEqual(args, ["process"])

    def test_unknown_tool_is_a_usage_error(self) -> None:
        result = run_py("modernize_loop.py", "--tools", "phpstan,bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown tool", result.stderr)


class WrapperTest(unittest.TestCase):
    def test_introspect_subcommand_dispatches_to_the_introspector(self) -> None:
        result = run(
            "bash",
            SCRIPTS / "verify-php-project.sh",
            "introspect",
            FIXTURES / "symfony-app-minimal",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads(result.stdout)
        self.assertEqual(profile["archetype"], "symfony-app")
        self.assertIn("baselines", profile)

    def test_default_subcommand_runs_the_verifier(self) -> None:
        with TempProject("fully-modern") as root:
            result = run("bash", SCRIPTS / "verify-php-project.sh", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
