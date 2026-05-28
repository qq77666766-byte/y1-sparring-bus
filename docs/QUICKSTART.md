# Y1 Sparring Bus v1.0 Quickstart

Y1 Sparring Bus is a local AI sparring console. You give it one file and one goal; Claude rewrites an isolated copy, Codex reviews the diff, local rules decide whether to continue, and you decide whether to merge.

## 1. Check The Local Environment

```bash
./scripts/doctor.sh
```

Required:

- macOS
- Python 3.9+
- Claude Code CLI available as `claude`
- Codex CLI available as `codex` or `/Applications/Codex.app/Contents/Resources/codex`
- Local login already completed for both tools

## 2. Start The Server

```bash
./scripts/start.sh
```

Open:

```text
http://127.0.0.1:8765/sparring
```

Limit the file browser to a workspace:

```bash
./scripts/start.sh 8765 ~/Documents
```

## 3. Create A Job

In the web page:

1. Pick one UTF-8 text file.
2. Write a concrete goal, for example: "make this proposal sharper for a leadership review, with conclusions first and no filler."
3. Set max rounds and threshold.
4. Keep auto mode enabled unless you want manual handoff.
5. Start the job after the preflight passes.

The tool creates:

```text
jobs/<job_id>/
  TASK.md
  STATUS.json
  INPUT_SNAPSHOT/
  worktree/
  rounds/
  ledger.jsonl
```

## 4. Let The Loop Run

The auto loop performs:

```text
Claude Builder
  -> Runner checks
  -> Codex Reviewer
  -> deterministic Judge
  -> continue / stop / escalate
```

If auto mode fails, use the generated Builder or Reviewer prompt from the UI and paste the result back.

## 5. Review The Effect

When the job reaches `READY_FOR_HUMAN_MERGE` or `ESCALATED`, inspect:

```text
FINAL_REVIEW.md
FINAL.diff
```

`FINAL_REVIEW.md` is the decision brief. It summarizes the improvement, score, unresolved issues, and recommended action.

Then decide:

- merge to the original file
- abandon the job
- manually edit the worktree and continue outside the tool

## 6. Stop The Server

```bash
./scripts/stop.sh
```

## Safety Rules

- The original file is never changed until human merge.
- `jobs/` is the audit trail.
- API keys, tokens, cookies, and passwords are not stored.
- Claude child processes strip `ANTHROPIC_*` environment variables.
- v1 is single-file only.
