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
A valid run that did not finish (non-zero exit, timeout) counts as failed.

Sandbox (``--sandbox``):

- ``docker`` (default) — the agent runs in a container built from
  ``evals/agent.Dockerfile`` with ``--permission-mode bypassPermissions``.
  The container sees its own tree, the plugin under test (read-only), the
  host's claude binary (read-only) and the Claude Code login file
  (read-only); no other host file and no host environment variable. It runs
  without capabilities and on an internal network whose only way out is a
  proxy that lets through api.anthropic.com alone. The agent can read the
  login file and reach that API with it: run evals with an account whose
  token you can rotate. The checker, which executes the agent's PHP code,
  runs in a container without network as well, and the host records the
  patch through a git dir outside the tree, so nothing the agent writes
  runs on the host.
- ``host`` — the agent runs on the host with an allowlist
  (``--allowedTools``) and a filtered environment. The allowlist is not a
  sandbox, and it refuses some ordinary commands, so tool use is not
  comparable to a run without it; ``result.permission_denials`` counts the
  refusals.

Isolation (``--isolation``):

- ``project`` (default) — ``claude --setting-sources project``: the user's
  settings, installed plugins, user-level skills and user CLAUDE.md are not
  loaded; the login stays as it is. Measured with Claude Code 2.1.325: the
  init event lists none of the installed plugins, and a model asked whether
  its context names the user's instructions answered NO here and YES with
  ``user,project``.
- ``bare`` — ``claude --bare``; needs ``ANTHROPIC_API_KEY``.
- ``none`` — everything installed loads; for debugging only. In a profile
  that has the skill installed, every run is invalid by the rule above.

    docker build -t php-modernization-evals -f evals/agent.Dockerfile evals
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
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = REPO / "evals" / "cases"
CHECKER = CASES / "check_case.py"
SKILL = "php-modernization"
# Paths inside the docker sandbox.
BOX_TREE = "/work"
BOX_PLUGIN = "/plugin"
BOX_HOME = "/home/agent"
PROMPT_SUFFIX = (
    "\n\nThe project is in the current directory. When the task is done, stop."
)
TOOL_PATTERNS = {
    "rector": re.compile(r"\brector\b"),
    "phpstan": re.compile(r"\bphpstan\b"),
    # The case projects alias the tools as Composer scripts: composer test,
    # composer lint, composer phpstan, composer rector.
    "phpunit": re.compile(r"\bphpunit\b|\bcomposer\s+(run(-script)?\s+)?test\b"),
    "phpcs": re.compile(r"\bphpc(s|bf)\b"),
    "php-lint": re.compile(
        r"\bphp\s+-l\b|parallel-lint|\bcomposer\s+(run(-script)?\s+)?lint\b"
    ),
    "skill-scripts": re.compile(
        r"introspect\.py|verify_php_project\.py|modernize_loop\.py"
    ),
}


def sh(cmd: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=False, **kw
    )


# Repository parts that are not the plugin. evals/ holds the solutions and
# acceptance tests; an agent that can read the plugin copy must not find them.
NOT_PLUGIN = ("evals", "tests", "fixtures")


def plugin_root(arm: str, out: Path) -> tuple[Path, str]:
    """Materialise the plugin for a ``with:*`` arm; return (path, commit).

    Only the plugin: evals/, tests/ and fixtures/ are left out.
    """
    ref = arm.split(":", 1)[1]
    if ref == "WORKTREE":
        target = out / "_plugins" / "WORKTREE"
        files = sh(["git", "ls-files", "-z"], REPO).stdout.split("\0")
        for rel in filter(None, files):
            if rel.split("/", 1)[0] in NOT_PLUGIN:
                continue
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
        for part in NOT_PLUGIN:
            shutil.rmtree(target / part, ignore_errors=True)
    return target, commit


