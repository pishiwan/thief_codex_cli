"""User entry point and small internal subprocess commands."""

from __future__ import annotations

import argparse
import asyncio
import codecs
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import create_user_config, default_config_path, load_config, user_config_path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("_"):
        return internal(argv)
    codex_args = []
    if "--" in argv:
        separator = argv.index("--")
        argv, codex_args = argv[:separator], argv[separator + 1 :]
    parser = argparse.ArgumentParser(description="等待 Codex 工作时，在仿 Codex 界面阅读本地 TXT")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, help="TOML 参数文件（快捷键、阅读设置）")
    parser.add_argument("--book", type=Path, help="本地 TXT 文件")
    parser.add_argument("--encoding", help="TXT 编码，例如 utf-8 或 gb18030")
    parser.add_argument("--no-auto-reader", action="store_true", help="只手动进入阅读页")
    parser.add_argument("--reader", action="store_true", help="单独预览阅读器，不启动 Codex / tmux")
    parser.add_argument("--demo", action="store_true", help="离线体验自动切换，不调用 Codex")
    parser.add_argument(
        "--check-config", action="store_true", help="校验并显示有效配置，不启动程序"
    )
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        reader_overrides = {}
        if args.book:
            reader_overrides["book"] = str(args.book.expanduser().resolve())
        if args.encoding:
            reader_overrides["encoding"] = args.encoding
        if args.no_auto_reader:
            reader_overrides["auto_read"] = False
        config_path = args.config or default_config_path()
        if config_path is None and not args.check_config:
            config_path = user_config_path()
            if create_user_config(config_path, reader_overrides):
                print(f"已创建配置文件：{config_path}", file=sys.stderr)
        config = load_config(config_path)
        config["reader"].update(reader_overrides)
        codecs.lookup(config["reader"]["encoding"])
        if args.check_config:
            print(json.dumps(config, indent=2, ensure_ascii=False))
            return 0
        if not config["reader"]["book"]:
            raise ValueError(f"请在 {config_path} 中设置 reader.book，或用 --book 指定 TXT")
        book = Path(config["reader"]["book"])
        if not book.is_file():
            raise ValueError(f"TXT 文件不存在：{book}")
        # Fail before starting Codex, rather than discover an encoding error later.
        book.read_text(encoding=config["reader"]["encoding"])
        Path(config["reader"]["state_dir"]).mkdir(parents=True, exist_ok=True)
        if not args.headless and (not sys.stdin.isatty() or not sys.stdout.isatty()):
            raise ValueError("请在交互式终端中运行；--check-config 可在非交互环境使用")
        if args.reader:
            from .reader import Reader

            Reader(config).run()
            return 0
        if not shutil.which("tmux"):
            raise ValueError("找不到 tmux，请先安装 tmux")
        if not args.demo and not shutil.which(config["codex"]["command"][0]):
            raise ValueError("找不到 Codex，请检查 codex.command")
        from .runtime import Runtime

        return asyncio.run(
            Runtime(config, codex_args, demo=args.demo, headless=args.headless).run()
        )
    except (OSError, ValueError, TypeError, LookupError, RuntimeError) as error:
        print(f"thief-agent: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def internal(argv):
    from .io import read_json, send_action

    command, runtime = argv[0], Path(argv[1])
    if command == "_action":
        try:
            send_action(runtime / "control.sock", argv[2])
        except OSError:
            return 1
    elif command == "_reader":
        from .reader import Reader

        Reader(read_json(runtime / "config.json"), runtime).run()
    elif command == "_demo":
        from .demo import run_demo

        run_demo(runtime)
    else:
        raise ValueError(f"Unknown internal command: {command}")
    return 0
