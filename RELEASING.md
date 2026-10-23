# 构建和发布

项目通过 GitHub Release 分发 wheel，不需要 PyPI 账号。版本号维护在 `thief_agent/__init__.py`，包元数据和 `thief-agent --version` 共用该版本。

## 本地构建

在源码目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install build twine
python -m build
python -m twine check dist/*
```

0.1.3 版本的产物：

- `dist/thief_agent-0.1.3-py3-none-any.whl`：用户下载后通过 pip 安装；Ubuntu 与 macOS 共用。
- `dist/thief_agent-0.1.3.tar.gz`：源码分发包。

wheel 包含本项目的 Python 代码和带完整注释的默认配置模板；安装时 pip 解析并安装依赖。Python、tmux、Codex CLI 仍由用户安装。

## GitHub 自动发布

工作流位于 `.github/workflows/release.yml`：

1. 推送 `main`、提交 PR 或手动触发时，构建并检查 wheel / sdist。
2. 在 Ubuntu 22.04、macOS 14 上分别用 Python 3.10 / 3.13 安装同一份 wheel；不检出源码，检查命令入口、首次配置创建、已有配置保留和运行模块导入。
3. 检查通过后，可在 Actions 中下载 `python-distributions` 产物。
4. 推送与包版本一致的 `v*` tag 时，检查通过后自动创建 GitHub Release，上传 wheel、sdist 和 `SHA256SUMS`。

发布 0.1.3：

```bash
git tag v0.1.3
git push origin v0.1.3
```

发布前应先提交并推送版本对应的代码。后续版本需更新 `thief_agent/__init__.py` 和 README 中的下载文件名，再创建新 tag。不要移动已发布的版本 tag。

工作流使用 GitHub 自带的 `GITHUB_TOKEN`，无需新增发布密钥；仓库需启用 Actions，并允许发布 job 使用 `contents: write`。若发布 job 因仓库策略失败，可从 Actions 下载产物，手动上传到相同 tag 的 Release。

安装检查不会调用模型，也不代表完成了真实终端与 Codex 的端到端验证。涉及阅读界面、快捷键或 app-server 协议的变更，仍需在目标系统上验证实际交互。
