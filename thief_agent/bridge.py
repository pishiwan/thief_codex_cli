"""WebSocket over a private Unix socket <-> unmodified Codex app-server JSONL."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from tornado.websocket import WebSocketClosedError, WebSocketHandler

logger = logging.getLogger(__name__)


async def stop_process(process):
    if process and process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 3)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


class CodexBridge(WebSocketHandler):
    def initialize(self, runtime):
        self.runtime = runtime
        self.process = None
        self.forwarder = None

    def check_origin(self, origin):
        return False  # CLI connections have no browser Origin; Unix socket is private.

    async def open(self):
        if self.runtime.bridge is not None:
            self.close(1013, "Codex connection already active")
            return
        self.runtime.bridge = self
        self.runtime.state.status = "idle"
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.runtime.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=self.runtime.log,
                limit=64 * 1024 * 1024,
                cwd=self.runtime.cwd,
                env=self.runtime.env,
                start_new_session=True,
            )
            self.forwarder = asyncio.create_task(self.forward())
        except OSError:
            logger.exception("Cannot start Codex app-server")
            self.close(1011, "Cannot start Codex app-server")

    async def on_message(self, raw):
        if not self.process or not self.process.stdin:
            self.close(1011, "app-server unavailable")
            return
        if isinstance(raw, bytes):
            self.close(1003, "JSON text required")
            return
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise TypeError("Expected an object")
            self.observe("client_message", message)
            # JSONL must stay one physical line even for pretty-printed input.
            self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
            await self.process.stdin.drain()
        except (ValueError, TypeError, BrokenPipeError, ConnectionResetError):
            self.close(1011, "Invalid message or disconnected app-server")

    def observe(self, direction, message):
        try:
            getattr(self.runtime.state, direction)(message)
        except (KeyError, TypeError, AttributeError):
            # UI observation must not break the original agent's connection.
            logger.exception("Could not observe Codex event")

    async def forward(self):
        try:
            while line := await self.process.stdout.readline():
                raw = line.decode()
                message = json.loads(raw)
                self.observe("server_message", message)
                await self.write_message(raw.rstrip("\n"))
        except (ValueError, WebSocketClosedError, ConnectionError):
            logger.exception("Codex transport ended")
        finally:
            if self.runtime.bridge is self:
                self.runtime.state.attention("disconnected")
            self.close()
            await stop_process(self.process)

    def on_close(self):
        if self.runtime.bridge is self:
            self.runtime.bridge = None
            self.runtime.state.attention("disconnected")
        if self.process:
            asyncio.create_task(stop_process(self.process))
