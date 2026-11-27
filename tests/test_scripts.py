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
import re
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


def fake_tool(root: Path, name: str, exit_code: int, stdout: str = "{}") -> Path:
    """Install an executable vendor/bin/<name> that logs its arguments.

    A fake Rector gets a rector.php when the project has no Rector config:
    the loop skips Rector without one.
    """
    if name == "rector" and not any(
        (root / rel).is_file()
        for rel in ("rector.php", "Build/rector.php", "Build/rector/rector.php")
    ):
        (root / "rector.php").write_text("<?php\n", encoding="utf-8")
    binary = root / "vendor" / "bin" / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    (binary.parent / f"{name}.stdout").write_text(stdout + "\n", encoding="utf-8")
    binary.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "$(dirname "$0")/{name}.args"\n'
        f'echo "{name} $*" >> "$(dirname "$0")/calls.log"\n'
        f'cat "$(dirname "$0")/{name}.stdout"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


class MakefileTargetTest(unittest.TestCase):
    def test_double_colon_rules_and_assignments(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import _common

        text = "clean::\nFOO ::= bar\nbuild: dep\nX := 1\ntest:\n"
        names = [m.group(1) for m in _common._MAKE_TARGET_RE.finditer(text)]
        self.assertEqual(names, ["clean", "build", "test"])


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

    def test_reports_the_project_tools_and_commands(self) -> None:
        result = run_py("introspect.py", "--root", FIXTURES / "generic-composer-phpcs")
        profile = json.loads(result.stdout)
        self.assertEqual(profile["coding_standard"], "phpcs")
        self.assertEqual(profile["config_files"]["phpcs"], "phpcs.xml.dist")
        self.assertIsNone(profile["config_files"]["php_cs_fixer"])
        self.assertTrue(profile["tooling"]["phpcs"])
        self.assertTrue(profile["tooling"]["phpunit"])
        self.assertFalse(profile["tooling"]["php_cs_fixer"])
        self.assertEqual(profile["source_dirs"], {"src": ["src"], "tests": ["tests"]})
        self.assertEqual(
            profile["project_commands"]["composer_scripts"], ["cs:check", "cs:fix"]
        )

    def test_source_dirs_follow_composer_autoload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for d in ("lib", "packages/a/src", "spec"):
                Path(tmp, d).mkdir(parents=True)
            Path(tmp, "composer.json").write_text(
                json.dumps(
                    {
                        "autoload": {
                            "psr-4": {
                                "A\\": ["lib/", "packages/a/src/"],
                                "B\\": "gone/",
                            }
                        },
                        "autoload-dev": {"classmap": ["spec"]},
                    }
                ),
                encoding="utf-8",
            )
            profile = json.loads(run_py("introspect.py", "--root", tmp).stdout)
            # Only existing directories; "gone/" is declared but absent.
            self.assertEqual(
                profile["source_dirs"],
                {"src": ["lib", "packages/a/src"], "tests": ["spec"]},
            )

    def test_classmap_wildcards_are_expanded(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import _common

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages" / "a" / "src").mkdir(parents=True)
            (root / "packages" / "b").mkdir(parents=True)
            dirs = _common.source_dirs(
                root, {"autoload": {"classmap": ["packages/*/src/"]}}
            )
            self.assertEqual(dirs["src"], ["packages/a/src"])
            # An absolute pattern makes Path.glob raise; it must not stop
            # the profile.
            absolute = _common.source_dirs(
                root, {"autoload": {"classmap": [f"{root}/packages/*/src/"]}}
            )
            self.assertEqual(absolute["src"], [f"{root}/packages/a/src"])

    @unittest.skipIf(os.geteuid() == 0, "root reads a directory without permission")
    def test_unreadable_workflow_directory_keeps_the_profile(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import _common

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (root / ".gitlab-ci.yml").write_text("{}\n", encoding="utf-8")
            workflows.chmod(0)
            try:
                self.assertEqual(_common.ci_files(root), [".gitlab-ci.yml"])
            finally:
                workflows.chmod(0o755)

    def test_makefile_targets_and_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "composer.json").write_text("{}", encoding="utf-8")
            Path(tmp, "Makefile").write_text(
                ".PHONY: test\ninclude Make/*.mk\nVAR := 1\ntest: lint\n\tphpunit\nlint:\n\tphp -l\n",
                encoding="utf-8",
            )
            Path(tmp, ".ddev").mkdir()
            Path(tmp, ".ddev", "config.yaml").write_text("name: x\n", encoding="utf-8")
            commands = json.loads(run_py("introspect.py", "--root", tmp).stdout)[
                "project_commands"
            ]
            self.assertEqual(
                commands["makefile"],
                {"file": "Makefile", "targets": ["test", "lint"], "includes": True},
            )
            self.assertTrue(commands["ddev"])

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


class SkillCopy:
    """Copy of the skill directory (SKILL.md and scripts/) in a temporary dir."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        skill = Path(self._tmp.name) / "php-modernization"
        shutil.copytree(
            SCRIPTS, skill / "scripts", ignore=shutil.ignore_patterns("__pycache__")
        )
        shutil.copy2(SCRIPTS.parent / "SKILL.md", skill / "SKILL.md")
        return skill

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()


def verify_with(skill: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the verifier from a skill copy against the fully-modern fixture."""
    return run(
        sys.executable,
        skill / "scripts" / "verify_php_project.py",
        "--root",
        FIXTURES / "fully-modern",
        "--no-tools",
        "--no-cache",
        *extra,
    )


class VersionTest(unittest.TestCase):
    def test_reports_carry_the_released_skill_version(self) -> None:
        # The verifier reads SKILL.md; both manifests are compared with what it
        # reports, so SKILL.md drifting from either plugin.json fails here.
        result = run_py(
            "verify_php_project.py",
            "--root",
            FIXTURES / "fully-modern",
            "--no-tools",
            "--no-cache",
            "--format",
            "sarif",
        )
        sarif_version = json.loads(result.stdout)["runs"][0]["tool"]["driver"][
            "version"
        ]
        result = run_py(
            "verify_php_project.py",
            "--root",
            FIXTURES / "fully-modern",
            "--no-tools",
            "--no-cache",
        )
        reported = json.loads(result.stdout)["skill_version"]
        self.assertNotEqual(reported, "unknown")
        self.assertEqual(sarif_version, reported)
        for manifest in ("plugin.json", ".claude-plugin/plugin.json"):
            with self.subTest(manifest=manifest):
                released = json.loads(
                    (REPO_ROOT / manifest).read_text(encoding="utf-8")
                )["version"]
                self.assertEqual(
                    reported,
                    released,
                    f"metadata.version in skills/php-modernization/SKILL.md "
                    f"differs from {manifest}",
                )

    def test_version_follows_skill_md(self) -> None:
        with SkillCopy() as skill:
            skill_md = skill / "SKILL.md"
            text, replaced = re.subn(
                r'(?m)^  version: ".*"$',
                '  version: "9.9.9"',
                skill_md.read_text(encoding="utf-8"),
                count=1,
            )
            self.assertEqual(replaced, 1)
            skill_md.write_text(text, encoding="utf-8")
            result = verify_with(skill)
            self.assertEqual(json.loads(result.stdout)["skill_version"], "9.9.9")

    def test_version_without_skill_md_is_unknown(self) -> None:
        with SkillCopy() as skill:
            (skill / "SKILL.md").unlink()
            for fmt in ("json", "sarif"):
                with self.subTest(format=fmt):
                    result = verify_with(skill, "--format", fmt)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    payload = json.loads(result.stdout)
                    if fmt == "json":
                        version = payload["skill_version"]
                    else:
                        version = payload["runs"][0]["tool"]["driver"]["version"]
                    self.assertEqual(version, "unknown")

    def test_only_metadata_version_counts(self) -> None:
        cases = {
            "no metadata.version": "---\nname: x\nmetadata:\n  author: y\n---\n",
            "top-level version only": "---\nversion: 1.0.0\nmetadata:\n  a: b\n---\n",
            "version under another key": "---\ncompat:\n  version: 1.5.0\n---\n",
            "version in the body": "---\nname: x\n---\n\nmetadata:\n  version: 2.0.0\n",
            "no frontmatter": "# Title\n\nmetadata:\n  version: 3.0.0\n",
        }
        with SkillCopy() as skill:
            for case, content in cases.items():
                with self.subTest(case=case):
                    (skill / "SKILL.md").write_text(content, encoding="utf-8")
                    result = verify_with(skill)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(
                        json.loads(result.stdout)["skill_version"], "unknown"
                    )

    def test_nested_version_under_metadata_is_ignored(self) -> None:
        cases = {
            "nested before": (
                (
                    '---\nmetadata:\n  release:\n    version: "9.9.9"\n'
                    '  version: "1.2.3"\n---\n'
                ),
                "1.2.3",
            ),
            "nested only": (
                '---\nmetadata:\n  release:\n    version: "9.9.9"\n---\n',
                "unknown",
            ),
        }
        with SkillCopy() as skill:
            for case, (content, expected) in cases.items():
                with self.subTest(case=case):
                    (skill / "SKILL.md").write_text(content, encoding="utf-8")
                    result = verify_with(skill)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(
                        json.loads(result.stdout)["skill_version"], expected
                    )

    def test_version_quoting_styles(self) -> None:
        cases = {
            "double": '  version: "4.5.6"',
            "single": "  version: '4.5.6'",
            "bare": "  version: 4.5.6",
            "comment": '  version: "4.5.6"  # bumped by bump-version.sh',
        }
        with SkillCopy() as skill:
            for case, line in cases.items():
                with self.subTest(case=case):
                    (skill / "SKILL.md").write_text(
                        f"---\r\nname: x\r\nmetadata:\r\n{line}\r\n---\r\n",
                        encoding="utf-8",
                    )
                    result = verify_with(skill)
                    self.assertEqual(
                        json.loads(result.stdout)["skill_version"], "4.5.6"
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
        report = json.loads(result.stdout)
        ids = {c["id"] for c in report["checks"]}
        self.assertEqual(ids, {"PM-02"})
        # The summary and the exit code describe PM-02 (skipped there: no
        # PHPStan config), not the whole project, which fails.
        self.assertEqual(report["summary"]["status"], "pass")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_of_a_review_checkpoint_is_not_evaluated(self) -> None:
        base = (
            "verify_php_project.py",
            "--root",
            FIXTURES / "fully-modern",
            "--no-tools",
            "--no-cache",
            "--check",
        )
        review = run_py(*base, "PM-21")
        self.assertEqual(review.returncode, 3, review.stderr)
        report = json.loads(review.stdout)
        self.assertEqual(report["summary"]["status"], "not_evaluated")
        self.assertEqual(report["checkpoint"]["status"], "not_reviewed")
        self.assertEqual(report["checks"], [])

        elsewhere = run_py(*base, "PM-07")
        self.assertEqual(elsewhere.returncode, 3, elsewhere.stderr)
        self.assertEqual(
            json.loads(elsewhere.stdout)["checkpoint"]["status"], "not_run"
        )

        unknown = run_py(*base, "PM-999")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("unknown checkpoint", unknown.stderr)

        # Without a readable checkpoints.yaml the id cannot be called
        # unknown: the answer is not_evaluated, exit 3.
        # The skill copy carries no checkpoints.yaml.
        with SkillCopy() as skill:
            self.assertFalse((skill / "checkpoints.yaml").exists())
            blind = verify_with(skill, "--check", "PM-21")
            self.assertEqual(blind.returncode, 3, blind.stderr)
            self.assertEqual(json.loads(blind.stdout)["checkpoint"]["kind"], "unknown")

        # JUnit says the checkpoint was not evaluated instead of an empty suite.
        junit = run_py(*base, "PM-21", "--format", "junit")
        self.assertEqual(junit.returncode, 3)
        self.assertIn('name="PM-21: not_reviewed"', junit.stdout)
        self.assertIn('skipped="1"', junit.stdout)

    def test_cache_follows_the_phpcs_config(self) -> None:
        with TempProject("generic-composer-phpcs") as root:
            config = root / "phpcs.xml.dist"
            saved = config.read_text(encoding="utf-8")
            config.unlink()
            base = ("verify_php_project.py", "--root", root, "--no-tools")
            first = json.loads(run_py(*base, "--check", "PM-04").stdout)
            self.assertEqual(first["checks"][0]["status"], "fail")
            config.write_text(saved, encoding="utf-8")
            second = json.loads(run_py(*base, "--check", "PM-04").stdout)
            self.assertEqual(second["checks"][0]["status"], "pass")

    def test_check_keeps_the_count_of_failed_tool_runs(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "phpstan", exit_code=1)
            base = ("verify_php_project.py", "--root", root, "--no-cache")
            full = json.loads(run_py(*base).stdout)
            self.assertEqual(full["summary"]["tool_runs_failed"], 1)
            one = json.loads(run_py(*base, "--check", "PM-01").stdout)
            self.assertEqual(one["summary"]["tool_runs_failed"], 1)

    def test_verifier_finds_phpstan_in_the_composer_bin_dir(self) -> None:
        with TempProject("fully-modern") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["config"] = {"bin-dir": "bin"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            fake_tool(root, "phpstan", exit_code=1)
            (root / "vendor" / "bin").rename(root / "bin")
            report = json.loads(
                run_py("verify_php_project.py", "--root", root, "--no-cache").stdout
            )
            self.assertEqual(report["summary"]["tool_runs_failed"], 1)

    def test_unwritable_tool_artifact_is_not_reported(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "phpstan", exit_code=0)
            fake_tool(root, "composer", exit_code=0)
            (root / "composer.lock").write_text("{}\n", encoding="utf-8")
            # A directory where the report file belongs makes the write fail.
            artifacts = root / ".build" / "php-modernization"
            (artifacts / "phpstan.json").mkdir(parents=True)
            (artifacts / "composer-audit.json").mkdir()
            # A PATH without a system composer, so the verifier takes the fake
            # one from vendor/bin; the fakes need only cat and dirname.
            path_dir = root / "path"
            path_dir.mkdir()
            for tool in ("cat", "dirname"):
                (path_dir / tool).symlink_to(shutil.which(tool))
            result = subprocess.run(
                [
                    sys.executable,
                    SCRIPTS / "verify_php_project.py",
                    "--root",
                    root,
                    "--no-cache",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
                env={**os.environ, "PATH": str(path_dir)},
            )
            runs = {r["tool"]: r for r in json.loads(result.stdout)["tool_runs"]}
            self.assertEqual(set(runs), {"phpstan", "composer-audit"})
            for tool, run_ in runs.items():
                with self.subTest(tool=tool):
                    self.assertEqual(run_["status"], "pass")
                    self.assertIsNone(run_["artifact"])

    def test_verifier_finds_phpcs_in_the_composer_bin_dir(self) -> None:
        with TempProject("generic-composer-phpcs") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer.get("require-dev", {}).pop("squizlabs/php_codesniffer")
            composer["config"] = {"bin-dir": "tools"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            base = ("verify_php_project.py", "--root", root, "--no-tools", "--no-cache")
            without = json.loads(run_py(*base, "--check", "PM-17").stdout)
            self.assertEqual(without["checks"][0]["status"], "fail")
            fake_tool(root, "phpcs", exit_code=0)
            (root / "vendor" / "bin").rename(root / "tools")
            found = json.loads(run_py(*base, "--check", "PM-17").stdout)
            self.assertEqual(found["checks"][0]["status"], "pass")

    def test_phpstan_dist_neon_is_a_phpstan_config(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            (root / "phpstan.dist.neon").write_text(
                "parameters:\n  level: 8\n", "utf-8"
            )
            profile = json.loads(run_py("introspect.py", "--root", root).stdout)
            self.assertEqual(profile["config_files"]["phpstan"], "phpstan.dist.neon")

    def test_report_lists_review_checkpoints_as_not_reviewed(self) -> None:
        result = run_py(
            "verify_php_project.py",
            "--root",
            FIXTURES / "fully-modern",
            "--no-tools",
            "--no-cache",
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["status"], "pass")
        coverage = report["review_coverage"]
        for checkpoint in ("PM-21", "PM-22", "PM-40"):
            self.assertIn(checkpoint, coverage["llm_reviews_not_reviewed"])
        self.assertIn("PM-02", coverage["verifier_checks"])
        self.assertNotIn("PM-02", coverage["mechanical_not_in_verifier"])

    def test_failing_phpstan_run_is_counted_without_changing_status(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "phpstan", exit_code=1)
            result = run_py("verify_php_project.py", "--root", root, "--no-cache")
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["tool_runs_failed"], 1)
            self.assertEqual(report["summary"]["status"], "pass")
            self.assertEqual(result.returncode, 0)

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


def phpcs_totals(errors: int, fixable: int, warnings: int = 0) -> str:
    return json.dumps(
        {
            "totals": {"errors": errors, "warnings": warnings, "fixable": fixable},
            "files": {},
        }
    )


def calls(root: Path) -> list[str]:
    log = root / "vendor" / "bin" / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.is_file() else []


def loop_status(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return {r["tool"]: r["status"] for r in json.loads(result.stdout)["results"]}


class ModernizeLoopTest(unittest.TestCase):
    def test_dry_run_without_tools_reports_them_missing(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "rector,php-cs-fixer,phpcs,phpstan,phpunit,infection-diff",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            transcript = json.loads(result.stdout)
            self.assertEqual(transcript["mode"], "dry-run")
            self.assertEqual(
                loop_status(result),
                {
                    "rector": "skipped",
                    "php-cs-fixer": "skipped",
                    "phpcs": "skipped",
                    "phpstan": "missing",
                    "phpunit": "skipped",
                    "infection-diff": "skipped",
                },
            )
            actions = {a["tool"] for a in transcript["next_actions"]}
            self.assertEqual(actions, {"phpstan"})

    def test_dry_run_passes_dry_run_flags_and_reports_proposed_changes(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            (root / ".php-cs-fixer.dist.php").write_text("<?php\n", "utf-8")
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
            self.assertEqual(
                loop_status(result), {"rector": "pass", "php-cs-fixer": "changes"}
            )
            actions = json.loads(result.stdout)["next_actions"]
            self.assertEqual(
                [(a["tool"], a["action"]) for a in actions],
                [("php-cs-fixer", "review_diff")],
            )
            self.assertTrue(
                (root / ".build" / "php-modernization" / "rector.json").is_file()
            )

    def test_rector_exit_two_is_changes_and_other_codes_are_errors(self) -> None:
        for code, expected in ((2, "changes"), (1, "fail")):
            with (
                self.subTest(code=code),
                TempProject("generic-composer-minimal") as root,
            ):
                fake_tool(root, "rector", exit_code=code)
                result = run_py(
                    "modernize_loop.py", "--root", root, "--tools", "rector"
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(loop_status(result), {"rector": expected})

    def test_refactoring_runs_before_formatting_whatever_the_tools_order(self) -> None:
        with TempProject("fully-modern") as root:
            for tool in ("rector", "php-cs-fixer", "phpstan"):
                fake_tool(root, tool, exit_code=0)
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "phpstan,php-cs-fixer,rector",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                [line.split()[0] for line in calls(root)],
                ["rector", "php-cs-fixer", "phpstan"],
            )

    def test_phpcs_project_uses_phpcs_and_not_php_cs_fixer(self) -> None:
        with TempProject("generic-composer-phpcs") as root:
            fake_tool(root, "phpcs", exit_code=1, stdout=phpcs_totals(2, 2))
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "php-cs-fixer,phpcs"
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            transcript = json.loads(result.stdout)
            self.assertEqual(transcript["coding_standard"], "phpcs")
            self.assertEqual(
                loop_status(result), {"php-cs-fixer": "skipped", "phpcs": "changes"}
            )
            self.assertIn(
                "--report=json",
                (root / "vendor" / "bin" / "phpcs.args").read_text().split(),
            )
            # No advice to install a second coding-standard tool.
            tools = {a["tool"] for a in transcript["next_actions"]}
            self.assertNotIn("php-cs-fixer", tools)

    def test_php_cs_fixer_without_a_config_does_not_run(self) -> None:
        # Without a config php-cs-fixer would apply its built-in rules.
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "php-cs-fixer", exit_code=8)
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "php-cs-fixer"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(loop_status(result), {"php-cs-fixer": "skipped"})
            self.assertEqual(calls(root), [])

    def test_phpcs_verdict_respects_the_ignore_on_exit_settings(self) -> None:
        # The project's own phpcs exits 0 for warnings with
        # ignore_warnings_on_exit; the loop must not fail where it passes.
        settings = (
            ("ignore_warnings_on_exit", phpcs_totals(0, 0, warnings=3), "pass"),
            ("ignore_errors_on_exit", phpcs_totals(2, 0), "pass"),
            ("ignore_warnings_on_exit", phpcs_totals(2, 0, warnings=3), "fail"),
            (None, phpcs_totals(0, 0, warnings=3), "fail"),
            # One unfixable error, one fixable warning: totals.fixable is 1,
            # but the fixable finding is the ignored warning.
            (
                "ignore_warnings_on_exit",
                json.dumps(
                    {
                        "totals": {"errors": 1, "warnings": 1, "fixable": 1},
                        "files": {
                            "src/A.php": {
                                "messages": [
                                    {"type": "ERROR", "fixable": False},
                                    {"type": "WARNING", "fixable": True},
                                ]
                            }
                        },
                    }
                ),
                "fail",
            ),
            # PHP printed a deprecation before the report.
            (None, "Deprecated: x in y\n" + phpcs_totals(2, 2), "changes"),
        )
        for name, stdout, expected in settings:
            with (
                self.subTest(setting=name, expected=expected),
                TempProject("generic-composer-phpcs") as root,
            ):
                if name:
                    config = root / "phpcs.xml.dist"
                    text = config.read_text(encoding="utf-8")
                    config.write_text(
                        text.replace(
                            "</ruleset>",
                            f'  <config name="{name}" value="1"/>\n</ruleset>',
                        ),
                        encoding="utf-8",
                    )
                fake_tool(root, "phpcs", exit_code=0, stdout=stdout)
                result = run_py("modernize_loop.py", "--root", root, "--tools", "phpcs")
                self.assertEqual(loop_status(result), {"phpcs": expected})

    def test_phpcs_verdict_follows_the_json_totals_not_the_exit_code(self) -> None:
        # PHPCS 3.x exits 2 for every finding, 4.x uses bit flags: the totals
        # of --report=json are the same in both.
        cases = (
            (2, phpcs_totals(2, 2), "changes"),  # 3.x, all fixable
            (1, phpcs_totals(2, 2), "changes"),  # 4.x, all fixable
            (2, phpcs_totals(3, 1), "fail"),  # needs a human
            (0, phpcs_totals(0, 0), "pass"),
            (16, "not json", "error"),
        )
        for code, stdout, expected in cases:
            with (
                self.subTest(code=code, expected=expected),
                TempProject("generic-composer-phpcs") as root,
            ):
                fake_tool(root, "phpcs", exit_code=code, stdout=stdout)
                result = run_py("modernize_loop.py", "--root", root, "--tools", "phpcs")
                self.assertEqual(loop_status(result), {"phpcs": expected})

    def test_apply_with_phpcs_runs_phpcbf_then_checks(self) -> None:
        for leftover, expected in ((0, "pass"), (2, "fail")):
            with (
                self.subTest(leftover=leftover),
                TempProject("generic-composer-phpcs") as root,
            ):
                # PHPCS 3.x phpcbf exits 1 after a successful fix.
                fake_tool(root, "phpcbf", exit_code=1)
                fake_tool(root, "phpcs", exit_code=0, stdout=phpcs_totals(leftover, 0))
                result = run_py(
                    "modernize_loop.py",
                    "--root",
                    root,
                    "--mode",
                    "apply",
                    "--confirm",
                    "--tools",
                    "phpcs",
                )
                self.assertEqual(loop_status(result), {"phpcs": expected})
                self.assertEqual(calls(root), ["phpcbf ", "phpcs --report=json"])

    def test_apply_without_confirm_exits_two_and_runs_nothing(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            result = run_py("modernize_loop.py", "--root", root, "--mode", "apply")
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires --confirm", result.stderr)
            self.assertFalse((root / "vendor" / "bin" / "rector.args").exists())

    def test_apply_with_confirm_runs_without_dry_run_then_rechecks(self) -> None:
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
            self.assertEqual(
                calls(root),
                ["rector process", "rector process --dry-run --output-format=json"],
            )
            self.assertEqual(
                loop_status(result), {"rector": "pass", "rector-recheck": "pass"}
            )

    def test_rector_recheck_runs_after_the_formatter(self) -> None:
        with TempProject("fully-modern") as root:
            for tool in ("rector", "php-cs-fixer", "phpstan"):
                fake_tool(root, tool, exit_code=0)
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--mode",
                "apply",
                "--confirm",
                "--tools",
                "rector,php-cs-fixer,phpstan",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                [" ".join(line.split()[:3]) for line in calls(root)],
                [
                    "rector process",
                    "php-cs-fixer fix --config=.php-cs-fixer.dist.php",
                    "rector process --dry-run",
                    "phpstan analyse --no-progress",
                ],
            )

    def test_scope_and_rule_are_passed_to_rector(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            rule = "Rector\\Php80\\Rector\\Switch_\\ChangeSwitchToMatchRector"
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "rector",
                "--path",
                "src",
                "--rector-only",
                rule,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (root / "vendor" / "bin" / "rector.args").read_text().split()
            self.assertEqual(args[:3], ["process", "src", f"--only={rule}"])
            self.assertEqual(json.loads(result.stdout)["scope"], ["src"])

    def test_configs_under_build_are_named_on_the_command_line(self) -> None:
        # PHPStan and Rector read their config from the working directory
        # only; without the flag a TYPO3 extension's Build/phpstan.neon is
        # ignored and the run ends with "At least one path must be specified".
        with TempProject("typo3-extension-minimal") as root:
            (root / "Build").mkdir()
            (root / "Build" / "phpstan.neon").write_text(
                "parameters:\n  level: 9\n", "utf-8"
            )
            (root / "Build" / "rector.php").write_text("<?php\n", "utf-8")
            for tool in ("rector", "phpstan"):
                fake_tool(root, tool, exit_code=0)
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "rector,phpstan"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            bin_dir = root / "vendor" / "bin"
            self.assertIn(
                "--config=Build/rector.php",
                (bin_dir / "rector.args").read_text().split(),
            )
            self.assertIn(
                "--configuration=Build/phpstan.neon",
                (bin_dir / "phpstan.args").read_text().split(),
            )
            (bin_dir / "phpstan.args").unlink()
            run_py("verify_php_project.py", "--root", root, "--no-cache")
            self.assertIn(
                "--configuration=Build/phpstan.neon",
                (bin_dir / "phpstan.args").read_text().split(),
            )

    def test_path_dot_keeps_the_configured_scope(self) -> None:
        # "rector process ." would replace the config's paths and reach vendor/.
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "rector", "--path", "."
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (root / "vendor" / "bin" / "rector.args").read_text().split()
            self.assertNotIn(".", args)
            self.assertEqual(json.loads(result.stdout)["scope"], [])

    def test_a_stale_stderr_report_is_removed(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "phpstan", exit_code=0)
            stale = root / ".build" / "php-modernization" / "phpstan.json.stderr"
            stale.parent.mkdir(parents=True)
            stale.write_text("crash from an earlier run\n", encoding="utf-8")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "phpstan")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(stale.exists())

    def test_missing_path_is_a_usage_error(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            result = run_py("modernize_loop.py", "--root", root, "--path", "nope")
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not exist", result.stderr)

    def test_path_outside_the_root_is_refused(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            fake_tool(root, "rector", exit_code=0)
            for outside in ("..", "../..", str(root.parent), "src/../../"):
                with self.subTest(path=outside):
                    result = run_py(
                        "modernize_loop.py",
                        "--root",
                        root,
                        "--tools",
                        "rector",
                        "--path",
                        outside,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("outside --root", result.stderr)
            self.assertEqual(calls(root), [])

    def test_phpunit_runs_with_the_project_config(self) -> None:
        with TempProject("generic-composer-phpcs") as root:
            fake_tool(root, "phpunit", exit_code=1)
            (root / "phpunit.xml.dist").write_text("<phpunit/>\n", encoding="utf-8")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "phpunit")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(loop_status(result), {"phpunit": "fail"})
            self.assertEqual(
                (root / "vendor" / "bin" / "phpunit.args").read_text().split(),
                ["--configuration=phpunit.xml.dist"],
            )

    @unittest.skipUnless(shutil.which("php"), "needs a php binary")
    def test_lint_finds_a_syntax_error_in_the_source_dirs(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            clean = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(loop_status(clean), {"lint": "pass"}, clean.stdout)
            (root / "src" / "Broken.php").write_text("<?php\nfunction (\n", "utf-8")
            broken = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(broken.returncode, 1)
            self.assertEqual(loop_status(broken), {"lint": "fail"})
            report = (root / ".build" / "php-modernization" / "lint.txt").read_text()
            self.assertIn("Broken.php", report)

    @unittest.skipUnless(shutil.which("php"), "needs a php binary")
    def test_lint_skips_vendor_and_the_project_excludes(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            for rel in ("vendor/pkg/Old.php", "tests/Fixtures/Invalid.php"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("<?php\nfunction (\n", "utf-8")
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer.setdefault("scripts", {})["lint"] = (
                "parallel-lint --exclude tests/Fixtures src tests"
            )
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "lint", "--path", "."
            )
            self.assertEqual(loop_status(result), {"lint": "pass"}, result.stdout)
            # Control: without the project's exclude the fixture is linted.
            del composer["scripts"]["lint"]
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(loop_status(result), {"lint": "fail"})

    @unittest.skipUnless(shutil.which("php"), "needs a php binary")
    def test_lint_of_a_root_mapped_package_skips_vendor(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["autoload"] = {"psr-4": {"Vendor\\Pkg\\": ""}}
            composer.pop("autoload-dev", None)
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            (root / "vendor" / "pkg").mkdir(parents=True)
            (root / "vendor" / "pkg" / "Old.php").write_text("<?php\nfunction (\n")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            # Linted, not skipped, and vendor/ is not part of it.
            self.assertEqual(loop_status(result), {"lint": "pass"}, result.stdout)
            (root / "Broken.php").write_text("<?php\nfunction (\n", "utf-8")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(loop_status(result), {"lint": "fail"})

    def test_rector_without_a_config_is_skipped_and_build_configs_are_found(
        self,
    ) -> None:
        # Rector without a config analyses nothing and exits 0.
        with TempProject("generic-composer-minimal") as root:
            binary = root / "vendor" / "bin" / "rector"
            fake_tool(root, "rector", exit_code=0)
            (root / "rector.php").unlink()
            result = run_py("modernize_loop.py", "--root", root, "--tools", "rector")
            self.assertEqual(loop_status(result), {"rector": "skipped"})
            self.assertEqual(calls(root), [])
            # The TYPO3 tea layout: Build/rector/config.php and
            # Build/php-cs-fixer/config.php.
            for rel in ("Build/rector/config.php", "Build/php-cs-fixer/config.php"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("<?php\n", encoding="utf-8")
            fake_tool(root, "php-cs-fixer", exit_code=0)
            self.assertTrue(binary.is_file())
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "rector,php-cs-fixer"
            )
            self.assertEqual(
                json.loads(result.stdout)["coding_standard"], "php-cs-fixer"
            )
            bin_dir = root / "vendor" / "bin"
            self.assertIn(
                "--config=Build/rector/config.php",
                (bin_dir / "rector.args").read_text().split(),
            )
            self.assertIn(
                "--config=Build/php-cs-fixer/config.php",
                (bin_dir / "php-cs-fixer.args").read_text().split(),
            )

    def test_php_cs_fixer_keeps_the_config_finder_for_a_path(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "php-cs-fixer", exit_code=0)
            run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "php-cs-fixer",
                "--path",
                "src",
            )
            args = (root / "vendor" / "bin" / "php-cs-fixer.args").read_text().split()
            self.assertIn("--path-mode=intersection", args)

    def test_php_cs_fixer_config_without_a_finder_gets_the_paths(self) -> None:
        # php-cs-fixer refuses intersection for a config with no Finder.
        with TempProject("fully-modern") as root:
            fixer = fake_tool(root, "php-cs-fixer", exit_code=8)
            fixer.write_text(
                fixer.read_text().replace(
                    "#!/bin/sh\n",
                    "#!/bin/sh\n"
                    'case " $* " in *" --path-mode=intersection "*)\n'
                    '  echo "Cannot create intersection with not-fully defined'
                    ' Finder in configuration file." >&2; exit 16;; esac\n',
                ),
                encoding="utf-8",
            )
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "php-cs-fixer",
                "--path",
                "src",
            )
            self.assertEqual(loop_status(result), {"php-cs-fixer": "changes"})
            self.assertNotIn(
                "--path-mode=intersection",
                (root / "vendor" / "bin" / "php-cs-fixer.args").read_text().split(),
            )

    def test_php_cs_fixer_pass_for_a_path_names_its_scope(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "php-cs-fixer", exit_code=0)
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "php-cs-fixer",
                "--path",
                "src",
            )
            summary = json.loads(result.stdout)["results"][0]["summary"]
            self.assertIn("not checked", summary)

    def test_lint_script_glob_skips_dotfiles_like_the_shell(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import modernize_loop

        with TempProject("generic-composer-minimal") as root:
            for name in ("ext_emconf.php", ".php-cs-fixer.dist.php"):
                (root / name).write_text("<?php\n", encoding="utf-8")
            targets = modernize_loop._lint_script_targets(
                root, {"scripts": {"lint": "parallel-lint *.php src"}}
            )
            self.assertEqual(targets, ["ext_emconf.php", "src"])

    def test_lint_script_targets_end_at_the_command(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import modernize_loop

        with TempProject("generic-composer-minimal") as root:
            (root / "Build").mkdir()
            for script, expected in (
                ("parallel-lint src tests && phpstan analyse Build", ["src", "tests"]),
                ("parallel-lint src tests; echo ok", ["src", "tests"]),
            ):
                with self.subTest(script=script):
                    targets = modernize_loop._lint_script_targets(
                        root, {"scripts": {"lint": script}}
                    )
                    self.assertEqual(targets, expected)

    def test_php_cs_fixer_config_without_a_finder_and_no_path(self) -> None:
        # Without a Finder the project passes its paths on the command line.
        with TempProject("fully-modern") as root:
            fixer = fake_tool(root, "php-cs-fixer", exit_code=8)
            fixer.write_text(
                fixer.read_text().replace(
                    "#!/bin/sh\n",
                    "#!/bin/sh\n"
                    'case " $* " in *" src "*) ;; *)\n'
                    '  echo "You must call one of in() or append()" >&2; exit 1;; esac\n',
                ),
                encoding="utf-8",
            )
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "php-cs-fixer"
            )
            self.assertEqual(loop_status(result), {"php-cs-fixer": "changes"})
            self.assertIn(
                "src",
                (root / "vendor" / "bin" / "php-cs-fixer.args").read_text().split(),
            )

    def test_rector_pass_for_a_path_names_its_scope(self) -> None:
        with TempProject("fully-modern") as root:
            fake_tool(root, "rector", exit_code=0)
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "rector",
                "--path",
                "src",
            )
            summary = json.loads(result.stdout)["results"][0]["summary"]
            self.assertIn("not checked", summary)

    def _fake_infection(self, root: Path, stdout: str, log: dict | None) -> None:
        """A vendor/bin/infection that writes the log to its --logger-json path."""
        fake_tool(root, "infection", exit_code=0, stdout=stdout)
        binary = root / "vendor" / "bin" / "infection"
        if log is not None:
            payload = json.dumps(log).replace("'", "'\\''")
            binary.write_text(
                binary.read_text(encoding="utf-8").replace(
                    "exit 0\n",
                    'for a in "$@"; do case "$a" in --logger-json=*) '
                    f"printf '%s' '{payload}' > \"${{a#--logger-json=}}\";; esac; done\n"
                    "exit 0\n",
                ),
                encoding="utf-8",
            )

    def _run_infection_diff(self, root: Path) -> dict:
        result = run_py(
            "modernize_loop.py",
            "--root",
            root,
            "--tools",
            "infection-diff",
            "--git-diff-base",
            "origin/main",
        )
        return json.loads(result.stdout)["results"][0]

    def test_infection_diff_passes_no_msi_threshold(self) -> None:
        # The diff run gates on escaped and not covered mutants, never on an MSI percentage:
        # the project's thresholds belong to the scheduled full run.
        for files in ({"infection.json5": '{"minMsi": 95}'}, {}):
            with (
                self.subTest(files=sorted(files)),
                TempProject("fully-modern") as root,
            ):
                self._fake_infection(
                    root,
                    "",
                    {
                        "stats": {
                            "totalMutantsCount": 2,
                            "escapedCount": 0,
                            "notCoveredCount": 0,
                        }
                    },
                )
                for name, text in files.items():
                    (root / name).write_text(text, encoding="utf-8")
                self._run_infection_diff(root)
                args = (root / "vendor" / "bin" / "infection.args").read_text().split()
                self.assertIn("--min-msi=0", args)
                self.assertIn("--min-covered-msi=0", args)
                self.assertIn("--git-diff-lines", args)
                self.assertTrue(any(a.startswith("--logger-json=") for a in args), args)

    def test_infection_diff_fails_on_an_escaped_mutant(self) -> None:
        cases = (
            (
                {
                    "stats": {
                        "totalMutantsCount": 3,
                        "escapedCount": 1,
                        "notCoveredCount": 0,
                    }
                },
                "fail",
                "1 escaped",
            ),
            (
                {
                    "stats": {
                        "totalMutantsCount": 3,
                        "escapedCount": 0,
                        "notCoveredCount": 0,
                    }
                },
                "pass",
                "3 generated",
            ),
        )
        for log, status, text in cases:
            with self.subTest(log=log), TempProject("fully-modern") as root:
                self._fake_infection(root, "", log)
                outcome = self._run_infection_diff(root)
                self.assertEqual(outcome["status"], status, outcome)
                self.assertIn(text, outcome["summary"])

    def test_infection_diff_without_a_log(self) -> None:
        # Infection writes no log when the diff holds no source line; any
        # other run without a log checked nothing and must not pass.
        nothing = (
            " [OK] Could not find any modified lines for the git filter"
            ' "AM" and the base "origin/main".'
        )
        excluded = (
            " [OK] No source file found for the filter applied to the configured"
            ' sources. The git filter used was: "AM".'
        )
        cases = (
            (
                nothing,
                "pass",
            ),
            (excluded, "pass"),
            ("Infection - PHP Mutation Testing Framework", "error"),
        )
        for stdout, status in cases:
            with self.subTest(stdout=stdout), TempProject("fully-modern") as root:
                self._fake_infection(root, stdout, None)
                outcome = self._run_infection_diff(root)
                self.assertEqual(outcome["status"], status, outcome)

    def test_infection_diff_fails_on_an_uncovered_mutant(self) -> None:
        # A method no test calls, added to a tested class: without
        # --with-uncovered Infection drops its nodes and reports 0 generated.
        # With the flag they count as not covered, and the run must fail.
        with TempProject("fully-modern") as root:
            self._fake_infection(
                root,
                "",
                {
                    "stats": {
                        "totalMutantsCount": 2,
                        "escapedCount": 0,
                        "notCoveredCount": 2,
                    }
                },
            )
            outcome = self._run_infection_diff(root)
            args = (root / "vendor" / "bin" / "infection.args").read_text().split()
            self.assertIn("--with-uncovered", args)
            self.assertEqual(outcome["status"], "fail", outcome)
            self.assertIn("2 not covered", outcome["summary"])

    def test_infection_diff_fails_when_no_test_executed_the_diff(self) -> None:
        # A new class no test executes: Infection prints this, exits 0 and
        # writes no log. The diff has source lines; no test ran them.
        stdout = (
            " [OK] No source code from the diff was executed by the test framework."
        )
        with TempProject("fully-modern") as root:
            self._fake_infection(root, stdout, None)
            outcome = self._run_infection_diff(root)
            self.assertEqual(outcome["status"], "fail", outcome)
            self.assertIn("no test executed", outcome["summary"])

    def test_binary_under_a_custom_vendor_dir(self) -> None:
        with TempProject("fully-modern") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["config"] = {"vendor-dir": ".Build/vendor"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            fake_tool(root, "phpstan", exit_code=0)
            target = root / ".Build" / "vendor" / "bin"
            target.parent.mkdir(parents=True)
            (root / "vendor").rename(root / ".Build" / "vendor")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "phpstan")
            self.assertEqual(loop_status(result), {"phpstan": "pass"}, result.stdout)

    @unittest.skipUnless(shutil.which("php"), "needs a php binary")
    def test_lint_covers_the_targets_of_the_project_lint_script(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            (root / "ext_emconf.php").write_text("<?php\nfunction (\n", "utf-8")
            clean = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(loop_status(clean), {"lint": "pass"})
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["scripts"] = {"lint": "parallel-lint *.php src tests"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(loop_status(result), {"lint": "fail"}, result.stdout)

    def test_lint_script_options_end_at_the_command(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import modernize_loop

        script = "parallel-lint src && tar --exclude=src -p x -cf dist.tar ."
        composer = {"scripts": {"lint": script}}
        self.assertEqual(modernize_loop._lint_excludes(REPO_ROOT, composer), [])
        self.assertIsNone(modernize_loop._lint_php(composer))
        composer = {"scripts": {"lint": "parallel-lint -p php8.1 --exclude x src"}}
        self.assertEqual(modernize_loop._lint_excludes(REPO_ROOT, composer), ["x"])
        self.assertEqual(modernize_loop._lint_php(composer), "php8.1")

    def test_lint_excludes_never_narrow_another_call(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import modernize_loop

        with TempProject("generic-composer-minimal") as root:
            (root / "tests" / "Fixtures").mkdir(parents=True, exist_ok=True)
            cases = (
                # Another script lints tests without excluding it.
                (["parallel-lint --exclude tests .", "parallel-lint tests"], []),
                # The same exclude in two scripts is kept.
                (
                    [
                        "parallel-lint --exclude tests/Fixtures src tests",
                        "parallel-lint --exclude tests/Fixtures --checkstyle src tests",
                    ],
                    ["tests/Fixtures"],
                ),
                # A script that does not lint the excluded path keeps it.
                (
                    [
                        "parallel-lint --exclude tests/Fixtures src tests",
                        "parallel-lint src",
                    ],
                    ["tests/Fixtures"],
                ),
            )
            for scripts, expected in cases:
                with self.subTest(scripts=scripts):
                    composer = {
                        "scripts": {f"lint{i}": c for i, c in enumerate(scripts)}
                    }
                    self.assertEqual(
                        modernize_loop._lint_excludes(root, composer), expected
                    )

    def test_lint_script_glob_matches_a_named_hidden_directory(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import modernize_loop

        with TempProject("generic-composer-minimal") as root:
            (root / "src" / ".checks").mkdir(parents=True)
            (root / "src" / ".checks" / "x.php").write_text("<?php\n", "utf-8")
            targets = modernize_loop._lint_script_targets(
                root, {"scripts": {"lint": "parallel-lint src/.checks/*.php"}}
            )
            self.assertEqual(targets, ["src/.checks/x.php"])

    @unittest.skipUnless(shutil.which("php"), "needs a php binary")
    def test_lint_resolves_a_relative_php_against_the_root(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            tools = root / "tools"
            tools.mkdir()
            (tools / "php").write_text(
                f'#!/bin/sh\nexec {shutil.which("php")} "$@"\n', "utf-8"
            )
            (tools / "php").chmod(0o755)
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["scripts"] = {"lint": "parallel-lint -p tools/php src"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            result = run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            self.assertEqual(loop_status(result), {"lint": "pass"}, result.stdout)

    def test_lint_passes_the_project_php_to_parallel_lint(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["scripts"] = {"lint": "parallel-lint -p php8.1 src"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            fake_tool(root, "parallel-lint", exit_code=0)
            run_py("modernize_loop.py", "--root", root, "--tools", "lint")
            args = (root / "vendor" / "bin" / "parallel-lint.args").read_text()
            self.assertIn("-p\nphp8.1\n", args)

    @unittest.skipUnless(shutil.which("php"), "needs a php binary")
    def test_lint_checks_an_explicit_template_file(self) -> None:
        with TempProject("generic-composer-minimal") as root:
            (root / "templates").mkdir()
            (root / "templates" / "bad.phtml").write_text("<?php\nfunction (\n")
            result = run_py(
                "modernize_loop.py",
                "--root",
                root,
                "--tools",
                "lint",
                "--path",
                "templates/bad.phtml",
            )
            self.assertEqual(loop_status(result), {"lint": "fail"}, result.stdout)

    def test_php_cs_fixer_fallback_keeps_a_root_mapped_package(self) -> None:
        # Without a Finder the loop passes the source dirs. A package that
        # maps its root ("") gets the top-level entries: its production
        # code and tests, but not node_modules or the vendor-dir, which the
        # real fixer would otherwise rewrite in apply mode.
        with TempProject("fully-modern") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["autoload"] = {"psr-4": {"Vendor\\Pkg\\": ""}}
            composer["autoload-dev"] = {"psr-4": {"Vendor\\Pkg\\Tests\\": "tests/"}}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            (root / "tests").mkdir(exist_ok=True)
            (root / "Root.php").write_text("<?php\n", "utf-8")
            (root / "node_modules" / "x").mkdir(parents=True)
            fixer = fake_tool(root, "php-cs-fixer", exit_code=0)
            # After the arguments are logged, so a failed call leaves them too.
            fixer.write_text(
                fixer.read_text().replace(
                    '/calls.log"\n',
                    '/calls.log"\n'
                    'case " $* " in *" tests "*) ;; *)\n'
                    '  echo "You must call one of in() or append()" >&2; exit 1;; esac\n',
                ),
                encoding="utf-8",
            )
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "php-cs-fixer"
            )
            self.assertEqual(loop_status(result), {"php-cs-fixer": "pass"})
            args = (root / "vendor" / "bin" / "php-cs-fixer.args").read_text().split()
            self.assertIn("Root.php", args)
            self.assertIn("tests", args)
            for third_party in ("node_modules", "vendor", "."):
                self.assertNotIn(third_party, args)
            # A nested vendor-dir: its parent's own code stays, it does not.
            composer["config"] = {"vendor-dir": "lib/deps"}
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            (root / "lib" / "deps" / "x").mkdir(parents=True)
            (root / "lib" / "Own.php").write_text("<?php\n", "utf-8")
            run_py("modernize_loop.py", "--root", root, "--tools", "php-cs-fixer")
            args = (root / "vendor" / "bin" / "php-cs-fixer.args").read_text().split()
            self.assertIn("lib/Own.php", args)
            self.assertNotIn("lib", args)
            self.assertNotIn("lib/deps", args)
            self.assertNotIn("vendor", args)

    def test_php_cs_fixer_fallback_without_own_code_is_skipped(self) -> None:
        with TempProject("fully-modern") as root:
            composer = json.loads((root / "composer.json").read_text("utf-8"))
            composer["autoload"] = {"psr-4": {"Vendor\\Pkg\\": ""}}
            composer.pop("autoload-dev", None)
            (root / "composer.json").write_text(json.dumps(composer), "utf-8")
            for entry in sorted(root.iterdir()):
                if entry.name not in {
                    "vendor",
                    "composer.json",
                } and not entry.name.startswith("."):
                    shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
            fixer = fake_tool(root, "php-cs-fixer", exit_code=0)
            fixer.write_text(
                fixer.read_text().replace(
                    '/calls.log"\n',
                    '/calls.log"\n'
                    'echo "You must call one of in() or append()" >&2; exit 1\n',
                ),
                encoding="utf-8",
            )
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "php-cs-fixer"
            )
            self.assertEqual(loop_status(result), {"php-cs-fixer": "skipped"})
            self.assertEqual(len(calls(root)), 1)

    def test_several_rector_rules_need_rector_2_6_7(self) -> None:
        rules = ("--rector-only", "A\\One", "--rector-only", "B\\Two")
        with TempProject("fully-modern") as root:
            fake_tool(root, "rector", exit_code=0, stdout="Rector 2.6.6")
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "rector", *rules
            )
            self.assertEqual(loop_status(result), {"rector": "fail"})
            self.assertEqual(calls(root), ["rector --version"])
            fake_tool(root, "rector", exit_code=0, stdout="Rector 2.6.7")
            result = run_py(
                "modernize_loop.py", "--root", root, "--tools", "rector", *rules
            )
            self.assertEqual(loop_status(result), {"rector": "pass"}, result.stdout)
            args = (root / "vendor" / "bin" / "rector.args").read_text().split()
            self.assertIn("--only=A\\One", args)
            self.assertIn("--only=B\\Two", args)

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


class WrapperWithoutUvTest(unittest.TestCase):
    """Without uv the wrapper may use python3 only when it is 3.11 or later.

    An older python3 dies on `from datetime import UTC`, which is the failure
    the 3.11 floor exists to prevent. PATH holds a directory with one python3
    and the system directories for `dirname`; uv must not be reachable.
    """

    SYSTEM_PATH = "/usr/bin:/bin"

    def setUp(self) -> None:
        if shutil.which("uv", path=self.SYSTEM_PATH):
            self.skipTest("uv is installed in a system directory")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name)

    def run_wrapper(self, root: Path) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PATH=f"{self.bin}:{self.SYSTEM_PATH}")
        return subprocess.run(
            ["/bin/bash", str(SCRIPTS / "verify-php-project.sh"), str(root)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=env,
        )

    def test_python_older_than_3_11_is_refused(self) -> None:
        marker = self.bin / "ran"
        stub = self.bin / "python3"
        # Answers the version probe like Python 3.9; records any other call.
        stub.write_text(f'#!/bin/sh\n[ "$1" = "-c" ] && exit 1\ntouch "{marker}"\n')
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        with TempProject("fully-modern") as root:
            result = self.run_wrapper(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("3.11 or later", result.stderr)
        self.assertFalse(marker.exists(), "the old python3 ran the script")

    def test_python_3_11_or_later_runs_the_verifier(self) -> None:
        (self.bin / "python3").symlink_to(sys.executable)
        with TempProject("fully-modern") as root:
            result = self.run_wrapper(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
