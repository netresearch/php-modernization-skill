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
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree  # the project's own config; trusted as code

# Sibling-import the shared module (see introspect.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    PHP_CS_FIXER_CANDIDATES,
    PHPCS_CONFIG_CANDIDATES,
    PHPSTAN_CONFIG_CANDIDATES,
    PHPUNIT_CONFIG_CANDIDATES,
    RECTOR_CONFIG_CANDIDATES,
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
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


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
    phpstan_config: str | None = None
    rector_config: str | None = None


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
) -> tuple[int | None, float, str | None, str]:
    """Run ``cmd``; return exit code, duration, run error and stderr's last line.

    The artifact receives stdout only, so a JSON report stays JSON; stderr
    (deprecations, stack traces) goes to ``<artifact>.stderr`` when present.
    """
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
        return None, time.monotonic() - start, "timeout", ""
    except OSError as exc:
        return None, time.monotonic() - start, f"error: {exc}", ""
    duration = time.monotonic() - start
    stderr = completed.stderr or ""
    if artifact is not None:
        try:
            artifact.write_text(completed.stdout or "", encoding="utf-8")
            stderr_file = artifact.with_name(artifact.name + ".stderr")
            if stderr.strip():
                stderr_file.write_text(stderr, encoding="utf-8")
            else:
                # A file from an earlier run must not sit beside this report.
                stderr_file.unlink(missing_ok=True)
        except OSError:
            # The reports are a convenience; status and summary do not
            # depend on them.
            pass
    plain = ANSI_ESCAPE_RE.sub("", stderr)
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    return completed.returncode, duration, None, (lines[-1][:200] if lines else "")


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
    rc, duration, err, stderr_tail = _run(cmd, ctx.root, artifact)
    command = " ".join(cmd)
    if err == "timeout":
        return ToolResult(tool, "timeout", None, command, duration, "exceeded timeout")
    if err:
        return ToolResult(tool, "error", None, command, duration, err)
    status, summary = classify(rc)
    if status in {"fail", "error"} and stderr_tail:
        summary = f"{summary} — stderr: {stderr_tail}"
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


def _rector_version(binary: Path) -> tuple[int, int, int] | None:
    """The version ``rector --version`` prints; None for a dev build or an error."""
    try:
        out = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", out)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def run_rector(ctx: Context, *, dry_run: bool, tool: str = "rector") -> ToolResult:
    if ctx.rector_config is None:
        # Rector without a config prints 'No "rector.php" config found',
        # analyses nothing and exits 0: that is no pass.
        return _skipped(tool, "no Rector config in the project")
    binary = find_binary(ctx.root, "rector", ctx.composer)
    if binary is None:
        return _missing(tool, "rector")
    if len(ctx.rector_rules) > 1:
        version = _rector_version(binary)
        if version is not None and version < (2, 6, 7):
            # Before 2.6.7, --only takes one value and a repeated --only keeps
            # the last one: the other rules would be skipped without a word.
            return ToolResult(
                tool=tool,
                status="fail",
                exit_code=None,
                command="(not run)",
                duration_seconds=0.0,
                summary=(
                    f"rector {'.'.join(map(str, version))} runs one --only rule; "
                    "repeated --rector-only needs Rector 2.6.7 or later"
                ),
            )
    cmd = [str(binary), "process", *ctx.paths]
    # Rector reads rector.php from the working directory only.
    if ctx.rector_config and ctx.rector_config != "rector.php":
        cmd.append(f"--config={ctx.rector_config}")
    cmd += [f"--only={rule}" for rule in ctx.rector_rules]
    if dry_run:
        cmd += ["--dry-run", "--output-format=json"]

    # Rector: 0 = nothing to change, 2 = changes proposed (dry-run), any
    # other code = an error (config, parse, crash).
    def classify(rc: int) -> tuple[str, str]:
        if rc == 0:
            return (
                "pass",
                ("rector: no change" if dry_run else "rector applied transforms")
                + (
                    "; a --path the config skips or excludes is not checked"
                    if ctx.paths
                    else ""
                ),
            )
        if dry_run and rc == 2:
            return (
                "changes",
                "rector: changes proposed — review the diff before applying",
            )
        return "fail", f"rector: error (exit {rc})"

    return _execute(ctx, tool, cmd, f"{tool}.json" if dry_run else None, classify)


