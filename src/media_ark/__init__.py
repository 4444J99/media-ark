"""media-ark — local-first media archive pipeline.

Brand module: the single source of truth for the product's identity.

Every consumer in this package — Python code, runtime config, the HTTP
and MCP server identity strings, the default data directory, the
environment variable prefix, the npm package name, the display name in
docs — reads from the BRAND constants defined here. The product's
display name, domain, and identity strings are *data*, not strings
baked into source.

Renaming the product is a one-file change: edit BRAND_* below, then
update the README h1 and any docs that hardcode the display name. The
Python import path (this package's directory name) is the only thing
that is not data — Python's import system requires the directory name
to match the import statement. See README.md and docs/ONBOARDING.md
for the brand rationale (the "ark" metaphor: a small, intentional,
durable collection of heterogeneous things kept safe through
disruption).

Public surface:
    BRAND_NAME          — lowercase identifier used in paths, imports
                          (mirrors the Python package directory).
    BRAND_DISPLAY       — human-readable display name (Title Case).
    BRAND_DOMAIN        — canonical domain (registered via Cloudflare).
    BRAND_REPO_URL      — canonical GitHub repo URL (post-rename).
    BRAND_DATA_DIR      — default runtime data directory (relative).
    BRAND_NPM           — npm package name.
    BRAND_PYTHON_PKG    — Python distribution name (matches the dir).
    BRAND_ENV_PREFIX    — environment variable prefix (used in
                          src/platform/config.py to read MEDIA_ARK_*
                          env vars; no CAPTURE_PLATFORM_* shim).
    BRAND_MCP_NAME      — serverInfo.name exposed to MCP clients.
    BRAND_SERVER_VERSION — HTTP Server: response header.
"""

from __future__ import annotations

BRAND_NAME: str = "media-ark"
BRAND_DISPLAY: str = "Media Ark"
BRAND_DOMAIN: str = "media-ark.org"
BRAND_REPO_URL: str = "https://github.com/4444J99/media-ark"
BRAND_DATA_DIR: str = ".media-ark"
BRAND_NPM: str = "media-ark"
BRAND_PYTHON_PKG: str = "media_ark"
BRAND_ENV_PREFIX: str = "MEDIA_ARK"
BRAND_MCP_NAME: str = "media-ark"
BRAND_SERVER_VERSION: str = "MediaArk/1.0"


def env_key(suffix: str) -> str:
    """Return the full env-var name for a given suffix, e.g. env_key('SOURCE') -> 'MEDIA_ARK_SOURCE'."""
    return f"{BRAND_ENV_PREFIX}_{suffix}"


__all__ = [
    "BRAND_NAME",
    "BRAND_DISPLAY",
    "BRAND_DOMAIN",
    "BRAND_REPO_URL",
    "BRAND_DATA_DIR",
    "BRAND_NPM",
    "BRAND_PYTHON_PKG",
    "BRAND_ENV_PREFIX",
    "BRAND_MCP_NAME",
    "BRAND_SERVER_VERSION",
    "env_key",
]
