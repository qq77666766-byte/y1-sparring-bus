# Install / 安装

Y1 Sparring Bus is a local macOS tool. It uses Python stdlib plus your local Claude and Codex CLI login state.

Y1 Sparring Bus 是一个本机 macOS 工具，只依赖 Python 标准库，以及你本机已经登录的 Claude / Codex CLI。

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
./scripts/doctor.sh
./scripts/start.sh
```

Choose a specific workspace / 指定可选择文件的工作区：

```bash
./scripts/start.sh 8765 ~/Documents
```

Open / 打开：

```text
http://127.0.0.1:8765/sparring
```

## 5. Stop / 停止

```bash
./scripts/stop.sh
```

## Uninstall / 卸载

Stop the server and delete the folder. Jobs are stored inside `jobs/`, so back that up first if you want the history.

停止服务后删除整个目录即可。历史任务在 `jobs/` 里，如果要保留，请先备份。

## Common Issues / 常见问题

| Issue | Fix | 问题 | 处理方式 |
|---|---|---|---|
| Port 8765 is busy | Run `./scripts/start.sh 8766` | 8765 端口被占用 | 运行 `./scripts/start.sh 8766` |
| Claude shows 401 | Re-login to Claude CLI; remove stale shell API-key env vars if testing manually | Claude 401 | 重新登录 Claude CLI；手动测试时移除旧 API-key 环境变量 |
| Codex auth missing | Run Codex login and confirm `~/.codex/auth.json` exists | Codex 未登录 | 运行 Codex login，并确认 `~/.codex/auth.json` 存在 |
| File is rejected | Start with a broader `--workspace-root`, or choose a normal UTF-8 text file | 文件被拒绝 | 调大 `--workspace-root` 范围，或选择普通 UTF-8 文本文件 |
