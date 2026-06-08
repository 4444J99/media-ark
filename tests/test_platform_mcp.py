from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


class TestMcpServer(unittest.TestCase):
    def test_mcp_initialize_and_tool_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "capture_status",
                        "arguments": {
                            "source": str(root / "source"),
                            "out": str(root / "out"),
                        },
                    },
                },
            ]
            proc = subprocess.run(
                [sys.executable, "-m", "src.platform.mcp_server"],
                input="\n".join(json.dumps(message) for message in messages).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=20,
            )
        self.assertEqual(proc.returncode, 0)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 3)

        initialize = json.loads(lines[0])
        self.assertEqual(initialize["result"]["serverInfo"]["name"], "screen-capture-platform")

        tools = json.loads(lines[1])
        tool_names = {entry["name"] for entry in tools["result"]["tools"]}
        self.assertIn("capture_status", tool_names)

        status = json.loads(lines[2])
        self.assertTrue(status["result"]["ok"])
        self.assertEqual(status["result"]["mode"], "status")
        self.assertEqual(status["result"]["tool"], "capture_status")

    def test_mcp_rejects_paths_outside_allowed_roots(self) -> None:
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "capture_status",
                    "arguments": {"source": "/etc", "out": "/etc"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "capture_check",
                    "arguments": {"source": "/etc", "out": "/etc"},
                },
            },
        ]
        proc = subprocess.run(
            [sys.executable, "-m", "src.platform.mcp_server"],
            input="\n".join(json.dumps(message) for message in messages).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0)
        lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        errors = {payload["id"]: payload["error"] for payload in lines if "error" in payload}
        self.assertEqual(errors[2]["code"], -32602)
        self.assertEqual(errors[3]["code"], -32602)

    def test_mcp_capture_check_persists_report_and_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            out = root / "out"
            source.mkdir()
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "capture_check",
                        "arguments": {
                            "source": str(source),
                            "out": str(out),
                        },
                    },
                },
            ]
            proc = subprocess.run(
                [sys.executable, "-m", "src.platform.mcp_server"],
                input="\n".join(json.dumps(message) for message in messages).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=20,
            )
            self.assertEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout.splitlines()[-1])
            result = payload["result"]
            self.assertTrue(result["ok"])
            self.assertTrue(Path(result["event_log"]).exists())
            self.assertTrue(Path(result["report"]).exists())
