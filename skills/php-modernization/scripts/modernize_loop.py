#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fix-loop orchestrator for PHP modernization.

Drives the four mechanical refactor/test tools (php-cs-fixer, rector, phpstan,
infection-diff) in either dry-run mode (default, safe) or apply mode (mutates
files; requires --confirm). Output is a structured JSON transcript that the
LLM agent reasons about to choose next actions.

Exit code: 0 if every required tool passes; 1 if any required tool reports
findings. Missing tools are warnings, not errors. Infection is required only
when --git-diff-base is set (PR mode); otherwise optional.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "1.0.0"
ARTIFACT_DIR = Path(".build/php-modernization")
SUBPROCESS_TIMEOUT_SECONDS = 600

ALL_TOOLS: tuple[str, ...] = ("php-cs-fixer", "rector", "phpstan", "infection-diff")


@dataclass
class ToolResult:
    tool: str
    status: str  # pass | fail | missing | timeout | error | skipped
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
    results: list[ToolResult]
    next_actions: list[NextAction] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def _find_binary(root: Path, name: str) -> Path | None:
    for rel in (f"vendor/bin/{name}", f".Build/bin/{name}"):
        p = root / rel
        if p.is_file():
            return p
    return None


def _ensure_artifact_dir(root: Path) -> Path:
    target = root / ARTIFACT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


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
            artifact.write_text(completed.stdout or "", encoding="utf-8")
        except OSError:
            pass
    return completed.returncode, duration, None


# ---------------------------------------------------------------------------
# Tool runners — dry-run vs apply
# ---------------------------------------------------------------------------


def _summary_for_dry_run_finding(tool: str, exit_code: int | None) -> str:
    if exit_code is None:
        return f"{tool}: did not complete"
    if exit_code == 0:
        return f"{tool}: clean"
    return f"{tool}: changes proposed (exit {exit_code})"


def run_php_cs_fixer(root: Path, *, mode: str) -> ToolResult:
    binary = _find_binary(root, "php-cs-fixer")
    if binary is None:
        return ToolResult(
            tool="php-cs-fixer",
            status="missing",
            exit_code=None,
            command="(php-cs-fixer not installed)",
            duration_seconds=0.0,
            summary="binary not found in vendor/bin or .Build/bin",
        )
    artifact = _ensure_artifact_dir(root) / "php-cs-fixer.json"
    if mode == "apply":
        cmd = [str(binary), "fix"]
        artifact_to_write: Path | None = None
        artifact_rel: str | None = None
    else:
        cmd = [str(binary), "fix", "--dry-run", "--diff", "--format=json"]
        artifact_to_write = artifact
        artifact_rel = str(artifact.relative_to(root))
    rc, duration, err = _run(cmd, root, artifact_to_write)
    if err == "timeout":
        return ToolResult(
            tool="php-cs-fixer",
            status="timeout",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary="exceeded timeout",
        )
    if err and err.startswith("error"):
        return ToolResult(
            tool="php-cs-fixer",
            status="error",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary=err,
        )
    # In dry-run: php-cs-fixer exits 8 when changes are needed; treat as fail.
    if mode == "apply":
        status = "pass" if rc == 0 else "fail"
        summary = (
            "all files fixed" if rc == 0 else f"php-cs-fixer apply failed (exit {rc})"
        )
    else:
        status = "pass" if rc == 0 else "fail"
        summary = _summary_for_dry_run_finding("php-cs-fixer", rc)
    return ToolResult(
        tool="php-cs-fixer",
        status=status,
        exit_code=rc,
        command=" ".join(cmd),
        duration_seconds=duration,
        summary=summary,
        artifact=artifact_rel,
    )


def run_rector(root: Path, *, mode: str) -> ToolResult:
    binary = _find_binary(root, "rector")
    if binary is None:
        return ToolResult(
            tool="rector",
            status="missing",
            exit_code=None,
            command="(rector not installed)",
            duration_seconds=0.0,
            summary="binary not found in vendor/bin or .Build/bin",
        )
    artifact = _ensure_artifact_dir(root) / "rector.json"
    if mode == "apply":
        cmd = [str(binary), "process"]
        artifact_to_write: Path | None = None
        artifact_rel: str | None = None
    else:
        cmd = [str(binary), "process", "--dry-run", "--output-format=json"]
        artifact_to_write = artifact
        artifact_rel = str(artifact.relative_to(root))
    rc, duration, err = _run(cmd, root, artifact_to_write)
    if err == "timeout":
        return ToolResult(
            tool="rector",
            status="timeout",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary="exceeded timeout",
        )
    if err and err.startswith("error"):
        return ToolResult(
            tool="rector",
            status="error",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary=err,
        )
    status = "pass" if rc == 0 else "fail"
    summary = (
        "rector applied transforms"
        if mode == "apply" and rc == 0
        else _summary_for_dry_run_finding("rector", rc)
    )
    return ToolResult(
        tool="rector",
        status=status,
        exit_code=rc,
        command=" ".join(cmd),
        duration_seconds=duration,
        summary=summary,
        artifact=artifact_rel,
    )


