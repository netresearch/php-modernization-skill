<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Executable eval cases

Eight small PHP projects. Each one poses a modernization task whose right answer depends on a judgement the tools do not make. An agent works on a copy of `project/`; `check_case.py` scores the result with acceptance tests the agent never sees.

| Case | Task | Right answer | The known-bad solution fails at |
| --- | --- | --- | --- |
| `enum-order-status` | Turn scattered status strings into an enum | Enum inside the domain; the API keeps its strings | PHPUnit: the enum object leaks into `toArray()` |
| `open-ticket-status` | Modernize a status list that installations extend | Keep the set open; no enum | PHPUnit: configured statuses are rejected |
| `unknown-stored-shipment` | Turn statuses into an enum; legacy rows exist | `tryFrom()`, legacy rows still load as "Unknown" | PHPUnit: `from()` throws on a legacy row |
| `switch-loose-http` | Replace a `switch` with `match` | Keep the loose comparison (`"200"` from headers) | PHPUnit: Rector's strict `match` sends `"200"` to `default` |
| `fallthrough-permissions` | Convert switches where behaviour stays | Keep the fall-through semantics | PHPUnit: one arm per case loses inherited permissions |
| `match-unhandled-payment` | Add an enum case | Add the case and its `match` arm | PHPStan: `match.unhandled` |
| `readonly-booking` | Make a class an immutable value object | Copy the mutable `\DateTime` into `\DateTimeImmutable` | PHPUnit: Rector's `readonly class` stays mutable |
| `php81-floor-money` | Make a class immutable; package supports PHP 8.1 | `readonly` properties, not a `readonly class` | PHPStan with `phpVersion: 80100` |

The known-bad solutions of `switch-loose-http` and `readonly-booking` are byte-identical to what Rector 2.8.4 produces from the case project with `withPhpSets(php82: true)`.

## Layout

```
<case>/
├── case.json            task, PHP floor, kind (convert | keep), expectations
├── project/             what the agent works on: src/, composer.json,
│                        phpstan.neon, rector.php, phpcs.xml.dist, phpunit.xml.dist
├── acceptance/          PHPUnit tests, copied in at check time
└── solutions/{good,good-alt,bad}/src/   files laid over project/
```

## Checks

`check_case.py` copies a result tree to a temporary directory, replaces `tests/Acceptance` and the tool configs with its own, and runs `php -l`, PHPStan (level 5, `phpVersion` = the case's PHP floor) and PHPUnit. An agent cannot pass by editing tests or configs.

```bash
composer install --working-dir=evals/cases          # PHPUnit, PHPStan, Rector, PHPCS
uv run evals/cases/check_case.py --self-test        # prove the checks
uv run evals/cases/check_case.py readonly-booking --solution bad
uv run evals/cases/check_case.py readonly-booking --tree /path/to/result
```

`--self-test` holds when, for every case, the start state does what `start_expect` says (a `convert` case fails unchanged, a `keep` case passes), every good solution passes everything (`good`, and `good-alt` where the task leaves room for a second correct answer), and the bad solution fails at its named check after the earlier checks passed — so it is a wrong answer, not a syntax or build error. `tests/test_eval_cases.py` runs it in CI.

## Agent runs

`evals/run_agent_cases.py` runs `claude -p` on each case per arm (`without`, `with:<git-ref>`, `with:WORKTREE`) and scores each result with `check_case.py`. A run is valid only when its transcript's init event shows the intended skill state; a valid run that did not finish (non-zero exit, timeout, `error_max_turns`) counts as failed. Runs are isolated with `--setting-sources project` by default, so the user's installed plugins, user-level skills and user CLAUDE.md stay out; `--isolation bare` uses `claude --bare` and needs `ANTHROPIC_API_KEY`. Per run it keeps the transcript, the patch, the checks, the project tools the agent ran and the skills it invoked or read.

`evals/run-ab-test.sh` compares output size and duration of text answers. Both of its arms pass `--disable-slash-commands`, and with that flag the session's init event lists 0 skills in either arm (measured with Claude Code 2.1.325), so neither arm has the skill to use. It cannot show whether the skill improves code.
