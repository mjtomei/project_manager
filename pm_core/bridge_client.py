"""Synchronous client for the Agent Bridge.

Usage:
    from pm_core.bridge_client import BridgeClient
    client = BridgeClient("/tmp/pm-bridge-xxx.sock")
    response = client.send_message("list the clusters")
    client.close()
"""

import json
import socket


class BridgeClient:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(socket_path)
        self._file = self._sock.makefile("rw")

    def _send(self, msg: dict) -> dict:
        self._file.write(json.dumps(msg) + "\n")
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise ConnectionError("Bridge closed connection")
        return json.loads(line)

    def send_message(self, text: str) -> str:
        """Send a message and wait for Claude's response. Returns response text."""
        resp = self._send({"cmd": "send", "message": text})
        if resp.get("event") == "error":
            raise RuntimeError(resp.get("text", "unknown error"))
        # ack received, now wait for turn_end
        line = self._file.readline()
        if not line:
            raise ConnectionError("Bridge closed connection")
        result = json.loads(line)
        if result.get("event") == "error":
            raise RuntimeError(result.get("text", "unknown error"))
        return result.get("text", "")

    def take_control(self) -> None:
        """Switch bridge to AGENT mode."""
        self._send({"cmd": "take_control"})

    def release_control(self) -> None:
        """Switch bridge to HUMAN mode."""
        self._send({"cmd": "release_control"})

    def get_status(self) -> dict:
        """Get bridge status. Returns dict with 'mode' and 'busy' keys."""
        return self._send({"cmd": "status"})

    def close(self) -> None:
        """Close the connection."""
        try:
            self._file.close()
            self._sock.close()
        except OSError:
            pass
