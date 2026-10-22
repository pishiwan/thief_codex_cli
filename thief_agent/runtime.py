"""Own the two tmux panes, key bindings, and local Codex event connection."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tornado.httpserver import HTTPServer
from tornado.netutil import bind_unix_socket
from tornado.web import Application

from .bridge import CodexBridge, stop_process
from .io import send_action, write_json
from .state import SessionState


def backend_options(arguments: list[str]) -> list[str]:
    """Agent-wide overrides must reach the backend as well as the original TUI."""
    result, index = [], 0
    valued = {"-c", "--config", "--enable", "--disable"}
    while index < len(arguments):
        arg = arguments[index]
        if (
            arg in {"-p", "--profile"}
            or arg.startswith("--profile=")
            or (arg.startswith("-p") and not arg.startswith("--"))
        ):
            raise ValueError("此版本的 app-server 不支持 --profile；请使用 -c 覆盖配置")
        if arg.split("=", 1)[0] in {"--remote", "--remote-auth-token-env", "--no-daemon"}:
            raise ValueError(f"{arg} 由 thief-agent 管理，不能再次指定")
        if arg in valued:
            if index + 1 >= len(arguments):
                raise ValueError(f"{arg} 缺少参数")
            result.extend(arguments[index : index + 2])
            index += 2
            continue
        if (
            arg == "--strict-config"
            or any(arg.startswith(flag + "=") for flag in valued if flag.startswith("--"))
            or arg.startswith("-c")
            and arg != "-c"
        ):
            result.append(arg)
        index += 1
    return result


class ControlProtocol(asyncio.DatagramProtocol):
    def __init__(self, runtime):
        self.runtime = runtime

    def datagram_received(self, data, address):
        try:
            self.runtime.action(json.loads(data)["action"])
        except (ValueError, KeyError, TypeError):
            pass


class Runtime:
    def __init__(self, config: dict, codex_args: list[str], *, demo=False, headless=False):
        self.config, self.demo, self.headless = config, demo, headless
        self.cwd = str(Path.cwd())
        # -C changes both the UI and backend's initial workspace.
        for index, arg in enumerate(codex_args):
            if arg in {"-C", "--cd"} and index + 1 < len(codex_args):
                self.cwd = str(Path(codex_args[index + 1]).expanduser().resolve())
            elif arg.startswith("--cd="):
                self.cwd = str(Path(arg.split("=", 1)[1]).expanduser().resolve())
        self.server_command = [
            *config["codex"]["command"],
            *backend_options(codex_args),
            "app-server",
            "--listen",
            "stdio://",
        ]
        self.codex_args = codex_args
        self.state = SessionState(
            auto_read=config["reader"]["auto_read"], delay=config["reader"]["delay"], cwd=self.cwd
        )
        self.directory = Path(tempfile.mkdtemp(prefix="thief-"))
        self.env = os.environ.copy()
        self.env.pop("TMUX", None)
        source = str(Path(__file__).resolve().parent.parent)
        self.env["PYTHONPATH"] = source + os.pathsep + self.env.get("PYTHONPATH", "")
        self.tmux_prefix = ["tmux", "-S", str(self.directory / "tmux.sock"), "-f", "/dev/null"]
        self.log = None
        self.bridge = None
        self.http = None
        self.transport = None
        self.attach = None
        self.stopping = False
        self.reader_alive = True
        self.panes = {}
        self.demo_tasks = set()
        self.demo_counter = 0

    def tmux(self, *args: str, check=True) -> str:
        result = subprocess.run(
            [*self.tmux_prefix, *args],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or "tmux command failed")
        return result.stdout.strip()

    def internal_command(self, *arguments):
        return shlex.join([sys.executable, "-m", "thief_agent", *map(str, arguments)])

    async def setup(self):
        self.log = (self.directory / "backend.log").open("ab", buffering=0)
        write_json(self.directory / "config.json", self.config)
        write_json(self.directory / "state.json", self.state.snapshot())
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: ControlProtocol(self),
            local_addr=str(self.directory / "control.sock"),
            family=socket.AF_UNIX,
        )
        if not self.demo:
            self.http = HTTPServer(
                Application(
                    [(r"/.*", CodexBridge, {"runtime": self})],
                    websocket_max_message_size=64 * 1024 * 1024,
                )
            )
            self.http.add_socket(bind_unix_socket(str(self.directory / "codex.sock"), mode=0o600))
        width, height = shutil.get_terminal_size((100, 32))
        self.panes["codex"] = self.tmux(
            "new-session",
            "-d",
            "-s",
            "work",
            "-x",
            str(max(40, width)),
            "-y",
            str(max(16, height)),
            "-P",
            "-F",
            "#{pane_id}",
            "sleep 86400",
        )
        self.tmux("set-option", "status", "off")
        self.tmux("set-option", "prefix", "None")
        self.tmux("set-option", "escape-time", "25")
        self.tmux("set-option", "mouse", "off")
        self.tmux("set-option", "-w", "remain-on-exit", "on")
        self.tmux("set-option", "-w", "automatic-rename", "off")
        self.tmux("unbind-key", "-a")
        self.panes["reader"] = self.tmux(
            "split-window", "-d", "-t", self.panes["codex"], "-P", "-F", "#{pane_id}", "sleep 86400"
        )
        self.tmux("select-pane", "-t", self.panes["codex"])
        self.tmux("resize-pane", "-Z", "-t", self.panes["codex"])
        for action, keys in self.config["keys"].items():
            # Reader keys go straight to curses so modal input can take precedence.
            if action not in {"toggle", "auto_read"}:
                continue
            command = self.internal_command("_action", self.directory, action)
            for key in keys:
                self.tmux("bind-key", "-n", key, "run-shell", "-b", command)
        if self.demo:
            codex = self.internal_command("_demo", self.directory)
        else:
            codex = shlex.join(
                [
                    *self.config["codex"]["command"],
                    "--remote",
                    "unix://" + str(self.directory / "codex.sock"),
                    *self.codex_args,
                ]
            )
        reader = self.internal_command("_reader", self.directory)
        self.tmux("respawn-pane", "-k", "-t", self.panes["reader"], reader)
        self.tmux("respawn-pane", "-k", "-t", self.panes["codex"], codex)
        if self.headless:
            print(json.dumps({"runtime": str(self.directory), "panes": self.panes}), flush=True)
        else:
            self.attach = await asyncio.create_subprocess_exec(
                *self.tmux_prefix, "attach-session", "-t", "work", env=self.env
            )

    def action(self, action: str):
        if action in {"toggle", "back", "auto_read"}:
            self.state.action(action)
            if not self.reader_alive:
                self.state.view = "codex"
        elif action == "demo_start" and self.demo:
            if self.state.status == "running":
                return
            self.demo_counter += 1
            turn_id = str(self.demo_counter)
            self.state.thread_id = "demo"
            self.state.start_turn(turn_id)
            task = asyncio.create_task(self.finish_demo(turn_id))
            self.demo_tasks.add(task)
            task.add_done_callback(self.demo_tasks.discard)
        elif action in {"demo_interrupt", "demo_wait"} and self.demo:
            self.state.attention("interrupted" if action == "demo_interrupt" else "waiting")
        elif action in self.config["keys"]:
            try:
                send_action(self.directory / "reader.sock", action)
            except OSError:
                pass

    async def finish_demo(self, turn_id):
        await asyncio.sleep(6)
        if self.state.turn_id == turn_id and self.state.status == "running":
            self.state.attention("completed")

    async def run(self):
        code, previous, last_check = 0, None, 0.0
        reader_hide_count = 0
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(sig, lambda: setattr(self, "stopping", True))
        try:
            await self.setup()
            while not self.stopping:
                self.state.tick()
                if not self.reader_alive:
                    self.state.view, self.state.deadline = "codex", None
                snapshot = self.state.snapshot()
                if previous and previous["view"] == "reader" and snapshot["view"] != "reader":
                    reader_hide_count += 1
                # A counter preserves hide events even if the reader misses a quick toggle.
                snapshot["reader_hide_count"] = reader_hide_count
                if snapshot != previous:
                    write_json(self.directory / "state.json", snapshot)
                    if previous and snapshot["view"] != previous["view"]:
                        self.tmux("select-pane", "-Z", "-t", self.panes[snapshot["view"]])
                    previous = snapshot
                if time.monotonic() - last_check > 0.5:
                    last_check = time.monotonic()
                    panes = self.tmux(
                        "list-panes",
                        "-t",
                        "work",
                        "-F",
                        "#{pane_id} #{pane_dead} #{pane_dead_status}",
                    )
                    for line in panes.splitlines():
                        values = line.split()
                        if len(values) >= 2 and values[1] == "1":
                            if values[0] == self.panes["codex"]:
                                self.stopping = True
                                code = int(values[2]) if len(values) > 2 else 1
                            elif self.reader_alive:
                                self.reader_alive = False
                                self.state.action("back")
                                self.tmux("display-message", "阅读器已退出，Codex 仍在运行")
                    if self.attach and self.attach.returncode is not None:
                        self.stopping = True
                await asyncio.sleep(0.05)
        finally:
            await self.cleanup()
        return code

    async def cleanup(self):
        for task in self.demo_tasks:
            task.cancel()
        if self.bridge:
            bridge = self.bridge
            bridge.close()
            await stop_process(bridge.process)
        if self.http:
            self.http.stop()
            await self.http.close_all_connections()
        if self.transport:
            self.transport.close()
        try:
            send_action(self.directory / "reader.sock", "save")
            await asyncio.sleep(0.2)
        except OSError:
            pass
        self.tmux("kill-server", check=False)
        if self.attach:
            await self.attach.wait()
        if self.log:
            self.log.close()
        # Keep a single diagnostic file per launch; never store the RPC stream.
        log_path = self.directory / "backend.log"
        if log_path.exists() and log_path.stat().st_size:
            dest = (
                Path(self.config["reader"]["state_dir"]) / "logs" / (self.directory.name + ".log")
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(log_path, dest)
            os.chmod(dest, 0o600)
            print(f"Codex 后端日志：{dest}", file=sys.stderr)
        shutil.rmtree(self.directory, ignore_errors=True)
