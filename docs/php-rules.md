# PHP Rules

The coding rules this skill applies to PHP source. Scoped to `**/*.php` through
`.coderabbit.yaml` (`knowledge_base.code_guidelines.filePatterns[].applyTo`), so
a review of a Markdown, YAML or shell change does not evaluate them.

They lived in the root `AGENTS.md` until #116: that file is supplied to reviews
for every path, so "`declare(strict_types=1)` in every file" was read against
`CHANGELOG.md` and reported as a finding. The rules are unchanged; only where
they apply is now stated in a place the tooling reads.

1. **PHP 8.1+ required** — promotion, readonly, enums, match, attributes, union types.
2. **Strict types** — `declare(strict_types=1)` in every PHP file.
3. **DTOs over arrays** — typed objects for structured data, never raw arrays.
4. **Backed enums** — replace string/int constants for fixed value sets.
5. **PHPStan ≥ 9** — level 9 minimum, level 10 for new projects, `treatPhpDocTypesAsCertain: false`.
6. **Static analysis stack** — PHPStan + PHPat + Rector + PHP-CS-Fixer (`@PER-CS`).
7. **PSR / PER-CS compliance** — see `../skills/php-modernization/references/psr-per-compliance.md`.
8. **Type-hint against PSR interfaces**, not implementations.
