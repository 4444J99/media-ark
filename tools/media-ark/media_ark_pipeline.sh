#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  media_ark_pipeline.sh [SOURCE_DIR] [OUT_DIR] [extra process args...]

Description:
  Run a full media-ark pass (check -> process -> verify) in one command.
  Useful for cron, launchd, or manual full-cycle maintenance windows.

Environment:
  MEDIA_ARK_PIPELINE_COPY (0/1, default: 0)
  MEDIA_ARK_PIPELINE_MEDIA_TYPES (default: all)
  MEDIA_ARK_PIPELINE_MIN_SIZE_BYTES (default: 0)
  MEDIA_ARK_PIPELINE_MAX_SIZE_BYTES (default: 0)
  MEDIA_ARK_PIPELINE_MAX_FILES (default: 0)
  MEDIA_ARK_PIPELINE_NO_OCR (0/1, default: 0)
  MEDIA_ARK_PIPELINE_NO_THUMBNAILS (0/1, default: 0)
  MEDIA_ARK_PIPELINE_SELF_HEAL (0/1, default: 1)
  MEDIA_ARK_PIPELINE_REPAIR_ORPHANS (0/1, default: 1)
  MEDIA_ARK_PIPELINE_CLEANUP_RAW (0/1, default: 0)
  MEDIA_ARK_PIPELINE_CLEANUP_RAW_DAYS (default: 30)
  MEDIA_ARK_PIPELINE_CLEANUP_STATE_DAYS (default: 0)
  MEDIA_ARK_PIPELINE_CHECK_SOURCE (0/1, default: 1)
  MEDIA_ARK_PIPELINE_VERIFY (0/1, default: 1)
  MEDIA_ARK_PIPELINE_EVENT_LOG (default: <out>/pipeline-events.jsonl)
  MEDIA_ARK_PIPELINE_REPORT_DIR (default: <out>/reports)
  MEDIA_ARK_PIPELINE_REPORT_BASENAME (default: pipeline)
  MEDIA_ARK_PIPELINE_RUN_ID (optional)

Examples:
  MEDIA_ARK_PIPELINE_COPY=1 MEDIA_ARK_PIPELINE_SELF_HEAL=1 \
    ./tools/media-ark/media_ark_pipeline.sh <repo-root> ./.media-ark

  ./tools/media-ark/media_ark_pipeline.sh <repo-root> ./.media-ark \
    --post-hook '/usr/local/bin/python3 src/media_ark/enrich_one.py'
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
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Source directory not found: $SOURCE_DIR" >&2
  exit 1
fi

OUT_DIR=".media-ark"
if [[ "$#" -ge 1 && "${1:0:1}" != "-" ]]; then
  OUT_DIR="$1"
  shift || true
fi
mkdir -p "$OUT_DIR"

if [[ "${MEDIA_ARK_PIPELINE_COPY:-0}" == "1" ]]; then
  COPY_FLAG=(--copy)
else
  COPY_FLAG=()
fi

MEDIA_TYPES="${MEDIA_ARK_PIPELINE_MEDIA_TYPES:-all}"
MIN_SIZE_BYTES="${MEDIA_ARK_PIPELINE_MIN_SIZE_BYTES:-0}"
MAX_SIZE_BYTES="${MEDIA_ARK_PIPELINE_MAX_SIZE_BYTES:-0}"
MAX_FILES="${MEDIA_ARK_PIPELINE_MAX_FILES:-0}"
CLEANUP_RAW="${MEDIA_ARK_PIPELINE_CLEANUP_RAW:-0}"
CLEANUP_RAW_DAYS="${MEDIA_ARK_PIPELINE_CLEANUP_RAW_DAYS:-30}"
CLEANUP_STATE_DAYS="${MEDIA_ARK_PIPELINE_CLEANUP_STATE_DAYS:-0}"
CHECK_SOURCE="${MEDIA_ARK_PIPELINE_CHECK_SOURCE:-1}"
VERIFY="${MEDIA_ARK_PIPELINE_VERIFY:-1}"
SELF_HEAL="${MEDIA_ARK_PIPELINE_SELF_HEAL:-1}"
REPAIR_ORPHANS="${MEDIA_ARK_PIPELINE_REPAIR_ORPHANS:-1}"
EVENT_LOG="${MEDIA_ARK_PIPELINE_EVENT_LOG:-$OUT_DIR/pipeline-events.jsonl}"
REPORT_DIR="${MEDIA_ARK_PIPELINE_REPORT_DIR:-$OUT_DIR/reports}"
REPORT_BASENAME="${MEDIA_ARK_PIPELINE_REPORT_BASENAME:-pipeline}"
RUN_ID="${MEDIA_ARK_PIPELINE_RUN_ID:-pipeline-$(date -u +%Y%m%dT%H%M%SZ)}"