def host_git(tree: Path) -> list[str]:
    """git for the host's view of a tree: its git dir lies outside the tree.

    The agent can write anything inside the tree, including its own .git;
    a git command on the host that read that .git/config could run code the
    agent put there (core.fsmonitor, hooks, a diff driver). This git dir is
    out of the agent's reach, and hooks and fsmonitor stay off regardless.
    """
    return [
        "git",
        f"--git-dir={tree.parent / (tree.name + '.git')}",
        f"--work-tree={tree}",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
    ]


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
    # Two repositories with the same baseline: the agent's own (tree/.git),
    # for git status and git diff, and the host's, which records the patch.
    for git in (["git"], host_git(tree)):
        for cmd in (
            [*git, "init", "-q", "-b", "main"],
            [*git, "add", "-A"],
            [
                *git,
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
            denied = event.get("permission_denials") or []
            result = {
                # Calls the allowlist refused. A high count means the run
                # measured the allowlist as much as the agent.
                "permission_denials": len(denied),
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


# What the agent may run, the same in every arm. With --print, a tool that
# is not listed is denied, not asked for. The list covers the project's own
# tools and reading the tree; it does not name the skill's advice, so it
# does not steer the without arm. It is not a sandbox: php and the vendor
# binaries execute code from the tree. Run evals on a machine or account
# without secrets you could not afford to expose, or in a container.
BASE_TOOLS: tuple[str, ...] = (
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "Bash(vendor/bin/:*)",
    "Bash(php:*)",
    "Bash(composer:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(cd:*)",
    "Bash(set:*)",
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(head:*)",
    "Bash(tail:*)",
    "Bash(wc:*)",
    "Bash(find:*)",
    "Bash(grep:*)",
    "Bash(which:*)",
    "Bash(mkdir:*)",
    "Bash(echo:*)",
    "Bash(printf:*)",
)
# Environment the agent inherits: enough for claude to start and log in,
# no tokens (VAULT_TOKEN, GITHUB_TOKEN, …) from the host.
ENV_KEEP: tuple[str, ...] = (
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "USER",
    "SHELL",
    "TMPDIR",
)


def allowed_tools(plugin: Path | None) -> list[str]:
    tools = list(BASE_TOOLS)
    if plugin is not None:
        # The skill's own scripts, from the plugin under test only.
        scripts = plugin / "skills" / SKILL / "scripts"
        tools += [f"Bash(uv run {scripts}/:*)", f"Bash(python3 {scripts}/:*)", "Skill"]
    return tools


def agent_env(isolation: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ENV_KEEP}
    if isolation == "bare" and "ANTHROPIC_API_KEY" in os.environ:
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    return env


PROXY_PORT = 8888


def box_base(name: str) -> list[str]:
    """``docker run`` options every eval container gets."""
    uid, gid = os.getuid(), os.getgid()
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--user",
        f"{uid}:{gid}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "1024",
        "--tmpfs",
        f"{BOX_HOME}:uid={uid},gid={gid}",
        "-e",
        f"HOME={BOX_HOME}",
    ]


def start_egress(args: argparse.Namespace, run_id: str) -> None:
    """An internal network for the agents and a proxy as its only way out.

    The network has no route to the outside, and the host has no address
    on it: an --internal network alone gives the host a gateway address
    there, and a host service listening on all interfaces answered on it
    (measured, Docker 29.9.3); inhibit_ipv4 removes that address. The proxy
    (tinyproxy, configured in agent.Dockerfile) sits on it and on the
    default bridge and lets CONNECT through to api.anthropic.com:443 only.
    """
    args.network = f"pm-eval-{run_id}"
    args.proxy = f"pm-eval-proxy-{run_id}"
    for cmd in (
        [
            "docker",
            "network",
            "create",
            "--internal",
            "-o",
            "com.docker.network.bridge.inhibit_ipv4=true",
            args.network,
        ],
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            args.proxy,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            args.image,
            "tinyproxy",
            "-d",
            "-c",
            "/etc/tinyproxy/eval.conf",
        ],
        ["docker", "network", "connect", args.network, args.proxy],
    ):
        done = sh(cmd, REPO)
        if done.returncode != 0:
            stop_egress(args)
            raise SystemExit(f"error: {' '.join(cmd)}: {done.stderr.strip()}")


def stop_egress(args: argparse.Namespace) -> None:
    if getattr(args, "proxy", None):
        sh(["docker", "rm", "-f", args.proxy], REPO)
    if getattr(args, "network", None):
        sh(["docker", "network", "rm", args.network], REPO)


def docker_prefix(
    args: argparse.Namespace, tree: Path, plugin: Path | None, name: str
) -> list[str]:
    """``docker run`` for an agent up to the image; the claude command follows."""
    claude_bin = Path(shutil.which(args.claude) or args.claude).resolve()
    proxy = f"http://{args.proxy}:{PROXY_PORT}"
    cmd = [
        *box_base(name),
        "--network",
        args.network,
        # Container names still resolve; nothing is forwarded upstream.
        "--dns",
        "0.0.0.0",
        "-e",
        f"HTTPS_PROXY={proxy}",
        "-e",
        f"HTTP_PROXY={proxy}",
        "-e",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
        "-v",
        f"{claude_bin}:/usr/local/bin/claude:ro",
        "-v",
        f"{tree}:{BOX_TREE}",
        "-w",
        BOX_TREE,
    ]
    if args.isolation == "bare":
        cmd += ["-e", "ANTHROPIC_API_KEY"]
    else:
        cmd += ["-v", f"{args.credentials}:{BOX_HOME}/.claude/.credentials.json:ro"]
    if plugin is not None:
        cmd += ["-v", f"{plugin}:{BOX_PLUGIN}:ro"]
    return [*cmd, args.image, "claude"]


def score(case_id: str, tree: Path, args: argparse.Namespace) -> str:
    """Run the checker on a result tree; return its stdout.

    The checker runs the agent's PHP code (PHPUnit executes src/). In docker
    mode that happens in a container with no network and read-only mounts,
    never on the host.
    """
    if args.sandbox != "docker":
        cmd = [sys.executable, str(CHECKER), case_id, "--tree", str(tree)]
        return sh(cmd, REPO, timeout=900).stdout
    name = f"pm-eval-check-{uuid.uuid4().hex[:12]}"
    cmd = [
        *box_base(name),
        "--network",
        "none",
        "-v",
        f"{CASES}:/cases:ro",
        "-v",
        f"{tree}:/tree:ro",
        args.image,
        "python3",
        "/cases/check_case.py",
        case_id,
        "--tree",
        "/tree",
    ]
    try:
        return sh(cmd, REPO, timeout=900).stdout
    except subprocess.TimeoutExpired:
        sh(["docker", "rm", "-f", name], REPO)
        return ""


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
    label = f"{arm.replace(':', '_').replace('/', '_')}-{n}"
    run_dir = out / case["id"] / label
    # The agent's tree lives outside this repository: inside it, the agent
    # could read evals/cases/*/solutions and the acceptance tests.
    tree = args.work_root / case["id"] / label
    run_dir.mkdir(parents=True)
    prepare_tree(case["id"], tree)
    box = args.sandbox == "docker"
    name = f"pm-eval-{uuid.uuid4().hex[:12]}"
    # The plugin path the agent sees, and the one its init event must show.
    seen_plugin = Path(BOX_PLUGIN) if box and plugin is not None else plugin
    cmd = [
        *(docker_prefix(args, tree, plugin, name) if box else [args.claude]),
        "-p",
        case["task"] + PROMPT_SUFFIX,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        args.model,
        "--max-turns",
        str(args.max_turns),
    ]
    if box:
        cmd += ["--permission-mode", "bypassPermissions"]
    else:
        cmd += ["--allowedTools", ",".join(allowed_tools(plugin))]
    if args.isolation == "bare":
        cmd.append("--bare")
    elif args.isolation == "project":
        cmd += ["--setting-sources", "project"]
    if seen_plugin is not None:
        cmd += ["--plugin-dir", str(seen_plugin)]
    transcript = run_dir / "transcript.jsonl"
    start = time.monotonic()
    with transcript.open("w", encoding="utf-8") as fh:
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                cwd=str(tree),
                # docker run passes no host variable into the container;
                # the docker client itself needs the host environment.
                env=os.environ.copy() if box else agent_env(args.isolation),
                stdout=fh,
                stderr=subprocess.PIPE,
                text=True,
                timeout=args.timeout,
            )
            exit_code: int | None = proc.returncode
            stderr = proc.stderr[-2000:]
        except subprocess.TimeoutExpired:
            exit_code, stderr = None, "timeout"
            if box:
                # Killing the docker client leaves the container running.
                sh(["docker", "rm", "-f", name], REPO)
    duration = time.monotonic() - start

    git = host_git(tree)
    sh([*git, "add", "-A"], tree.parent)
    (run_dir / "patch.diff").write_text(
        sh(
            [*git, "diff", "--cached", "--no-ext-diff", "--no-textconv"], tree.parent
        ).stdout,
        encoding="utf-8",
    )
    checked = score(case["id"], tree, args)
    try:
        checks = json.loads(checked)
    except json.JSONDecodeError:
        checks = {"passed": False, "error": "the checker printed no JSON"}
    (run_dir / "checks.json").write_text(
        json.dumps(checks, indent=2) + "\n", encoding="utf-8"
    )

    # valid = the skill state matched the arm. A run that did not finish
    # (non-zero exit, timeout, turn limit) stays valid and counts as not
    # passed: dropping it would raise the pass rate of the arm that fails
    # to finish more often.
    valid, reason = validity(arm, init_event(transcript), seen_plugin)
    completed = exit_code == 0
    record = {
        "case": case["id"],
        "kind": case["kind"],
        "arm": arm,
        "run": n,
        "skill_commit": commit,
        "model": args.model,
        "isolation": args.isolation,
        "sandbox": args.sandbox,
        "valid": valid,
        "invalid_reason": reason,
        "completed": completed,
        "exit_code": exit_code,
        "stderr_tail": stderr.strip()[-300:],
        "passed": completed and bool(checks.get("passed")),
        "checks": {c["check"]: c["status"] for c in checks.get("checks", [])},
        "duration_seconds": round(duration, 1),
        **tool_usage(transcript),
    }
    (run_dir / "run.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    # The tree's vendor/ is a 100+ MB copy; patch.diff and checks.json keep
    # the result, so the tree goes.
    shutil.rmtree(tree, ignore_errors=True)
    shutil.rmtree(tree.parent / (tree.name + ".git"), ignore_errors=True)
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
        "--work-root",
        type=Path,
        default=None,
        help="where agent trees and plugin copies live; must be outside this repository "
        "(default: ~/.cache/php-modernization-evals/<timestamp>)",
    )
    parser.add_argument(
        "--sandbox",
        choices=("docker", "host"),
        default="docker",
        help="docker: container with bypassPermissions (default); host: allowlist on the host",
    )
    parser.add_argument(
        "--image",
        default="php-modernization-evals",
        help="image for --sandbox docker (build: evals/agent.Dockerfile)",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path.home() / ".claude" / ".credentials.json",
        help="Claude Code login file, mounted read-only into the container",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="runs in parallel (default: 1)"
    )
    parser.add_argument(
        "--isolation",
        choices=("project", "bare", "none"),
        default="project",
        help="project: --setting-sources project (default); bare: --bare, needs ANTHROPIC_API_KEY; none: debugging",
    )
    args = parser.parse_args(argv)

    if args.isolation == "bare" and not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("--isolation bare needs ANTHROPIC_API_KEY")
    if not (CASES / "vendor" / "bin" / "phpunit").is_file():
        parser.error(
            "evals/cases/vendor is missing: composer install --working-dir=evals/cases"
        )
    if shutil.which(args.claude) is None:
        parser.error(f"{args.claude!r} not found")
    if args.sandbox == "docker":
        image = sh(["docker", "image", "inspect", args.image], REPO)
        if image.returncode != 0:
            parser.error(
                f"image {args.image!r} not found: docker build -t {args.image} "
                "-f evals/agent.Dockerfile evals"
            )
        if args.isolation != "bare" and not args.credentials.is_file():
            parser.error(f"--credentials {args.credentials} is not a file")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")

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
    args.work_root = (
        args.work_root or Path.home() / ".cache" / "php-modernization-evals" / out.name
    ).resolve()
    if args.work_root.is_relative_to(REPO):
        parser.error(
            "--work-root must be outside the repository: agents could read the solutions"
        )
    args.work_root.mkdir(parents=True, exist_ok=True)
    plugins = {
        arm: plugin_root(arm, args.work_root) for arm in arms if arm != "without"
    }

    def one(job: tuple[dict, str, int]) -> dict:
        case, arm, n = job
        plugin, commit = plugins.get(arm, (None, ""))
        record = run_one(
            case=case, arm=arm, n=n, out=out, args=args, plugin=plugin, commit=commit
        )
        flag = "PASS" if record["passed"] else "fail"
        if not record["valid"]:
            flag = f"INVALID ({record['invalid_reason'][:80]})"
        print(f"{case['id']:26} {arm:22} #{n} {flag}", flush=True)
        return record

    cases = [
        json.loads((CASES / c / "case.json").read_text(encoding="utf-8"))
        for c in selected
    ]
    jobs = [(c, arm, n) for c in cases for arm in arms for n in range(1, args.runs + 1)]
    if args.sandbox == "docker":
        start_egress(args, out.name.lower())
    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            records = list(pool.map(one, jobs))
    finally:
        if args.sandbox == "docker":
            stop_egress(args)

    summary = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": args.model,
        "isolation": args.isolation,
        "sandbox": args.sandbox,
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
