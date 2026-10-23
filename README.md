# Thief Agent

等待 Codex CLI 工作时，在同一个终端里读小说。阅读页复刻 Codex 的输入框、状态栏和留白，任务结束后自动返回真正的 Codex。

## 安装（Ubuntu / macOS）

发布产物为 `thief_agent-0.1.1-py3-none-any.whl`，同一个 wheel 可安装在 Ubuntu 和 macOS 上，无需克隆源码。需要 **Python 3.10+、tmux 3.2+ 和已安装的 Codex CLI**。正常使用前，请先确认 `codex` 能在当前终端启动并完成登录；已验证的 Codex 版本与平台见下文“自动切换与兼容性”。

### 1. 安装系统依赖

Ubuntu 22.04 及更新版本：

```bash
sudo apt update
sudo apt install python3 python3-venv tmux
```

macOS（已安装 [Homebrew](https://brew.sh/)）：

```bash
brew install python tmux
```

两种系统均可用以下命令检查：

```bash
python3 --version
tmux -V
codex --version
```

### 2. 下载并通过 pip 安装 wheel

从 [GitHub Releases](https://github.com/pishiwan/thief_codex_cli/releases) 的 Assets 下载 `.whl` 文件。在下载目录执行下列命令；使用虚拟环境可避免 Ubuntu / Homebrew Python 的 `externally-managed-environment` 限制：

```bash
python3 -m venv ~/.venvs/thief-agent
source ~/.venvs/thief-agent/bin/activate
python -m pip install ./thief_agent-0.1.1-py3-none-any.whl
thief-agent --version
```

如果已经使用 Python 3.10+ 的虚拟环境，直接执行 `python -m pip install ./thief_agent-0.1.1-py3-none-any.whl` 即可。安装其他版本时，将文件名替换为下载的实际名称。

pip 会联网安装 Tornado、wcwidth，以及 Python 3.10 所需的 tomli。wheel 不包含 Python、tmux 或 Codex，因此单独下载 wheel 不等于完整的离线安装包。本项目目前通过 GitHub Release 分发，尚未发布到 PyPI。

新开终端后，先执行 `source ~/.venvs/thief-agent/bin/activate`，或直接使用完整路径：

```bash
~/.venvs/thief-agent/bin/thief-agent --book ~/books/novel.txt
```

也可以用已安装的 pipx 安装下载的 wheel，让命令在所有终端可用：

```bash
pipx install ./thief_agent-0.1.1-py3-none-any.whl
pipx ensurepath
# 重新打开终端后使用 thief-agent
```

## 快速开始

将下面的路径替换成自己的 TXT 文件：

```bash
# 正常使用：在需要 Codex 工作的项目目录中运行
thief-agent --book ~/books/novel.txt

# 离线体验：Enter 模拟 6 秒任务，自动进入小说，结束后自动返回
thief-agent --demo --book ~/books/novel.txt

# 只预览阅读器，不启动 Codex 或 tmux
thief-agent --reader --book ~/books/novel.txt

# 显式指定参数文件
thief-agent --config /path/to/config.toml --book ~/books/novel.txt
```

正常启动后，像平时一样给 Codex 输入任务。任务开始后自动进入阅读页，按 **F8** 随时切回，任务完成或需要审批、输入时自动返回 Codex。按 **PgDn / Space** 翻页，按 **Ctrl+G** 输入原文行号跳转；阅读进度自动保存。

阅读页的输入框支持输入跳转行号。要输入追加指令，请切回真正的 Codex。小说由阅读器本地读取，不会加入模型上下文。

### 首次启动自动创建配置

安装 wheel 后，首次运行 `thief-agent` 会自动创建 `~/.config/thief-agent/config.toml`，并在终端显示文件位置。文件包含完整中文注释、小说路径、编码、自动阅读参数、Codex 命令和全部快捷键，无需手动创建目录或配置文件。

首次启动时可以直接指定小说：

```bash
thief-agent --book ~/books/novel.txt
```

创建配置时会将这次传入的小说绝对路径写入 `reader.book`，同时保存显式传入的 `--encoding`、`--no-auto-reader`。以后直接执行 `thief-agent` 即可继续阅读。

如果首次启动没有传入 `--book`，程序会先生成完整配置，再提示设置 `reader.book`。打开生成的文件，将该项改为自己的 TXT 路径即可，例如：

```toml
[reader]
book = "~/books/novel.txt"
```

已有配置不会被覆盖或自动改写；后续启动的命令行参数只对本次运行生效。可直接修改文件里的 `[keys]` 等配置，重新启动后生效。

设置了 `XDG_CONFIG_HOME` 时，文件创建在 `$XDG_CONFIG_HOME/thief-agent/config.toml`。显式指定 `--config`，或从源码运行且已有源码配置时，继续使用对应文件，不额外创建用户配置。`--help`、`--version`、`--check-config` 不创建文件；`--check-config` 可检查当前有效配置。

## 快捷键全部可配置

编辑用户配置文件的 `[keys]` 段，重新启动后生效。完整示例见 [config.toml](https://github.com/pishiwan/thief_codex_cli/blob/main/config.toml)。按键直接生效，无需 tmux 前缀。

| 配置项 | 默认按键 | 功能 |
| --- | --- | --- |
| `toggle` | **F8** | Codex ↔ 小说，两页均有效 |
| `auto_read` | **F9** | 开关任务开始后的自动阅读，两页均有效 |
| `next_page` | **PgDn / Space** | 下一页 |
| `previous_page` | **PgUp** | 上一页 |
| `line_down` / `line_up` | **↓ / ↑** | 滚动一行 |
| `book_start` / `book_end` | **Home / End** | 书首 / 书尾 |
| `goto_line` | **Ctrl+G** | 输入原文行号并跳转 |
| `back` | **Esc / Ctrl+C** | 从小说返回 Codex，不中断任务 |

例如改成 Ctrl+R 切换、Alt+A 开关自动阅读、J/K 翻页：

```toml
[keys]
toggle = ["Ctrl+r"]
auto_read = ["Alt+a"]
next_page = ["j", "PgDn"]
previous_page = ["k", "PgUp"]
goto_line = ["Ctrl+g"]
```

单个动作可以绑定多个键。未配置的动作使用默认值，`[]` 禁用该动作；`toggle` 至少保留一个键。重复按键会在启动前报错。

支持 `F1`–`F12`、`Ctrl+r` / `C-r`、`Alt+r` / `M-r`、单个 ASCII 字符，以及 `PgUp`、`PgDn`、`Space`、`Escape`、方向键、`Home`、`End`、`Enter`、`Tab`、`BSpace`、`DC`、`IC`。终端自身截获的组合键需要换一个绑定。

只有 `toggle`、`auto_read` 会覆盖真正 Codex 页的按键。其他绑定仅在小说页生效，Codex 页保留自己的编辑、翻页和中断行为。

macOS 的 F8/F9 可能被系统用作媒体键，可尝试 **Fn+F8 / Fn+F9**，或按上面的示例改为 Ctrl+R / Alt+A；如果终端没有把 Option 作为 Alt 发送，可选择其他组合键。没有 PgUp/PgDn 的键盘可使用 Space、方向键，或自定义 J/K。

## 按原文行号快速跳转

左下角显示 `原文行 123 / 8240`，表示正文顶部所在的原文行和总行数。行号从 1 开始，按 TXT 中的实际换行计算，空行也算；文件末尾的换行符不额外增加一行。Windows / Unix 换行及单独的 CR 按相同规则处理，空文件显示 `原文行 0 / 0`。

在阅读页按 **Ctrl+G**，输入行号后按 **Enter**，目标行会出现在正文顶部，并立即保存进度；接近书尾时允许下方留白。**Backspace** 修改数字，**Esc** 取消并留在阅读页，**F8** 取消并返回 Codex。空输入、0 或超过总行数时提示错误，不改变位置；空文件不能跳转。

长段落会折成多个屏幕行，例如 `原文行 123 / 8240 · 本行第 3 / 8 屏幕行`。改变终端宽度会重新折行，但原文行号和总行数不变，当前原文位置和正在输入的数字都会保留。如果 TXT 只有很少的实际换行，行号定位会较粗，可配合翻页键阅读。

跳转输入期间，数字、退格、Enter 和 Esc 优先处理输入，即使这些键已配置为阅读动作；两页通用的切换和自动阅读键仍然有效。任务完成或等待输入而自动返回 Codex 时，未确认的跳转会取消，再次打开小说不会执行旧输入。

## 阅读参数

```toml
[reader]
book = "~/books/novel.txt"
encoding = "utf-8"
auto_read = true
delay = 1.5
margin = 2
state_dir = ""

[codex]
command = ["codex"]
```

- 参数文件选择顺序：`--config` → `~/.config/thief-agent/config.toml` → 源码目录的 `config.toml`（从源码运行时）→ 内置默认值。用户配置目录遵循 `XDG_CONFIG_HOME`。
- 未指定 `--config` 且没有现有配置时，正常启动会先把完整默认配置写入用户配置目录，再读取该文件。
- 文件中的相对路径以参数文件所在目录为准；命令行 `--book` 以当前工作目录为准。
- `--book`、`--encoding`、`--no-auto-reader` 覆盖文件中的对应参数；仅首次自动创建配置时会保存这些参数，已有文件不改写。
- 任务开始后默认等待 1.5 秒再切换，快速结束的任务不会闪屏。
- F9 只修改本次运行的自动阅读开关；默认值始终由参数文件决定。
- 阅读进度按 TXT 的绝对路径保存到 `~/.local/state/thief-agent/books/`，遵循 `XDG_STATE_HOME`。也可用 `state_dir` 指定目录。
- 保存的是原文位置，窗口缩放后重新排版；若替换或大幅修改同一路径的文件，旧位置可能不再对应原来的段落。

其他命令：

```bash
thief-agent --help
thief-agent --version
thief-agent --check-config
thief-agent --book ~/books/novel.txt --encoding gb18030
thief-agent --book ~/books/novel.txt --no-auto-reader

# -- 后的参数交给原版 Codex
thief-agent --book ~/books/novel.txt -- -C /path/to/project
thief-agent --book ~/books/novel.txt -- resume --last
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

已在 Linux、Python 3.10、tmux 3.2a、Codex CLI 0.162.1 上验证原版连接和真实最小任务。发布工作流会在 Ubuntu 和 macOS 上验证 wheel 安装与模块导入；macOS 的真实 Codex 交互仍需实机验证。其他 Codex 版本的 app-server 协议仍需按版本验证。自动返回按“当前轮次结束”处理，尚未实现跨多轮自动续跑目标的最终完成判定。

当前接入方式由工具管理 `--remote` / `--no-daemon`；请勿再次传入这些选项。Codex 0.162.1 的 app-server 不支持 `--profile`，本版本会提前拒绝该参数，可使用 `-c` 覆盖配置。它使用专用本地后端，不附着到已经运行的共享 daemon。

## 升级与卸载

下载新版本 wheel 后，在原来的虚拟环境中安装：

```bash
source ~/.venvs/thief-agent/bin/activate
python -m pip install --upgrade /path/to/thief_agent-VERSION-py3-none-any.whl
thief-agent --version

# 卸载程序
python -m pip uninstall thief-agent
```

上面的新版本路径是占位示例，请替换为实际文件路径。使用 pipx 安装的用户，可用 `pipx install --force /path/to/新版本.whl` 更新，用 `pipx uninstall thief-agent` 卸载。升级或卸载程序不会删除用户配置、小说文件或阅读进度。

## 从源码开发

```bash
git clone https://github.com/pishiwan/thief_codex_cli.git
cd thief_codex_cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
./thief-agent --demo --book examples/sample.txt
```

源码启动脚本优先使用项目 `.venv`，不存在时使用系统 Python。构建 wheel 和发布 GitHub Release 的步骤见 [RELEASING.md](https://github.com/pishiwan/thief_codex_cli/blob/main/RELEASING.md)。

## 开发验证

```bash
python3 -m unittest discover -s tests -v
ruff check thief_agent tests
```

自动检查覆盖快捷键冲突、路径解析、中文换行、原文行号和跳转、过期事件过滤、手动切回和等待输入等关键边界。实际 tmux 联调还验证了 F8/F9、Ctrl+R/Alt+A/J 自定义绑定、输入草稿保留、缩放后的阅读位置，以及阅读器异常后的回退。

仅在后端产生诊断输出时，退出后会提示本地日志路径；不记录完整对话协议。实现说明见 [DESIGN.md](https://github.com/pishiwan/thief_codex_cli/blob/main/DESIGN.md)。
