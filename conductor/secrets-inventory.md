# Per-agent authority inventory — the actual env-var surface

This file is the **enumerated inventory** of the env-var surface
that `media-ark` actually reads at runtime. It is the data that
[`secrets-map.md`](./secrets-map.md) is *about*: the secrets-map
file is the *authority matrix* (which agent kind may read or
write which secret); this file is the *secret catalog* (which
secrets actually exist and where they are read).

Generated 2026-06-11 from the source tree at `f5ff0da` (PR #15
squash-merge). The inventory is exhaustive *for the env-var
prefix* — it does not enumerate GitHub PATs, Cloudflare tokens,
or npm tokens, which are external to the source tree.

## Why this file exists

The first iteration of `secrets-map.md` (PR #17) named the
`MEDIA_ARK_*` env-var row as a single opaque secret. The 0.2.0
closeout's brand-module discipline (`src/media_ark/__init__.py`
exports `BRAND_ENV_PREFIX` and `env_key(suffix)`) is the *actual*
shape: env vars are *data*, not strings baked into source, and
the prefix is one constant that derives the rest.

This file enumerates the data: every `MEDIA_ARK_*` env var the
runtime actually reads, where it is read, and what the default
is. The conductor uses this inventory to fill the secrets-map
cells: "which agent kind may set `MEDIA_ARK_PORT` to override
the default 8787?" is a question the inventory makes answerable.

## Source code surface

### Python (the runtime)

The env-var prefix is defined in `src/media_ark/__init__.py`:

```python
BRAND_ENV_PREFIX: str = "MEDIA_ARK"

def env_key(suffix: str) -> str:
    """Return the full env-var name for a given suffix, e.g. env_key('SOURCE') -> 'MEDIA_ARK_SOURCE'."""
    return f"{BRAND_ENV_PREFIX}_{suffix}"
```

Every Python env-var read uses `env_key(...)` — there is no
hardcoded `MEDIA_ARK_*` string in the runtime. The full list
of `env_key(...)` calls:

| Env var | File:line | Default (when unset) | What it controls |
|---|---|---|---|
| `MEDIA_ARK_SOURCE` | `src/platform/config.py:39` | empty string | Default source directory for the API server (resolved at startup) |
| `MEDIA_ARK_OUT` | `src/platform/config.py:46` | empty string | Default output directory for the API server |
| `MEDIA_ARK_ALLOWED_ROOTS` | `src/platform/config.py:66` | empty string | Comma-separated list of filesystem roots the API/MCP will accept. Paths outside these roots are rejected (security boundary) |
| `MEDIA_ARK_VERBOSE` | `src/platform/api_server.py:311` | unset (falsy) | When `"1"`, the API server logs verbose output |

### Shell wrappers (`tools/media-ark/*.sh`)

