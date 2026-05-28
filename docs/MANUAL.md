# Y1 Sparring Bus v1.0 Manual

## Concept

Y1 Sparring Bus is a local file-based workflow for making drafts stronger without handing final control to AI:

```text
one file + one goal
  -> Claude Builder edits an isolated copy
  -> Runner performs deterministic checks
  -> Codex Reviewer critiques the diff
  -> Judge decides continue / stop / escalate
  -> human merges or abandons
```

It is a writing and review pipeline, not an autonomous deployment system. The goal is to produce a better final candidate plus a readable explanation of why it improved.

## Start And Stop

```bash
./scripts/start.sh
./scripts/start.sh 8765 ~/Documents
./scripts/stop.sh
```

Manual equivalent:

```bash
python3 tools/sparring_center.py --host 127.0.0.1 --port 8765 --workspace-root ~/Documents
```

Open `http://127.0.0.1:8765/sparring`.

## Job States

| State | Meaning |
|---|---|
| `WAIT_BUILDER` | Builder should edit the isolated worktree copy |
| `WAIT_REVIEWER` | Reviewer should return structured review JSON |
| `READY_FOR_HUMAN_MERGE` | Stop gates passed; human decision required |
| `ESCALATED` | Round limit reached before gates passed |
| `MERGED` | Human merged `FINAL.md` into the original file |
| `ABORTED` | Human abandoned the job |

## Stop Rules

Judge returns `stop` only when all conditions pass:

- `requirement_fit >= threshold`
- `p0 = 0`
- `p1 = 0`
- `runner_failures = 0`
- reviewer verdict is `accept` or `accept_with_minors`

Judge returns `escalate` when max rounds are reached before stop conditions pass.

Everything else returns `continue`.

## Job Folder

```text
jobs/<job_id>/
  TASK.md
  STATUS.json
  ledger.jsonl
  INPUT_SNAPSHOT/<filename>
  worktree/<filename>
  rounds/
    r001.before_builder.<filename>
    r001.builder.prompt.md
    r001.builder.json
    r001.builder.patch
    r001.runner.log
    r001.reviewer.prompt.md
    r001.reviewer.schema.json
    r001.reviewer.json
    r001.judge.json
  FINAL.md
  FINAL.diff
  FINAL_REVIEW.md
  ORIGINAL_BEFORE_MERGE.<filename>
```

## The Main Effect

The app improves a draft in three ways:

1. It separates rewriting from reviewing, so one model does not grade its own work.
2. It records each round, so improvements and regressions are visible.
3. It stops only when explicit score and issue gates pass, or when the round limit forces escalation.

The most important output for humans is `FINAL_REVIEW.md`. Read it before merging.

## Manual Builder Fallback

If auto Builder fails:

1. Open or copy `rounds/rNNN.builder.prompt.md`.
2. Paste it into Claude.
3. Claude edits only `worktree/<filename>`.
4. Claude writes `rounds/rNNN.builder.json`.
5. Click "Builder complete" in the UI.

## Manual Reviewer Fallback

If auto Reviewer fails:

1. Open or copy `rounds/rNNN.reviewer.prompt.md`.
2. Paste it into Codex.
3. Keep only the JSON object in the output.
4. Paste it into the UI.

Expected JSON shape:

```json
{
  "round": 1,
  "actor": "reviewer",
  "issues": {
    "p0": [],
    "p1": [],
    "p2": []
  },
  "scores": {
    "requirement_fit": 88,
    "correctness": 90,
    "clarity": 86,
    "risk": 20
  },
  "verdict": "accept_with_minors",
  "summary": "The file meets the goal with only minor optional edits."
}
```

## Runner Checks

| Check | Markdown | Python | Effect |
|---|---|---|---|
| H1 exists | yes | no | warning/fail signal |
| CYA phrases | yes | no | blocking fail |
| Suspicious unsourced numbers | yes | no | warning |
| `py_compile` | no | yes | blocking fail |

## Safety Boundaries

- Builder may edit only `worktree/<filename>`.
- Reviewer may not edit files.
- The source file is checked after Builder execution; accidental writes are restored and recorded.
- Merge is blocked if the original file changed since the snapshot.
- Job IDs and file reads are path-validated.
- Logs are append-only.
- Claude child processes run with `ANTHROPIC_*` and `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` stripped.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Page does not open | Check whether port 8765 is listening; rerun `scripts/start.sh`. |
| Claude not detected | Install/login to Claude Code CLI and rerun `scripts/doctor.sh`. |
| Codex not detected | Check the Codex app CLI path and local login. |
| Reviewer JSON fails | Remove prose before/after the JSON object and retry. |
| Job never stops | Read latest reviewer JSON, lower ambiguity in the goal, or accept escalation. |
| Merge blocked | Compare the current source file with `INPUT_SNAPSHOT` and decide manually. |

## Limits

- v1 supports one UTF-8 text file per job.
- No direct Word/PDF/Excel handling.
- No cloud deployment.
- No multi-user server.
- No automatic merge.
