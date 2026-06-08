#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_capture_automation.sh [SOURCE_DIR] [OUT_DIR] [process_captures options...]

Arguments:
  SOURCE_DIR  Source folder containing media (default: current directory)
  OUT_DIR     Output root for process_captures.py (default: .capture-automation)

Examples:
  run_capture_automation.sh
  run_capture_automation.sh /path/to/captures
  run_capture_automation.sh /path/to/captures /path/to/out --copy --verbose
EOF
}

SOURCE_DIR="$(pwd)"
OUT_DIR=".capture-automation"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  shift
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found in PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROCESS_SCRIPT="${REPO_ROOT}/src/capture_automation/process_captures.py"

if [[ ! -f "$PROCESS_SCRIPT" ]]; then
  echo "Processing script missing: $PROCESS_SCRIPT" >&2
  exit 1
fi

if [[ "${#}" -gt 0 && "${1:0:1}" != "-" ]]; then
  SOURCE_DIR="$1"
  shift || true
  if [[ "${#}" -gt 0 && "${1:0:1}" != "-" ]]; then
    OUT_DIR="$1"
    shift || true
  fi
fi

if [[ "${1:-}" == "--help" ]]; then
  python3 "$PROCESS_SCRIPT" --help
  exit 0
fi

if [[ ! -f "$SOURCE_DIR" && ! -d "$SOURCE_DIR" ]]; then
  echo "Source path does not exist: $SOURCE_DIR" >&2
  exit 1
fi

python3 "$PROCESS_SCRIPT" "$SOURCE_DIR" --out "$OUT_DIR" "$@"
