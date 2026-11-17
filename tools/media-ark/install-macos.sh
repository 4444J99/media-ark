#!/usr/bin/env bash
set -euo pipefail

# Brand: media-ark (Media Ark). Env-var prefix: MEDIA_ARK_*. Reverse-domain
# identifier prefix: org.media-ark (canonical domain media-ark.org). These
# mirror the brand constants in src/media_ark/__init__.py — keep them in sync
# if the product is renamed.

BRAND_DISPLAY="Media Ark"
BRAND_ID="org.media-ark"
AGENT_LABEL="${BRAND_ID}.api"

usage() {
  cat <<'USAGE'
Usage:
  install-macos.sh [options]
  install-macos.sh --uninstall [options]

Description:
  One-command macOS installer for the Media Ark platform. It:
    1. Ensures Homebrew and a Python >= 3.11 toolchain are present.
    2. Creates an isolated virtualenv and installs the project into it.
    3. Registers a launchd LaunchAgent that starts the HTTP API/dashboard
       server at login and keeps it alive.
    4. Builds a "Media Ark.app" launcher bundle and symlinks it into
       ~/Applications so the dashboard opens from Spotlight/Finder.
    5. Writes a first-run config file (never overwrites an existing one).

Options:
  --host HOST        API bind host (default: 127.0.0.1)
  --port PORT        API port (default: 8787)
  --source DIR       Capture source directory (default: <repo>/data/captures/raw)
  --out DIR          Archive output directory (default: $HOME/.media-ark)
  --prefix DIR       Install prefix for venv + app bundle
                     (default: $HOME/.local/media-ark)
  --no-launchd       Skip registering the launchd LaunchAgent
  --no-app           Skip building/symlinking the .app launcher bundle
  --no-brew          Do not touch Homebrew; require a suitable python3 in PATH
  --force            Overwrite an existing first-run config file
  --uninstall        Unload the LaunchAgent and remove the app symlink + plist
                     (leaves the venv, archive data, and config in place)
  -h, --help         Show this help

Environment overrides (consulted when the matching flag is omitted):
  MEDIA_ARK_HOST, MEDIA_ARK_PORT, MEDIA_ARK_SOURCE, MEDIA_ARK_OUT,
  MEDIA_ARK_PREFIX, MEDIA_ARK_CONFIG_DIR

Examples:
  ./tools/media-ark/install-macos.sh
  ./tools/media-ark/install-macos.sh --port 8790 --out "$HOME/Media/Archive"
  ./tools/media-ark/install-macos.sh --uninstall
USAGE
}

log() { printf '[install] %s\n' "$*"; }
warn() { printf '[install] %s\n' "$*" >&2; }
die() {
  printf '[install] error: %s\n' "$*" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

HOST="${MEDIA_ARK_HOST:-127.0.0.1}"
PORT="${MEDIA_ARK_PORT:-8787}"
SOURCE_DIR="${MEDIA_ARK_SOURCE:-}"
OUT_DIR="${MEDIA_ARK_OUT:-$HOME/.media-ark}"
PREFIX="${MEDIA_ARK_PREFIX:-$HOME/.local/media-ark}"
CONFIG_DIR="${MEDIA_ARK_CONFIG_DIR:-$HOME/.config/media-ark}"
WITH_LAUNCHD=1
WITH_APP=1
WITH_BREW=1
FORCE=0
UNINSTALL=0

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
  --prefix)
    PREFIX="${2:?--prefix requires a value}"
    shift 2
    ;;
  --no-launchd)
    WITH_LAUNCHD=0
    shift
    ;;
  --no-app)
    WITH_APP=0
    shift
    ;;
  --no-brew)
    WITH_BREW=0
    shift
    ;;
  --force)
    FORCE=1
    shift
    ;;
  --uninstall)
    UNINSTALL=1
    shift
    ;;
  *)
    warn "Unknown argument: $1"
    usage >&2
    exit 2
    ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "this installer targets macOS (Darwin); detected $(uname -s)"
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || ((PORT < 1 || PORT > 65535)); then
  die "--port must be an integer between 1 and 65535 (got: $PORT)"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Default the capture source to the repo's standard location once REPO_ROOT
# is known (kept here so an explicit --source/env value still wins).
if [[ -z "$SOURCE_DIR" ]]; then
  SOURCE_DIR="${REPO_ROOT}/data/captures/raw"
