#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Acceptance checks for the executable eval cases in evals/cases/.

Each case directory holds:

- ``case.json``      — task text, PHP floor, what the start state and the
                       known-bad solution are expected to do
- ``project/``       — the code an agent works on
- ``acceptance/``    — PHPUnit tests the agent never sees or edits
- ``solutions/good`` and ``solutions/bad`` — files laid over ``project/``

A check copies a result tree into a temporary directory, replaces its tests
and tool configs with the checker's own (so an agent cannot weaken them),
and runs, in order: ``php -l`` on every source file, PHPStan with the case's
PHP floor as ``phpVersion``, and PHPUnit on the acceptance tests. The tools
come from ``evals/cases/vendor`` (``composer install`` in ``evals/cases``).

    uv run evals/cases/check_case.py --self-test
    uv run evals/cases/check_case.py enum-order-status --solution good
    uv run evals/cases/check_case.py enum-order-status --tree /path/to/agent/result

``--self-test`` proves the checks before any agent is scored: for every case
the start state does what ``start_expect`` says, the good solution passes
every check, and the bad solution fails at the named check — with the
named PHPStan identifier or message — after the earlier checks passed, so
it is not a syntax or build error.

Exit code: 0 when the checked tree passes (or the self-test holds), 1 when
it does not, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent
VENDOR = CASES_DIR / "vendor"
CHECK_ORDER = ("lint", "phpstan", "phpunit")
PHPSTAN_LEVEL = 5
TIMEOUT = 300


@dataclass
class CheckResult:
    check: str
    status: str  # pass | fail | error
    exit_code: int | None
    detail: str
    identifiers: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def load_case(case_id: str) -> dict:
    path = CASES_DIR / case_id / "case.json"
    if not path.is_file():
        raise SystemExit(f"error: unknown case {case_id!r} (no {path})")
    return json.loads(path.read_text(encoding="utf-8"))


def all_cases() -> list[str]:
    return sorted(p.parent.name for p in CASES_DIR.glob("*/case.json"))


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("vendor", ".git", ".build", "var", "*.cache"),
    )


def prepare(case: dict, tree: Path, work: Path) -> None:
    """Lay ``tree`` out in ``work`` with the checker's tests and configs."""
    _copy_tree(tree, work)
    acceptance = work / "tests" / "Acceptance"
    if acceptance.exists():
        shutil.rmtree(acceptance)
    shutil.copytree(CASES_DIR / case["id"] / "acceptance", acceptance)
    # _copy_tree left the tree's own vendor/ out; the checker's tools are used.
    (work / "vendor").symlink_to(VENDOR, target_is_directory=True)
    ns = case["namespace"].replace("\\", "\\\\")
    (work / "check-bootstrap.php").write_text(
        "<?php\n"
        "declare(strict_types=1);\n"
        "require __DIR__ . '/vendor/autoload.php';\n"
        "spl_autoload_register(static function (string $class): void {\n"
        f"    $prefix = '{ns}';\n"
        "    if (!str_starts_with($class, $prefix)) {\n"
        "        return;\n"
        "    }\n"
        "    $file = __DIR__ . '/src/' . str_replace('\\\\', '/', substr($class, strlen($prefix))) . '.php';\n"
        "    if (is_file($file)) {\n"
        "        require $file;\n"
        "    }\n"
        "});\n",
        encoding="utf-8",
    )
    major, minor = (int(x) for x in case["php_floor"].split(".")[:2])
    (work / "check-phpstan.neon").write_text(
        "parameters:\n"
        f"  level: {PHPSTAN_LEVEL}\n"
        f"  phpVersion: {major * 10000 + minor * 100}\n"
        "  treatPhpDocTypesAsCertain: false\n"
        "  paths:\n"
        "    - src\n"
        "  bootstrapFiles:\n"
        "    - check-bootstrap.php\n"
        "  tmpDir: .build/phpstan\n",
        encoding="utf-8",
    )
    (work / "check-phpunit.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<phpunit bootstrap="check-bootstrap.php" colors="false" cacheDirectory=".build/phpunit">\n'
        '  <testsuites><testsuite name="acceptance"><directory>tests/Acceptance</directory></testsuite></testsuites>\n'
        "</phpunit>\n",
        encoding="utf-8",
    )


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def check_lint(work: Path) -> CheckResult:
    php = shutil.which("php")
    if php is None:
        return CheckResult("lint", "error", None, "php is not installed")
    failures: list[str] = []
    files = sorted((work / "src").rglob("*.php"))
    for f in files:
        done = _run([php, "-l", str(f)], work)
        if done is None or done.returncode != 0:
            out = "" if done is None else (done.stdout + done.stderr).strip()
            failures.append(out or str(f.relative_to(work)))
    if failures:
        return CheckResult("lint", "fail", 1, "; ".join(failures))
    return CheckResult("lint", "pass", 0, f"{len(files)} files")


