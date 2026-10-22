# Thief Agent

等待 Codex CLI 工作时，在同一个终端里读小说。阅读页复刻 Codex 的输入框、状态栏和留白，任务结束后自动返回真正的 Codex。

## 快速开始

当前机器已具备依赖，可直接运行：

```bash
cd /home/ziyang/thief_agent

# 离线体验：Enter 模拟 6 秒任务，自动进入小说，结束后自动返回
./thief-agent --demo --book examples/sample.txt

# 正常使用，换成你的 TXT 路径
./thief-agent --book /path/to/novel.txt

# 显式指定参数文件
./thief-agent --config config.toml --book /path/to/novel.txt
```

阅读页的输入框用于复刻外观。要输入追加指令，请切回真正的 Codex。小说由阅读器本地读取，不会加入模型上下文。

## 快捷键全部可配置

编辑 [config.toml](config.toml) 的 `[keys]` 段，重新启动后生效。按键直接生效，无需 tmux 前缀。

| 配置项 | 默认按键 | 功能 |
| --- | --- | --- |
| `toggle` | **F8** | Codex ↔ 小说，两页均有效 |
| `auto_read` | **F9** | 开关任务开始后的自动阅读，两页均有效 |
| `next_page` | **PgDn / Space** | 下一页 |
| `previous_page` | **PgUp** | 上一页 |
| `line_down` / `line_up` | **↓ / ↑** | 滚动一行 |
| `book_start` / `book_end` | **Home / End** | 书首 / 书尾 |
| `back` | **Esc / Ctrl+C** | 从小说返回 Codex，不中断任务 |

例如改成 Ctrl+R 切换、Alt+A 开关自动阅读、J/K 翻页：

```toml
[keys]
toggle = ["Ctrl+r"]
auto_read = ["Alt+a"]
next_page = ["j", "PgDn"]
previous_page = ["k", "PgUp"]
```

单个动作可以绑定多个键。未配置的动作使用默认值，`[]` 禁用该动作；`toggle` 至少保留一个键。重复按键会在启动前报错。

支持 `F1`–`F12`、`Ctrl+r` / `C-r`、`Alt+r` / `M-r`、单个 ASCII 字符，以及 `PgUp`、`PgDn`、`Space`、`Escape`、方向键、`Home`、`End`、`Enter`、`Tab`、`BSpace`、`DC`、`IC`。终端自身截获的组合键需要换一个绑定。

只有 `toggle`、`auto_read` 会覆盖真正 Codex 页的按键。其他绑定仅在小说页生效，Codex 页保留自己的编辑、翻页和中断行为。

## 阅读参数

```toml
[reader]
book = "/home/yourname/books/novel.txt"
encoding = "utf-8"
auto_read = true
delay = 1.5
margin = 2
state_dir = ""

[codex]
command = ["codex"]
```

- 参数文件选择顺序：`--config` → `~/.config/thief-agent/config.toml` → 源码目录的 `config.toml` → 内置默认值。用户配置目录遵循 `XDG_CONFIG_HOME`。
- 文件中的相对路径以参数文件所在目录为准；命令行 `--book` 以当前工作目录为准。
- `--book`、`--encoding`、`--no-auto-reader` 覆盖文件中的对应参数。
- 任务开始后默认等待 1.5 秒再切换，快速结束的任务不会闪屏。
- F9 只修改本次运行的自动阅读开关；默认值始终由参数文件决定。
- 阅读进度按 TXT 的绝对路径保存到 `~/.local/state/thief-agent/books/`，遵循 `XDG_STATE_HOME`。也可用 `state_dir` 指定目录。
- 保存的是原文位置，窗口缩放后重新排版；若替换或大幅修改同一路径的文件，旧位置可能不再对应原来的段落。

其他命令：

```bash
./thief-agent --check-config
./thief-agent --reader --book examples/sample.txt
./thief-agent --book /path/to/novel.txt --encoding gb18030
./thief-agent --book /path/to/novel.txt --no-auto-reader

# -- 后的参数交给原版 Codex
./thief-agent --book /path/to/novel.txt -- -C /path/to/project
./thief-agent --book /path/to/novel.txt -- resume --last
```

`--reader` 只打开阅读器，返回键会退出预览；`--demo` 不启动 Codex、不调用模型。在演示页，`/wait` 模拟等待输入，`Ctrl+C` 模拟任务中断，`/exit` 退出。

正常使用时，返回 Codex 并使用它的正常退出流程即可关闭整个工具。终端关闭也会清理本工具启动的进程。本工具使用独立 tmux 服务器，不改变已有 tmux 会话的配置；从 tmux 内启动时，外层 tmux 自己的按键绑定仍有优先权。

## 自动切换与兼容性

两个 tmux 面板分别运行原版 Codex 和阅读器，当前面板全屏放大。使用原版 `codex --remote unix://...` 连接本地桥接器，再由桥接器连接同一个 Codex 程序的 `app-server --listen stdio://`。原有登录、配置、权限和工具处理仍由 Codex 负责。

桥接器观察结构化事件并转发原始协议语义，不修改 `~/.codex/config.toml`、hooks 或 notify：

- 真正的 `turn/started` 触发自动进入。
- `turn/completed` 的完成、失败或中断状态，以及主会话空闲状态，触发返回。
- 待审批、等待用户输入、MCP 表单及带问题的异步消息触发返回。
- 手动返回后，本轮不会再自动切走；下一轮恢复自动阅读规则。
- 其他会话或子 agent 的完成事件不会误切当前页面。
- 阅读器退出后，Codex 仍可继续使用。

已在 Linux、Python 3.10、tmux 3.2a、Codex CLI 0.162.1 上验证原版连接和真实最小任务；其他 Codex 版本的 app-server 协议仍需按版本验证。自动返回按“当前轮次结束”处理，尚未实现跨多轮自动续跑目标的最终完成判定。

当前接入方式由工具管理 `--remote` / `--no-daemon`；请勿再次传入这些选项。Codex 0.162.1 的 app-server 不支持 `--profile`，本版本会提前拒绝该参数，可使用 `-c` 覆盖配置。它使用专用本地后端，不附着到已经运行的共享 daemon。

## 在其他机器安装

需要 Python 3.10+、tmux 和支持上述 remote/app-server 接口的 Codex CLI：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
./thief-agent --demo --book examples/sample.txt
```

Python 依赖为 Tornado、wcwidth，以及 Python 3.10 上的 tomli。源码启动脚本优先使用项目 `.venv`，不存在时使用系统 Python。

## 开发验证

```bash
python3 -m unittest discover -s tests -v
ruff check thief_agent tests
```

自动检查覆盖快捷键冲突、路径解析、中文换行、过期事件过滤、手动切回和等待输入等关键边界。实际 tmux 联调还验证了 F8/F9、Ctrl+R/Alt+A/J 自定义绑定、输入草稿保留、缩放后的阅读位置，以及阅读器异常后的回退。

仅在后端产生诊断输出时，退出后会提示本地日志路径；不记录完整对话协议。实现说明见 [DESIGN.md](DESIGN.md)。
