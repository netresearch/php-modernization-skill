#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Agent evals on the executable cases: does the skill make the PHP better?

For every case in evals/cases/, every arm and every run, this script:

1. copies the case project into a fresh git repository with its own copy of
   the case tools (``vendor/``, autoload regenerated for the case);
2. runs ``claude -p`` there with the case task, tools enabled;
3. records the transcript, the agent's patch, the tools it ran and the
   skill it loaded;
4. scores the result with ``evals/cases/check_case.py --tree`` — the
   checker's own acceptance tests and configs, which the agent never sees.

Arms:

- ``without``          no php-modernization skill
- ``with:<git-ref>``   the skill as committed at that ref (``with:origin/main``)
- ``with:WORKTREE``    the skill as it is in this working tree

A run is **valid** only when its transcript's init event shows the intended
skill state: no php-modernization skill in ``without``; exactly the plugin
under test in ``with:*``. Invalid runs are kept and reported, never scored.

Isolation: with ``ANTHROPIC_API_KEY`` set, every run uses ``claude --bare``,
so no installed plugin, hook or CLAUDE.md reaches it. Without the key the
script refuses, unless ``--allow-unisolated`` is given; then the user's
installed plugins load too, and a ``without`` run in a profile that has the
skill installed is invalid by the rule above.

    uv run evals/run_agent_cases.py --arms without,with:origin/main,with:WORKTREE --runs 3
    uv run evals/run_agent_cases.py --cases switch-loose-http --runs 1 --model haiku

Results go to ``evals/results/agent-cases/<UTC timestamp>/`` (git-ignored):
``summary.json`` plus one directory per run with ``transcript.jsonl``,
``patch.diff``, ``checks.json`` and ``run.json``.

Exit code: 0 when every run completed (valid or not), 2 on usage errors.
The script reports; it does not judge the skill.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = REPO / "evals" / "cases"
CHECKER = CASES / "check_case.py"
SKILL = "php-modernization"
PROMPT_SUFFIX = (
    "\n\nThe project is in the current directory. When the task is done, stop."
)
TOOL_PATTERNS = {
    "rector": re.compile(r"\brector\b"),
    "phpstan": re.compile(r"\bphpstan\b"),
    "phpunit": re.compile(r"\bphpunit\b"),
    "phpcs": re.compile(r"\bphpc(s|bf)\b"),
    "php-lint": re.compile(r"\bphp\s+-l\b|parallel-lint"),
    "skill-scripts": re.compile(
        r"introspect\.py|verify_php_project\.py|modernize_loop\.py"
    ),
}


def sh(cmd: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=False, **kw
    )


def plugin_root(arm: str, out: Path) -> tuple[Path, str]:
    """Materialise the plugin for a ``with:*`` arm; return (path, commit)."""
    ref = arm.split(":", 1)[1]
    if ref == "WORKTREE":
        target = out / "_plugins" / "WORKTREE"
        files = sh(["git", "ls-files", "-z"], REPO).stdout.split("\0")
        for rel in filter(None, files):
            src = REPO / rel
            if src.is_file():
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        head = sh(["git", "rev-parse", "HEAD"], REPO).stdout.strip()
        dirty = bool(sh(["git", "status", "--porcelain"], REPO).stdout.strip())
        return target, head + ("+dirty" if dirty else "")
    sha = sh(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], REPO)
    if sha.returncode != 0:
        raise SystemExit(f"error: arm {arm!r}: {ref!r} is not a commit")
    commit = sha.stdout.strip()
    target = out / "_plugins" / commit[:12]
    if not target.is_dir():
        target.mkdir(parents=True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", "--format=tar", commit],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["tar", "-x", "-C", str(target)], input=archive.stdout, check=True
        )
    return target, commit