def _fixer_needs_paths(ctx: Context, artifact: str, result: ToolResult) -> bool:
    """Whether php-cs-fixer stopped because the config has no Finder paths."""
    try:
        stderr = (ctx.root / ARTIFACT_DIR / f"{artifact}.stderr").read_text("utf-8")
    except OSError:
        stderr = ""
    text = stderr + result.summary
    return result.status == "fail" and (
        "You must call one of in() or append()" in text
        or "not-fully defined Finder" in text
    )


def _third_party_dirs(ctx: Context) -> list[str]:
    """Existing directories at the root that hold code the project does not own."""
    vendor_dir = ((ctx.composer or {}).get("config") or {}).get("vendor-dir")
    found: list[str] = []
    for name in (vendor_dir or "vendor", ".Build", "node_modules"):
        if not isinstance(name, str):
            continue
        name = name.rstrip("/")
        if (ctx.root / name).is_dir() and name not in found:
            found.append(name)
    return found


def _root_entries(ctx: Context) -> list[str]:
    """The project root as explicit paths, without third-party directories."""
    # A nested vendor-dir (lib/vendor) keeps its parent, which can hold the
    # project's own code; the fixer's Finder skips a directory named vendor.
    skip = {d for d in _third_party_dirs(ctx) if "/" not in d}
    try:
        entries = sorted(ctx.root.iterdir())
    except OSError:
        return ["."]
    paths = [
        p.name
        for p in entries
        if not p.name.startswith(".")
        and p.name not in skip
        and (p.is_dir() or p.suffix == ".php")
    ]
    return paths or ["."]


def run_php_cs_fixer(ctx: Context, *, dry_run: bool) -> ToolResult:
    if ctx.coding_standard == "phpcs":
        return _skipped(
            "php-cs-fixer",
            f"the project uses PHPCS ({ctx.phpcs_config}); see the phpcs result",
        )
    if ctx.coding_standard == "none":
        # Without a config php-cs-fixer applies its built-in rules, which the
        # project never chose.
        return _skipped("php-cs-fixer", "no PHP-CS-Fixer config in the project")
    binary = find_binary(ctx.root, "php-cs-fixer", ctx.composer)
    if binary is None:
        return _missing("php-cs-fixer", "php-cs-fixer")
    base = [str(binary), "fix"]
    if ctx.php_cs_fixer_config:
        base.append(f"--config={ctx.php_cs_fixer_config}")
    tail = ["--dry-run", "--diff", "--format=json"] if dry_run else []
    # Apply mode keeps a report too: its stderr decides the fallback below.
    artifact = "php-cs-fixer.json" if dry_run else "php-cs-fixer.txt"
    # A pass for a --path says nothing about files outside the config's
    # Finder: intersection leaves them out.
    scoped = " within the config's Finder; a path outside it is not checked"

    # PHP-CS-Fixer exit codes are bit flags; 8 alone = "files need fixing".
    def classify(rc: int) -> tuple[str, str]:
        if rc == 0:
            done = "php-cs-fixer: clean" if dry_run else "all files fixed"
            return "pass", done + (scoped if ctx.paths else "")
        if dry_run and rc == 8:
            return "changes", "php-cs-fixer: changes proposed (exit 8)"
        return "fail", f"php-cs-fixer: error (exit {rc})"

    if not ctx.paths:
        result = _execute(ctx, "php-cs-fixer", base + tail, artifact, classify)
        if not _fixer_needs_paths(ctx, artifact, result):
            return result
        # The project passes its paths on the command line; without a
        # --path the loop uses the source and test directories.
        # A package that maps its root ("") gets the top-level entries
        # instead of ".": the fixer's Finder skips directories named vendor
        # and dot-directories, but not node_modules or a vendor-dir with
        # another name, and apply mode would rewrite them.
        dirs = source_dirs(ctx.root, ctx.composer)
        found = dirs["src"] + [d for d in dirs["tests"] if d not in dirs["src"]]
        paths = _root_entries(ctx) if "." in found or not found else found
        return _execute(ctx, "php-cs-fixer", [*base, *paths, *tail], artifact, classify)
    # Without intersection the paths replace the config's Finder, and files
    # the project excludes get fixed.
    result = _execute(
        ctx,
        "php-cs-fixer",
        [*base, "--path-mode=intersection", *ctx.paths, *tail],
        artifact,
        classify,
    )
    # The message is not stderr's last line (php-cs-fixer prints its usage
    # after it): _fixer_needs_paths reads the whole stderr report.
    if not _fixer_needs_paths(ctx, artifact, result):
        return result
    # A config without a Finder takes its paths from the command line, and
    # php-cs-fixer refuses intersection for it: nothing to exclude, so the
    # paths are used as given.
    scoped = ""
    return _execute(ctx, "php-cs-fixer", [*base, *ctx.paths, *tail], artifact, classify)


