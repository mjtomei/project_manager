"""FastAPI server backing the ``pm rc`` document viewer/editor.

Run via ``python -m pm_core.rc.server --path FILE --port N --host H``.
The CLI in ``pm_core.cli.rc`` launches this as a detached background
daemon; the API is consumed by the rc-driver Claude pane (over loopback)
and by browser clients on the LAN (over LAN IP).

The runtime deps (``fastapi``, ``uvicorn``) are an optional extra
(``pip install 'pm[rc]'``).  Importing this module without them raises
``RuntimeError`` with an install hint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover - import guard
    raise RuntimeError(
        "pm rc requires fastapi and uvicorn. Install with: pip install 'pm[rc]'"
    ) from e


_TEMPLATE_PATH = Path(__file__).parent / "templates" / "viewer.html"


@dataclass
class State:
    """Mutable server state. Guarded by ``lock``."""
    path: Path
    version: int = 0
    selection: tuple[int, int] | None = None
    proposal: str | None = None
    viewport: dict | None = None
    missing: bool = False
    last_mtime_ns: int = 0
    last_size: int = -1
    lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: list[queue.Queue] = field(default_factory=list)

    def read_text(self) -> str:
        try:
            return self.path.read_text()
        except FileNotFoundError:
            return ""

    def line_count(self) -> int:
        text = self.read_text()
        if not text:
            return 0
        # Count lines, treating a trailing newline as ending the last line
        # rather than starting a new empty one.
        n = text.count("\n")
        return n if text.endswith("\n") else n + 1

    def snapshot(self, include_text: bool) -> dict:
        d: dict[str, Any] = {
            "path": str(self.path),
            "version": self.version,
            "viewport": dict(self.viewport) if self.viewport else None,
            "selection": (
                {"start": self.selection[0], "end": self.selection[1]}
                if self.selection else None
            ),
            "proposal": ({"text": self.proposal} if self.proposal is not None else None),
            "missing": self.missing,
        }
        if include_text:
            d["text"] = self.read_text()
        return d

    def stat_signature(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def remember_disk_state(self) -> None:
        """Record current on-disk signature so the watcher won't re-fire."""
        sig = self.stat_signature()
        if sig is None:
            self.last_mtime_ns = 0
            self.last_size = -1
            self.missing = True
        else:
            self.last_mtime_ns, self.last_size = sig
            self.missing = False

    def check_disk(self) -> tuple[bool, dict | None, dict | None]:
        """Detect external file changes. Returns (changed, state_snap, doc_snap).

        ``doc_snap`` is None if the file is missing (no text to send).
        Caller broadcasts after releasing the lock.
        """
        sig = self.stat_signature()
        with self.lock:
            now_missing = sig is None
            if now_missing:
                if self.missing:
                    return (False, None, None)
                self.missing = True
                self.last_mtime_ns = 0
                self.last_size = -1
                self.version += 1
                return (True, self.snapshot(include_text=False), None)
            mtime, size = sig
            if not self.missing and mtime == self.last_mtime_ns and size == self.last_size:
                return (False, None, None)
            self.missing = False
            self.last_mtime_ns = mtime
            self.last_size = size
            self.version += 1
            return (True, self.snapshot(include_text=False),
                    self.snapshot(include_text=True))

    def broadcast(self, event: str, data: dict) -> None:
        """Push an event to every subscriber. Drops slow subscribers."""
        payload = (event, data)
        dead: list[queue.Queue] = []
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                self.subscribers.remove(q)
            except ValueError:
                pass


class SelectBody(BaseModel):
    start: int
    end: int


class FocusBody(BaseModel):
    top_line: int


class ProposeBody(BaseModel):
    text: str


class ViewportBody(BaseModel):
    top: int
    bottom: int


