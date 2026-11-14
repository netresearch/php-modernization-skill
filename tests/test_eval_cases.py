#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Prove the checks of the executable eval cases in evals/cases/.

Runs ``evals/cases/check_case.py --self-test``: for every case the start
state does what ``case.json`` says, the good solution passes lint, PHPStan
and PHPUnit, and the bad solution fails at the named check. A broken case
would let an agent eval score a wrong patch as correct, so this runs in CI
with the other tests.

Needs ``php`` and ``composer`` on PATH; installs the case tools into
``evals/cases/vendor`` when they are missing. Without php or composer the
test fails — a missing check is not a pass.

Stdlib only. Run with ``python3 tests/test_eval_cases.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES = REPO_ROOT / "evals" / "cases"
CHECKER = CASES / "check_case.py"


def run(*args: str | Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(a) for a in args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


class EvalCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [tool for tool in ("php", "composer") if shutil.which(tool) is None]
        if missing:
            raise AssertionError(f"needs {', '.join(missing)} on PATH")
        if not (CASES / "vendor" / "bin" / "phpunit").is_file():
            done = run(
                "composer",
                "install",
                "--no-interaction",
                "--no-progress",
                f"--working-dir={CASES}",
            )
            if done.returncode != 0:
                raise AssertionError(f"composer install failed:\n{done.stderr}")

    def test_every_case_has_the_parts_the_checker_needs(self) -> None:
        cases = sorted(p.parent for p in CASES.glob("*/case.json"))
        self.assertEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case.name):
                meta = json.loads((case / "case.json").read_text(encoding="utf-8"))
                self.assertEqual(meta["id"], case.name)
                self.assertIn(meta["kind"], {"convert", "keep"})
                self.assertIn(meta["bad"]["fails_at"], {"lint", "phpstan", "phpunit"})
                for part in (
                    "project/src",
                    "acceptance",
                    "solutions/good/src",
                    "solutions/bad/src",
                ):
                    self.assertTrue((case / part).is_dir(), part)

    def test_self_test_holds_for_every_case(self) -> None:
        done = run(sys.executable, CHECKER, "--self-test")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("8 case(s), 0 broken", done.stdout)

    def test_an_agent_cannot_pass_by_replacing_the_acceptance_tests(self) -> None:
        # A result tree whose own tests/Acceptance claims success must still
        # be judged by the checker's acceptance tests.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            shutil.copytree(
                CASES / "readonly-booking" / "project", tree, dirs_exist_ok=True
            )
            fake = tree / "tests" / "Acceptance"
            fake.mkdir(parents=True)
            (fake / "BookingTest.php").write_text(
                "<?php\nnamespace Cases\\ReadonlyBooking\\Tests\\Acceptance;\n"
                "final class BookingTest extends \\PHPUnit\\Framework\\TestCase\n"
                "{ public function testNothing(): void { self::assertTrue(true); } }\n",
                encoding="utf-8",
            )
            done = run(sys.executable, CHECKER, "readonly-booking", "--tree", tree)
            self.assertEqual(done.returncode, 1, done.stdout)
            self.assertFalse(json.loads(done.stdout)["passed"])