def _phpcs_exit_settings(ctx: Context) -> tuple[bool, bool]:
    """``ignore_warnings_on_exit`` and ``ignore_errors_on_exit`` from the config.

    The project's own phpcs passes when these are set, so the verdict counts
    what phpcs's exit code would count.
    """
    if not ctx.phpcs_config:
        return False, False
    try:
        # The project's own phpcs.xml: the project is trusted as code (its
        # phpcs runs anyway), and the scripts are stdlib-only. See
        # docs/SECURITY-ASSURANCE.md.
        # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
        tree = ElementTree.parse(ctx.root / ctx.phpcs_config)
    except (OSError, ElementTree.ParseError):
        return False, False
    settings = {
        el.get("name"): (el.get("value") or "").strip()
        for el in tree.getroot().iter("config")
    }
    return (
        settings.get("ignore_warnings_on_exit") in {"1", "true"},
        settings.get("ignore_errors_on_exit") in {"1", "true"},
    )


def _phpcs_report(stdout: str) -> dict:
    """The JSON report, also when PHP printed a notice before it."""
    try:
        return json.loads(stdout)
    except ValueError:
        start = stdout.find('{"totals"')
        if start < 0:
            raise
        return json.loads(stdout[start:])


def _phpcs_counts(
    report: dict, ignore_warnings: bool, ignore_errors: bool
) -> tuple[int, int]:
    """(findings, fixable findings) of the types phpcs's exit code counts.

    ``totals.fixable`` counts errors and warnings together, so with an
    ignored type the fixable count comes from the messages.
    """
    totals = report["totals"]
    found = (0 if ignore_errors else int(totals.get("errors", 0))) + (
        0 if ignore_warnings else int(totals.get("warnings", 0))
    )
    if not (ignore_warnings or ignore_errors):
        return found, int(totals.get("fixable", 0))
    ignored = {"WARNING"} if ignore_warnings else set()
    if ignore_errors:
        ignored.add("ERROR")
    fixable = sum(
        1
        for entry in (report.get("files") or {}).values()
        for message in entry.get("messages") or []
        if message.get("fixable") and message.get("type") not in ignored
    )
    return found, fixable


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
        phpcbf_rc, took, err, _ = _run(cmd, ctx.root, None)
        duration += took
        if err:
            status = "timeout" if err == "timeout" else "error"
            return ToolResult("phpcs", status, phpcbf_rc, commands[0], duration, err)

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
        report = _phpcs_report(completed.stdout or "")
        found, fixable = _phpcs_counts(report, *_phpcs_exit_settings(ctx))
    except (ValueError, KeyError, TypeError, AttributeError):
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
        if ctx.paths:
            summary += "; a --path the config skips or excludes is not checked"
        return ToolResult("phpcs", "pass", rc, command, duration, summary, rel)
    if dry_run and fixable == found:
        summary = f"phpcs: {found} finding(s), all fixable by phpcbf"
        return ToolResult("phpcs", "changes", rc, command, duration, summary, rel)
    if dry_run:
        summary = f"phpcs: {found} finding(s), {found - fixable} need a human"
        return ToolResult("phpcs", "fail", rc, command, duration, summary, rel)
    summary = (
        f"phpcbf applied (exit {phpcbf_rc}); phpcs still reports {found} "
        "finding(s) that need a human"
    )
    return ToolResult("phpcs", "fail", rc, command, duration, summary, rel)


