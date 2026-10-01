<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Security assurance case — php-modernization-skill

This document states what a user can expect from this repository in terms of security, and argues why that expectation holds. Every claim names the file that implements it. Reporting a vulnerability: see the [security policy](https://github.com/netresearch/.github/blob/main/SECURITY.md). Components and data flow: [ARCHITECTURE.md](ARCHITECTURE.md). Paths below starting with `scripts/` inside `skills/php-modernization/` are the shipped tools; `scripts/` at the repository root holds contributor tools.

## What the repository ships

| Part | Files | Runs where |
| --- | --- | --- |
| Skill instructions for an AI agent | `skills/php-modernization/SKILL.md`, `skills/php-modernization/references/*.md`, `skills/php-modernization/checkpoints.yaml` | Read by the agent or by assessment tooling; not executed. The agent may run the PHP tools they describe in the user's project. |
| Introspector | `skills/php-modernization/scripts/introspect.py` | On the user's machine, against a PHP project root. |
| Verifier | `skills/php-modernization/scripts/verify_php_project.py`, `skills/php-modernization/scripts/_common.py` | On the user's machine or in the user's CI, against a PHP project root. |
| Fix-loop orchestrator | `skills/php-modernization/scripts/modernize_loop.py` | On the user's machine or in the user's CI, against a PHP project root. |
| Bash wrapper | `skills/php-modernization/scripts/verify-php-project.sh` | Starts the introspector or the verifier with `uv`, or with `python3` when `uv` is missing. |
| Templates | `skills/php-modernization/templates/composer-scripts.json`, `skills/php-modernization/templates/github-actions/php-modernization.yml` | Copied by the user into their own project and run there. |
| Output contracts | `schemas/*.schema.json` | Data; not executed. |
| Contributor tools | `scripts/test_fixtures.py`, `tests/test_scripts.py`, `scripts/verify-harness.sh`, `evals/run-ab-test.sh`, `Build/Scripts/check-plugin-version.sh`, `Build/hooks/pre-push` | In this repository's CI and on contributors' machines. |

The Python tools use only the Python standard library (`dependencies = []` in their PEP 723 blocks). The repository ships no server component, no container image and no compiled code. The tools store no credentials, open no network connection themselves and handle no user accounts.

## Security requirements

1. The introspector and the verifier do not change the analysed project's source files. The introspector writes nothing. The verifier itself writes only below `.build/php-modernization/` in the project (tool output and its cache), or to the file named with `--cache-file`; the tools it starts may write their own caches.
2. The orchestrator changes source files only in `--mode apply`, and only when `--confirm` is also given. Without `--confirm` it exits 2 before running any tool. In the default `--mode dry-run` it passes `--dry-run` to PHP-CS-Fixer and Rector.
3. No command-line argument and no content of the analysed project is run through a shell or evaluated as code by the tools.
4. A tool that hangs does not hang the agent: every subprocess has a timeout, and a timeout is reported as a result (status `timeout`, or `unknown` for the PHP version probe) instead of an exception.
5. A malformed or unexpected project file does not crash the verifier or the introspector; it yields `unknown` or a failed check.
6. The report states the verifier's version correctly, so a user can tell which rules produced it.
7. Nothing committed to this repository contains a secret, and a release can be verified against the build that produced it.

## Actors and trust boundaries

- **Skill user and agent.** The agent reads `SKILL.md` and the references and runs commands in the user's project with the user's privileges. `SKILL.md` declares `allowed-tools` (`Bash(php:*)`, `Bash(composer:*)`, `Bash(uv:*)`, `Bash(vendor/bin/*)`, `Bash(.Build/bin/*)`, `Read`, `Write`, `Glob`, `Grep`). That list pre-approves these tools so the agent does not ask for each call; it does not take away any tool the agent already has.
- **The analysed project.** The tools read files from the project root given with `--root`: `composer.json`, `composer.lock`, PHPStan, Rector and PHP-CS-Fixer configuration, and archetype markers such as `ext_emconf.php` or `bin/console` (`_common.py`, `verify_php_project.py`, `introspect.py`). The verifier follows `includes:` in PHPStan configuration files to find the effective level, also to files outside the project root; it only reads them. The project is trusted as code: the verifier runs `vendor/bin/phpstan` or `.Build/bin/phpstan` from the project and `composer audit` (from `PATH`, else the project's `vendor/bin/composer`), and the orchestrator runs the project's `php-cs-fixer`, `rector`, `phpstan` and `infection` from `vendor/bin` or `.Build/bin`.
- **The verifier cache.** Unless `--no-cache` is given, the verifier reads `.build/php-modernization/last-run.json` from the project and prints the stored report when its signature (modification times of `composer.json`, `composer.lock` and the known configuration files) and its flags match (`cache_load`, `cache_signature` in `verify_php_project.py`). The cache is part of the analysed project and trusted like it.
- **Command-line arguments.** `--root`, `--check`, `--cache-file`, `--tools` and `--git-diff-base` are chosen by the caller. `--tools` is checked against the four known tool names; `--git-diff-base` is passed to Infection as one argument.
- **PHP runtime.** Both the introspector and the verifier run the `php` found on `PATH` once to read its version (`php --version`, `php -r "echo PHP_VERSION;"`).
- **Contributors.** Changes reach `main` through pull requests, checked by the workflows in `.github/workflows/`.
- **CI.** Workflows run on GitHub-hosted runners with `permissions: {}` at the top level and grant each job only the scopes its called reusable workflow needs (`.github/workflows/*.yml`). The three `pull_request_target` callers (`auto-merge-deps.yml`, `labeler.yml`, `pr-quality.yml`) call reusable workflows that have no checkout step: they merge dependency update pull requests, label pull requests, and approve pull requests from repository collaborators. `auto-merge-deps.yml` passes two named secrets instead of `secrets: inherit`.

## Threats and countermeasures

| Threat | Countermeasure | Evidence |
| --- | --- | --- |
| An agent rewrites a codebase without review | The orchestrator defaults to `--mode dry-run`; `--mode apply` without `--confirm` exits 2 before any tool runs; in dry-run PHP-CS-Fixer and Rector receive `--dry-run`. The skill tells the agent never to run Rector without a dry run first. | `modernize_loop.py` (`main`, `run_php_cs_fixer`, `run_rector`); `tests/test_scripts.py` (`test_apply_without_confirm_exits_two_and_runs_nothing`, `test_dry_run_passes_dry_run_flags_and_fails_on_findings`); `SKILL.md` hard guardrails |
| An argument or a project value is executed as a command (CWE-78) | Every subprocess is started with an argument list and without a shell; tool paths come from fixed locations (`vendor/bin`, `.Build/bin`, `PATH`); `--tools` accepts only the four known names | `verify_php_project.py`, `modernize_loop.py`, `introspect.py`; `tests/test_scripts.py` (`test_unknown_tool_is_a_usage_error`) |
| A tool hangs and blocks the agent or the CI job | Timeouts: 10 s for the PHP version probe, 300 s for each of the verifier's tool runs, 600 s for each orchestrator tool; a timed-out tool is reported with status `timeout` | `introspect.py`, `verify_php_project.py`, `modernize_loop.py` |
| A malformed `composer.json` or cache file crashes the tools | JSON is parsed with `json.loads` inside `try`, and the result's type is checked before use; an unreadable file counts as missing | `read_composer_json` in `_common.py`; `cache_load` in `verify_php_project.py` |
| A cyclic or very deep chain of PHPStan `includes:` exhausts the verifier (CWE-674) | Resolution keeps a set of visited paths and stops after 5 levels | `resolve_phpstan_level` in `verify_php_project.py` |
| A stale cached report hides a configuration change | The cache key covers the modification times of `composer.json`, `composer.lock` and every top-level configuration file the checks look for, the flags and the skill version; `--no-cache` bypasses it. Files pulled in through PHPStan `includes:` are not part of the key, so a change to one needs `--no-cache` | `CACHE_INVALIDATION_FILES`, `cache_signature` and `main` in `verify_php_project.py`; `tests/test_scripts.py` (`test_cache_is_written_and_reused`, `test_cache_from_an_older_release_is_not_reused`) |
| Special characters in a message break the JUnit output | The JUnit document is built with `xml.etree.ElementTree`, which escapes text and attributes | `to_junit` in `verify_php_project.py` |
| A report names the wrong verifier version | `tests/test_scripts.py` compares the reported `skill_version` with `.claude-plugin/plugin.json` | `SKILL_VERSION` in `_common.py`; `tests/test_scripts.py` (`test_reports_carry_the_released_skill_version`) |
| A change breaks the verifier's output contract | The fixture suite diffs the verifier's JSON for ten synthetic projects against committed snapshots; both suites run on every pull request and push to `main` | `scripts/test_fixtures.py`, `fixtures/`, `tests/test_scripts.py`, `.github/workflows/tests.yml` |
| A secret is committed | Betterleaks scans every push to `main` and every pull request to `main` | `.github/workflows/security.yml` |
| A vulnerable or malicious dependency is added | Dependency review fails on vulnerabilities of severity high or above in a pull request; Composer Audit checks the Composer dependency (`netresearch/composer-agent-skill-plugin`); Renovate proposes updates, including the pinned pre-commit hooks | `.github/workflows/security.yml`, `composer.json`, `renovate.json`, `.pre-commit-config.yaml` |
| Insecure code or workflow patterns | Opengrep SAST fails on findings at the threshold the organisation's [static analysis rule](https://github.com/netresearch/.github/blob/main/SECURITY.md#static-analysis-sast) sets; zizmor analyses the workflows; ShellCheck and Ruff run in Skill Validation | `.github/workflows/security.yml`, `.github/workflows/lint.yml` |
| A released archive is tampered with | The release workflow publishes a Cosign-signed checksum file and build-provenance attestations | `.github/workflows/release.yml` (calls the skill-repo-skill release reusable) |

Which of these checks must pass before a pull request can merge is set in the branch rules of `main`, not in this repository.

## Secure design principles applied

- **Least privilege:** the introspector only reads; the verifier writes only below `.build/php-modernization/`; source changes need an explicit `--mode apply --confirm`; workflows start from `permissions: {}` and grant per job.
- **Fail-safe defaults:** dry-run is the default mode; the verifier treats a report without a status as `fail` (`main` in `verify_php_project.py`); the orchestrator reports a tool that timed out or could not start as a failure of a required tool.
- **Economy of mechanism:** the Python tools use only the standard library and a fixed list of tool locations.
- **Open design:** every check the verifier runs is plain Python in this repository, and every instruction the skill gives an agent is plain text in `SKILL.md` and `references/`.

## What a user cannot expect

- Running the verifier without `--no-tools`, or the orchestrator at all, executes the analysed project's own binaries (`vendor/bin`, `.Build/bin`) and `composer`. Point them only at projects whose dependencies you would install and run anyway. For a first look at an unknown project use `introspect.py` or the verifier with `--no-tools`; they run only the `php` on `PATH` to read its version.
- `--mode dry-run` does not change source files, but it is not free of side effects: it writes reports below `.build/php-modernization/`, and the tools it starts may write their own caches.
- A cache file in the project is trusted. When its signature matches, the verifier prints the stored report without evaluating again. Use `--no-cache` where the project directory is not under your control.
- The checks inspect configuration and source text. A `pass` means the modernization checkpoints are met; it is not a security audit. A failing `composer audit` is listed in `tool_runs[]` and does not change `summary.status` or the exit code.
- The five hard guardrails in `SKILL.md` are instructions to the agent. Apart from the `--confirm` requirement of the orchestrator, no code enforces them.
- Reports contain the absolute path of the analysed project (`project_root`). Uploading a report, for example as SARIF, publishes that path.
- The templates are starting points. `templates/github-actions/php-modernization.yml` uses major-version action tags, grants `pull-requests: write` and `security-events: write`, and installs the project's Composer dependencies; pin the actions and review the permissions before using it.
- `evals/run-ab-test.sh` is a contributor tool. It runs the `claude` CLI with `--dangerously-skip-permissions` on the prompts in `evals/evals.json`; run it only in an environment where that is acceptable.
- Security fixes follow the supported-versions rules of the organisation's security policy; older releases may not receive them.