def load_runner():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_agent_cases", REPO_ROOT / "evals" / "run_agent_cases.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunValidityTest(unittest.TestCase):
    """An agent run counts only when its skill state is the intended one."""

    plugin = Path("/tmp/plugins/abc")

    def init(self, skills: list[str], plugins: list[dict]) -> dict:
        return {
            "type": "system",
            "subtype": "init",
            "skills": skills,
            "plugins": plugins,
        }

    def ours(self) -> dict:
        return {
            "name": "php-modernization",
            "path": str(self.plugin),
            "source": "php-modernization@inline",
        }

    def test_without_arm(self) -> None:
        runner = load_runner()
        self.assertEqual(
            runner.validity("without", self.init(["other"], []), None), (True, "")
        )
        valid, reason = runner.validity(
            "without", self.init(["php-modernization"], []), None
        )
        self.assertFalse(valid)
        self.assertIn("without arm", reason)

    def test_with_arm_needs_exactly_the_plugin_under_test(self) -> None:
        runner = load_runner()
        ok = self.init(["php-modernization:php-modernization"], [self.ours()])
        self.assertEqual(runner.validity("with:HEAD", ok, self.plugin), (True, ""))
        # The installed user-level copy loads as well: invalid.
        both = self.init(
            ["php-modernization", "php-modernization:php-modernization"], [self.ours()]
        )
        self.assertFalse(runner.validity("with:HEAD", both, self.plugin)[0])
        # Another plugin path: the run measured a different skill.
        other = dict(self.ours(), path="/elsewhere")
        self.assertFalse(
            runner.validity("with:HEAD", self.init([], [other]), self.plugin)[0]
        )
        self.assertFalse(runner.validity("with:HEAD", None, self.plugin)[0])

    def test_invoke_arm_needs_the_slash_command(self) -> None:
        runner = load_runner()
        ok = self.init(["php-modernization:php-modernization"], [self.ours()])
        valid, reason = runner.validity("invoke:HEAD", ok, self.plugin)
        self.assertFalse(valid)
        self.assertIn("slash command", reason)
        ok["slash_commands"] = ["php-modernization:php-modernization"]
        self.assertEqual(runner.validity("invoke:HEAD", ok, self.plugin), (True, ""))
        self.assertTrue(
            runner.prompt("invoke:HEAD", "Do X.").startswith(
                "/php-modernization:php-modernization Do X."
            )
        )
        self.assertTrue(runner.prompt("with:HEAD", "Do X.").startswith("Do X."))


def load_reviewer():
    sys.path.insert(0, str(REPO_ROOT / "evals"))
    import run_review_cases

    return run_review_cases


class ReviewScoringTest(unittest.TestCase):
    """What the review evals read from the agent's tree."""

    def test_verdict_line(self) -> None:
        r = load_reviewer()
        self.assertEqual(r.verdict("Verdict: approve\n- ok"), "approve")
        self.assertEqual(
            r.verdict("# Review\n**Verdict:** Request changes"), "request changes"
        )
        self.assertIsNone(r.verdict("Looks good to me."))

    def test_review_file_is_not_followed_through_a_link(self) -> None:
        r = load_reviewer()
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "secret"
            secret.write_text("host data", encoding="utf-8")
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "REVIEW.md").symlink_to(secret)
            self.assertEqual(r.read_review(tree), "")
            (tree / "REVIEW.md").unlink()
            (tree / "REVIEW.md").write_text("Verdict: approve\n", encoding="utf-8")
            self.assertEqual(r.read_review(tree), "Verdict: approve\n")


class HostGitTest(unittest.TestCase):
    """The host records the patch without reading the agent's .git."""

    def test_planted_clean_filter_does_not_run_on_the_host(self) -> None:
        runner = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "a.php").write_text("<?php\n", encoding="utf-8")
            git = runner.host_git(tree)
            ident = ["-c", "user.name=t", "-c", "user.email=t@invalid"]
            for cmd in (["init", "-q"], ["add", "-A"], [*ident, "commit", "-qm", "b"]):
                subprocess.run([*git, *cmd], cwd=tmp, check=True)
            # What an agent can do inside its tree: its own repository with a
            # clean filter that git runs on add. No -c option of host_git
            # switches a filter off; only the separate git dir keeps it out.
            marker = Path(tmp) / "ran"
            trap = tree / "trap.sh"
            trap.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n", encoding="utf-8")
            trap.chmod(0o755)
            subprocess.run(["git", "init", "-q"], cwd=tree, check=True)
            subprocess.run(
                ["git", "config", "filter.x.clean", str(trap)], cwd=tree, check=True
            )
            (tree / ".gitattributes").write_text("*.php filter=x\n", encoding="utf-8")
            (tree / "a.php").write_text("<?php\necho 1;\n", encoding="utf-8")

            subprocess.run([*git, "add", "-A"], cwd=tmp, check=True)
            diff = subprocess.run(
                [*git, "diff", "--cached", "--no-ext-diff"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("+echo 1;", diff)
            self.assertFalse(marker.exists(), "the host ran the agent's filter")
            # Control: plain git in the tree reads that config and runs it.
            subprocess.run(["git", "add", "-A"], cwd=tree, check=True)
            self.assertTrue(marker.exists(), "the trap did not fire: no control")


if __name__ == "__main__":
    unittest.main()
