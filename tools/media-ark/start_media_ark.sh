#!/usr/bin/env bash
set -euo pipefail

# Brand: media-ark (Media Ark). Env-var prefix: MEDIA_ARK_*. Default
# data dir: .media-ark. Python package: media_ark (in src/).

usage() {
  cat <<'USAGE'
Usage:
  start_media_ark.sh [--host HOST] [--port PORT] [--source SOURCE_DIR] [--out OUT_DIR]

Description:
  One-command local platform start for the HTTP API and dashboard. The MCP server
  is stdio-based, so this command preflights its initialize/tools contract before
  handing off to the API/dashboard server.

Environment:
  MEDIA_ARK_HOST (default: 127.0.0.1)
  MEDIA_ARK_PORT (default: 8787)
  MEDIA_ARK_SOURCE (default: data/captures/raw)
  MEDIA_ARK_OUT (default: .media-ark)
  MEDIA_ARK_MCP_PREFLIGHT (0/1, default: 1)

Examples:
  ./tools/media-ark/start_media_ark.sh
  MEDIA_ARK_PORT=8790 npm run platform:start
USAGE
}

HOST="${MEDIA_ARK_HOST:-127.0.0.1}"
PORT="${MEDIA_ARK_PORT:-8787}"
SOURCE_DIR="${MEDIA_ARK_SOURCE:-data/captures/raw}"
OUT_DIR="${MEDIA_ARK_OUT:-.media-ark}"
MCP_PREFLIGHT="${MEDIA_ARK_MCP_PREFLIGHT:-1}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
  -h | --help)
    usage
    exit 0
    ;;
  --host)
    HOST="${2:?--host requires a value}"
    shift 2
    ;;
  --port)
    PORT="${2:?--port requires a value}"
    shift 2
    ;;
  --source)
    SOURCE_DIR="${2:?--source requires a value}"
    shift 2
    ;;
  --out)
    OUT_DIR="${2:?--out requires a value}"
    shift 2
    ;;
  *)
    echo "Unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

mkdir -p "$SOURCE_DIR" "$OUT_DIR"

python3 - <<'PY'
from pathlib import Path

required = [
    Path("src/platform/api_server.py"),
    Path("src/platform/mcp_server.py"),
    Path("web/index.html"),
    Path("web/app.js"),
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit(f"platform files missing: {', '.join(missing)}")
PY

if [[ "$MCP_PREFLIGHT" == "1" ]]; then
  python3 - <<'PY'
import json
import subprocess
import sys

messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]

proc = subprocess.run(
    [sys.executable, "-m", "src.platform.mcp_server"],
    input="\n".join(json.dumps(message) for message in messages).encode("utf-8"),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
    timeout=20,
)
if proc.returncode != 0:
    raise SystemExit(proc.stderr.decode("utf-8", errors="ignore") or "MCP preflight failed")

lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
payloads = [json.loads(line) for line in lines]
tools = next((item["result"]["tools"] for item in payloads if item.get("id") == 2), [])
tool_names = {tool.get("name") for tool in tools}
required = {"capture_status", "capture_check", "capture_run", "capture_verify", "capture_query"}
missing = sorted(required - tool_names)
if missing:
    raise SystemExit(f"MCP tools missing: {missing}")
PY
fi

echo "media-ark platform API/dashboard: http://${HOST}:${PORT}/"
echo "MCP stdio command: python3 -m src.platform.mcp_server"
export MEDIA_ARK_HOST="$HOST"
export MEDIA_ARK_PORT="$PORT"
export MEDIA_ARK_SOURCE="$SOURCE_DIR"
export MEDIA_ARK_OUT="$OUT_DIR"
exec python3 -m src.platform.api_server --host "$HOST" --port "$PORT"
