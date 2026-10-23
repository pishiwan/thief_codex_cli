"""Configuration and a single key vocabulary shared by tmux and the reader."""

from __future__ import annotations

import copy
import json
import math
import os
import re
from importlib.resources import files
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib


DEFAULT_TEMPLATE = files(__package__).joinpath("default_config.toml").read_text(encoding="utf-8")
DEFAULTS = tomllib.loads(DEFAULT_TEMPLATE)


def normalize_key(key: str) -> str:
    aliases = {
        "PgDn": "NPage",
        "PageDown": "NPage",
        "PgUp": "PPage",
        "PageUp": "PPage",
        "Esc": "Escape",
        "Enter": "Enter",
        "Return": "Enter",
    }
    key = key.replace("Ctrl+", "C-").replace("Alt+", "M-")
    key = aliases.get(key, key)
    if key in {"C-i", "C-m", "C-[", "C-h"}:
        key = {"C-i": "Tab", "C-m": "Enter", "C-[": "Escape", "C-h": "BSpace"}[key]
    if (
        key
        in {
            "NPage",
            "PPage",
            "Space",
            "Escape",
            "Up",
            "Down",
            "Left",
            "Right",
            "Home",
            "End",
            "Enter",
            "Tab",
            "BSpace",
            "DC",
            "IC",
        }
        or re.fullmatch(r"F(?:[1-9]|1[0-2])", key)
        or re.fullmatch(r"[CM]-[a-z]", key)
        or (len(key) == 1 and key.isascii() and key.isprintable() and not key.isspace())
    ):
        return key
    raise ValueError(f"不支持的快捷键 {key!r}，请用 F8、Ctrl+r、Alt+r、PgDn 等写法")


def load_config(path: Path | None) -> dict:
    result = copy.deepcopy(DEFAULTS)
    if path:
        path = path.expanduser().resolve()
        with path.open("rb") as handle:
            custom = tomllib.load(handle)
        for section, values in custom.items():
            if section not in result or not isinstance(values, dict):
                raise ValueError(f"未知配置段或格式错误：{section}")
            for name, value in values.items():
                if name not in result[section]:
                    raise ValueError(f"未知配置项：{section}.{name}")
                result[section][name] = value
    reader = result["reader"]
    for field in ("book", "encoding", "state_dir"):
        if not isinstance(reader[field], str):
            raise TypeError(f"reader.{field} 必须为字符串")
    if not isinstance(reader["auto_read"], bool):
        raise TypeError("reader.auto_read 必须为 true 或 false")
    delay = reader["delay"]
    if type(delay) not in (int, float) or not math.isfinite(delay) or not 0 <= delay <= 60:
        raise ValueError("reader.delay 必须为 0 到 60 秒之间的数值")
    if type(reader["margin"]) is not int or not 0 <= reader["margin"] <= 20:
        raise ValueError("reader.margin 必须为 0 到 20 的整数")
    command = result["codex"]["command"]
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(s, str) or not s for s in command)
    ):
        raise ValueError('codex.command 必须为非空字符串数组，例如 ["codex"]')
    seen = {}
    for action, keys in result["keys"].items():
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise ValueError(f"keys.{action} 必须为字符串数组")
        normalized = []
        for key in keys:
            key = normalize_key(key)
            if key in seen:
                raise ValueError(f"快捷键 {key} 重复：{seen[key]} 与 {action}")
            seen[key] = action
            normalized.append(key)
        result["keys"][action] = normalized
    if not result["keys"]["toggle"]:
        raise ValueError("keys.toggle 至少需要一个按键，确保可以随时返回 Codex")
    base = path.parent if path else Path.cwd()
    for field in ("book", "state_dir"):
        if reader[field]:
            value = Path(reader[field]).expanduser()
            reader[field] = str((base / value).resolve())
    if not reader["state_dir"]:
        reader["state_dir"] = str(
            Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser() / "thief-agent"
        )
    return result


def user_config_path() -> Path:
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
        / "thief-agent/config.toml"
    )


def create_user_config(path: Path, reader_overrides: dict) -> bool:
    """Write the commented defaults once; never overwrite an existing configuration."""
    content = DEFAULT_TEMPLATE
    for name, value in reader_overrides.items():
        # JSON strings/booleans are valid TOML values; TOML also requires DEL to be escaped.
        encoded = json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
        content = re.sub(
            rf"^{name} = .*?$",
            lambda _, replacement=f"{name} = {encoded}": replacement,
            content,
            count=1,
            flags=re.MULTILINE,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError:
        return False
    return True


def default_config_path() -> Path | None:
    user = user_config_path()
    source = Path(__file__).resolve().parent.parent / "config.toml"
    return next((path for path in (user, source) if path.is_file()), None)


def label(keys: list[str]) -> str:
    aliases = {"NPage": "PgDn", "PPage": "PgUp", "Escape": "Esc"}
    return (
        "/".join(aliases.get(key, key).replace("C-", "Ctrl+").replace("M-", "Alt+") for key in keys)
        or "未绑定"
    )
