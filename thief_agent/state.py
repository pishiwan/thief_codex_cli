"""Pure UI state driven by real app-server events, never terminal text."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SessionState:
    auto_read: bool = True
    delay: float = 1.5
    view: str = "codex"
    thread_id: str | None = None
    turn_id: str | None = None
    status: str = "idle"
    model: str = ""
    cwd: str = ""
    deadline: float | None = None
    manual: bool = False
    requests: dict = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            key: getattr(self, key)
            for key in ("auto_read", "view", "thread_id", "turn_id", "status", "model", "cwd")
        }

    def action(self, action: str) -> None:
        if action == "toggle":
            self.view = "reader" if self.view == "codex" else "codex"
            self.manual = True
            self.deadline = None
        elif action == "back":
            self.view = "codex"
            self.manual = True
            self.deadline = None
        elif action == "auto_read":
            self.auto_read = not self.auto_read
            if not self.auto_read:
                self.deadline = None

    def tick(self, now: float | None = None) -> None:
        if (
            self.deadline is not None
            and (time.monotonic() if now is None else now) >= self.deadline
        ):
            self.deadline = None
            if self.auto_read and not self.manual and self.status == "running":
                self.view = "reader"

    def attention(self, status: str) -> None:
        self.status = status
        self.view = "codex"
        self.deadline = None
        self.manual = True

    def select_thread(self, thread: dict, result: dict) -> None:
        tid = thread.get("id")
        if tid != self.thread_id:
            self.thread_id, self.turn_id = tid, None
            self.deadline, self.manual = None, False
            self.view = "codex"
        self.model = result.get("model") or thread.get("model") or self.model
        self.cwd = result.get("cwd") or thread.get("cwd") or self.cwd
        status = thread.get("status", {})
        self.status = "running" if status.get("type") == "active" else "idle"
        for turn in thread.get("turns", []):
            if turn.get("status") == "inProgress":
                self.start_turn(turn.get("id"))
        if status.get("activeFlags"):
            self.attention("waiting")

    def start_turn(self, turn_id: str | None) -> None:
        if self.turn_id == turn_id:
            return
        self.turn_id = turn_id
        self.status, self.manual = "running", False
        self.deadline = time.monotonic() + self.delay if self.auto_read else None

    def client_message(self, message: dict) -> None:
        method, params = message.get("method", ""), message.get("params") or {}
        if method in {"thread/start", "thread/resume", "thread/fork"} and "id" in message:
            self.requests[message["id"]] = method
        # Explicitly submitting to another thread selects that conversation.
        if method in {"turn/start", "turn/steer"}:
            tid = params.get("threadId")
            if tid and tid != self.thread_id:
                self.thread_id, self.turn_id, self.deadline = tid, None, None

    def server_message(self, message: dict) -> None:
        if "method" not in message:
            method = self.requests.pop(message.get("id"), None)
            result = message.get("result") or {}
            if method and isinstance(result.get("thread"), dict):
                self.select_thread(result["thread"], result)
            return
        method, params = message["method"], message.get("params") or {}
        tid = params.get("threadId")
        if tid != self.thread_id or not self.thread_id:
            return
        if method == "turn/started":
            self.start_turn(params.get("turn", {}).get("id"))
        elif method == "turn/completed":
            turn = params.get("turn", {})
            if turn.get("id") == self.turn_id:
                self.attention(turn.get("status", "completed"))
        elif method == "thread/status/changed":
            status = params.get("status", {})
            if status.get("activeFlags"):
                self.attention("waiting")
            elif status.get("type") in {"idle", "systemError"}:
                self.attention("idle" if status["type"] == "idle" else "failed")
            elif status.get("type") == "active" and self.status == "waiting":
                self.status = "running"
        elif "id" in message and (
            method.endswith("requestApproval")
            or method
            in {
                "item/tool/requestUserInput",
                "mcpServer/elicitation/request",
                "item/permissions/requestApproval",
            }
        ):
            if not params.get("turnId") or params["turnId"] == self.turn_id:
                self.attention("waiting")
        elif method in {"item/started", "item/completed"}:
            item = params.get("item", {})
            if item.get("type") == "userInputRequest" or (
                item.get("type") == "agentMessage" and item.get("questions")
            ):
                self.attention("waiting")
