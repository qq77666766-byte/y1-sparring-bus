# Install / 安装

Y1 Sparring Bus is a local macOS tool. It uses Python stdlib plus your local Claude and Codex CLI login state.

Y1 Sparring Bus 是一个本机 macOS 工具，只依赖 Python 标准库，以及你本机已经登录的 Claude / Codex CLI。

## What Installs What? / 到底安装什么

This repository installs only the local Python web backend, scripts, examples, and docs. It does not install or log in to Claude or Codex for you.

这个仓库只安装本机 Python 网页后端、脚本、演示案例和文档。它不会替你安装或登录 Claude / Codex。

Capability levels:

能力档位：

- Python only: local UI, docs, examples, backend smoke test.  
  只有 Python：可启动本机页面、看文档、跑演示后端烟测。
- Python + manual LLM access: manual Builder/Reviewer handoff.  
  Python + 手动可用 LLM：可复制 prompt 手动接力。
- Python + Claude Code CLI + Codex CLI login: full automatic sparring.  
  Python + Claude Code CLI + Codex CLI 登录：完整自动互搏。

See [docs/RUN_MODES.md](docs/RUN_MODES.md).

详见 [docs/RUN_MODES.md](docs/RUN_MODES.md)。

## 0. One-Step Local Setup / 一步本机准备

From this repository / 在仓库根目录：

```bash
bash scripts/install.sh
```

This creates `jobs/`, checks Python, fixes script permissions when possible, and prints the next steps.

它会创建 `jobs/`，检查 Python，尽量修复脚本执行权限，并打印下一步。

## 1. Python / Python 环境

```bash
python3 --version
```

Required: Python 3.9+.  
要求：Python 3.9 或以上。

## 2. Claude Code CLI / 安装 Claude Code CLI

Install and log in through the official Claude Code flow.

通过 Claude Code 官方流程安装并登录。

Verify / 验证：

```bash
claude --version
claude
```

The tool does not need an Anthropic API key.  
本工具不需要 Anthropic API key。

## 3. Codex App CLI / 安装 Codex App CLI

Install Codex for macOS and log in.

安装 macOS 版 Codex 并完成登录。

Verify / 验证：

```bash
/Applications/Codex.app/Contents/Resources/codex --version
/Applications/Codex.app/Contents/Resources/codex login
test -f ~/.codex/auth.json && echo "Codex auth found"
```

If `codex` is on your `PATH`, the scripts will use it. Otherwise they fall back to the app bundle path above.

如果 `codex` 已在 `PATH` 中，脚本会直接使用；否则会回退到上面的 App bundle 路径。

## 4. Start / 启动

From this repository / 在仓库根目录运行：

```bash
bash scripts/doctor.sh
bash scripts/start.sh
```

Choose a specific workspace / 指定可选择文件的工作区：

```bash
bash scripts/start.sh 8765 ~/Documents
```

Open / 打开：

```text
http://127.0.0.1:8765/sparring
```

## 5. Verify / 验证

Backend smoke test without Claude/Codex:

不依赖 Claude/Codex 的后端烟测：

```bash
bash scripts/smoke-test.sh
```

Full automatic readiness:

完整自动互搏体检：

```bash
bash scripts/doctor.sh --strict
```

Status:

状态：

```bash
bash scripts/status.sh
```

## 6. Optional Background Service / 可选后台服务

Normal `start.sh` already starts a local background process. If you want the backend to start after macOS login, install the optional LaunchAgent:

普通 `start.sh` 已经会启动一个本机后台进程。如果你希望 macOS 登录后自动启动后端，可以安装可选 LaunchAgent：

```bash
bash scripts/install-service.sh 8765 ~/Documents
```

Uninstall:

卸载：

```bash
bash scripts/uninstall-service.sh
```

Details: [docs/BACKGROUND_SERVICE.md](docs/BACKGROUND_SERVICE.md)

详情：[docs/BACKGROUND_SERVICE.md](docs/BACKGROUND_SERVICE.md)

## 7. Stop / 停止

```bash
bash scripts/stop.sh
```

## Uninstall / 卸载

Stop the server, uninstall the optional LaunchAgent if installed, and delete the folder. Jobs are stored inside `jobs/`, so back that up first if you want the history.

停止服务、卸载可选 LaunchAgent 后删除整个目录即可。历史任务在 `jobs/` 里，如果要保留，请先备份。

## Common Issues / 常见问题

| Issue | Fix | 问题 | 处理方式 |
|---|---|---|---|
| Port 8765 is busy | Run `bash scripts/start.sh 8766` | 8765 端口被占用 | 运行 `bash scripts/start.sh 8766` |
| Claude shows 401 | Re-login to Claude CLI; remove stale shell API-key env vars if testing manually | Claude 401 | 重新登录 Claude CLI；手动测试时移除旧 API-key 环境变量 |
| Codex auth missing | Run Codex login and confirm `~/.codex/auth.json` exists | Codex 未登录 | 运行 Codex login，并确认 `~/.codex/auth.json` 存在 |
| File is rejected | Start with a broader `--workspace-root`, or choose a normal UTF-8 text file | 文件被拒绝 | 调大 `--workspace-root` 范围，或选择普通 UTF-8 文本文件 |
| Scripts are not executable | Use `bash scripts/<name>.sh` or run `chmod +x scripts/*.sh` | 脚本没有执行权限 | 用 `bash scripts/<name>.sh` 或运行 `chmod +x scripts/*.sh` |
