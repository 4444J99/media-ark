# Secrets map — per-secret, per-agent-kind access matrix

> **STATUS: SKELETON. Every cell is `unset — awaiting conductor`
> by design.** This file is *not* a generated artifact. Agent
> authority is a human decision. The conductor must fill each
> cell explicitly before any agent is authorized to touch a
> secret in a way the standing rules do not already permit.

## Why this file exists

The `secrets-map.md` skeleton is the *fourth* sub-deliverable of
the conductor-evolve work (gap 4d). The other three (4a per-agent
dispatch projections, 4b routing, 4c fleet standing rules) are
authored in this PR. This file is intentionally a skeleton because
the data it carries — which agent kind may read or write which
secret — is a conductor decision, not a generated one.

The default for any unlisted agent is **no access**. An agent
that has not been explicitly granted access to a secret may not
touch that secret, even if the secret's name appears in the
agent's prompt or in the agent's tool surface.

## Secret inventory

The following secrets are observable in this repo's surface or
referenced in the closeout narrative. Each row is a secret; each
column is an agent kind. Cells are `unset — awaiting conductor`
unless the conductor has explicitly filled them.

| Secret | What it is | Where it appears | codex | claude | gemini | opencode | jules | gpt-scheduled | conductor (human) |
|---|---|---|---|---|---|---|---|---|---|
| `MEDIA_ARK_*` env vars | Runtime env-var prefix for the platform (per `src/media_ark/__init__.py` `BRAND_ENV_PREFIX`). | Brand module, `src/platform/config.py`, `src/platform/api_server.py` (`MEDIA_ARK_VERBOSE`), `tools/media-ark/verify_release.py`. | unset | unset | n/a (read-only agent) | unset | unset | unset | unset (default = full; conductor fills explicitly) |
| GitHub PAT (for `gh`) | The token that powers `gh pr`, `gh issue`, `gh workflow`, `gh api`. Scoped per the user's GitHub account. | Implicit in every `gh` invocation. Not stored in the repo; the agent's runtime environment supplies it. | unset | unset | n/a | unset | unset | unset | unset |
| Cloudflare account ID / API token | The account that owns `media-ark.org` (registered 2026-06-10). Used for DNS, Pages, Workers, R2 if any. | Domain registration is in Cloudflare; DNS only (no Workers/Pages/R2 currently used by this repo per the closeout narrative). | unset | unset | n/a | unset | unset | unset | unset |
| `LIMEN_API_TOKEN` / `LIMEN_CLIENT_TOKEN` | Referenced in the 0.2.0 closeout resume prompt as the precedent for per-secret authority. **Not actually used by this repo** — the resume prompt may be conflating with a different repo (`limen`). The `media-ark` codebase does not import or reference these tokens. | n/a — not in this repo. | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| npm publish token | The token that publishes `media-ark` to npm. Not yet provisioned; the `BRAND_NPM` constant exists in the brand module, but no `npm publish` has been observed in the closeout narrative. | Brand module (`BRAND_NPM`); no `package.json` publish config. | unset | unset | n/a | unset | unset | unset | unset |
| `GCP_SA_KEY` (per the limen-architecture session memory) | The Google Cloud service account key for Cloud Run deployment. **Not used by this repo** — the limen repo uses it, the media-ark repo does not. | n/a — not in this repo. | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

**Cells marked `n/a` are unreachable by that agent kind by
construction.** `gemini`, `jules`, and `gpt-scheduled` are
read-only or comment-only agents; they do not touch secrets
regardless of the conductor's decision.

## Cell value semantics

A filled cell may take one of three values:

- **`read`** — the agent may read the secret (e.g. read an
  env var's value, read a token's value, read a config from
  Cloudflare). The agent may not write, rotate, or expose the
  secret in a logged surface.
- **`write`** — the agent may write or rotate the secret. The
  default for `write` is that the agent must also `read`; the
  two are not mutually exclusive. `write` includes `read`.
- **`none`** — the agent is explicitly denied access. This is
  the explicit form of the default `unset`; use it when the
  conductor has considered the cell and decided to forbid
  access.

Cells that are `unset` are *implicit* `none`. The conductor
should fill the `none` cells explicitly when the absence of
authorization is non-obvious (e.g. when the secret is named in
a session prompt and the agent might infer access from the
prompt's framing).

## What this file does *not* cover

- **Secret rotation cadence.** The conductor's responsibility.
  This file is the *who* (which agent), not the *when*
  (rotation schedule).
- **Secret provenance.** Where the secret was provisioned, who
  provisioned it, when. The conductor's responsibility.
- **Cross-repo secret sharing.** If a secret is shared between
  `media-ark` and another repo (e.g. a Cloudflare account that
  hosts multiple domains), the secret's authority matrix may
  need to be coordinated across repos. This file is
  `media-ark`-local.
- **Recovery from a leaked secret.** If an agent discovers
  that a secret is leaked (in a commit, in a log, in a public
  surface), the recovery protocol is to *stop and report* —
  not to rotate the secret. Rotation is a conductor decision.

## Cross-references

- [`fleet-standing-rules.md`](./fleet-standing-rules.md) §"Per-agent override slots" — the per-agent authority that the secrets-map cells operationalize
- [`routing.tables.toml`](./routing.tables.toml) (parseable) and [`routing.md`](./routing.md) (narrative) — the intent → agent map (cells here are independent of routing; an agent may be authorized for an intent without being authorized for the secret that intent touches)
- [`dispatch/<agent>.md`](./dispatch/) — the per-agent-kind projections (each one references this file by name)
- [`../../docs/handoff/media-ark-0.2.0-2026-06-10.md`](../../docs/handoff/media-ark-0.2.0-2026-06-10.md) §"Critical Context" — the closeout narrative's reference to repo-level secrets (which is, as of this writing, minimal — `media-ark` is a local-first pipeline that does not require service-account-class secrets to run)
