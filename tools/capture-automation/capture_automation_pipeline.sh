#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  capture_automation_pipeline.sh [SOURCE_DIR] [OUT_DIR] [extra process args...]

Description:
  Run a full capture automation pass (check -> process -> verify) in one command.
  Useful for cron, launchd, or manual full-cycle maintenance windows.

Environment:
  CAPTURE_PIPELINE_COPY (0/1, default: 0)
  CAPTURE_PIPELINE_MEDIA_TYPES (default: all)
  CAPTURE_PIPELINE_MIN_SIZE_BYTES (default: 0)
  CAPTURE_PIPELINE_MAX_SIZE_BYTES (default: 0)
  CAPTURE_PIPELINE_MAX_FILES (default: 0)
  CAPTURE_PIPELINE_NO_OCR (0/1, default: 0)
  CAPTURE_PIPELINE_NO_THUMBNAILS (0/1, default: 0)
  CAPTURE_PIPELINE_SELF_HEAL (0/1, default: 1)
  CAPTURE_PIPELINE_REPAIR_ORPHANS (0/1, default: 1)
  CAPTURE_PIPELINE_CLEANUP_RAW (0/1, default: 0)
  CAPTURE_PIPELINE_CLEANUP_RAW_DAYS (default: 30)
  CAPTURE_PIPELINE_CLEANUP_STATE_DAYS (default: 0)
  CAPTURE_PIPELINE_CHECK_SOURCE (0/1, default: 1)
  CAPTURE_PIPELINE_VERIFY (0/1, default: 1)
  CAPTURE_PIPELINE_EVENT_LOG (default: <out>/pipeline-events.jsonl)
  CAPTURE_PIPELINE_REPORT_DIR (default: <out>/reports)
  CAPTURE_PIPELINE_REPORT_BASENAME (default: pipeline)
  CAPTURE_PIPELINE_RUN_ID (optional)

Examples:
  CAPTURE_PIPELINE_COPY=1 CAPTURE_PIPELINE_SELF_HEAL=1 \
    ./tools/capture-automation/capture_automation_pipeline.sh <repo-root> ./.capture-automation

  ./tools/capture-automation/capture_automation_pipeline.sh <repo-root> ./.capture-automation \
    --post-hook '/usr/local/bin/python3 src/capture_automation/enrich_one.py'
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
PROCESS_SCRIPT="${SCRIPT_DIR}/../src/capture_automation/process_captures.py"
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

OUT_DIR=".capture-automation"
if [[ "$#" -ge 1 && "${1:0:1}" != "-" ]]; then
  OUT_DIR="$1"
  shift || true
fi
mkdir -p "$OUT_DIR"

if [[ "${CAPTURE_PIPELINE_COPY:-0}" == "1" ]]; then
  COPY_FLAG=(--copy)
else
  COPY_FLAG=()
fi

MEDIA_TYPES="${CAPTURE_PIPELINE_MEDIA_TYPES:-all}"
MIN_SIZE_BYTES="${CAPTURE_PIPELINE_MIN_SIZE_BYTES:-0}"
MAX_SIZE_BYTES="${CAPTURE_PIPELINE_MAX_SIZE_BYTES:-0}"
MAX_FILES="${CAPTURE_PIPELINE_MAX_FILES:-0}"
CLEANUP_RAW="${CAPTURE_PIPELINE_CLEANUP_RAW:-0}"
CLEANUP_RAW_DAYS="${CAPTURE_PIPELINE_CLEANUP_RAW_DAYS:-30}"
CLEANUP_STATE_DAYS="${CAPTURE_PIPELINE_CLEANUP_STATE_DAYS:-0}"
CHECK_SOURCE="${CAPTURE_PIPELINE_CHECK_SOURCE:-1}"
VERIFY="${CAPTURE_PIPELINE_VERIFY:-1}"
SELF_HEAL="${CAPTURE_PIPELINE_SELF_HEAL:-1}"
REPAIR_ORPHANS="${CAPTURE_PIPELINE_REPAIR_ORPHANS:-1}"
EVENT_LOG="${CAPTURE_PIPELINE_EVENT_LOG:-$OUT_DIR/pipeline-events.jsonl}"
REPORT_DIR="${CAPTURE_PIPELINE_REPORT_DIR:-$OUT_DIR/reports}"
REPORT_BASENAME="${CAPTURE_PIPELINE_REPORT_BASENAME:-pipeline}"
RUN_ID="${CAPTURE_PIPELINE_RUN_ID:-pipeline-$(date -u +%Y%m%dT%H%M%SZ)}"

if [[ "${CAPTURE_PIPELINE_NO_OCR:-0}" == "1" ]]; then
  NO_OCR=(--no-ocr)
else
  NO_OCR=()
fi

if [[ "${CAPTURE_PIPELINE_NO_THUMBNAILS:-0}" == "1" ]]; then
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
  cat > "$file" <<EOF
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
  run_step "check-source" \
    "${COMMON_ARGS[@]}" \
    --check-source \
    "$@" \
    "${NO_OCR[@]}" \
    "${NO_THUMBNAILS[@]}"
fi

run_step_args=(
  "${COMMON_ARGS[@]}"
  --max-files "$MAX_FILES"
  --cleanup-state-days "$CLEANUP_STATE_DAYS"
)
run_step_args+=("${COPY_FLAG[@]}")
run_step_args+=("${NO_OCR[@]}")
run_step_args+=("${NO_THUMBNAILS[@]}")
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

echo "Pipeline complete. Reports in $REPORT_DIR, event log at $EVENT_LOG"
