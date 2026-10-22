"""Codex-style local TXT reader; it never sends book text to the agent."""

from __future__ import annotations

import bisect
import curses
import hashlib
import locale
import socket
import time
from pathlib import Path

from wcwidth import wcswidth, wcwidth

from .config import label
from .io import read_json, send_action, write_json


def wrap_text(text: str, width: int) -> tuple[list[int], list[str]]:
    """Keep source offsets so reflow doesn't lose the current reading position."""
    offsets, lines = [], []
    start, cells, buf = 0, 0, []
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(start)
            lines.append("".join(buf))
            start, cells, buf = index + 1, 0, []
            continue
        if char == "\t":
            char = " " * (4 - cells % 4)
        count = wcswidth(char)
        if count < 0:
            char, count = "�", 1
        if cells + count > width and buf:
            offsets.append(start)
            lines.append("".join(buf))
            start, cells, buf = index, 0, []
        buf.append(char)
        cells += count
    offsets.append(start)
    lines.append("".join(buf))
    return offsets, lines


def clip(text: str, width: int) -> str:
    output, cells = [], 0
    for char in text:
        size = wcwidth(char)
        if size < 0:
            char, size = "�", 1
        if cells + size > width:
            break
        cells += size
        output.append(char)
    return "".join(output)


def put(screen, y: int, x: int, text: str, style=0) -> None:
    height, width = screen.getmaxyx()
    if not (0 <= y < height and 0 <= x < width - 1):
        return
    try:
        screen.addstr(y, x, clip(text, width - x - 1), style)
    except curses.error:
        pass  # A terminal resize can happen between getmaxyx and addstr.


def key_name(key) -> str | None:
    if isinstance(key, str):
        special = {
            " ": "Space",
            "\x1b": "Escape",
            "\n": "Enter",
            "\r": "Enter",
            "\t": "Tab",
            "\x7f": "BSpace",
        }
        if key in special:
            return special[key]
        if len(key) == 1 and 1 <= ord(key) <= 26:
            return "C-" + chr(ord(key) + 96)
        return key
    for index in range(1, 13):
        if key == curses.KEY_F0 + index:
            return f"F{index}"
    return {
        curses.KEY_NPAGE: "NPage",
        curses.KEY_PPAGE: "PPage",
        curses.KEY_UP: "Up",
        curses.KEY_DOWN: "Down",
        curses.KEY_LEFT: "Left",
        curses.KEY_RIGHT: "Right",
        curses.KEY_HOME: "Home",
        curses.KEY_END: "End",
        curses.KEY_BACKSPACE: "BSpace",
        curses.KEY_DC: "DC",
        curses.KEY_IC: "IC",
    }.get(key)