def _lint_targets(ctx: Context) -> list[str]:
    if ctx.paths:
        return list(ctx.paths)
    scripted = _lint_script_targets(ctx.root, ctx.composer)
    if scripted:
        return scripted
    dirs = source_dirs(ctx.root, ctx.composer)
    targets = dirs["src"] + [d for d in dirs["tests"] if d not in dirs["src"]]
    # A package that maps its root ("psr-4": {"Vendor\\": ""}) is linted
    # as "."; run_lint keeps vendor/ out of that.
    return ["."] if "." in targets else targets


# parallel-lint options that take a value (1.4.0, Settings::parseArguments).
_LINT_VALUE_OPTIONS = {
    "--exclude",
    "-e",
    "-p",
    "-j",
    "--git",
    "--syntax-error-callback",
}
_COMMAND_SEPARATORS = {"&&", "||", ";", "|"}


def _lint_script_calls(composer: dict | None) -> list[list[str]]:
    """The arguments of each parallel-lint call in the Composer scripts.

    Each list ends where that shell command ends, so the arguments of the
    next command (``&& tar --exclude=src …``) are never read as lint options.
    """
    scripts = (composer or {}).get("scripts")
    if not isinstance(scripts, dict):
        return []
    calls: list[list[str]] = []
    for value in scripts.values():
        for command in value if isinstance(value, list) else [value]:
            if not isinstance(command, str):
                continue
            try:
                tokens = shlex.split(command)
            except ValueError:
                continue
            for start, name in enumerate(tokens):
                if not name.endswith("parallel-lint"):
                    continue
                args: list[str] = []
                for token in tokens[start + 1 :]:
                    if token in _COMMAND_SEPARATORS:
                        break
                    if token.endswith(";"):
                        if token.rstrip(";"):
                            args.append(token.rstrip(";"))
                        break
                    args.append(token)
                calls.append(args)
    return calls


def _lint_php(composer: dict | None) -> str | None:
    """The PHP binary the project's parallel-lint script selects with -p."""
    for args in _lint_script_calls(composer):
        for i, token in enumerate(args[:-1]):
            if token == "-p":
                return args[i + 1]
    return None


def _lint_script_targets(root: Path, composer: dict | None) -> list[str]:
    """The paths the project's own parallel-lint script lints, globs expanded.

    A TYPO3 extension lints ``*.php Classes Configuration Tests``; the
    autoload directories alone leave out ext_emconf.php and the TCA.
    """
    targets: list[str] = []
    for args in _lint_script_calls(composer):
        for rel in _lint_call_targets(root, args):
            if rel not in targets:
                targets.append(rel)
    return targets


def _lint_call_targets(root: Path, args: list[str]) -> list[str]:
    """The existing paths one parallel-lint call lints, globs expanded."""
    targets: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token in _LINT_VALUE_OPTIONS:
            skip = True
            continue
        if token.startswith("-"):
            continue
        # glob.glob follows the shell: a wildcard does not match a leading
        # dot, a hidden directory named in the pattern is matched.
        matches = (
            sorted(glob.glob(token, root_dir=root))
            if any(c in token for c in "*?[")
            else [token.rstrip("/")]
        )
        for rel in matches:
            if (root / rel).exists() and rel not in targets:
                targets.append(rel)
    return targets


def _lint_call_excludes(args: list[str]) -> list[str]:
    excludes: list[str] = []
    for i, token in enumerate(args):
        if token == "--exclude" and i + 1 < len(args):
            path = args[i + 1]
        elif token.startswith("--exclude="):
            path = token.split("=", 1)[1]
        else:
            continue
        path = path.rstrip("/")
        if path and path not in excludes:
            excludes.append(path)
    return excludes


def _overlaps(a: str, b: str) -> bool:
    pa, pb = PurePosixPath(a), PurePosixPath(b)
    return "." in (a, b) or pa.is_relative_to(pb) or pb.is_relative_to(pa)


