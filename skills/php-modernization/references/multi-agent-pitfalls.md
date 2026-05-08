# Multi-Agent Modernization Pitfalls

Empirical hazards when dispatching parallel sub-agents for a PHP
modernization pass. All of these were observed in production runs and
are worth bracing against in the agent's instructions.

## Hazard 1: `composer SCRIPT -- --flag` does NOT forward the flag

Composer scripts have well-known argument-forwarding limitations. The
canonical example:

```jsonc
"scripts": {
    "rector": "rector process src --config=config/quality/rector.php"
}
```

```bash
# Looks like a dry-run. Actually runs rector in APPLY mode.
composer rector -- --dry-run
```

**Why it bites in multi-agent runs**: a "config cleanup" sub-agent
running this thinking it's safe will modify source files. If it
notices and reverts via `git checkout -- <files>`, those files may have
been modified by a sibling agent — its uncommitted work vanishes
silently.

**Workaround**: invoke the binary directly when you need the flag.

```bash
bin/rector process src --config=config/quality/rector.php --dry-run
vendor/bin/php-cs-fixer fix --dry-run --diff
vendor/bin/phpstan analyse --no-progress
```

**Brief every agent**: when scripted commands accept flags, hand the
agent the raw binary invocation, not the composer alias.

## Hazard 2: `git checkout --` outside your declared scope

If sub-agents run in parallel against the same working tree, one
agent's `git checkout -- <path>` on a file outside its declared scope
can wipe out a sibling agent's uncommitted edits.

**The rule (single, unambiguous):**

> An agent may only `git checkout --` / `git restore` files **inside
> its own declared file scope**. For any file outside that scope —
> including auto-generated files (Hazard 6) — use `git stash`,
> `git diff`, or coordinate with the orchestrator instead.

**Safer alternatives** when comparing to a baseline:

- `git stash push -m "tmp"`, do the read-only test, `git stash pop`.
  Stashes are agent-private as long as the name is unique.
- Spawn a separate read-only worktree with `isolation: "worktree"` for
  the discovery work. (Don't write across worktrees.)
- `git diff main -- <path>` to see differences without reverting.

## Hazard 3: Local PHPStan cache lies vs CI

`phpstan.neon` typically configures `tmpDir: /tmp/phpstan-X`. The cache
indexes analysis results keyed to vendor stubs. Two lab conditions in
which this routinely diverges from CI:

- After a rebase that bumped a `phpstan-*-bridge` extension or
  PHPUnit major (CI builds vendor cleanly; local doesn't unless
  `composer install` was re-run).
- After mass test refactors where the local `tmpDir` already analysed
  the OLD code shape.

**Mitigation in the agent's verification step**:

```bash
composer install                            # if composer.lock changed
vendor/bin/phpstan clear-result-cache       # invalidate analysis cache safely
vendor/bin/phpstan analyse --no-progress
```

`vendor/bin/phpstan clear-result-cache` is the supported way to clear
PHPStan's cache — it knows the actual `tmpDir` from the config, and
won't accidentally nuke caches from sibling projects on the same
machine the way `rm -rf /tmp/phpstan-*` could.

Always run this **before** reporting `[OK] No errors`. The skill's
default verify scripts should not declare success on a cached run.

## Hazard 4: Vendor skew after rebase

If a rebase pulled in `composer.lock` updates (e.g. another PR
upgraded a major version) and the agent doesn't run `composer install`,
the local `vendor/` still has the old version. Tests may pass locally
on the old binary while failing in CI on the new.

**Brief**: any agent that rebases or merges into its working tree
should run `composer install --ignore-platform-req=...` afterwards (or
inside Docker if the host lacks the project's PHP extensions).

## Hazard 5: File-scope overlap between concurrent agents

If two agents have overlapping file scopes, the second to finish
overwrites the first's edits. Even with no overlap on lines, edits
made via Read+Edit on different lines of the same file race.

**Allocate scopes by file, not by feature**. If two agents both need to
touch `JiraHttpClientService.php`, sequence them — the second runs
after the first commits.

When a third agent must touch a file the previous two also touched,
brief it with the post-merge state and the specific line ranges, and
have it re-read the file before editing.

## Hazard 6: Auto-generated files repeatedly re-appearing in the diff

Symfony's `symfony-cmd`-driven `cache:clear` post-install hook
regenerates `config/reference.php`. Doctrine migrations and schema
files have similar regenerators. If the agent commits these, every
subsequent `composer install` produces a fresh diff.

**Mitigation** (in order of preference):

1. **Best**: project gitignores the file. Suggest this in the PR.
2. **Without gitignore**: at the END of the agent's work, after all
   sibling agents have committed, run `git restore <generated-file>`
   *only if that file is in YOUR declared scope* (per Hazard 2). The
   orchestrator should give exactly one agent ownership of cleanup.
3. **Mid-run**: don't restore. Commit your real edits, then submit a
   follow-up commit that restores the regenerated file.
4. **Alternative**: `git update-index --assume-unchanged <file>` for
   the duration of the run — files don't appear in `git status` and
   regenerators won't pollute the diff. Reset with `--no-assume-unchanged`
   when done.

## Hazard 7: Pre-commit hooks running tests on the host

Many projects' `captainhook` / husky / pre-commit configs run
`phpunit` directly on host PHP. If the host lacks the project's
required extensions (`pdo_mysql`, `ldap`, etc.) or has stale-cache
issues, the hook fails on every commit with environmental errors that
have nothing to do with the staged changes.

**Workarounds in priority order**:

1. Ask the user to install the missing extension or configure the hook
   to run via `docker compose run --rm app-dev …`.
2. Commit inside the project's Docker container:
   ```bash
   docker compose run --rm app-dev sh -c \
     'git config --global --add safe.directory "*" &&
      git -c user.email=YOU -c user.name=YOU commit --signoff -m "…"'
   ```
3. As a last resort, `--no-verify` — but only with explicit user
   permission, and only after confirming the staged change passes the
   tests in the project's preferred environment (Docker).

## Concise briefing template

Include this in every multi-agent dispatch where modifications happen
in parallel:

```
SHARED REPO HAZARDS:
- Use vendor/bin/rector / vendor/bin/php-cs-fixer / vendor/bin/phpstan
  directly. Composer script aliases sometimes drop --forwarded flags
  depending on the script body's quoting.
- Do NOT run `git checkout --`, `git restore`, or `git reset --hard`
  on files OUTSIDE your declared scope. Use `git stash` / `git diff`
  to compare to a baseline.
- Before reporting clean: `vendor/bin/phpstan clear-result-cache`
  and re-run analyse.
- After any composer.lock change in your scope: run `composer install`.
- If pre-commit hooks block your commit: report the hook output, do
  NOT --no-verify.
```
