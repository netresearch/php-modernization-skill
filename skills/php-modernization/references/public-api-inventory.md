# Inventorying a Public API Against Its Consumers

Use when a library's public surface (`@api` tags, a frozen API snapshot, a 1.0
freeze) is to be sorted into keep / `@internal` / deprecate / remove. The sort
is a decision. The inventory that feeds it is a measurement, and three of its
steps fail silently: each produces a plausible number that is wrong.

## 1. Find the consumers from their manifests

Code search finds candidates; the manifest decides whether a repository is a
consumer. For packages on GitHub:

```bash
gh search code 'vendor/package filename:composer.json' --owner <org> \
  --json repository --jq '.[].repository.nameWithOwner' | sort -u

# per candidate: is it actually required, and as runtime or dev dependency?
gh api repos/<org>/<repo>/contents/composer.json --jq .content | base64 -d \
  | jq '{require: .require["vendor/package"], dev: .["require-dev"]["vendor/package"]}'
```

Packagist's `dependents` count (`https://packagist.org/packages/<vendor>/<package>.json`)
is a cross-check, not a list. Private projects appear in neither source, and a
self-hosted GitLab CE has no instance-wide code search. Name that gap in the
result: the keep-set measured this way is a lower bound.

## 2. Extract the symbols each consumer uses

```bash
grep -rhoE 'Vendor\\Package\\[A-Za-z0-9_\\]+' <consumer> \
  --include='*.php' --include='*.yaml' --include='*.yml' \
  --exclude-dir=vendor --exclude-dir=.Build | sort -u
```

Run it once over the consumer's production code (`Classes/`, `src/`) and once
over the whole tree. A type that only a consumer's test mocks is a weaker keep
signal than one its production code imports, so keep the two apart.

## 3. The traps

- **FQCN counting misses same-namespace callers.** A class used by a sibling in
  its own namespace needs no `use` statement, so a grep for the fully-qualified
  name reports it as uncalled. Count the short name inside the class's own
  directory as well. In one inventory of 169 types, FQCN-only counting reported
  17 types without any caller; with same-namespace names the true number was 5.
- **Read `@internal` from the class docblock, not the file.** A file-wide grep
  labels a class `@internal` when only one of its methods carries the tag.
  Match the docblock directly above `class` / `interface` / `trait` / `enum`.
- **Zero callers is a question, not a verdict.** Leaf entry points — a service
  consumers are meant to call, a test double shipped for them — have no in-repo
  caller by construction. A declared extension point without an adopter is a
  deliberate publication. Keep both out of the `@internal` and remove lists.

## 4. Diff in the other direction too

Compare the consumers' symbols against the published surface both ways. The
most valuable rows are usually outside it: a consumer importing an `@internal`
or untagged class from production code is a contract that exists in practice
and nowhere on paper. Each one needs either promotion to the public surface or
a supported replacement plus a migration note — before anything is frozen.

## Output

One row per surface type: FQCN, consumers (production / tests only), in-repo
references (FQCN plus same-namespace), extension-point flag. Report the buckets
as counts, list the outside-surface imports separately, and state every gap
(unsearched hosts, leaf entry points) with its number.
