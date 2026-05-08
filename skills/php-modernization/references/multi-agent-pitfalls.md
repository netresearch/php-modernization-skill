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

## Hazard 2: Never `git checkout -- <file>` mid-multi-agent run

If sub-agents are running in parallel against the same working tree,
one agent's `git checkout -- <path>` can wipe out another agent's
uncommitted edits.

**Safer alternatives** when an agent needs to test a "main" baseline:

- `git stash push -m "tmp"`, do the read-only test, `git stash pop`.
  Stashes are agent-private as long as the name is unique.
- Spawn a separate read-only worktree with `isolation: "worktree"` for
  the discovery work. (Don't write across worktrees.)
- Just `git diff main -- <path>` to see what's different without
  reverting.

**Brief every agent that touches state**: "Do not run `git checkout
--` or `git restore` on files outside your declared scope. If you need
to compare against main, use `git stash` or `git diff` instead."

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
rm -rf /tmp/phpstan-* var/cache/phpstan
composer install                # if composer.lock changed since last run
vendor/bin/phpstan analyse --no-progress
```

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

**Mitigation**:

- Agents should `git checkout -- <generated-file>` (yes, this hazard
  collides with #2 — agents have to be precise) BEFORE staging final
  commits.
- The verify script should detect Symfony auto-generated files in the
  staged diff and warn.
- Better: project should gitignore them. Suggest this in the PR.

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
- Use bin/rector / vendor/bin/php-cs-fixer / vendor/bin/phpstan
  directly. Do NOT use `composer rector -- --dry-run` (composer
  swallows the flag).
- Do NOT run `git checkout --`, `git restore`, or `git reset --hard`
  on any file. Use `git stash` for temporary baselines.
- Before reporting clean: `rm -rf /tmp/phpstan-* var/cache/phpstan`
  and re-run analyse.
- After any composer.lock change in your scope: run `composer install`.
- If pre-commit hooks block your commit: report the hook output, do
  NOT --no-verify.
```