class Reader:
    def __init__(self, config: dict, runtime: Path | None = None):
        self.config, self.runtime = config, runtime
        self.book = Path(config["reader"]["book"])
        self.text = (
            self.book.read_text(encoding=config["reader"]["encoding"])
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        digest = hashlib.sha256(str(self.book.resolve()).encode()).hexdigest()
        self.progress = Path(config["reader"]["state_dir"]) / "books" / (digest + ".json")
        saved = read_json(self.progress, {})
        offset = saved.get("offset", 0) if isinstance(saved, dict) else 0
        self.offset = min(max(offset if type(offset) is int else 0, 0), len(self.text))
        self.rows, self.starts, self.top = [""], [0], 0
        self.size = None
        self.last_save, self.dirty = 0.0, False
        self.warning = ""
        self.keys = {key: action for action, keys in config["keys"].items() for key in keys}

    def save(self):
        try:
            write_json(self.progress, {"book": str(self.book), "offset": self.offset})
            self.dirty, self.last_save = False, time.monotonic()
        except OSError:
            self.warning = "阅读进度保存失败，请检查 state_dir"
            self.last_save = time.monotonic()

    def run(self):
        locale.setlocale(locale.LC_ALL, "")
        incoming = None
        try:
            if self.runtime:
                incoming = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                incoming.bind(str(self.runtime / "reader.sock"))
                incoming.setblocking(False)
            curses.wrapper(self.loop, incoming)
        finally:
            self.save()
            if incoming:
                incoming.close()
                (self.runtime / "reader.sock").unlink(missing_ok=True)

    def loop(self, screen, incoming):
        import json

        curses.raw()  # Ctrl+C belongs to the reader, not the background Codex.
        screen.keypad(True)
        screen.timeout(100)
        curses.set_escdelay(25)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        dim, accent = curses.A_DIM, curses.A_BOLD
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            accent = curses.color_pair(1)
        state = {
            "status": "idle",
            "auto_read": self.config["reader"]["auto_read"],
            "cwd": str(Path.cwd()),
        }
        previous_view = None
        while True:
            height, width = screen.getmaxyx()
            margin = min(self.config["reader"]["margin"], max(0, (width - 12) // 2))
            page_size = max(1, height - 10)
            if self.size != (height, width):
                self.starts, self.rows = wrap_text(self.text, max(2, width - margin * 2 - 1))
                self.top = max(0, bisect.bisect_right(self.starts, self.offset) - 1)
                self.size = (height, width)
            if self.runtime:
                state = read_json(self.runtime / "state.json", state)
                if previous_view == "reader" and state.get("view") != "reader":
                    self.save()
                previous_view = state.get("view")
            actions = []
            if incoming:
                while True:
                    try:
                        actions.append(json.loads(incoming.recv(2048))["action"])
                    except BlockingIOError:
                        break
                    except (KeyError, ValueError):
                        continue
            try:
                key = screen.get_wch()
                name = key_name(key)
                if name == "Escape":
                    screen.timeout(25)
                    try:
                        following = screen.get_wch()
                        name = "M-" + following if isinstance(following, str) else None
                    except curses.error:
                        pass
                    screen.timeout(100)
                if name in self.keys:
                    actions.append(self.keys[name])
            except curses.error:
                pass
            for action in actions:
                if action == "save":
                    self.save()
                    continue
                if action in {"back", "toggle", "auto_read"}:
                    self.save()
                    if self.runtime:
                        try:
                            send_action(self.runtime / "control.sock", action)
                        except OSError:
                            self.warning = "控制器连接已断开"
                    elif action in {"back", "toggle"}:
                        return
                    else:
                        state["auto_read"] = not state["auto_read"]
                    continue
                moves = {
                    "next_page": page_size,
                    "previous_page": -page_size,
                    "line_down": 1,
                    "line_up": -1,
                }
                if action in moves:
                    self.top += moves[action]
                elif action == "book_start":
                    self.top = 0
                elif action == "book_end":
                    self.top = max(0, len(self.rows) - page_size)
                self.top = min(max(self.top, 0), max(0, len(self.rows) - 1))
                self.offset, self.dirty = self.starts[self.top], True
            if self.dirty and time.monotonic() - self.last_save >= 0.5:
                self.save()
            screen.erase()
            if height < 12 or width < 28:
                put(screen, 0, 0, "请放大终端；" + label(self.config["keys"]["toggle"]) + " 返回")
                screen.refresh()
                continue
            put(screen, 0, margin, "╭─ Codex · " + self.book.name, dim)
            for number, line in enumerate(self.rows[self.top : self.top + page_size]):
                put(screen, number + 2, margin, line)
            status = state.get("status", "idle")
            status_text = {
                "running": "Working…",
                "waiting": "Waiting for input",
                "completed": "Completed",
                "idle": "Ready",
                "failed": "Failed",
                "interrupted": "Interrupted",
                "disconnected": "Disconnected",
            }.get(status, status)
            toggle = label(self.config["keys"]["toggle"])
            put(screen, height - 6, margin, "• " + status_text, accent)
            put(screen, height - 4, margin, "─" * (width - margin * 2 - 1), dim)
            put(screen, height - 3, margin, "› ", curses.A_BOLD)
            put(screen, height - 3, margin + 3, self.warning or f"{toggle} 返回 Codex 输入", dim)
            put(screen, height - 2, margin, "─" * (width - margin * 2 - 1), dim)
            end = self.starts[min(self.top + page_size, len(self.starts) - 1)]
            percent = (
                100
                if self.top + page_size >= len(self.rows)
                else int(end * 100 / max(1, len(self.text)))
            )
            model = state.get("model") or "Codex"
            auto = "自动阅读开" if state.get("auto_read") else "自动阅读关"
            paging = (
                label(self.config["keys"]["previous_page"][:1])
                + "/"
                + label(self.config["keys"]["next_page"][:1])
            )
            put(
                screen,
                height - 1,
                margin,
                f"{model} · {Path(state.get('cwd') or '.').name}  {percent}% · {paging} · {auto}",
                dim,
            )
            screen.refresh()