fi

VENV_DIR="${PREFIX}/venv"
VENV_PY="${VENV_DIR}/bin/python"
LOG_DIR="${PREFIX}/logs"
APP_BUNDLE="${PREFIX}/${BRAND_DISPLAY}.app"
APP_LINK="${HOME}/Applications/${BRAND_DISPLAY}.app"
PLIST_PATH="${HOME}/Library/LaunchAgents/${AGENT_LABEL}.plist"
CONFIG_FILE="${CONFIG_DIR}/config.json"

GUI_DOMAIN="gui/$(id -u)"

# ---------------------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------------------

unload_agent() {
  if [[ -f "$PLIST_PATH" ]]; then
    launchctl bootout "$GUI_DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 ||
      launchctl unload -w "$PLIST_PATH" >/dev/null 2>&1 || true
  fi
}

if [[ "$UNINSTALL" -eq 1 ]]; then
  log "Uninstalling ${BRAND_DISPLAY} launchd agent and app launcher..."
  unload_agent
  if [[ -f "$PLIST_PATH" ]]; then
    rm -f "$PLIST_PATH"
    log "Removed LaunchAgent: $PLIST_PATH"
  fi
  if [[ -L "$APP_LINK" ]]; then
    rm -f "$APP_LINK"
    log "Removed app symlink: $APP_LINK"
  fi
  log "Done. The venv ($VENV_DIR), archive data ($OUT_DIR), and config"
  log "($CONFIG_FILE) were left in place; remove them by hand if desired."
  exit 0
fi

# ---------------------------------------------------------------------------
# 1. Homebrew + Python toolchain
# ---------------------------------------------------------------------------

# Echo a python3 interpreter that satisfies requires-python (>=3.11), or
# nothing if none is found.
find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' >/dev/null 2>&1; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$WITH_BREW" -eq 0 ]]; then
    return 1
  fi
  die "Homebrew is not installed. Install it first (https://brew.sh):

    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"

  then re-run this installer, or pass --no-brew to use an existing python3."
}

PYTHON_BIN="$(find_python || true)"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ "$WITH_BREW" -eq 1 ]]; then
    ensure_homebrew
    log "No Python >= 3.11 found; installing python@3.12 via Homebrew..."
    brew install python@3.12
    PYTHON_BIN="$(find_python || true)"
  fi
fi

[[ -n "$PYTHON_BIN" ]] || die "could not find or install Python >= 3.11"
log "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

# ---------------------------------------------------------------------------
# 2. Virtualenv + project install
# ---------------------------------------------------------------------------

mkdir -p "$PREFIX" "$LOG_DIR"

if [[ ! -x "$VENV_PY" ]]; then
  log "Creating virtualenv at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  log "Reusing existing virtualenv at $VENV_DIR"
fi

log "Upgrading pip and installing ${BRAND_DISPLAY} into the venv..."
"$VENV_PY" -m pip install --upgrade pip >/dev/null
# Editable install: the launchd job runs from the repo, so the venv tracks the
# checkout in place rather than snapshotting it.
"$VENV_PY" -m pip install -e "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 3. First-run config (never clobber an existing one without --force)
# ---------------------------------------------------------------------------

mkdir -p "$CONFIG_DIR"
if [[ -f "$CONFIG_FILE" && "$FORCE" -ne 1 ]]; then
  log "Keeping existing config: $CONFIG_FILE (pass --force to overwrite)"
else
  log "Writing first-run config: $CONFIG_FILE"
  HOST="$HOST" PORT="$PORT" SOURCE_DIR="$SOURCE_DIR" OUT_DIR="$OUT_DIR" \
    REPO_ROOT="$REPO_ROOT" "$VENV_PY" - "$CONFIG_FILE" <<'PY'
import json
import os
import sys