def _lint_excludes(root: Path, composer: dict | None) -> list[str]:
    """``--exclude`` paths of the project's own parallel-lint script.

    Fixture files that are invalid PHP on purpose are excluded there; the
    loop excludes the same paths. The loop lints the targets of all calls
    at once, so an exclude is kept only when every other call that lints an
    overlapping path excludes it too: one call's exclude never narrows
    another call's targets, and the loop lints wider, never narrower.
    """
    calls = [
        (_lint_call_targets(root, args), _lint_call_excludes(args))
        for args in _lint_script_calls(composer)
    ]
    excludes: list[str] = []
    for own, (_, own_excludes) in enumerate(calls):
        for path in own_excludes:
            if path in excludes:
                continue
            if all(
                path in other_excludes
                or not any(_overlaps(path, t) for t in other_targets)
                for other, (other_targets, other_excludes) in enumerate(calls)
                if other != own
            ):
                excludes.append(path)
    return excludes


def run_lint(ctx: Context) -> ToolResult:
    targets = _lint_targets(ctx)
    if not targets:
        return _skipped(
            "lint", "no source directories found (composer autoload, src/, Classes/)"
        )
    excludes = _lint_excludes(ctx.root, ctx.composer)
    if "." in targets:
        excludes += [d for d in _third_party_dirs(ctx) if d not in excludes]
    # The PHP the project lints with; without -p, parallel-lint uses the PHP
    # it runs under, which can be newer than the project's floor.
    lint_php = _lint_php(ctx.composer)
    if lint_php and "/" in lint_php and not Path(lint_php).is_absolute():
        # Composer runs the script in the project root.
        lint_php = str(ctx.root / lint_php)
    parallel = find_binary(ctx.root, "parallel-lint", ctx.composer)
    if parallel is not None:
        cmd = [str(parallel), "--no-progress"]
        if lint_php:
            cmd += ["-p", lint_php]
        for path in excludes:
            cmd += ["--exclude", path]
        cmd += targets
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
    php = shutil.which(lint_php) if lint_php else shutil.which("php")
    if php is None:
        return _missing("lint", lint_php or "php")
    files: list[Path] = []
    for target in targets:
        p = ctx.root / target
        if p.is_file():
            # A file named on the command line or in the script is linted
            # whatever its suffix (.phtml, ext_emconf.php, a bin script).
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.php")))
    excluded = [ctx.root / e for e in excludes]
    files = [f for f in files if not any(f.is_relative_to(e) for e in excluded)]
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
    try:
        version = subprocess.run(
            [php, "-r", "echo PHP_VERSION;"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        ).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        version = "unknown"
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
    cmd = [str(binary), "analyse", "--no-progress", "--error-format=json"]
    # PHPStan reads a config from the working directory only; one under
    # Build/ has to be named.
    if ctx.phpstan_config:
        cmd.append(f"--configuration={ctx.phpstan_config}")
    cmd += ctx.paths
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


def _infection_sets_min_msi(root: Path) -> bool:
    """Whether the config Infection loads sets its own minMsi.

    Infection loads the first of these that exists (0.35.11,
    SchemaConfigurationLoader::POSSIBLE_DEFAULT_CONFIG_FILE_NAMES).
    """
    for name in (
        "infection.json5",
        "infection.json",
        "infection.json5.dist",
        "infection.json.dist",
    ):
        try:
            text = (root / name).read_text(encoding="utf-8")
        except OSError:
            continue
        # A commented-out "// minMsi: 80" sets nothing.
        return bool(_MIN_MSI_KEY_RE.search(_strip_json5_comments(text)))
    return False


_MIN_MSI_KEY_RE = re.compile(r"""(?:^|[{,])\s*["']?minMsi["']?\s*:""")


def _strip_json5_comments(text: str) -> str:
    """The text without // and /* */ comments; string contents are kept."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            out.append(char)
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        else:
            out.append(char)
        i += 1
    return "".join(out)


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
        *([] if _infection_sets_min_msi(ctx.root) else ["--min-msi=80"]),
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
        phpstan_config=first_existing(root, PHPSTAN_CONFIG_CANDIDATES),
        rector_config=first_existing(root, RECTOR_CONFIG_CANDIDATES),
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
        # The whole project is the tools' configured scope: passing "."
        # would replace the configs' paths and reach vendor/.
        if target != root:
            paths.append(str(target.relative_to(root)))

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
