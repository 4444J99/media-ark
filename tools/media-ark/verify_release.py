#!/usr/bin/env python3
"""Release acceptance verifier for the capture automation platform."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from media_ark import BRAND_DATA_DIR, BRAND_PYTHON_PKG, env_key  # noqa: E402

PROCESSOR = REPO_ROOT / "src" / BRAND_PYTHON_PKG / "process_captures.py"
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".mov", ".mp4", ".webm"}


def run_cmd(
    args: List[str], *, timeout: int = 120, env: Dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return proc


def last_json(stdout: str) -> Dict[str, Any]:
    for line in reversed(
        [item.strip() for item in stdout.splitlines() if item.strip()]
    ):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise AssertionError(f"no JSON object found in stdout: {stdout}")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _auth_headers(token: str | None) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def read_json_url(
    url: str, *, timeout: int = 2, token: str | None = None
) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers=_auth_headers(token))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"expected object response from {url}")
    return payload


def post_json(
    url: str, payload: Dict[str, Any], *, timeout: int = 10, token: str | None = None
) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    headers.update(_auth_headers(token))
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise AssertionError(f"expected object response from {url}")
    return result


def read_text_url(url: str, *, timeout: int = 2) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def media_files(out: Path) -> List[str]:
    return sorted(
        path.relative_to(out).as_posix()
        for path in out.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    )


def verify_engine_determinism_and_recovery(tmp_root: Path) -> Dict[str, Any]:
    source = tmp_root / "engine-source"
    out = tmp_root / "engine-out"
    source.mkdir(parents=True)
    sample = source / "Screen Shot 2026-06-08 at 10.00.00 AM.png"
    sample.write_bytes(b"release verifier sample")

    base = [
        sys.executable,
        str(PROCESSOR),
        str(source),
        "--out",
        str(out),
        "--copy",
        "--no-ocr",
        "--no-thumbnails",
        "--json-report",
    ]

    first = run_cmd(base)
    first_payload = last_json(first.stdout)
    first_index = (out / "index.jsonl").read_text(encoding="utf-8")
    first_media = media_files(out)

    second = run_cmd(base)
    second_payload = last_json(second.stdout)
    second_index = (out / "index.jsonl").read_text(encoding="utf-8")
    second_media = media_files(out)

    if first_payload["stats"]["new"] != 1:
        raise AssertionError("first engine run did not process exactly one new capture")
    if second_payload["stats"]["new"] != 0 or second_payload["stats"]["skipped"] != 1:
        raise AssertionError("second engine run was not idempotent")
    if first_index != second_index or first_media != second_media:
        raise AssertionError(
            "deterministic output changed between identical copy-mode runs"
        )

    for name in ("manifest.json", "index.jsonl", "index-summary.json"):
        target = out / name
        if target.exists():
            target.unlink()

    verify_before = subprocess.run(
        base + ["--verify"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if verify_before.returncode != 2:
        raise AssertionError(
            "verify before repair did not detect missing manifest/index state"
        )

    repair = run_cmd(base + ["--repair"])
    repair_payload = last_json(repair.stdout)
    if repair_payload["summary"]["recovered_sidecars"] < 1:
        raise AssertionError("repair did not recover from sidecar state")

    verify_after = run_cmd(base + ["--verify"])
    verify_after_payload = last_json(verify_after.stdout)
    if verify_after_payload["health"]["status"] != "ok":
        raise AssertionError("verify after repair was not healthy")

    return {
        "first_index_rows": first_payload["stats"]["index_rows"],
        "recovered_sidecars": repair_payload["summary"]["recovered_sidecars"],
    }


def verify_mcp(tmp_root: Path) -> Dict[str, Any]:
    source = tmp_root / "mcp-source"
    out = tmp_root / "mcp-out"
    source.mkdir(parents=True)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "capture_check",
                "arguments": {"source": str(source), "out": str(out)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "capture_status",
                "arguments": {"source": "/etc", "out": "/etc"},
            },
        },
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "src.platform.mcp_server"],
        cwd=REPO_ROOT,
        input="\n".join(json.dumps(message) for message in messages),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(f"MCP verifier failed: {proc.stderr}")

    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    tools = next(item["result"]["tools"] for item in responses if item.get("id") == 2)
    tool_names = {item["name"] for item in tools}
    required = {
        "capture_status",
        "capture_check",
        "capture_run",
        "capture_verify",
        "capture_query",
    }
    missing = required - tool_names
    if missing:
        raise AssertionError(f"MCP tool list missing: {sorted(missing)}")

    check = next(item["result"] for item in responses if item.get("id") == 3)
    if (
        not check["ok"]
        or not Path(check["event_log"]).exists()
        or not Path(check["report"]).exists()
    ):
        raise AssertionError("MCP capture_check did not persist telemetry")

    rejected = next(item for item in responses if item.get("id") == 4)
    if rejected.get("error", {}).get("code") != -32602:
        raise AssertionError("MCP did not reject outside-root paths")

    return {
        "tools": sorted(tool_names),
        "event_log": check["event_log"],
        "report": check["report"],
    }


def verify_platform(tmp_root: Path) -> Dict[str, Any]:
    port = free_port()
    env = os.environ.copy()
    # Post-#43 the /api/* surface authenticates against a user store and confines
    # each user to a sandbox. Isolate that store + sandbox tree under tmp_root so
    # the verifier neither reads nor writes the developer's real data.
    env.update(
        {
            env_key("PORT"): str(port),
            env_key("USERS_DB"): str(tmp_root / "users.db"),
            env_key("USER_SANDBOX_ROOT"): str(tmp_root / "sandboxes"),
        }
    )
    proc = subprocess.Popen(
        ["npm", "run", "platform:start"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        # Readiness: the static root is public; every /api/* route now requires a
        # bearer token, so probing /api/status unauthenticated would loop on 401.
        ready = False
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                read_text_url(f"http://127.0.0.1:{port}/")
                ready = True
                break
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
        if not ready:
            stdout, stderr = proc.communicate(timeout=5)
            raise AssertionError(
                f"platform did not start\nstdout={stdout}\nstderr={stderr}"
            )

        # Register a user and drive every authenticated call as that principal,
        # operating strictly inside the sandbox it is granted.
        auth = post_json(
            f"http://127.0.0.1:{port}/api/auth/register",
            {"username": "verifier", "password": "correct horse battery"},
        )
        token = auth["api_key"]
        source = Path(auth["source"])
        out = Path(auth["out"])

        status = read_json_url(
            f"http://127.0.0.1:{port}/api/status", token=token
        )
        if status.get("ok") is not True:
            raise AssertionError("platform status was not ok")

        html = read_text_url(f"http://127.0.0.1:{port}/")
        if "Screen Capture Platform" not in html:
            raise AssertionError("dashboard HTML did not render expected title")

        run_payload = post_json(
            f"http://127.0.0.1:{port}/api/run",
            {"action": "check-source", "source": str(source), "out": str(out)},
            token=token,
        )
        if run_payload.get("ok") is not True:
            raise AssertionError("API check-source did not succeed")
        if (
            not Path(run_payload["event_log"]).exists()
            or not Path(run_payload["report"]).exists()
        ):
            raise AssertionError("API run did not persist telemetry")

        status_after = read_json_url(
            f"http://127.0.0.1:{port}/api/status?out={out}", token=token
        )
        if (
            status_after.get("platform_events_exists") is not True
            or status_after.get("report_count", 0) < 1
        ):
            raise AssertionError("API status did not expose telemetry evidence")

        # An authenticated request for a path outside the user's sandbox is a 400.
        try:
            read_json_url(
                f"http://127.0.0.1:{port}/api/status?out=/etc", token=token
            )
            raise AssertionError("API accepted outside-root path")
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            exc.close()

        return {
            "port": port,
            "event_log": run_payload["event_log"],
            "report": run_payload["report"],
        }
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


def verify_docs() -> Dict[str, Any]:
    required = [
        "README.md",
        "docs/api-reference.md",
        "docs/ONBOARDING.md",
        "docs/RELEASE.md",
        "docs/ROADMAP.md",
    ]
    missing = [path for path in required if not (REPO_ROOT / path).exists()]
    if missing:
        raise AssertionError(f"required docs missing: {missing}")
    release_text = (
        (REPO_ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8").lower()
    )
    if (
        "rollback plan" not in release_text
        or "verified recovery path" not in release_text
    ):
        raise AssertionError(
            "release artifact does not document rollback and verified recovery"
        )
    onboarding = (
        (REPO_ROOT / "docs" / "ONBOARDING.md").read_text(encoding="utf-8").lower()
    )
    for surface in ("cli", "api", "mcp", "dashboard"):
        if surface not in onboarding:
            raise AssertionError(f"onboarding missing {surface}")
    return {"checked": required}


def main() -> None:
    if not PROCESSOR.exists():
        raise SystemExit(f"processor missing: {PROCESSOR}")

    summary: Dict[str, Any] = {}
    print("release verifier: running unit/platform suite", flush=True)
    run_cmd(["npm", "test"], timeout=180)
    with tempfile.TemporaryDirectory(prefix="capture-release-verify-") as tmpdir:
        tmp_root = Path(tmpdir)
        print(
            "release verifier: checking deterministic engine and recovery", flush=True
        )
        summary["engine"] = verify_engine_determinism_and_recovery(tmp_root)
        print(
            "release verifier: checking one-command API/dashboard startup", flush=True
        )
        summary["platform"] = verify_platform(tmp_root)
        print("release verifier: checking MCP contract and telemetry", flush=True)
        summary["mcp"] = verify_mcp(tmp_root)
    print("release verifier: checking docs and release artifacts", flush=True)
    summary["docs"] = verify_docs()
    print(json.dumps({"ok": True, "summary": summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
