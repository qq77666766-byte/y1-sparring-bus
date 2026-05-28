# Background Service / 本机后台服务

Y1 Sparring Bus has no cloud backend. The "backend" is a local Python HTTP server bound to `127.0.0.1`.

Y1 Sparring Bus 没有云端后台。这里说的“后台”是绑定在 `127.0.0.1` 的本机 Python HTTP 服务。

## Option A: Temporary Background Process / 临时后台进程

Use this for normal testing and demos:

日常测试和演示用这个：

```bash
bash scripts/start.sh
```

Open:

```text
http://127.0.0.1:8765/sparring
```

Stop:

```bash
bash scripts/stop.sh
```

This writes:

会生成：

```text
sparring-center.pid
sparring-center.log
jobs/
```

## Option B: Login-Time LaunchAgent / 开机登录后自动启动

Use this only if you want the local backend to start after macOS login.

只有当你希望 macOS 登录后自动启动本机后端时才使用。

```bash
bash scripts/install-service.sh 8765 ~/Documents
```

Status:

```bash
bash scripts/status.sh
```

Uninstall:

```bash
bash scripts/uninstall-service.sh
```

The service is a user-level LaunchAgent:

这个服务是用户级 LaunchAgent：

- no `sudo` / 不需要 `sudo`
- binds only to `127.0.0.1` / 只绑定本机地址
- uses your local Python / 使用本机 Python
- does not store Claude, Codex, API keys, tokens, cookies, or passwords / 不保存 Claude、Codex、API key、token、cookie 或密码

## Logs / 日志

Temporary process logs:

临时后台进程日志：

```text
sparring-center.log
```

LaunchAgent logs:

LaunchAgent 日志：

```text
~/Library/Logs/y1-sparring-bus/stdout.log
~/Library/Logs/y1-sparring-bus/stderr.log
```

## Which One Should Users Choose? / 用户应该选哪个？

For most users, start with `bash scripts/start.sh`. It is easier to stop, debug, and delete.

大多数用户先用 `bash scripts/start.sh`。它更容易停止、排查和删除。

Use `install-service.sh` only after the app already works manually.

只有在手动启动已经跑通以后，再考虑 `install-service.sh`。
