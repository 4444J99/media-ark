# Cross-agent routing — intent verbs to authorized agent kinds

> **STATUS: This file is the human-readable narrative. The
> parseable TOML tables live in [`routing.tables.toml`](./routing.tables.toml).
> Tools that need to enumerate intents read the `.tables.toml`
> file; humans read this narrative.**

This directory is the **single source of truth for "who does what"**
in the `media-ark` conductor fleet. An agent reads this file (or
its parseable companion) to learn which intent verbs they may
execute, which they may not, and which are conductor-only.

## Why two files (routing.md + routing.tables.toml)?

A previous iteration of this surface (PR #17) kept the narrative
and the data in one file, calling it `routing.toml`. The file was
*markdown-with-embedded-TOML* — readable to humans, unparseable
to TOML parsers. That was a false claim: the file's preamble
narrative was not valid TOML syntax (e.g. the line `This file is
the **single source of truth**...` is a TOML key with no value).

The PR #18 refactor splits the surface:

- `routing.md` (this file) — the narrative. The format spec, the
  field semantics, the per-intent human-readable descriptions,
  the cross-references.
- `routing.tables.toml` — the parseable data. Every intent is a
  TOML table with `description`, `agents`, and `constraints`
  fields. Tools that need to *enumerate* intents read this file
  and parse it with `tomllib`.

The split is the same pattern as `src/media_ark/__init__.py`
(data: `BRAND_*` constants) vs. `docs/regression-findings.md`
(narrative: the S1/S2/S3 + F1–F9 story). Identity-as-data lives
in the parseable file; reasoning-about-identity lives in the
narrative file.

## Format (per-intent)

Every intent is a TOML table with three fields:

```toml
[intent.<verb>]
description = "<one-line purpose, in plain prose>"
agents      = ["<agent-kind>", "<agent-kind>", ...]
constraints = [
  "<human-readable rule the agent must satisfy>",
  "<...>",
]
```

- **`agents`** lists every agent kind that may execute this
  intent. The conductor is *implicit* — the conductor may
  execute any intent. An agent kind *not* listed may **not**
  execute the intent, even if their `dispatch/<agent>.md`
  claims otherwise. The TOML file is the source of truth;
  the dispatch file is the lens-shaped render of it.
- **`constraints`** is a list of free-form rules an agent
  must satisfy before executing. These are *not* automated
  gates; they are human-readable conditions. (See
  [`fleet-standing-rules.md`](./fleet-standing-rules.md) for
  the rationale — *name what the rule cannot enforce*.)

## Field semantics

| Field | Type | Required? | Default |
|---|---|---|---|
| `description` | string | yes | n/a |
| `agents` | array of strings | yes | `[]` (conductor-only) |
| `constraints` | array of strings | yes | `[]` |

A `description` should be one line, plain prose, and reference
the relevant cross-link (e.g. "Conductor-only. See MERGE_PATH.md
§Rollback."). A `constraints` entry should be one specific rule,
not a paragraph. Multiple rules in one entry are a smell.

## Intents

The full intent inventory is in
[`routing.tables.toml`](./routing.tables.toml). As of PR #18, the
inventory has 14 named intents (PR #18 fills the 4 originally-named gaps):

**Read-only or comment-only:**

- `verify` — run `npm run release:verify` and report. No state change.
- `triage` — issue comments and labels. No code changes.

**Code-authoring agents (codex, claude, opencode):**

- `commit` — atomic commit on a feature branch. No push.
- `push` — push a feature branch. Never force, never `main`.
- `pr-draft` — open a PR against `main`. Squash-merge path.
- `handoff-write` — author or amend `docs/handoff/<file>.md`.
- `fleet-handoff-author` — author or amend `conductor/<file>.{md,toml}`.

**Worktree management:**

- `worktree-new` — create a worktree (`opencode` is the only agent
  with the cross-host Desktop peer convention).
- `worktree-prune` — remove a worktree. Conductor-only.

**Conductor-only (originally 4 named gaps in PR #17, now 5 with the
secrets authority):**

- `pr-merge` — squash-merge. Conductor-only.
- `branch-protect-edit` — modify `main` branch protection. Conductor-only.
- `release-publish` — version bump, CHANGELOG date, tag. Conductor-only.
- `npm-publish` — publish `media-ark` to npm. Conductor-only.
- `worktree-peer-Desktop` — *retired*; the legacy `~/Desktop/`
  convention is no longer canonical.

## What this file does *not* cover (still named, still gaps)

- **`runner-register`** — registering a self-hosted runner for
  this repo. The 0.2.0 closeout's `MERGE_PATH.md` §"Runner-group
  diagnostic probes" exhaustively documents why this is not
  possible from an agent session. Closing this gap is the
  *conductor's* hands-on action, not an agent's.
- **`npm-token-provision`** — provisioning the npm publish token
  and adding it to the [`secrets-map.md`](./secrets-map.md)
  matrix. Not possible from an agent session; conductor-only.
- **`branch-protect-re-enable`** — re-enabling required status
  checks on `main` once Actions billing recovers per issue #5.
  This is the *execution* of `branch-protect-edit`'s recipe; the
  agent drafts the recipe (in `docs/repo-audit.md` Gap #1), the
  conductor runs `gh api .../protection --input ...`.
- **`secrets-map-cell-fill`** — filling the cells in
  `secrets-map.md`. The skeleton is intentional. Per Rule #1
  (N/A is a vacuum), the empty cells are named gaps, not
  papered-over authorization. The conductor fills them.

## Cross-references

- [`routing.tables.toml`](./routing.tables.toml) — the parseable TOML data
- [`fleet-standing-rules.md`](./fleet-standing-rules.md) — the shared invariants and per-agent override slots
- [`dispatch/<agent>.md`](./dispatch/) — the per-agent-kind projections that operationalize these rules
- [`secrets-map.md`](./secrets-map.md) — the per-secret authority matrix (skeleton; conductor fills cells)
- [`../../MERGE_PATH.md`](../../MERGE_PATH.md) — the canonical merge policy this surface extends
