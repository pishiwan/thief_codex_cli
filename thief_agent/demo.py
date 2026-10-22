"""Offline demo pane: exercise switching without starting an agent or spending tokens."""

import curses
import locale
from pathlib import Path

from .config import label
from .io import read_json, send_action
from .reader import put


def run_demo(runtime: Path):
    locale.setlocale(locale.LC_ALL, "")
    config = read_json(runtime / "config.json")

    def loop(screen):
        curses.raw()
        screen.keypad(True)
        screen.timeout(100)
        text = ""
        while True:
            state = read_json(runtime / "state.json", {})
            height, width = screen.getmaxyx()
            screen.erase()
            put(screen, 1, 2, "╭─ Codex · 离线演示", curses.A_BOLD)
            put(screen, 3, 2, "Enter 模拟一个 6 秒任务；/wait 模拟等待输入；/exit 退出。")
            put(screen, 5, 2, "状态：" + state.get("status", "idle"))
            put(screen, height - 5, 2, "─" * max(0, width - 5), curses.A_DIM)
            put(screen, height - 4, 2, "› " + text)
            put(
                screen,
                height - 2,
                2,
                label(config["keys"]["toggle"]) + " 切换小说 · 此模式不调用模型",
                curses.A_DIM,
            )
            screen.refresh()
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key in ("\n", "\r"):
                if text == "/exit":
                    return
                send_action(
                    runtime / "control.sock", "demo_wait" if text == "/wait" else "demo_start"
                )
                text = ""
            elif key == "\x03":
                send_action(runtime / "control.sock", "demo_interrupt")
            elif key in ("\x7f", "\b", curses.KEY_BACKSPACE):
                text = text[:-1]
            elif isinstance(key, str) and key.isprintable():
                text += key

    curses.wrapper(loop)
