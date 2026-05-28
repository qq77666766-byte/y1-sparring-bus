# Install

Y1 Sparring Bus is a local macOS tool. It uses Python stdlib plus your local Claude and Codex CLI login state.

## 1. Python

```bash
python3 --version
```

Python 3.9+ is required.

## 2. Claude Code CLI

Install and log in through the official Claude Code flow.

Verify:

```bash
claude --version
claude
```

The tool does not need an Anthropic API key.

## 3. Codex App CLI

Install Codex for macOS and log in.

Verify:

```bash
/Applications/Codex.app/Contents/Resources/codex --version
/Applications/Codex.app/Contents/Resources/codex login
test -f ~/.codex/auth.json && echo "Codex auth found"
```

If `codex` is on your `PATH`, the scripts will use it. Otherwise they fall back to the app bundle path above.

## 4. Start

From this repository:

```bash
./scripts/doctor.sh
./scripts/start.sh
```

Choose a specific workspace:

```bash
./scripts/start.sh 8765 ~/Documents
```

Open:

```text
http://127.0.0.1:8765/sparring
```

## 5. Stop

```bash
./scripts/stop.sh
```

## Uninstall

Stop the server and delete the folder. Jobs are stored inside `jobs/`, so back that up first if you want the history.

## Common Issues

| Issue | Fix |
|---|---|
| Port 8765 is busy | Run `./scripts/start.sh 8766` |
| Claude shows 401 | Re-login to Claude CLI; remove stale shell API-key env vars if testing manually |
| Codex auth missing | Run Codex login and confirm `~/.codex/auth.json` exists |
| File is rejected | Start with a broader `--workspace-root`, or choose a normal UTF-8 text file |
