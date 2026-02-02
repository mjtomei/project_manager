"""Agent Bridge: Human-visible sub-agent with shared control.

Run as: python3 -m pm_core.bridge <socket_path> --cwd <dir> --prompt "initial prompt"

Manages a Claude session in a tmux pane, allowing both an orchestrating agent
(via Unix socket) and a human (via stdin) to send messages.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import uuid


class Bridge:
    def __init__(self, socket_path: str, cwd: str, initial_prompt: str | None = None):
        self.socket_path = socket_path
        self.cwd = cwd
        self.initial_prompt = initial_prompt
        self.session_id: str | None = None
        self.mode = "AGENT"  # AGENT or HUMAN
        self.busy = False
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pending_response: asyncio.Future | None = None
        self._stop = False

    async def run(self):
        server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        print(f"[bridge] Socket: {self.socket_path}", flush=True)
        print(f"[bridge] Mode: AGENT — press Enter to take over", flush=True)
        print("─" * 40, flush=True)

        # Send initial prompt if provided
        if self.initial_prompt:
            await self._run_turn(self.initial_prompt)

        # Start stdin reader
        loop = asyncio.get_event_loop()
        stdin_task = asyncio.create_task(self._stdin_loop(loop))

        try:
            while not self._stop:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            server.close()
            await server.wait_closed()
            stdin_task.cancel()
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    async def _stdin_loop(self, loop):
        """Read stdin in a thread, dispatch to asyncio."""
        if not sys.stdin.isatty():
            # No terminal attached — skip stdin reading
            return

        try:
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except (PermissionError, OSError):
            return

        while not self._stop:
            try:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode().rstrip("\n")
            except Exception:
                break

            if self.busy:
                # Ignore input while Claude is running
                continue

            if line == "":
                # Toggle mode
                if self.mode == "AGENT":
                    self.mode = "HUMAN"
                    print(f"\n[bridge] Mode: HUMAN — type message, empty line returns to AGENT", flush=True)
                    print("You> ", end="", flush=True)
                else:
                    self.mode = "AGENT"
                    print(f"\n[bridge] Mode: AGENT — press Enter to take over", flush=True)
                continue

            if self.mode == "HUMAN":
                # Human typed a message
                await self._run_turn(line)
                if self.mode == "HUMAN":
                    print("You> ", end="", flush=True)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a socket connection from Session A."""
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                try:
                    msg = json.loads(data.decode())
                except json.JSONDecodeError:
                    continue

                cmd = msg.get("cmd")
                if cmd == "status":
                    resp = {"event": "status", "mode": self.mode, "busy": self.busy}
                    writer.write(json.dumps(resp).encode() + b"\n")
                    await writer.drain()

                elif cmd == "take_control":
                    self.mode = "AGENT"
                    print(f"\n[bridge] Mode: AGENT (agent took control)", flush=True)
                    resp = {"event": "mode_changed", "mode": "agent"}
                    writer.write(json.dumps(resp).encode() + b"\n")
                    await writer.drain()

                elif cmd == "release_control":
                    self.mode = "HUMAN"
                    print(f"\n[bridge] Mode: HUMAN — type message, empty line returns to AGENT", flush=True)
                    resp = {"event": "mode_changed", "mode": "human"}
                    writer.write(json.dumps(resp).encode() + b"\n")
                    await writer.drain()

                elif cmd == "send":
                    message = msg.get("message", "")
                    if not message:
                        resp = {"event": "error", "text": "empty message"}
                        writer.write(json.dumps(resp).encode() + b"\n")
                        await writer.drain()
                        continue

                    # Ack first
                    writer.write(json.dumps({"event": "ack"}).encode() + b"\n")
                    await writer.drain()

                    if self.mode != "AGENT":
                        resp = {"event": "error", "text": "not in agent mode"}
                        writer.write(json.dumps(resp).encode() + b"\n")
                        await writer.drain()
                        continue

                    # Run the turn
                    result_text = await self._run_turn(message)
                    resp = {"event": "turn_end", "text": result_text}
                    writer.write(json.dumps(resp).encode() + b"\n")
                    await writer.drain()

        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def _run_turn(self, message: str) -> str:
        """Execute one Claude turn and return the response text."""
        self.busy = True
        print(f"\n{'[agent]' if self.mode == 'AGENT' else 'You'}> {message}", flush=True)
        print("─" * 40, flush=True)

        try:
            result = await self._invoke_claude(message)
        finally:
            self.busy = False

        print("─" * 40, flush=True)
        return result

    async def _invoke_claude(self, message: str) -> str:
        """Run claude -p --resume for a single turn."""
        import shutil
        claude = shutil.which("claude")
        if not claude:
            print("[bridge] ERROR: claude CLI not found", flush=True)
            return "ERROR: claude CLI not found"

        cmd = [claude, "-p"]
        if os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS") == "true":
            cmd.append("--dangerously-skip-permissions")
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        cmd.extend(["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"])

        stdin_msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": message},
        })

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )

        proc.stdin.write(stdin_msg.encode() + b"\n")
        proc.stdin.close()

        result_text = ""
        current_text = ""

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line_str = line.decode().strip()
            if not line_str:
                continue
            try:
                obj = json.loads(line_str)
            except json.JSONDecodeError:
                # Non-JSON output (verbose logging)
                print(line_str, flush=True)
                continue

            msg_type = obj.get("type")

            if msg_type == "system" and obj.get("subtype") == "init":
                self.session_id = obj.get("session_id")

            elif msg_type == "assistant":
                content_blocks = obj.get("message", {}).get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block["text"]
                        # Print incremental text
                        new = text[len(current_text):]
                        if new:
                            print(new, end="", flush=True)
                            current_text = text
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "tool")
                        print(f"\n[tool: {tool_name}]", flush=True)

            elif msg_type == "result":
                result_text = obj.get("result", current_text)
                sid = obj.get("session_id")
                if sid:
                    self.session_id = sid
                if not current_text:
                    # Print result if we didn't get streaming content
                    print(result_text, flush=True)

        # Ensure newline after streaming
        if current_text:
            print(flush=True)

        await proc.wait()
        return result_text


def main():
    parser = argparse.ArgumentParser(description="Agent Bridge")
    parser.add_argument("socket_path", help="Unix socket path")
    parser.add_argument("--cwd", default=".", help="Working directory for Claude")
    parser.add_argument("--prompt", default=None, help="Initial prompt to send")
    args = parser.parse_args()

    bridge = Bridge(args.socket_path, args.cwd, args.prompt)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(sig, frame):
        bridge._stop = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(bridge.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