def check_phpstan(work: Path) -> CheckResult:
    done = _run(
        [
            str(VENDOR / "bin" / "phpstan"),
            "analyse",
            "-c",
            "check-phpstan.neon",
            "--no-progress",
            "--error-format=json",
            "--memory-limit=1G",
        ],
        work,
    )
    if done is None:
        return CheckResult("phpstan", "error", None, "timeout or not runnable")
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        return CheckResult(
            "phpstan", "error", done.returncode, done.stderr.strip()[:500]
        )
    identifiers: list[str] = []
    messages: list[str] = list(report.get("errors") or [])
    for file_report in (report.get("files") or {}).values():
        for m in file_report.get("messages", []):
            identifiers.append(m.get("identifier") or "")
            messages.append(m.get("message", ""))
    if done.returncode == 0 and not messages:
        return CheckResult("phpstan", "pass", 0, "no errors")
    return CheckResult(
        "phpstan",
        "fail",
        done.returncode,
        f"{len(messages)} error(s)",
        identifiers=identifiers,
        messages=messages,
    )


def check_phpunit(work: Path) -> CheckResult:
    junit = work / ".build" / "junit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    done = _run(
        [
            str(VENDOR / "bin" / "phpunit"),
            "-c",
            "check-phpunit.xml",
            "--no-coverage",
            f"--log-junit={junit}",
        ],
        work,
    )
    if done is None:
        return CheckResult("phpunit", "error", None, "timeout or not runnable")
    tests = failures = errors = 0
    if junit.is_file():
        try:
            suite = ET.parse(junit).getroot()
            tests = int(suite.get("tests") or 0)
            failures = int(suite.get("failures") or 0)
            errors = int(suite.get("errors") or 0)
            first = suite.find("testsuite")
            if first is not None and tests == 0:
                tests = int(first.get("tests") or 0)
                failures = int(first.get("failures") or 0)
                errors = int(first.get("errors") or 0)
        except ET.ParseError:
            pass
    # A JUnit log with failing or erroring tests = the tests ran and some did
    # not pass (PHPUnit exits 1 for failures, 2 for errors such as a
    # ValueError from the code under test). No log, no test, or a fatal
    # (255) is an error of the run itself, not a verdict on the code.
    if done.returncode == 0 and tests > 0:
        return CheckResult("phpunit", "pass", 0, f"{tests} tests")
    if done.returncode in (1, 2) and junit.is_file() and failures + errors > 0:
        return CheckResult(
            "phpunit",
            "fail",
            1,
            f"{tests} tests, {failures} failures, {errors} errors",
            messages=[(done.stdout or "")[-2000:]],
        )
    return CheckResult(
        "phpunit",
        "error",
        done.returncode,
        ((done.stdout or "") + (done.stderr or "")).strip()[-1000:],
    )


RUNNERS = {"lint": check_lint, "phpstan": check_phpstan, "phpunit": check_phpunit}


def check_tree(case: dict, tree: Path) -> list[CheckResult]:
    with tempfile.TemporaryDirectory(prefix=f"case-{case['id']}-") as tmp:
        work = Path(tmp)
        prepare(case, tree, work)
        return [RUNNERS[name](work) for name in CHECK_ORDER]


