"""Focused regression checks for routing and terminal layout boundaries."""

import tempfile
import unittest
from pathlib import Path

from wcwidth import wcswidth

from thief_agent.config import load_config
from thief_agent.io import read_json, write_json
from thief_agent.reader import Reader, key_name, source_line_starts, wrap_text
from thief_agent.state import SessionState


def event(method, thread="main", **params):
    return {"method": method, "params": {"threadId": thread, **params}}


class ConfigurationTests(unittest.TestCase):
    def test_custom_keys_and_relative_book(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[reader]\nbook="book.txt"\n[keys]\ntoggle=["Ctrl+r"]\nnext_page=["j"]\n'
            )
            config = load_config(path)
            self.assertEqual(config["reader"]["book"], str(path.parent / "book.txt"))
            self.assertEqual(config["keys"]["toggle"], ["C-r"])
            self.assertEqual(config["keys"]["next_page"], ["j"])

    def test_alias_conflicts_and_invalid_values_fail_early(self):
        for content in (
            '[keys]\ntoggle=["Ctrl+i"]\nnext_page=["Tab"]',
            "[reader]\ndelay=nan",
            '[reader]\nauto_read="false"',
            "[keys]\ntoggle=[]",
            '[keys]\nnext_pgae=["j"]',
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.toml"
                path.write_text(content)
                with self.assertRaises((ValueError, TypeError)):
                    load_config(path)


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.state = SessionState(delay=0)
        self.state.client_message({"id": 1, "method": "thread/start", "params": {}})
        self.state.server_message(
            {
                "id": 1,
                "result": {
                    "model": "example",
                    "thread": {"id": "main", "status": {"type": "idle"}},
                },
            }
        )

    def start(self, turn="a"):
        self.state.server_message(event("turn/started", turn={"id": turn, "status": "inProgress"}))

    def test_fast_completion_cancels_auto_entry(self):
        self.start()
        self.state.server_message(event("turn/completed", turn={"id": "a", "status": "completed"}))
        self.state.tick()
        self.assertEqual(self.state.view, "codex")

    def test_manual_return_survives_duplicate_events(self):
        self.start()
        self.state.tick()
        self.assertEqual(self.state.view, "reader")
        self.state.action("back")
        self.start()
        self.state.server_message(
            event("thread/status/changed", status={"type": "active", "activeFlags": []})
        )
        self.state.tick()
        self.assertEqual(self.state.view, "codex")
        self.start("b")
        self.state.tick()
        self.assertEqual(self.state.view, "reader")

    def test_child_and_stale_completion_cannot_steal_focus(self):
        self.start("b")
        self.state.tick()
        self.state.server_message(
            event("turn/completed", thread="child", turn={"id": "b", "status": "completed"})
        )
        self.state.server_message(event("turn/completed", turn={"id": "a", "status": "completed"}))
        self.assertEqual(self.state.view, "reader")

    def test_approvals_async_questions_and_failures_return(self):
        messages = [
            event(
                "thread/status/changed",
                status={"type": "active", "activeFlags": ["waitingOnUserInput"]},
            ),
            {**event("item/commandExecution/requestApproval", turnId="a"), "id": 9},
            event(
                "item/completed", item={"type": "agentMessage", "questions": [{"title": "Which?"}]}
            ),
            event("turn/completed", turn={"id": "a", "status": "failed"}),
            event("turn/completed", turn={"id": "a", "status": "interrupted"}),
        ]
        for message in messages:
            with self.subTest(method=message["method"]):
                self.setUp()
                self.start()
                self.state.tick()
                self.state.server_message(message)
                self.assertEqual(self.state.view, "codex")

    def test_disable_auto_still_returns_on_completion(self):
        self.state.action("auto_read")
        self.start()
        self.state.tick()
        self.assertEqual(self.state.view, "codex")
        self.state.action("toggle")
        self.state.server_message(event("turn/completed", turn={"id": "a", "status": "completed"}))
        self.assertEqual(self.state.view, "codex")

    def test_resume_waiting_thread_does_not_hide_prompt(self):
        self.state.select_thread(
            {
                "id": "resumed",
                "status": {"type": "active", "activeFlags": ["waitingOnApproval"]},
                "turns": [{"id": "r", "status": "inProgress"}],
            },
            {},
        )
        self.state.tick()
        self.assertEqual(self.state.view, "codex")
        self.assertEqual(self.state.status, "waiting")


class LayoutTests(unittest.TestCase):
    def test_source_lines_and_trailing_newlines(self):
        for text, offsets, rows in (
            ("", [], [""]),
            ("a\n", [0], ["a"]),
            ("a\n\n", [0, 2], ["a", ""]),
            ("\n", [0], [""]),
            ("\n\n", [0, 1], ["", ""]),
            ("a\nb", [0, 2], ["a", "b"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(source_line_starts(text), offsets)
                self.assertEqual(wrap_text(text, 10), (offsets or [0], rows))

    def test_chinese_combining_marks_and_source_offsets(self):
        text = "雨后的车站 cafe\u0301\n第二行文字\n\n最后一行"
        for width in (4, 7, 15):
            offsets, lines = wrap_text(text, width)
            self.assertTrue(all(wcswidth(line) <= width for line in lines))
            self.assertEqual("".join(lines), text.replace("\n", ""))
            for offset, line in zip(offsets, lines):
                self.assertTrue(text[offset:].startswith(line))


class ReaderJumpTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.book = self.root / "book.txt"
        self.book.write_bytes(("标题\r\n" + "中文" * 12 + "\r\r尾行\r\n").encode())
        self.config = load_config(None)
        self.config["reader"].update(book=str(self.book), state_dir=str(self.root))
        self.reader = Reader(self.config)
        self.reader.reflow(8)

    def test_jump_blank_last_and_long_lines_survives_resize_and_restart(self):
        reader = self.reader
        self.assertEqual(len(reader.line_starts), 4)
        for line, text in ((3, ""), (4, "尾行"), (2, "中文中文")):
            self.assertTrue(reader.jump_to_line(line))
            self.assertEqual(reader.rows[reader.top], text)
            self.assertTrue(reader.position_label().startswith(f"原文行 {line} / 4"))
            self.assertEqual(read_json(reader.progress)["offset"], reader.offset)
        reader.top += 2
        reader.offset = reader.starts[reader.top]
        self.assertEqual(reader.position_label(), "原文行 2 / 4 · 本行第 3 / 6 屏幕行")
        offset = reader.offset
        reader.begin_jump()
        reader.input_action("3")
        reader.reflow(16)
        self.assertEqual(reader.position_label(), "原文行 2 / 4 · 本行第 2 / 3 屏幕行")
        self.assertEqual(reader.jump_digits, "3")
        self.assertEqual(reader.offset, offset)
        reader.save()
        restored = Reader(self.config)
        restored.reflow(8)
        self.assertEqual(restored.offset, offset)
        self.assertEqual(restored.position_label(), "原文行 2 / 4 · 本行第 3 / 6 屏幕行")

    def test_modal_validation_editing_and_navigation_precedence(self):
        reader = self.reader
        reader.keys.update(
            {"3": "book_end", "Enter": "next_page", "BSpace": "line_down", "C-j": "previous_page"}
        )
        reader.begin_jump()
        for digits in ("", "0", "9", "9" * 5000):
            reader.jump_digits = ""
            for key in digits:
                reader.input_action(key)
            reader.input_action("Enter")
            self.assertTrue(reader.jump_error)
            self.assertEqual(reader.offset, 0)
        reader.input_action("Escape")
        self.assertIsNone(reader.jump_digits)
        reader.begin_jump()
        reader.input_action("3")
        reader.input_action(key_name("\x08"))
        self.assertEqual(reader.jump_digits, "")
        reader.input_action("3")
        reader.input_action(key_name("\n"))
        self.assertIsNone(reader.jump_digits)
        self.assertEqual(reader.offset, reader.line_starts[2])
        self.assertEqual(read_json(reader.progress)["offset"], reader.offset)
        self.assertEqual(reader.input_action("Enter"), "next_page")
        self.assertEqual(reader.input_action(key_name("\n")), "previous_page")

    def test_empty_book_and_hide_cancel_unconfirmed_input(self):
        reader = self.reader
        reader.runtime = self.root
        reader.begin_jump()
        reader.input_action("4")
        previous = {"view": "reader", "reader_hide_count": 0}
        # A rapid round trip can leave the view unchanged between reader polls.
        write_json(self.root / "state.json", {"view": "reader", "reader_hide_count": 1})
        reader.read_state(previous)
        self.assertIsNone(reader.jump_digits)
        self.assertEqual(reader.offset, 0)
        self.book.write_text("")
        empty = Reader(self.config)
        empty.reflow(8)
        empty.begin_jump()
        self.assertIsNone(empty.jump_digits)
        self.assertEqual(empty.position_label(), "原文行 0 / 0")
        self.assertFalse(empty.jump_to_line(1))


if __name__ == "__main__":
    unittest.main()
