---
name: y1-sparring-bus
description: "Operate Y1 Sparring Bus v1.0: a local AI sparring console where Claude rewrites an isolated copy, Codex reviews the diff, deterministic rules decide whether to continue, and a human chooses merge or abandon."
---

# Y1 Sparring Bus Skill

This skill helps operate **Y1 Sparring Bus v1.0**, a local human-in-the-loop AI editing pipeline.

The product promise is simple: Claude improves the draft, Codex challenges it, deterministic gates decide whether another round is needed, and the user keeps the final merge decision.

## When To Use

Use this skill when the user asks to:

1. Start or stop the local web console.
2. Run a sparring loop on a proposal, report, strategy note, code file, prompt, or `SKILL.md`.
3. Explain what the app does and what effect it has on drafts.
4. Inspect `TASK.md`, `STATUS.json`, `FINAL_REVIEW.md`, `FINAL.diff`, and round artifacts.
5. Troubleshoot Claude/Codex CLI detection, auth errors, structured JSON failures, or stuck states.

## Do Not Use

Do not use this skill to:

1. Rewrite whole folders or multi-file projects in v1.
2. Process Word, PDF, Excel, or binary files directly.
3. Auto-merge without explicit user confirmation.
4. Forward, store, print, or request API keys, tokens, cookies, or passwords.
5. Launch a long-running background service unless the user asked to start the local server.
6. Deploy the tool to a remote server.

## Quick Commands

From the repository root:

```bash
./scripts/doctor.sh
./scripts/start.sh
./scripts/stop.sh
```

Use a specific workspace root:

```bash
./scripts/start.sh 8765 ~/Documents
```

Open:

```text
http://127.0.0.1:8765/sparring
```

## Workflow

1. Confirm the target is one UTF-8 text file.
2. Turn the user's intent into one concrete improvement goal.
3. Start the local server only if requested.
4. Create a job from the web UI.
5. Let the auto loop run, or use manual Builder/Reviewer fallback from generated prompts.
6. Inspect `FINAL_REVIEW.md` and `FINAL.diff`.
7. Ask the user to choose merge, abandon, or manual follow-up.

## Failure Handling

| Symptom | Action |
|---|---|
| Claude not found | Ask the user to install/login to Claude Code CLI, then rerun `scripts/doctor.sh`. |
| Codex not found | Check `/Applications/Codex.app/Contents/Resources/codex` and `~/.codex/auth.json`. |
| Claude 401 | Ensure the child process strips `ANTHROPIC_*`; use local OAuth login, not API keys. |
| Reviewer JSON parse fails | Open the raw reviewer output and keep only the JSON object. |
| Job keeps continuing | Read latest `rNNN.reviewer.json`; tighten the goal or accept escalation. |
| Merge is blocked | Original file changed since snapshot; compare blocked copy before deciding. |

## Invariants

1. Builder edits only `worktree/<file>`.
2. Reviewer never edits files.
3. Judge is deterministic in v1.
4. Original file changes only on explicit merge.
5. Every job leaves an audit trail in `jobs/<job_id>/`.
6. No API key is required or forwarded.
