#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fix-loop orchestrator for PHP modernization.

Runs the project's own tools in a fixed order, in either dry-run mode
(default, safe) or apply mode (mutates files; requires --confirm):

1. rector          — refactoring (``--only`` and paths narrow the scope)
2. php-cs-fixer    — formatter, when the project uses PHP-CS-Fixer
   phpcs           — formatter, when the project uses PHPCS (phpcbf in apply,
                     then phpcs; the verdict comes from phpcs's JSON totals)
3. lint            — syntax, with parallel-lint when installed, else ``php -l``
4. phpstan         — static analysis
5. phpunit         — the project's test suite, when it has a PHPUnit config
6. infection-diff  — mutation testing of the changed lines (PR mode)

Refactoring runs before formatting, so the formatter tidies what Rector
wrote; the checks run last, on the final code. In apply mode Rector runs a
second dry-run of the same scope after the formatter (``rector-recheck``): a
finished step proposes no further change.

Output is a structured JSON transcript the agent reasons about. Statuses:
pass, changes (a dry-run proposes edits), fail (the tool reports findings or
errors), missing (binary not installed), skipped (not configured or not
applicable), timeout, error.

Exit code: 0 if no required tool ends in changes, fail, timeout or error;
1 otherwise; 2 on usage errors. Missing and skipped tools are not failures.
Infection is required only when --git-diff-base is set (PR mode).

Dry-run changes no tracked file: the reports go to .build/php-modernization/,
and the tools may write their own caches.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Sibling-import the shared module (see introspect.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    PHP_CS_FIXER_CANDIDATES,
    PHPCS_CONFIG_CANDIDATES,
    PHPUNIT_CONFIG_CANDIDATES,
    coding_standard,
    find_binary,
    first_existing,
    read_composer_json,
    source_dirs,
)

SCHEMA_VERSION = "1.1.0"
ARTIFACT_DIR = Path(".build/php-modernization")
SUBPROCESS_TIMEOUT_SECONDS = 600

# Execution order. --tools selects a subset; the order stays this one.
ALL_TOOLS: tuple[str, ...] = (
    "rector",
    "php-cs-fixer",
    "phpcs",
    "lint",
    "phpstan",
    "phpunit",
    "infection-diff",
)
# Statuses of a required tool that make the run exit 1. "changes" counts: a
# dry-run that proposes edits has work left for the agent.
FAILING_STATUSES = frozenset({"changes", "fail", "timeout", "error"})
FORMATTERS = frozenset({"php-cs-fixer", "phpcs"})


@dataclass
class ToolResult:
    tool: str
    status: str  # pass | changes | fail | missing | skipped | timeout | error
    exit_code: int | None
    command: str
    duration_seconds: float
    summary: str
    artifact: str | None = None


@dataclass
class NextAction:
    action: str
    tool: str
    rationale: str
    artifact: str | None = None


@dataclass
class Transcript:
    schema_version: str
    mode: str
    tools_invoked: list[str]
    scope: list[str]
    coding_standard: str
    results: list[ToolResult]
    next_actions: list[NextAction] = field(default_factory=list)


@dataclass
class Context:
    root: Path
    mode: str
    paths: list[str]
    rector_rules: list[str]
    composer: dict | None
    coding_standard: str
    php_cs_fixer_config: str | None
    phpcs_config: str | None
    phpunit_config: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_artifact_dir(root: Path) -> Path:
    target = root / ARTIFACT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _run(
    cmd: list[str],
    cwd: Path,
    artifact: Path | None,
) -> tuple[int | None, float, str | None]:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - start, "timeout"
    except OSError as exc:
        return None, time.monotonic() - start, f"error: {exc}"
    duration = time.monotonic() - start
    if artifact is not None:
        try:
            artifact.write_text(
                (completed.stdout or "") + (completed.stderr or ""), encoding="utf-8"
            )
        except OSError:
            pass
    return completed.returncode, duration, None


def _missing(tool: str, what: str) -> ToolResult:
    return ToolResult(
        tool=tool,
        status="missing",
        exit_code=None,
        command=f"({what} not installed)",
        duration_seconds=0.0,
        summary="binary not found in the Composer bin-dir, vendor/bin or .Build/bin",
    )


def _skipped(tool: str, reason: str) -> ToolResult:
    return ToolResult(
        tool=tool,
        status="skipped",
        exit_code=None,
        command="(not run)",
        duration_seconds=0.0,
        summary=reason,
    )


def _execute(
    ctx: Context,
    tool: str,
    cmd: list[str],
    artifact_name: str | None,
    classify,
) -> ToolResult:
    """Run ``cmd`` and map its exit code with ``classify(rc) -> (status, summary)``."""
    artifact = _ensure_artifact_dir(ctx.root) / artifact_name if artifact_name else None
    rc, duration, err = _run(cmd, ctx.root, artifact)
    command = " ".join(cmd)
    if err == "timeout":
        return ToolResult(tool, "timeout", None, command, duration, "exceeded timeout")
    if err:
        return ToolResult(tool, "error", None, command, duration, err)
    status, summary = classify(rc)
    return ToolResult(
        tool=tool,
        status=status,
        exit_code=rc,
        command=command,
        duration_seconds=duration,
        summary=summary,
        artifact=str(artifact.relative_to(ctx.root)) if artifact else None,
    )


# ---------------------------------------------------------------------------
# Tool runners
# ---------------------------------------------------------------------------


def run_rector(ctx: Context, *, dry_run: bool, tool: str = "rector") -> ToolResult:
    binary = find_binary(ctx.root, "rector", ctx.composer)
    if binary is None:
        return _missing(tool, "rector")
    cmd = [str(binary), "process", *ctx.paths]
    cmd += [f"--only={rule}" for rule in ctx.rector_rules]
    if dry_run:
        cmd += ["--dry-run", "--output-format=json"]

    # Rector: 0 = nothing to change, 2 = changes proposed (dry-run), any
    # other code = an error (config, parse, crash).
    def classify(rc: int) -> tuple[str, str]:
        if rc == 0:
            return (
                "pass",
                "rector: no change" if dry_run else "rector applied transforms",
            )
        if dry_run and rc == 2:
            return (
                "changes",
                "rector: changes proposed — review the diff before applying",
            )
        return "fail", f"rector: error (exit {rc})"

    return _execute(ctx, tool, cmd, f"{tool}.json" if dry_run else None, classify)


def run_php_cs_fixer(ctx: Context, *, dry_run: bool) -> ToolResult:
    if ctx.coding_standard == "phpcs":
        return _skipped(
            "php-cs-fixer",
            f"the project uses PHPCS ({ctx.phpcs_config}); see the phpcs result",
        )
    binary = find_binary(ctx.root, "php-cs-fixer", ctx.composer)
    if binary is None:
        return _missing("php-cs-fixer", "php-cs-fixer")
    cmd = [str(binary), "fix"]
    if ctx.php_cs_fixer_config:
        cmd.append(f"--config={ctx.php_cs_fixer_config}")
    cmd += ctx.paths
    if dry_run:
        cmd += ["--dry-run", "--diff", "--format=json"]

    # PHP-CS-Fixer exit codes are bit flags; 8 alone = "files need fixing".
    def classify(rc: int) -> tuple[str, str]:
        if rc == 0:
            return "pass", "php-cs-fixer: clean" if dry_run else "all files fixed"
        if dry_run and rc == 8:
            return "changes", "php-cs-fixer: changes proposed (exit 8)"
        return "fail", f"php-cs-fixer: error (exit {rc})"

    return _execute(
        ctx, "php-cs-fixer", cmd, "php-cs-fixer.json" if dry_run else None, classify
    )


def run_phpcs(ctx: Context, *, dry_run: bool) -> ToolResult:
    """PHPCS in dry-run, PHPCBF followed by a PHPCS check in apply.

    The verdict comes from the totals of ``phpcs --report=json``, not from
    exit codes: those differ between the major versions. Measured with
    3.13.6 and 4.0.4 — phpcs exits 2 for any finding in 3.x, while 4.x uses
    bit flags (1 = fixable, 2 = needs a human); phpcbf exits 1 after a
    successful fix in 3.x and 2 in 4.x when unfixable findings remain.
    """
    if ctx.coding_standard not in {"phpcs", "both"}:
        return _skipped("phpcs", "no PHPCS config in the project")
    phpcs = find_binary(ctx.root, "phpcs", ctx.composer)
    if phpcs is None:
        return _missing("phpcs", "phpcs")
    args: list[str] = []
    # PHPCS finds a config only in the working directory; one under Build/
    # has to be named.
    if ctx.phpcs_config and "/" in ctx.phpcs_config:
        args.append(f"--standard={ctx.phpcs_config}")
    args += ctx.paths

    commands: list[str] = []
    duration = 0.0
    if not dry_run:
        phpcbf = find_binary(ctx.root, "phpcbf", ctx.composer)
        if phpcbf is None:
            return _missing("phpcs", "phpcbf")
        cmd = [str(phpcbf), *args]
        commands.append(" ".join(cmd))
        rc, took, err = _run(cmd, ctx.root, None)
        duration += took
        if err:
            status = "timeout" if err == "timeout" else "error"
            return ToolResult("phpcs", status, rc, commands[0], duration, err)

    cmd = [str(phpcs), "--report=json", *args]
    commands.append(" ".join(cmd))
    artifact = _ensure_artifact_dir(ctx.root) / "phpcs.json"
    command = " && ".join(commands)
    start = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(ctx.root),
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            "phpcs", "timeout", None, command, duration, "exceeded timeout"
        )
    except OSError as exc:
        return ToolResult("phpcs", "error", None, command, duration, f"error: {exc}")
    duration += time.monotonic() - start
    rc = completed.returncode
    try:
        report = json.loads(completed.stdout or "")
        totals = report["totals"]
        found = int(totals.get("errors", 0)) + int(totals.get("warnings", 0))
        fixable = int(totals.get("fixable", 0))
    except (ValueError, KeyError, TypeError):
        return ToolResult(
            "phpcs",
            "error",
            rc,
            command,
            duration,
            "phpcs: no JSON report (config or run error)",
        )
    try:
        artifact.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        artifact = None  # type: ignore[assignment]  # the verdict does not need the file
    rel = str(artifact.relative_to(ctx.root)) if artifact else None
    if found == 0:
        summary = "phpcs: clean" if dry_run else "phpcbf applied; phpcs: clean"
        return ToolResult("phpcs", "pass", rc, command, duration, summary, rel)
    if dry_run and fixable == found:
        summary = f"phpcs: {found} finding(s), all fixable by phpcbf"
        return ToolResult("phpcs", "changes", rc, command, duration, summary, rel)
    if dry_run:
        summary = f"phpcs: {found} finding(s), {found - fixable} need a human"
        return ToolResult("phpcs", "fail", rc, command, duration, summary, rel)
    summary = (
        f"phpcbf applied; phpcs still reports {found} finding(s) that need a human"
    )
    return ToolResult("phpcs", "fail", rc, command, duration, summary, rel)


