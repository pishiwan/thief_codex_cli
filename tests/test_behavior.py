"""Focused regression checks for routing and terminal layout boundaries."""

import tempfile
import unittest
from pathlib import Path

from wcwidth import wcswidth

from thief_agent.config import load_config
from thief_agent.reader import wrap_text
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
    def test_chinese_combining_marks_and_source_offsets(self):
        text = "雨后的车站 cafe\u0301\n第二行文字\n\n最后一行"
        for width in (4, 7, 15):
            offsets, lines = wrap_text(text, width)
            self.assertTrue(all(wcswidth(line) <= width for line in lines))
            self.assertEqual("".join(lines), text.replace("\n", ""))
            for offset, line in zip(offsets, lines):
                self.assertTrue(text[offset:].startswith(line))


if __name__ == "__main__":
    unittest.main()