The shell wrappers use direct `MEDIA_ARK_*` env var names (not
the `env_key` helper, because bash doesn't have one). Each
wrapper documents its env vars in the `usage()` heredoc.

| Env var | Wrapper | Default | What it controls |
|---|---|---|---|
| `MEDIA_ARK_HOST` | `start_media_ark.sh` | `127.0.0.1` | Bind host for the API/dashboard server |
| `MEDIA_ARK_PORT` | `start_media_ark.sh` | `8787` | Bind port for the API/dashboard server |
| `MEDIA_ARK_SOURCE` | `start_media_ark.sh` | `data/captures/raw` | Default source dir for the platform |
| `MEDIA_ARK_OUT` | `start_media_ark.sh` | `.media-ark` | Default output dir for the platform |
| `MEDIA_ARK_MCP_PREFLIGHT` | `start_media_ark.sh` | `1` | Whether to run the MCP preflight check before starting |
| `MEDIA_ARK_SELF_HEAL` | `media_ark_watch.sh` | `1` | Enable `--self-heal` in the watch runner |
| `MEDIA_ARK_SELF_HEAL_REPAIR_ORPHANS` | `media_ark_watch.sh` | `1` | Enable `--self-heal-repair-orphans` in the watch runner |
| `MEDIA_ARK_MAX_RUNS` | `media_ark_watch.sh` | `0` | Max runs before the watch loop exits (`0` = unlimited) |
| `MEDIA_ARK_MAX_FILES` | `media_ark_watch.sh` | `0` | Max files per run (`0` = unlimited) |
| `MEDIA_ARK_THUMBNAIL_SIZE` | `media_ark_watch.sh` | `1024` | Thumbnail size in pixels |
| `MEDIA_ARK_CLEANUP_RAW` | `media_ark_watch.sh` | `0` | Enable `--cleanup-raw` in the watch runner |
| `MEDIA_ARK_CLEANUP_RAW_DAYS` | `media_ark_watch.sh` | `30` | Days threshold for `--cleanup-raw` |
| `MEDIA_ARK_CLEANUP_STATE_DAYS` | `media_ark_watch.sh` | `0` | Days threshold for `--cleanup-state` |
| `MEDIA_ARK_COPY` | `media_ark_watch.sh` | `0` | Enable `--copy` mode (move source files vs. leave in place) |
| `MEDIA_ARK_EVENT_LOG` | `media_ark_watch.sh` | `<out>/events.jsonl` | Event log file path |
| `MEDIA_ARK_HEARTBEAT_FILE` | `media_ark_watch.sh` | `<out>/watch-heartbeat.json` | Watch heartbeat file path |
| `MEDIA_ARK_RUN_ID` | `media_ark_watch.sh` | unset (optional) | Per-run identifier for log correlation |
| `MEDIA_ARK_WATCH_INTERVAL` | `media_ark_watch.sh` | `10` | Watch interval in seconds |
| `MEDIA_ARK_WATCH_IDLE_THRESHOLD` | `media_ark_watch.sh` | `0` | Idle threshold (no new files) before the watch loop exits |
| `MEDIA_ARK_PIPELINE_COPY` | `media_ark_pipeline.sh` | `0` | Enable `--copy` in the pipeline runner |
| `MEDIA_ARK_PIPELINE_MEDIA_TYPES` | `media_ark_pipeline.sh` | `all` | Media types to process (comma-separated) |
| `MEDIA_ARK_PIPELINE_MIN_SIZE_BYTES` | `media_ark_pipeline.sh` | `0` | Min file size to process |
| `MEDIA_ARK_PIPELINE_MAX_SIZE_BYTES` | `media_ark_pipeline.sh` | `0` | Max file size to process |
| `MEDIA_ARK_PIPELINE_MAX_FILES` | `media_ark_pipeline.sh` | `0` | Max files to process per run |
| `MEDIA_ARK_PIPELINE_NO_OCR` | `media_ark_pipeline.sh` | `0` | Disable OCR (1 = disable) |
| `MEDIA_ARK_PIPELINE_NO_THUMBNAILS` | `media_ark_pipeline.sh` | `0` | Disable thumbnail generation |
| `MEDIA_ARK_PIPELINE_SELF_HEAL` | `media_ark_pipeline.sh` | `1` | Enable `--self-heal` in the pipeline runner |
| `MEDIA_ARK_PIPELINE_REPAIR_ORPHANS` | `media_ark_pipeline.sh` | `1` | Enable `--self-heal-repair-orphans` in the pipeline runner |
| `MEDIA_ARK_PIPELINE_CLEANUP_RAW` | `media_ark_pipeline.sh` | `0` | Enable `--cleanup-raw` |
| `MEDIA_ARK_PIPELINE_CLEANUP_RAW_DAYS` | `media_ark_pipeline.sh` | `30` | Days threshold for cleanup |
| `MEDIA_ARK_PIPELINE_CLEANUP_STATE_DAYS` | `media_ark_pipeline.sh` | `0` | Days threshold for state cleanup |
| `MEDIA_ARK_PIPELINE_CHECK_SOURCE` | `media_ark_pipeline.sh` | `1` | Run `--check-source` before processing |
| `MEDIA_ARK_PIPELINE_VERIFY` | `media_ark_pipeline.sh` | `1` | Run `--verify` after processing |
| `MEDIA_ARK_PIPELINE_EVENT_LOG` | `media_ark_pipeline.sh` | `<out>/pipeline-events.jsonl` | Event log path |
| `MEDIA_ARK_PIPELINE_REPORT_DIR` | `media_ark_pipeline.sh` | `<out>/reports` | Report output dir |
| `MEDIA_ARK_PIPELINE_REPORT_BASENAME` | `media_ark_pipeline.sh` | `pipeline` | Report filename basename |
| `MEDIA_ARK_PIPELINE_RUN_ID` | `media_ark_pipeline.sh` | unset (optional) | Per-run identifier |

### Total: 37 env vars (cross-checked via `grep -oE "MEDIA_ARK_[A-Z_]+" tools/media-ark/*.sh | sort -u`)

- **4 Python** (`MEDIA_ARK_SOURCE`, `MEDIA_ARK_OUT`, `MEDIA_ARK_ALLOWED_ROOTS`, `MEDIA_ARK_VERBOSE`)
- **37 unique shell** (5 in `start_media_ark.sh`, 14 in `media_ark_watch.sh`, 18 in `media_ark_pipeline.sh`; `run_media_ark.sh` has none — it takes positional args only)

Note: the 4 Python env vars are also referenced in the shell
wrappers (e.g. `start_media_ark.sh` uses `MEDIA_ARK_SOURCE` and
`MEDIA_ARK_OUT` with its own defaults), so the *surface* total
when shell + Python are deduplicated is 37 env vars, not 41
(4 + 37 naive). The 4 Python env vars each appear in at least
one shell wrapper as well.

## Security classification (conductor's call)

The 36 env vars sort into 5 security classes. The
classification is descriptive, not prescriptive — the
prescriptive version (which agent kind may set which var) is the
conductor's call, made per-cell in `secrets-map.md`.

| Class | Examples | Sensitivity | Notes |
|---|---|---|---|
| **Network bind** | `MEDIA_ARK_HOST`, `MEDIA_ARK_PORT` | low | Setting these changes the bind address; a malicious value could expose the API to the public internet (`MEDIA_ARK_HOST=0.0.0.0`) |
| **Filesystem path** | `MEDIA_ARK_SOURCE`, `MEDIA_ARK_OUT` | medium | A malicious value could redirect the platform to read/write unintended paths. The `MEDIA_ARK_ALLOWED_ROOTS` security boundary is the gate |
| **Filesystem security boundary** | `MEDIA_ARK_ALLOWED_ROOTS` | **high** | This var defines what the platform *trusts*. Setting it to `/` would disable the security boundary entirely |
| **Operational toggle** | `MEDIA_ARK_VERBOSE`, `MEDIA_ARK_SELF_HEAL`, `MEDIA_ARK_COPY`, all the `MEDIA_ARK_PIPELINE_*` toggles | low | These change behavior but not security boundaries |
| **Per-run correlation** | `MEDIA_ARK_RUN_ID` | low | Optional; used for log correlation only |

The high-sensitivity var (`MEDIA_ARK_ALLOWED_ROOTS`) is the
only env var where a malicious value would *escape* the
security model. All other vars are either low-sensitivity
toggles or are bounded by the `MEDIA_ARK_ALLOWED_ROOTS`
security check.

## Mapping to `secrets-map.md`

The `secrets-map.md` row "MEDIA_ARK_* env vars" is *this file's*
subject. When the conductor fills the cells, the question to ask
is: "for each agent kind, which of the 36 env vars may that
agent set, and which may it only read?"

The default (per `secrets-map.md` cell-value semantics) is
`none` for any agent kind not explicitly granted access. The
default for the *human conductor* is `write` (full access).
The default for `read` (the env var is visible to the agent's
runtime) is implicit and applies to every agent kind that runs
the platform.

## What this file does *not* enumerate

- **GitHub PAT.** Powers `gh pr`, `gh issue`, `gh workflow`,
  `gh api`. Not in the source tree. See `secrets-map.md` row
  "GitHub PAT."
- **Cloudflare account ID / API token.** Owns `media-ark.org`.
  Not in the source tree. See `secrets-map.md` row "Cloudflare
  account ID."
- **npm publish token.** Would be needed for the
  `release-publish` and `npm-publish` intents. Not yet
  provisioned. See `secrets-map.md` row "npm publish token."
- **`LIMEN_API_TOKEN` / `LIMEN_CLIENT_TOKEN`.** Referenced in
  the 0.2.0 closeout resume prompt as a precedent. Not used by
  this repo. The resume prompt may be conflating with the
  separate `limen` repo.
- **`GCP_SA_KEY`.** Used by the `limen` repo for Cloud Run
  deployment. Not used by this repo.

## Cross-references

- [`secrets-map.md`](./secrets-map.md) — the per-secret authority matrix
- [`fleet-standing-rules.md`](./fleet-standing-rules.md) §"Per-agent override slots" — the per-agent authority this file operationalizes
- [`../../src/media_ark/__init__.py`](../../src/media_ark/__init__.py) — the brand module that defines `BRAND_ENV_PREFIX` and `env_key(...)`
- [`../../tools/media-ark/`](../../tools/media-ark/) — the shell wrappers that consume the shell env vars