def run_phpstan(root: Path) -> ToolResult:
    binary = _find_binary(root, "phpstan")
    if binary is None:
        return ToolResult(
            tool="phpstan",
            status="missing",
            exit_code=None,
            command="(phpstan not installed)",
            duration_seconds=0.0,
            summary="binary not found in vendor/bin or .Build/bin",
        )
    artifact = _ensure_artifact_dir(root) / "phpstan.json"
    cmd = [str(binary), "analyse", "--no-progress", "--error-format=json"]
    rc, duration, err = _run(cmd, root, artifact)
    if err == "timeout":
        return ToolResult(
            tool="phpstan",
            status="timeout",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary="exceeded timeout",
        )
    if err and err.startswith("error"):
        return ToolResult(
            tool="phpstan",
            status="error",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary=err,
        )
    status = "pass" if rc == 0 else "fail"
    summary = "phpstan: clean" if rc == 0 else f"phpstan: errors detected (exit {rc})"
    return ToolResult(
        tool="phpstan",
        status=status,
        exit_code=rc,
        command=" ".join(cmd),
        duration_seconds=duration,
        summary=summary,
        artifact=str(artifact.relative_to(root)),
    )


def run_infection_diff(root: Path, *, git_diff_base: str) -> ToolResult:
    binary = _find_binary(root, "infection")
    if binary is None:
        return ToolResult(
            tool="infection-diff",
            status="missing",
            exit_code=None,
            command="(infection not installed)",
            duration_seconds=0.0,
            summary="binary not found in vendor/bin or .Build/bin",
        )
    artifact = _ensure_artifact_dir(root) / "infection.txt"
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
    rc, duration, err = _run(cmd, root, artifact)
    if err == "timeout":
        return ToolResult(
            tool="infection-diff",
            status="timeout",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary="exceeded timeout",
        )
    if err and err.startswith("error"):
        return ToolResult(
            tool="infection-diff",
            status="error",
            exit_code=None,
            command=" ".join(cmd),
            duration_seconds=duration,
            summary=err,
        )
    status = "pass" if rc == 0 else "fail"
    summary = (
        "infection diff: MSI threshold met"
        if rc == 0
        else f"infection diff: below MSI (exit {rc})"
    )
    return ToolResult(
        tool="infection-diff",
        status=status,
        exit_code=rc,
        command=" ".join(cmd),
        duration_seconds=duration,
        summary=summary,
        artifact=str(artifact.relative_to(root)),
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
    required = {"php-cs-fixer", "rector", "phpstan"} & set(tools)
    if pr_mode and "infection-diff" in tools:
        required.add("infection-diff")
    return required


def build_next_actions(results: Iterable[ToolResult]) -> list[NextAction]:
    out: list[NextAction] = []
    for r in results:
        if r.status == "fail":
            out.append(
                NextAction(
                    action="review_diff",
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


def execute(
    root: Path,
    *,
    mode: str,
    tools: list[str],
    git_diff_base: str | None,
) -> Transcript:
    results: list[ToolResult] = []
    if "php-cs-fixer" in tools:
        results.append(run_php_cs_fixer(root, mode=mode))
    if "rector" in tools:
        results.append(run_rector(root, mode=mode))
    if "phpstan" in tools:
        results.append(run_phpstan(root))
    if "infection-diff" in tools:
        if git_diff_base is None:
            results.append(
                ToolResult(
                    tool="infection-diff",
                    status="skipped",
                    exit_code=None,
                    command="(no --git-diff-base supplied)",
                    duration_seconds=0.0,
                    summary="infection-diff requires --git-diff-base",
                )
            )
        else:
            results.append(run_infection_diff(root, git_diff_base=git_diff_base))
    return Transcript(
        schema_version=SCHEMA_VERSION,
        mode=mode,
        tools_invoked=tools,
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
        help=f"Comma-separated subset of tools to run (default: {','.join(ALL_TOOLS)})",
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

    transcript = execute(
        root,
        mode=args.mode,
        tools=args.tools if isinstance(args.tools, list) else list(args.tools),
        git_diff_base=args.git_diff_base,
    )

    sys.stdout.write(json.dumps(asdict(transcript), indent=2) + "\n")

    pr_mode = args.git_diff_base is not None
    required = required_tools(transcript.tools_invoked, pr_mode=pr_mode)
    failing_required = [
        r
        for r in transcript.results
        if r.tool in required and r.status not in {"pass", "missing", "skipped"}
    ]
    return 1 if failing_required else 0


if __name__ == "__main__":
    sys.exit(main())