def create_app(path: Path, watch_interval: float = 0.15) -> FastAPI:
    """Build the FastAPI app bound to *path*.

    Exposed as a factory so tests can construct an app against a temp
    file without spawning a uvicorn process.

    A background thread polls *path* every *watch_interval* seconds and
    broadcasts a state+doc event on external modification (and a state
    event on file deletion / reappearance). Set ``watch_interval=0`` to
    disable the watcher (tests drive ``state.check_disk()`` directly).
    """
    state = State(path=path.resolve())
    state.remember_disk_state()
    app = FastAPI()
    app.state.rc = state
    stop_event = threading.Event()
    app.state.rc_stop = stop_event

    @app.get("/", response_class=HTMLResponse)
    def _root() -> str:
        return _TEMPLATE_PATH.read_text()

    @app.get("/api/doc")
    def _doc() -> dict:
        with state.lock:
            return state.snapshot(include_text=True)

    @app.post("/api/select")
    def _select(body: SelectBody) -> dict:
        with state.lock:
            total = state.line_count()
            if body.start < 1 or body.end < body.start or body.end > total:
                raise HTTPException(400, f"selection out of range (file has {total} lines)")
            state.selection = (body.start, body.end)
            top = max(1, body.start - 3)
            state.viewport = {"top": top, "bottom": (state.viewport or {}).get("bottom", top)}
            snap = state.snapshot(include_text=False)
        state.broadcast("state", snap)
        return {"ok": True}

    @app.post("/api/focus")
    def _focus(body: FocusBody) -> dict:
        with state.lock:
            total = max(1, state.line_count())
            top = max(1, min(body.top_line, total))
            bottom = (state.viewport or {}).get("bottom", top)
            state.viewport = {"top": top, "bottom": max(top, bottom)}
            vp = dict(state.viewport)
            snap = state.snapshot(include_text=False)
        state.broadcast("state", snap)
        return {"ok": True, "viewport": vp}

    @app.post("/api/propose")
    def _propose(body: ProposeBody) -> dict:
        with state.lock:
            if state.selection is None:
                raise HTTPException(400, "no selection")
            state.proposal = body.text
            snap = state.snapshot(include_text=False)
        state.broadcast("state", snap)
        return {"ok": True}

    @app.post("/api/accept")
    def _accept() -> dict:
        with state.lock:
            if state.selection is None or state.proposal is None:
                raise HTTPException(400, "nothing to accept")
            start, end = state.selection
            text = state.read_text()
            had_trailing_nl = text.endswith("\n")
            lines = text.split("\n")
            # text.split("\n") yields N+1 items when text ends with \n;
            # the last item is "" representing the terminator. Map our
            # 1-indexed inclusive range against the "real" lines.
            real_lines = lines[:-1] if had_trailing_nl else lines
            if not (1 <= start <= end <= len(real_lines)):
                raise HTTPException(400, "selection out of range")
            prop = state.proposal
            prop_lines = prop.split("\n")
            # If proposal ends with newline, drop the trailing empty
            # element so we don't insert a blank line.
            if prop.endswith("\n") and prop_lines and prop_lines[-1] == "":
                prop_lines = prop_lines[:-1]
            new_lines = real_lines[: start - 1] + prop_lines + real_lines[end:]
            new_text = "\n".join(new_lines) + ("\n" if had_trailing_nl else "")
            state.path.write_text(new_text)
            state.version += 1
            state.proposal = None
            state.selection = None
            # Update the disk signature so the file watcher doesn't see
            # our own write as an external modification and re-broadcast.
            state.remember_disk_state()
            new_version = state.version
            snap = state.snapshot(include_text=False)
            doc = state.snapshot(include_text=True)
        state.broadcast("state", snap)
        state.broadcast("doc", doc)
        return {"ok": True, "version": new_version}

    @app.post("/api/reject")
    def _reject() -> dict:
        with state.lock:
            state.proposal = None
            snap = state.snapshot(include_text=False)
        state.broadcast("state", snap)
        return {"ok": True}

    @app.post("/api/viewport")
    def _viewport(body: ViewportBody) -> dict:
        # Intentionally does NOT broadcast: viewer devices are expected to
        # be independent (e.g. phone vs tablet) and must not scroll-sync
        # off each other. The stored value is read by `pm rc status`.
        with state.lock:
            state.viewport = {"top": body.top, "bottom": body.bottom}
        return {"ok": True}

    @app.get("/api/events")
    async def _events(request: Request) -> StreamingResponse:
        q: queue.Queue = queue.Queue(maxsize=100)
        with state.lock:
            state.subscribers.append(q)
            initial = state.snapshot(include_text=False)

        async def gen():
            try:
                yield _sse_format("state", initial)
                while True:
                    if await request.is_disconnected():
                        break
                    # Run the blocking queue read in a worker thread so a
                    # quiet stream doesn't pin the asyncio event loop —
                    # otherwise every subscriber would serialize all other
                    # request handling for up to the timeout.
                    try:
                        event, data = await asyncio.to_thread(
                            q.get, True, 0.5
                        )
                    except queue.Empty:
                        yield ": ping\n\n"
                        continue
                    yield _sse_format(event, data)
            finally:
                try:
                    state.subscribers.remove(q)
                except ValueError:
                    pass

        return StreamingResponse(gen(), media_type="text/event-stream")

    def _watch_loop():
        # Polling mtime+size avoids a watchdog/inotify dependency. The
        # 150ms interval naturally debounces editor multi-step saves
        # (vim's write→swap→rename burst settles within the window).
        while not stop_event.wait(watch_interval):
            try:
                changed, snap, doc = state.check_disk()
            except Exception:
                continue
            if changed:
                state.broadcast("state", snap)
                if doc is not None:
                    state.broadcast("doc", doc)

    if watch_interval > 0:
        watcher = threading.Thread(target=_watch_loop, name="rc-watcher",
                                   daemon=True)
        watcher.start()

        @app.on_event("shutdown")
        def _shutdown():  # pragma: no cover - lifecycle
            stop_event.set()

    return app


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - entrypoint
    import uvicorn

    p = argparse.ArgumentParser()
    p.add_argument("--path", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args(argv)

    app = create_app(Path(args.path))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    main()