def solution_tree(case: dict, solution: str | None, into: Path) -> Path:
    base = CASES_DIR / case["id"]
    _copy_tree(base / "project", into)
    if solution:
        _copy_tree(base / "solutions" / solution, into)
    return into


def check_solution(case: dict, solution: str | None) -> list[CheckResult]:
    with tempfile.TemporaryDirectory() as tmp:
        return check_tree(case, solution_tree(case, solution, Path(tmp)))


def passed(results: list[CheckResult]) -> bool:
    return all(r.status == "pass" for r in results)


def self_test_case(case: dict) -> list[str]:
    """Return the problems with one case's checks; empty when the case holds."""
    problems: list[str] = []
    by = {}
    for label in ("start", "good", "bad"):
        by[label] = check_solution(case, None if label == "start" else label)

    start_ok = passed(by["start"])
    if case["start_expect"] == "pass" and not start_ok:
        problems.append(f"start state should pass: {_brief(by['start'])}")
    if case["start_expect"] == "fail" and start_ok:
        problems.append(
            "start state passes; an unchanged tree would count as a solved task"
        )
    if not passed(by["good"]):
        problems.append(f"good solution fails: {_brief(by['good'])}")

    target = case["bad"]["fails_at"]
    for r in by["bad"]:
        if r.check == target:
            if r.status != "fail":
                problems.append(
                    f"bad solution: {target} is {r.status}, expected fail ({r.detail})"
                )
            expect = case["bad"].get("expect") or {}
            if "identifier" in expect and expect["identifier"] not in r.identifiers:
                problems.append(
                    f"bad solution: {target} lacks identifier {expect['identifier']} (got {r.identifiers})"
                )
            if "message" in expect and not any(
                expect["message"] in m for m in r.messages
            ):
                problems.append(
                    f"bad solution: {target} lacks message {expect['message']!r}"
                )
            break
        if r.status != "pass":
            problems.append(
                f"bad solution fails earlier, at {r.check} ({r.status}: {r.detail}) — not at {target}"
            )
            break
    return problems


def _brief(results: list[CheckResult]) -> str:
    return ", ".join(
        f"{r.check}={r.status}" + (f" ({r.detail})" if r.status != "pass" else "")
        for r in results
    )


def ensure_vendor() -> None:
    if (
        not (VENDOR / "bin" / "phpunit").is_file()
        or not (VENDOR / "bin" / "phpstan").is_file()
    ):
        raise SystemExit(
            "error: evals/cases/vendor is not installed — run "
            "`composer install --working-dir=evals/cases` first"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_case", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("case", nargs="?", help="case id (directory name)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--solution", choices=("good", "bad"), help="check a shipped solution"
    )
    group.add_argument(
        "--tree", type=Path, help="check this result tree (an agent's copy of project/)"
    )
    parser.add_argument(
        "--self-test", action="store_true", help="prove the checks of every case"
    )
    args = parser.parse_args(argv)

    ensure_vendor()
    if args.self_test:
        failures = 0
        for case_id in [args.case] if args.case else all_cases():
            problems = self_test_case(load_case(case_id))
            print(f"{case_id:28} {'ok' if not problems else 'BROKEN'}")
            for p in problems:
                print(f"    {p}")
            failures += bool(problems)
        print(f"{len(all_cases()) if not args.case else 1} case(s), {failures} broken")
        return 1 if failures else 0

    if not args.case:
        parser.error("a case id is required without --self-test")
    case = load_case(args.case)
    if args.tree:
        if not args.tree.is_dir():
            parser.error(f"--tree {args.tree} is not a directory")
        results = check_tree(case, args.tree.resolve())
    else:
        results = check_solution(case, args.solution)
    print(
        json.dumps(
            {
                "case": case["id"],
                "passed": passed(results),
                "checks": [asdict(r) for r in results],
            },
            indent=2,
        )
    )
    return 0 if passed(results) else 1


if __name__ == "__main__":
    sys.exit(main())
