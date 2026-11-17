# Conductor — cross-agent coordination surface

This directory is the **conductor layer** for `media-ark`: the place where
the rules of engagement between human and agents, and between agents
themselves, are written down in a form any agent can read on cold start.

It exists because the repo is worked on by more than one agent kind
(Codex, Claude, Gemini, opencode, Jules, GPT-scheduled) and more than one
human (the conductor, plus their future selves), and the standing rules
that govern that work need a single addressable surface — the same way
`src/media_ark/__init__.py` is the single source of truth for the
product's *identity strings*.

## Layout

| Path | Purpose |
|---|---|
| `routing.md` | The human-readable narrative for cross-agent routing: format spec, field semantics, per-intent descriptions, cross-references. |
| `routing.tables.toml` | The parseable TOML data: every intent is a `[intent.<verb>]` table with `description`, `agents`, and `constraints`. Tools enumerate intents by parsing this file. |
| `fleet-standing-rules.md` | Shared invariants (additive-only, squash-merge-only, atomic-commit-only, N/A-is-a-vacuum, no-destroy-without-conductor-auth) and the per-agent override slots where an agent's authority differs from the default. Extends — does not duplicate — `MERGE_PATH.md`. |
| `dispatch/<agent>.md` | Per-agent-kind projection of the canonical handoff. Same facts as the source handoff, agent-shaped (scope, authority, blind spots, lane markers). One file per agent kind that has touched the repo. |
| `secrets-map.md` | Per-secret, per-agent-kind access matrix. **All cells are `unset — awaiting conductor` until the conductor explicitly authorizes an agent's access.** This file is a skeleton by design: agent authority is a human decision, not a generated one. |

## How to read this directory (cold-start protocol)

1. Read [`fleet-standing-rules.md`](./fleet-standing-rules.md) first.
   The shared invariants apply to every agent; the per-agent override
   slots are where this session's authority differs.
2. Read your own `dispatch/<your-agent-kind>.md`. The projection names
   exactly which actions you may take, which you may not, and which
   actions are conductor-only.
3. If your intent is named in `routing.tables.toml`, follow the
   routing rule (the narrative in `routing.md` is the human
   companion). If your intent is *not* named, **stop and report** —
   the routing files are the single source of truth for who does
   what, and the absence of a rule is a gap, not an invitation.
4. If a secret is in `secrets-map.md` and the cell for your agent
   kind is `unset`, **do not touch it.** Cells get filled by the
   conductor, not by an agent, not by a bot, not by inference.

## How this directory is *not* read

- It is not a substitute for `MERGE_PATH.md`. The merge policy
  (squash-only, linear history, conversation-resolution-required,
  no-force-push) lives there and is cross-referenced from the
  standing rules, not duplicated.
- It is not a substitute for the canonical handoff at
  `docs/handoff/media-ark-0.2.0-2026-06-10.md`. The handoff
  carries session-specific state; this directory carries fleet-wide
  rules. When the canonical handoff updates, the per-agent
  projections may need re-rendering — the convention is
  `dispatch/<agent>.md` is a *lens* on the canonical handoff, not a
  copy of it.
- It is not a substitute for the brand module
  (`src/media_ark/__init__.py`). That module exports identity
  *strings* (display name, domain, env-var prefix). This directory
  exports identity *behaviors* (scope, authority, lane). Same
  pattern (identity as data, not prose), different surface.

## What this directory does *not* cover yet (named gaps)

- **Per-secret authority (4d):** `secrets-map.md` is a skeleton.
  Cells are `unset` by design. Filling them is a conductor decision
  per agent kind per secret.
- **Failure-mode documentation:** if an agent overruns its lane and
  pushes to `main` against branch protection, the recovery protocol
  is in `MERGE_PATH.md` §"Rollback." A future iteration may add a
  cross-link here; for now, the cross-link is implicit (an agent
  that has read this README is expected to have read the standing
  rules, which reference MERGE_PATH.md).
- **Cross-agent coordination contracts:** when two agents need to
  hand off work mid-task (e.g. Claude drafts a PR body, Codex
  commits it), the contract is implicit in `routing.tables.toml` (and the narrative in `routing.md`) and the
  per-agent dispatch files. A future iteration may promote this to
  an explicit `coordination-protocol.md` if hand-offs start failing.

## Provenance

This directory was authored in the 2026-06-11 conductor-evolve
session (the session that surfaced gap 4 from the 0.2.0 closeout
narrative). It is a forward-looking proposal, not a 0.2.0 closeout
artifact. The 0.2.0 closeout is closed; this directory is the next
lane.

## Style discipline

The files in this directory follow the same discipline as
[`docs/regression-findings.md`](../docs/regression-findings.md):
lean facts, dense context, named blind spots. Every standing rule
in `fleet-standing-rules.md` names what it *cannot* enforce (the
S1-walker F2 Blindspot A pattern). Every dispatch projection names
the failure modes that an agent in that lane can step into. The
discipline is the load-bearing structure, not the prose.