def _lint_targets(ctx: Context) -> list[str]:
    if ctx.paths:
        return list(ctx.paths)
    dirs = source_dirs(ctx.root, ctx.composer)
    return [d for d in dirs["src"] + dirs["tests"] if d != "."]


def run_lint(ctx: Context) -> ToolResult:
    targets = _lint_targets(ctx)
    if not targets:
        return _skipped(
            "lint", "no source directories found (composer autoload, src/, Classes/)"
        )
    parallel = find_binary(ctx.root, "parallel-lint", ctx.composer)
    if parallel is not None:
        cmd = [str(parallel), "--no-progress", *targets]
        return _execute(
            ctx,
            "lint",
            cmd,
            "lint.txt",
            lambda rc: (
                ("pass", "parallel-lint: no syntax error")
                if rc == 0
                else ("fail", f"parallel-lint: syntax errors (exit {rc})")
            ),
        )
    php = shutil.which("php")
    if php is None:
        return _missing("lint", "php")
    files: list[Path] = []
    for target in targets:
        p = ctx.root / target
        if p.is_file() and p.suffix == ".php":
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.php")))
    start = time.monotonic()
    failures: list[str] = []
    for f in files:
        try:
            completed = subprocess.run(
                [php, "-l", str(f)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            failures.append(f"{f.relative_to(ctx.root)}: {exc}")
            continue
        if completed.returncode != 0:
            failures.append(
                (completed.stdout + completed.stderr).strip()
                or f"{f.relative_to(ctx.root)}: exit {completed.returncode}"
            )
    duration = time.monotonic() - start
    artifact = _ensure_artifact_dir(ctx.root) / "lint.txt"
    try:
        artifact.write_text("\n".join(failures) + ("\n" if failures else ""), "utf-8")
    except OSError:
        # The report file is a convenience; the failures are in the summary
        # and the status, which do not depend on it.
        pass
    version = subprocess.run(
        [php, "-r", "echo PHP_VERSION;"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return ToolResult(
        tool="lint",
        status="fail" if failures else "pass",
        exit_code=1 if failures else 0,
        command=f"php -l <file> ({len(files)} files in {', '.join(targets)})",
        duration_seconds=duration,
        summary=(
            f"php -l under PHP {version}: {len(failures)} of {len(files)} files fail"
            if failures
            else f"php -l under PHP {version}: {len(files)} files, no syntax error"
            " (a lower supported PHP version needs its own run, or PHPStan phpVersion)"
        ),
        artifact=str(artifact.relative_to(ctx.root)),
    )


def run_phpstan(ctx: Context) -> ToolResult:
    binary = find_binary(ctx.root, "phpstan", ctx.composer)
    if binary is None:
        return _missing("phpstan", "phpstan")
    cmd = [str(binary), "analyse", "--no-progress", "--error-format=json", *ctx.paths]
    return _execute(
        ctx,
        "phpstan",
        cmd,
        "phpstan.json",
        lambda rc: (
            ("pass", "phpstan: clean")
            if rc == 0
            else ("fail", f"phpstan: errors detected (exit {rc})")
        ),
    )


def run_phpunit(ctx: Context) -> ToolResult:
    if ctx.phpunit_config is None:
        return _skipped("phpunit", "no PHPUnit config in the project")
    binary = find_binary(ctx.root, "phpunit", ctx.composer)
    if binary is None:
        return _missing("phpunit", "phpunit")
    cmd = [str(binary), f"--configuration={ctx.phpunit_config}"]
    return _execute(
        ctx,
        "phpunit",
        cmd,
        "phpunit.txt",
        lambda rc: (
            ("pass", "phpunit: all tests pass")
            if rc == 0
            else ("fail", f"phpunit: failures or errors (exit {rc})")
        ),
    )


def run_infection_diff(ctx: Context, *, git_diff_base: str) -> ToolResult:
    binary = find_binary(ctx.root, "infection", ctx.composer)
    if binary is None:
        return _missing("infection-diff", "infection")
    threads = str(os.cpu_count() or 1)
    cmd = [
        str(binary),
        f"--git-diff-base={git_diff_base}",
        "--git-diff-lines",
        f"--threads={threads}",
        "--min-msi=80",
        "--logger-github",
        "--formatter=summary",
    ]
    return _execute(
        ctx,
        "infection-diff",
        cmd,
        "infection.txt",
        lambda rc: (
            ("pass", "infection diff: MSI threshold met")
            if rc == 0
            else ("fail", f"infection diff: below MSI (exit {rc})")
        ),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def parse_tools(value: str) -> list[str]:
    requested = [t.strip() for t in value.split(",") if t.strip()]
    unknown = [t for t in requested if t not in ALL_TOOLS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown tool(s): {', '.join(unknown)} — choose from {', '.join(ALL_TOOLS)}"
        )
    return requested


def required_tools(tools: Iterable[str], *, pr_mode: bool) -> set[str]:
    tools = set(tools)
    required = tools - {"infection-diff"}
    if "rector" in tools:
        required.add("rector-recheck")
    if pr_mode and "infection-diff" in tools:
        required.add("infection-diff")
    return required


def build_next_actions(results: Iterable[ToolResult]) -> list[NextAction]:
    out: list[NextAction] = []
    for r in results:
        if r.status == "changes":
            out.append(
                NextAction(
                    action="review_diff",
                    tool=r.tool,
                    rationale=r.summary,
                    artifact=r.artifact,
                )
            )
        elif r.status == "fail":
            out.append(
                NextAction(
                    action="fix_findings",
                    tool=r.tool,
                    rationale=r.summary,
                    artifact=r.artifact,
                )
            )
        elif r.status == "missing":
            out.append(
                NextAction(
                    action="install_tool",
                    tool=r.tool,
                    rationale=f"{r.tool} is not installed; add it to require-dev",
                )
            )
        elif r.status in {"timeout", "error"}:
            out.append(
                NextAction(
                    action="investigate",
                    tool=r.tool,
                    rationale=f"{r.tool} ended with status {r.status}: {r.summary}",
                    artifact=r.artifact,
                )
            )
    return out


def build_context(
    root: Path, *, mode: str, paths: list[str], rector_rules: list[str]
) -> Context:
    composer = read_composer_json(root)
    fixer_config = first_existing(root, PHP_CS_FIXER_CANDIDATES)
    return Context(
        root=root,
        mode=mode,
        paths=paths,
        rector_rules=rector_rules,
        composer=composer,
        coding_standard=coding_standard(root, fixer_config),
        php_cs_fixer_config=fixer_config,
        phpcs_config=first_existing(root, PHPCS_CONFIG_CANDIDATES),
        phpunit_config=first_existing(root, PHPUNIT_CONFIG_CANDIDATES),
    )


def execute(
    root: Path,
    *,
    mode: str,
    tools: list[str],
    git_diff_base: str | None,
    paths: list[str] | None = None,
    rector_rules: list[str] | None = None,
) -> Transcript:
    ctx = build_context(
        root, mode=mode, paths=list(paths or []), rector_rules=list(rector_rules or [])
    )
    dry_run = mode != "apply"
    selected = [t for t in ALL_TOOLS if t in tools]
    results: list[ToolResult] = []
    # In apply mode Rector's dry-run is repeated once the formatter has run,
    # so that the recheck sees the final code of the step.
    recheck_pending = False
    for tool in selected:
        if recheck_pending and tool not in FORMATTERS:
            results.append(run_rector(ctx, dry_run=True, tool="rector-recheck"))
            recheck_pending = False
        if tool == "rector":
            first = run_rector(ctx, dry_run=dry_run)
            results.append(first)
            recheck_pending = not dry_run and first.status == "pass"
        elif tool == "php-cs-fixer":
            results.append(run_php_cs_fixer(ctx, dry_run=dry_run))
        elif tool == "phpcs":
            results.append(run_phpcs(ctx, dry_run=dry_run))
        elif tool == "lint":
            results.append(run_lint(ctx))
        elif tool == "phpstan":
            results.append(run_phpstan(ctx))
        elif tool == "phpunit":
            results.append(run_phpunit(ctx))
        elif tool == "infection-diff":
            if git_diff_base is None:
                results.append(
                    _skipped(
                        "infection-diff", "infection-diff requires --git-diff-base"
                    )
                )
            else:
                results.append(run_infection_diff(ctx, git_diff_base=git_diff_base))
    if recheck_pending:
        results.append(run_rector(ctx, dry_run=True, tool="rector-recheck"))
    return Transcript(
        schema_version=SCHEMA_VERSION,
        mode=mode,
        tools_invoked=selected,
        scope=ctx.paths,
        coding_standard=ctx.coding_standard,
        results=results,
        next_actions=build_next_actions(results),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="modernize_loop",
        description="Run PHP modernization tools as a structured fix-loop (dry-run by default).",
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "apply"),
        default="dry-run",
        help="dry-run reports proposed changes; apply mutates files (requires --confirm)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required when --mode=apply; explicit acknowledgment that files will be mutated",
    )
    parser.add_argument(
        "--root", default=".", help="Project root (default: current directory)"
    )
    parser.add_argument(
        "--tools",
        type=parse_tools,
        default=list(ALL_TOOLS),
        help=f"Comma-separated subset of tools to run, always in this order: {','.join(ALL_TOOLS)}",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        metavar="PATH",
        help="Limit rector, the formatter, lint and phpstan to this path (repeatable); phpunit always runs the whole suite",
    )
    parser.add_argument(
        "--rector-only",
        action="append",
        default=[],
        dest="rector_rules",
        metavar="RULE",
        help="Run only this Rector rule (FQCN, repeatable); it must be registered in the Rector config or a set it loads",
    )
    parser.add_argument(
        "--git-diff-base",
        default=None,
        help="Base ref for infection-diff (e.g. origin/main); enables PR-mode infection requirement",
    )
    parser.add_argument(
        "--format",
        choices=("json",),
        default="json",
        help="Output format (only json is currently supported)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.stderr.write(f"error: --root {args.root!r} is not a directory\n")
        return 2
    if args.mode == "apply" and not args.confirm:
        sys.stderr.write("error: --mode=apply requires --confirm to mutate files\n")
        return 2
    paths: list[str] = []
    for rel in args.paths:
        target = (root / rel).resolve()
        # Apply mode rewrites these paths: they must stay inside the project.
        if not target.is_relative_to(root):
            sys.stderr.write(f"error: --path {rel!r} is outside --root\n")
            return 2
        if not target.exists():
            sys.stderr.write(f"error: --path {rel!r} does not exist under --root\n")
            return 2
        paths.append(str(target.relative_to(root)) if target != root else ".")

    transcript = execute(
        root,
        mode=args.mode,
        tools=args.tools if isinstance(args.tools, list) else list(args.tools),
        git_diff_base=args.git_diff_base,
        paths=paths,
        rector_rules=args.rector_rules,
    )

    sys.stdout.write(json.dumps(asdict(transcript), indent=2) + "\n")

    pr_mode = args.git_diff_base is not None
    required = required_tools(transcript.tools_invoked, pr_mode=pr_mode)
    failing_required = [
        r
        for r in transcript.results
        if r.tool in required and r.status in FAILING_STATUSES
    ]
    return 1 if failing_required else 0


if __name__ == "__main__":
    sys.exit(main())