config = {
    "host": os.environ["HOST"],
    "port": int(os.environ["PORT"]),
    "source": os.environ["SOURCE_DIR"],
    "out": os.environ["OUT_DIR"],
    "repo_root": os.environ["REPO_ROOT"],
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(config, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY
fi

# Ensure the data directories referenced by the config exist.
mkdir -p "$SOURCE_DIR" "$OUT_DIR"

# ---------------------------------------------------------------------------
# 4. launchd LaunchAgent (API server at login, kept alive)
# ---------------------------------------------------------------------------

write_plist() {
  mkdir -p "$(dirname "$PLIST_PATH")"
  # The agent runs the proven module invocation (matches start_media_ark.sh)
  # with the venv interpreter and the repo as the working directory.
  cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PY}</string>
    <string>-m</string>
    <string>src.platform.api_server</string>
    <string>--host</string>
    <string>${HOST}</string>
    <string>--port</string>
    <string>${PORT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MEDIA_ARK_HOST</key>
    <string>${HOST}</string>
    <key>MEDIA_ARK_PORT</key>
    <string>${PORT}</string>
    <key>MEDIA_ARK_SOURCE</key>
    <string>${SOURCE_DIR}</string>
    <key>MEDIA_ARK_OUT</key>
    <string>${OUT_DIR}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/api.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/api.err.log</string>
</dict>
</plist>
PLIST
}

if [[ "$WITH_LAUNCHD" -eq 1 ]]; then
  log "Registering LaunchAgent: $AGENT_LABEL"
  unload_agent
  write_plist
  # Modern bootstrap, falling back to legacy load on older macOS.
  if ! launchctl bootstrap "$GUI_DOMAIN" "$PLIST_PATH" >/dev/null 2>&1; then
    launchctl load -w "$PLIST_PATH" >/dev/null 2>&1 ||
      warn "could not load LaunchAgent; load it manually: launchctl load -w \"$PLIST_PATH\""
  fi
  launchctl kickstart -k "${GUI_DOMAIN}/${AGENT_LABEL}" >/dev/null 2>&1 || true
  log "API server will run at login: http://${HOST}:${PORT}/"
else
  log "Skipping launchd registration (--no-launchd)"
fi

# ---------------------------------------------------------------------------
# 5. App launcher bundle + ~/Applications symlink
# ---------------------------------------------------------------------------

build_app_bundle() {
  local macos_dir="${APP_BUNDLE}/Contents/MacOS"
  local info_plist="${APP_BUNDLE}/Contents/Info.plist"
  local launcher="${macos_dir}/${BRAND_DISPLAY}"

  mkdir -p "$macos_dir"

  cat >"$info_plist" <<INFO
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>${BRAND_DISPLAY}</string>
  <key>CFBundleDisplayName</key>
  <string>${BRAND_DISPLAY}</string>
  <key>CFBundleIdentifier</key>
  <string>${BRAND_ID}.app</string>
  <key>CFBundleVersion</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>${BRAND_DISPLAY}</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
INFO

  cat >"$launcher" <<LAUNCHER
#!/usr/bin/env bash
# Opens the ${BRAND_DISPLAY} dashboard. If the API agent is registered but not
# running, launchd's KeepAlive brings it back; we just open the browser.
set -euo pipefail
URL="http://${HOST}:${PORT}/"
launchctl kickstart "${GUI_DOMAIN}/${AGENT_LABEL}" >/dev/null 2>&1 || true
exec open "\$URL"
LAUNCHER
  chmod +x "$launcher"
}

if [[ "$WITH_APP" -eq 1 ]]; then
  log "Building app launcher bundle: $APP_BUNDLE"
  build_app_bundle
  mkdir -p "$(dirname "$APP_LINK")"
  # Replace a stale symlink; refuse to clobber a real directory/app.
  if [[ -L "$APP_LINK" || ! -e "$APP_LINK" ]]; then
    ln -snf "$APP_BUNDLE" "$APP_LINK"
    log "Symlinked launcher into ~/Applications: $APP_LINK"
  else
    warn "not a symlink, leaving in place: $APP_LINK"
    warn "remove it and re-run, or launch directly from: $APP_BUNDLE"
  fi
else
  log "Skipping app bundle (--no-app)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

log "Install complete."
log "  Dashboard : http://${HOST}:${PORT}/"
log "  Config    : $CONFIG_FILE"
log "  Venv      : $VENV_DIR"
if [[ "$WITH_APP" -eq 1 ]]; then
  log "  Launcher  : $APP_LINK"
fi
if [[ "$WITH_LAUNCHD" -eq 1 ]]; then
  log "  Logs      : ${LOG_DIR}/api.{out,err}.log"
fi
log "Uninstall with: ${SCRIPT_DIR}/install-macos.sh --uninstall"
