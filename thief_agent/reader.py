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


def source_line_starts(text: str) -> list[int]:
    """Index normalized source lines; a final newline only terminates its line."""
    if not text:
        return []
    return [0] + [i + 1 for i, char in enumerate(text) if char == "\n" and i + 1 < len(text)]


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
    if start < len(text) or not lines:
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
            "\n": "C-j",
            "\r": "Enter",
            "\t": "Tab",
            "\x7f": "BSpace",
            "\x08": "BSpace",
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
        curses.KEY_ENTER: "Enter",
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
        self.line_starts = source_line_starts(self.text)
        digest = hashlib.sha256(str(self.book.resolve()).encode()).hexdigest()
        self.progress = Path(config["reader"]["state_dir"]) / "books" / (digest + ".json")
        saved = read_json(self.progress, {})
        offset = saved.get("offset", 0) if isinstance(saved, dict) else 0
        self.offset = min(max(offset if type(offset) is int else 0, 0), len(self.text))
        self.rows, self.starts, self.top = [""], [0], 0
        self.size = None
        self.last_save, self.dirty = 0.0, False
        self.warning = ""
        self.jump_digits: str | None = None
        self.jump_error = ""
        self.keys = {key: action for action, keys in config["keys"].items() for key in keys}

    def reflow(self, width: int):
        self.starts, self.rows = wrap_text(self.text, width)
        self.top = max(0, bisect.bisect_right(self.starts, self.offset) - 1)

    def position_label(self) -> str:
        total = len(self.line_starts)
        if not total:
            return "原文行 0 / 0"
        line = bisect.bisect_right(self.line_starts, self.starts[self.top]) - 1
        first_row = bisect.bisect_left(self.starts, self.line_starts[line])
        next_row = (
            bisect.bisect_left(self.starts, self.line_starts[line + 1])
            if line + 1 < total
            else len(self.rows)
        )
        label = f"原文行 {line + 1} / {total}"
        if next_row - first_row > 1:
            label += f" · 本行第 {self.top - first_row + 1} / {next_row - first_row} 屏幕行"
        return label

    def begin_jump(self):
        if not self.line_starts:
            self.warning = "空文件，无法跳转"
            return
        self.jump_digits, self.jump_error = "", ""

    def cancel_jump(self):
        self.jump_digits, self.jump_error = None, ""

    def jump_to_line(self, number: int) -> bool:
        if not 1 <= number <= len(self.line_starts):
            return False
        self.offset = self.line_starts[number - 1]
        self.top = bisect.bisect_left(self.starts, self.offset)
        self.dirty = True
        self.save()
        return True

    def input_action(self, name: str | None) -> str | None:
        # Preserve an explicit Ctrl+J binding; otherwise accept LF as Enter too.
        if name == "C-j" and name not in self.keys:
            name = "Enter"
        action = self.keys.get(name)
        if self.jump_digits is None or action in {"toggle", "auto_read"}:
            return action
        # Modal editing takes precedence over reader bindings, including Enter/digits.
        if name is not None and len(name) == 1 and name in "0123456789":
            self.jump_digits += name
            self.jump_error = ""
        elif name == "BSpace":
            self.jump_digits = self.jump_digits[:-1]
            self.jump_error = ""
        elif name == "Escape":
            self.cancel_jump()
        elif name in {"Enter", "C-j"}:
            digits = self.jump_digits.lstrip("0") or "0"
            total = len(self.line_starts)
            if not self.jump_digits:
                self.jump_error = "请输入原文行号"
            elif len(digits) > len(str(total)) or not self.jump_to_line(int(digits)):
                self.jump_error = f"行号超出范围，请输入 1–{total}"
            else:
                self.cancel_jump()
        elif action == "back":
            return action
        return None

    def read_state(self, previous: dict) -> dict:
        if not self.runtime:
            return previous
        state = read_json(self.runtime / "state.json", previous)
        hidden = state.get("view") != "reader"
        if state.get("reader_hide_count", 0) != previous.get("reader_hide_count", 0) or (
            hidden and previous.get("view") == "reader"
        ):
            self.cancel_jump()
            self.save()
        if hidden:
            self.cancel_jump()
        return state

    def jump_prompt(self, width: int) -> str:
        prefix = f"跳转到原文行（1–{len(self.line_starts)}）："
        if wcswidth(prefix) + 5 > width:
            prefix = "原文行："
        available = max(1, width - wcswidth(prefix) - 1)
        return prefix + (self.jump_digits or "")[-available:] + "▏"

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
        curses.nonl()  # Keep Enter (CR) distinct from a configured Ctrl+J (LF).
        screen.keypad(True)
        screen.timeout(100)
        # Some macOS Python builds use curses without set_escdelay.
        if hasattr(curses, "set_escdelay"):
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
        while True:
            height, width = screen.getmaxyx()
            margin = min(self.config["reader"]["margin"], max(0, (width - 12) // 2))
            page_size = max(1, height - 10)
            if self.size != (height, width):
                self.reflow(max(2, width - margin * 2 - 1))
                self.size = (height, width)
            state = self.read_state(state)
            actions = []
            if incoming:
                while True:
                    try:
                        actions.append(json.loads(incoming.recv(2048))["action"])
                    except BlockingIOError:
                        break
                    except (KeyError, ValueError):
                        continue
            name = None
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
            except curses.error:
                pass
            # Reading a key can block while the controller switches panes.
            state = self.read_state(state)
            if not self.runtime or state.get("view") == "reader":
                action = self.input_action(name)
                if action:
                    actions.append(action)
            for action in actions:
                if action == "save":
                    self.save()
                    continue
                if self.runtime and state.get("view") != "reader":
                    continue
                if action in {"back", "toggle", "auto_read"}:
                    if action != "auto_read":
                        self.cancel_jump()
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
                if action == "goto_line":
                    self.begin_jump()
                    continue
                if self.jump_digits is not None:
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
            if self.jump_digits is not None:
                put(
                    screen,
                    height - 5,
                    margin,
                    self.jump_error or f"Enter 确认 · Esc 取消 · {toggle} 返回 Codex",
                    accent if self.jump_error else dim,
                )
            put(screen, height - 4, margin, "─" * (width - margin * 2 - 1), dim)
            put(screen, height - 3, margin, "› ", curses.A_BOLD)
            composer = self.warning or (
                f"{toggle} 返回 Codex 输入 · {label(self.config['keys']['goto_line'])} 跳转行"
            )
            if self.jump_digits is not None:
                composer = self.jump_prompt(width - margin * 2 - 4)
            put(screen, height - 3, margin + 3, composer, dim)
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
                f"{self.position_label()} · {percent}% · {paging} · {auto}"
                f" · {model} · {Path(state.get('cwd') or '.').name}",
                dim,
            )
            screen.refresh()