def prepare_tree(case_id: str, tree: Path) -> None:
    shutil.copytree(CASES / case_id / "project", tree)
    # The agent gets its own vendor/: it may run composer dump-autoload or
    # install a package without touching the shared copy the checker uses.
    shutil.copytree(CASES / "vendor", tree / "vendor", symlinks=True)
    done = sh(["composer", "dump-autoload", "--no-interaction", "--quiet"], tree)
    if done.returncode != 0:
        raise SystemExit(f"error: composer dump-autoload in {tree}: {done.stderr}")
    (tree / ".gitignore").write_text(
        "vendor/\n.build/\n.phpunit.cache/\n", encoding="utf-8"
    )
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "user.name=eval",
            "-c",
            "user.email=eval@invalid",
            "commit",
            "-qm",
            "baseline",
        ],
    ):
        done = sh(cmd, tree)
        if done.returncode != 0:
            raise SystemExit(f"error: {' '.join(cmd)} in {tree}: {done.stderr}")


def init_event(transcript: Path) -> dict | None:
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            return event
    return None


def validity(arm: str, init: dict | None, plugin: Path | None) -> tuple[bool, str]:
    if init is None:
        return False, "no init event in the transcript"
    skills = [str(s) for s in init.get("skills") or []]
    ours = [s for s in skills if SKILL in s]
    plugins = [p for p in init.get("plugins") or [] if p.get("name") == SKILL]
    if arm == "without":
        if ours or plugins:
            return False, f"the skill is loaded in the without arm: {ours or plugins}"
        return True, ""
    expected = str(plugin.resolve()) if plugin else ""
    paths = [str(Path(p.get("path", "")).resolve()) for p in plugins]
    if paths != [expected]:
        return False, f"expected exactly the plugin {expected}, got {paths}"
    stray = [s for s in ours if s != f"{SKILL}:{SKILL}"]
    if stray:
        return False, f"another copy of the skill is loaded as well: {stray}"
    return True, ""


def tool_usage(transcript: Path) -> dict:
    names: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    skills: list[str] = []
    reads_of_skill: list[str] = []
    result: dict = {}
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = {
                "num_turns": event.get("num_turns"),
                "total_cost_usd": event.get("total_cost_usd"),
                "is_error": event.get("is_error"),
                "subtype": event.get("subtype"),
            }
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            names[name] += 1
            data = block.get("input") or {}
            if name == "Bash":
                command = str(data.get("command", ""))
                for tool, pattern in TOOL_PATTERNS.items():
                    if pattern.search(command):
                        commands[tool] += 1
            elif name == "Skill":
                skills.append(str(data.get("skill", "")))
            elif name == "Read" and SKILL in str(data.get("file_path", "")):
                reads_of_skill.append(str(data.get("file_path")))
    return {
        "tool_calls": dict(names),
        "project_tools_run": dict(commands),
        "skills_invoked": skills,
        "skill_files_read": reads_of_skill,
        "result": result,
    }


