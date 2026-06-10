#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  media_ark_watch.sh [SOURCE_DIR] [OUT_DIR] [extra options...]

Description:
  Opinionated watch runner for unattended media-ark automation with sensible defaults
  and optional self-heal/event logging.

Environment:
  MEDIA_ARK_WATCH_INTERVAL (default: 10)
  MEDIA_ARK_WATCH_IDLE_THRESHOLD (default: 0)
  MEDIA_ARK_MAX_RUNS (default: 0)
  MEDIA_ARK_MAX_FILES (default: 0)
  MEDIA_ARK_THUMBNAIL_SIZE (default: 1024)
  MEDIA_ARK_CLEANUP_RAW (0/1, default: 0)
  MEDIA_ARK_CLEANUP_RAW_DAYS (default: 30)
  MEDIA_ARK_SELF_HEAL (0/1, default: 1)
  MEDIA_ARK_SELF_HEAL_REPAIR_ORPHANS (0/1, default: 1)
  MEDIA_ARK_CLEANUP_STATE_DAYS (default: 0)
  MEDIA_ARK_COPY (0/1, default: 0)
  MEDIA_ARK_EVENT_LOG (default: <out>/events.jsonl)
  MEDIA_ARK_HEARTBEAT_FILE (default: <out>/watch-heartbeat.json)
  MEDIA_ARK_RUN_ID (optional)

Examples:
  MEDIA_ARK_SELF_HEAL=1 MEDIA_ARK_SELF_HEAL_REPAIR_ORPHANS=1 \
    ./tools/media-ark/media_ark_watch.sh /path/to/source ./.media-ark \
    --media-types image,document --thumbnail-size 640 --query-format json
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found in PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROCESS_SCRIPT="${REPO_ROOT}/src/media_ark/process_captures.py"
if [[ ! -f "$PROCESS_SCRIPT" ]]; then
  echo "Missing processor: $PROCESS_SCRIPT" >&2
  exit 1
fi

SOURCE_DIR="${1:-$(pwd)}"
if [[ "$#" -ge 1 && "$1" != "" && "${1:0:1}" != "-" ]]; then
  SOURCE_DIR="$1"
  shift || true
fi

OUT_DIR=".media-ark"
if [[ "$#" -ge 1 && "${1:0:1}" != "-" ]]; then
  OUT_DIR="$1"
  shift || true
fi

if [[ -n "${MEDIA_ARK_COPY:-}" ]]; then
  if [[ "$MEDIA_ARK_COPY" == "1" ]]; then
    COPY_FLAG="--copy"
  else
    COPY_FLAG=""
  fi
else
  COPY_FLAG=""
fi

if [[ -n "${MEDIA_ARK_CLEANUP_RAW:-}" && "$MEDIA_ARK_CLEANUP_RAW" == "1" ]]; then
  CLEANUP_RAW="--cleanup-raw --cleanup-raw-days ${MEDIA_ARK_CLEANUP_RAW_DAYS:-30}"
else
  CLEANUP_RAW=""
fi

if [[ "${MEDIA_ARK_SELF_HEAL:-1}" == "1" ]]; then
  SELF_HEAL_FLAGS="--self-heal --self-heal-repair-orphans"
  if [[ "${MEDIA_ARK_SELF_HEAL_REPAIR_ORPHANS:-1}" != "1" ]]; then
    SELF_HEAL_FLAGS="--self-heal"
  fi
else
  SELF_HEAL_FLAGS=""
fi

WATCH_INTERVAL="${MEDIA_ARK_WATCH_INTERVAL:-10}"
WATCH_IDLE_THRESHOLD="${MEDIA_ARK_WATCH_IDLE_THRESHOLD:-0}"
MAX_RUNS="${MEDIA_ARK_MAX_RUNS:-0}"
MAX_FILES="${MEDIA_ARK_MAX_FILES:-0}"
THUMBNAIL_SIZE="${MEDIA_ARK_THUMBNAIL_SIZE:-1024}"
EVENT_LOG="${MEDIA_ARK_EVENT_LOG:-$OUT_DIR/events.jsonl}"
HEARTBEAT="${MEDIA_ARK_HEARTBEAT_FILE:-$OUT_DIR/watch-heartbeat.json}"
RUN_ID="${MEDIA_ARK_RUN_ID:-}"
CLEANUP_STATE_DAYS="${MEDIA_ARK_CLEANUP_STATE_DAYS:-0}"

run_args=(
  "$SOURCE_DIR"
  --out "$OUT_DIR"
  --watch
  --interval "$WATCH_INTERVAL"
  --watch-idle-threshold "$WATCH_IDLE_THRESHOLD"
  --max-runs "$MAX_RUNS"
  --max-files "$MAX_FILES"
  --thumbnail-size "$THUMBNAIL_SIZE"
  --watch-heartbeat "$HEARTBEAT"
  --event-log "$EVENT_LOG"
  --cleanup-state-days "$CLEANUP_STATE_DAYS"
)

if [[ -n "$COPY_FLAG" ]]; then
  run_args+=("$COPY_FLAG")
fi
if [[ -n "$CLEANUP_RAW" ]]; then
  # shellcheck disable=SC2206
  cleanup_parts=($CLEANUP_RAW)
  run_args+=("${cleanup_parts[@]}")
fi
if [[ -n "$SELF_HEAL_FLAGS" ]]; then
  # shellcheck disable=SC2206
  heal_parts=($SELF_HEAL_FLAGS)
  run_args+=("${heal_parts[@]}")
fi
if [[ -n "$RUN_ID" ]]; then
  run_args+=(--run-id "$RUN_ID")
fi

run_args+=("$@")

python3 "$PROCESS_SCRIPT" "${run_args[@]}"