if [[ "${MEDIA_ARK_PIPELINE_NO_OCR:-0}" == "1" ]]; then
  NO_OCR=(--no-ocr)
else
  NO_OCR=()
fi

if [[ "${MEDIA_ARK_PIPELINE_NO_THUMBNAILS:-0}" == "1" ]]; then
  NO_THUMBNAILS=(--no-thumbnails)
else
  NO_THUMBNAILS=()
fi

if [[ "$CLEANUP_RAW" == "1" ]]; then
  CLEANUP_RAW_ARGS=(--cleanup-raw --cleanup-raw-days "$CLEANUP_RAW_DAYS")
else
  CLEANUP_RAW_ARGS=()
fi

if [[ "$SELF_HEAL" == "1" ]]; then
  if [[ "$REPAIR_ORPHANS" == "1" ]]; then
    SELF_HEAL_ARGS=(--self-heal --self-heal-repair-orphans)
  else
    SELF_HEAL_ARGS=(--self-heal)
  fi
else
  SELF_HEAL_ARGS=()
fi

COMMON_ARGS=(
  --json-report
  --out "$OUT_DIR"
  --media-types "$MEDIA_TYPES"
  --min-size-bytes "$MIN_SIZE_BYTES"
  --max-size-bytes "$MAX_SIZE_BYTES"
)

report_step() {
  local step="$1"
  local file="$2"
  mkdir -p "$(dirname "$file")"
  cat >"$file" <<EOF
{"step":"$step","source":"$SOURCE_DIR","out":"$OUT_DIR","time":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","status":"starting"}
EOF
}

run_step() {
  local step="$1"
  shift
  local report_path="$REPORT_DIR/${REPORT_BASENAME}-${step}.json"
  local tmp_report="$REPORT_DIR/.tmp-${REPORT_BASENAME}-${step}.json"
  report_step "$step" "$tmp_report"
  python3 "$PROCESS_SCRIPT" "$SOURCE_DIR" "$@" --event-log "$EVENT_LOG" --run-id "$RUN_ID" --report "$tmp_report"
  mv "$tmp_report" "$report_path"
}

mkdir -p "$REPORT_DIR"

if [[ "$CHECK_SOURCE" == "1" ]]; then
  check_step_args=(
    "${COMMON_ARGS[@]}"
    --check-source
  )
  if ((${#NO_OCR[@]} > 0)); then
    check_step_args+=("${NO_OCR[@]}")
  fi
  if ((${#NO_THUMBNAILS[@]} > 0)); then
    check_step_args+=("${NO_THUMBNAILS[@]}")
  fi
  check_step_args+=("$@")
  run_step "check-source" "${check_step_args[@]}"
fi

run_step_args=(
  "${COMMON_ARGS[@]}"
  --max-files "$MAX_FILES"
  --cleanup-state-days "$CLEANUP_STATE_DAYS"
)
if ((${#COPY_FLAG[@]} > 0)); then
  run_step_args+=("${COPY_FLAG[@]}")
fi
if ((${#NO_OCR[@]} > 0)); then
  run_step_args+=("${NO_OCR[@]}")
fi
if ((${#NO_THUMBNAILS[@]} > 0)); then
  run_step_args+=("${NO_THUMBNAILS[@]}")
fi
if [[ "$CLEANUP_RAW" == "1" ]]; then
  run_step_args+=("${CLEANUP_RAW_ARGS[@]}")
fi
if ((${#SELF_HEAL_ARGS[@]} > 0)); then
  run_step_args+=("${SELF_HEAL_ARGS[@]}")
fi
run_step_args+=("$@")

run_step "process" "${run_step_args[@]}"

if [[ "$VERIFY" == "1" ]]; then
  run_step "verify" \
    "${COMMON_ARGS[@]}" \
    --verify \
    "$@"
fi

echo "media-ark pipeline complete. Reports in $REPORT_DIR, event log at $EVENT_LOG"