def run_one(
    *,
    case: dict,
    arm: str,
    n: int,
    out: Path,
    args: argparse.Namespace,
    plugin: Path | None,
    commit: str,
) -> dict:
    run_dir = out / case["id"] / f"{arm.replace(':', '_').replace('/', '_')}-{n}"
    tree = run_dir / "tree"
    run_dir.mkdir(parents=True)
    prepare_tree(case["id"], tree)
    cmd = [
        args.claude,
        "-p",
        case["task"] + PROMPT_SUFFIX,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        args.model,
        "--max-turns",
        str(args.max_turns),
        "--permission-mode",
        "bypassPermissions",
    ]
    if args.isolation == "bare":
        cmd.append("--bare")
    if plugin is not None:
        cmd += ["--plugin-dir", str(plugin)]
    transcript = run_dir / "transcript.jsonl"
    start = time.monotonic()
    with transcript.open("w", encoding="utf-8") as fh:
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                cwd=str(tree),
                stdout=fh,
                stderr=subprocess.PIPE,
                text=True,
                timeout=args.timeout,
            )
            exit_code: int | None = proc.returncode
            stderr = proc.stderr[-2000:]
        except subprocess.TimeoutExpired:
            exit_code, stderr = None, "timeout"
    duration = time.monotonic() - start

    sh(["git", "add", "-A"], tree)
    (run_dir / "patch.diff").write_text(
        sh(["git", "diff", "--cached"], tree).stdout, encoding="utf-8"
    )
    checked = sh(
        [sys.executable, str(CHECKER), case["id"], "--tree", str(tree)],
        REPO,
        timeout=900,
    )
    try:
        checks = json.loads(checked.stdout)
    except json.JSONDecodeError:
        checks = {"passed": False, "error": checked.stderr[-2000:]}
    (run_dir / "checks.json").write_text(
        json.dumps(checks, indent=2) + "\n", encoding="utf-8"
    )

    valid, reason = validity(arm, init_event(transcript), plugin)
    if exit_code != 0:
        valid, reason = (
            False,
            reason or f"claude exited {exit_code}: {stderr.strip()[:300]}",
        )
    record = {
        "case": case["id"],
        "kind": case["kind"],
        "arm": arm,
        "run": n,
        "skill_commit": commit,
        "model": args.model,
        "isolation": args.isolation,
        "valid": valid,
        "invalid_reason": reason,
        "passed": bool(checks.get("passed")),
        "checks": {c["check"]: c["status"] for c in checks.get("checks", [])},
        "duration_seconds": round(duration, 1),
        **tool_usage(transcript),
    }
    (run_dir / "run.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    # The tree's vendor/ is a 100+ MB copy; the patch and the checks keep the result.
    shutil.rmtree(tree / "vendor", ignore_errors=True)
    return record


def summarise(records: list[dict]) -> dict:
    table: dict[str, dict[str, dict[str, int]]] = {}
    for r in records:
        cell = table.setdefault(r["case"], {}).setdefault(
            r["arm"], {"runs": 0, "valid": 0, "passed": 0}
        )
        cell["runs"] += 1
        if r["valid"]:
            cell["valid"] += 1
            cell["passed"] += int(r["passed"])
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_agent_cases", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--cases", default="", help="comma-separated case ids (default: all)"
    )
    parser.add_argument(
        "--arms", default="without,with:WORKTREE", help="comma-separated arms"
    )
    parser.add_argument("--runs", type=int, default=1, help="runs per case and arm")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument(
        "--timeout", type=int, default=1800, help="seconds per agent run"
    )
    parser.add_argument("--claude", default="claude", help="claude CLI binary")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--allow-unisolated",
        action="store_true",
        help="run without --bare when ANTHROPIC_API_KEY is not set (installed plugins load too)",
    )
    args = parser.parse_args(argv)

    if os.environ.get("ANTHROPIC_API_KEY"):
        args.isolation = "bare"
    elif args.allow_unisolated:
        args.isolation = "none"
    else:
        parser.error(
            "set ANTHROPIC_API_KEY for isolated runs, or pass --allow-unisolated"
        )
    if not (CASES / "vendor" / "bin" / "phpunit").is_file():
        parser.error(
            "evals/cases/vendor is missing: composer install --working-dir=evals/cases"
        )
    if shutil.which(args.claude) is None:
        parser.error(f"{args.claude!r} not found")

    available = sorted(p.parent.name for p in CASES.glob("*/case.json"))
    selected = [c for c in args.cases.split(",") if c] or available
    unknown = set(selected) - set(available)
    if unknown:
        parser.error(f"unknown case(s): {', '.join(sorted(unknown))}")
    arms = [a for a in args.arms.split(",") if a]
    for arm in arms:
        if arm != "without" and not arm.startswith("with:"):
            parser.error(f"unknown arm {arm!r}")

    out = args.out or REPO / "evals" / "results" / "agent-cases" / datetime.now(
        UTC
    ).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=False)
    plugins = {arm: plugin_root(arm, out) for arm in arms if arm != "without"}

    records: list[dict] = []
    for case_id in selected:
        case = json.loads((CASES / case_id / "case.json").read_text(encoding="utf-8"))
        for arm in arms:
            plugin, commit = plugins.get(arm, (None, ""))
            for n in range(1, args.runs + 1):
                record = run_one(
                    case=case,
                    arm=arm,
                    n=n,
                    out=out,
                    args=args,
                    plugin=plugin,
                    commit=commit,
                )
                records.append(record)
                flag = "PASS" if record["passed"] else "fail"
                if not record["valid"]:
                    flag = f"INVALID ({record['invalid_reason'][:80]})"
                print(f"{case_id:26} {arm:22} #{n} {flag}", flush=True)

    summary = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": args.model,
        "isolation": args.isolation,
        "arms": {arm: plugins.get(arm, (None, ""))[1] for arm in arms},
        "table": summarise(records),
        "runs": records,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
