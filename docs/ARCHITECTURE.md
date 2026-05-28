# Y1 Sparring Bus v1.0 Architecture

Y1 Sparring Bus is intentionally small. The product is a local AI sparring loop, not a general automation platform.

- one Python stdlib web server
- one embedded HTML/CSS/JS page
- one file-based job store
- local subprocess calls to Claude and Codex

There is no database, queue, web framework, or remote agent service.

The architecture exists to protect four promises:

1. Builder can improve drafts quickly.
2. Reviewer can challenge the patch independently.
3. Judge can explain why the loop stopped.
4. Human merge remains the final gate.

## Directory Layout

```text
y1-sparring-bus/
  README.md
  SKILL.md
  INSTALL.md
  LICENSE
  tools/
    sparring_center.py
  scripts/
    doctor.sh
    start.sh
    stop.sh
  docs/
    QUICKSTART.md
    MANUAL.md
    ARCHITECTURE.md
  examples/
    sample_proposal.md
  jobs/
    <created at runtime>
```

## Runtime Roots

| Name | Meaning |
|---|---|
| `APP_ROOT` | repository or extracted package root |
| `JOBS_ROOT` | `APP_ROOT/jobs` |
| `WORKSPACE_ROOT` | file browser and source-file allowlist root |

`WORKSPACE_ROOT` defaults to `SPARRING_WORKSPACE_ROOT` if set, otherwise the parent of `APP_ROOT`. It can also be set at startup:

```bash
python3 tools/sparring_center.py --workspace-root ~/Documents
```

## Layers

```text
HTTP API + embedded UI
  -> job state functions
  -> Builder / Reviewer subprocess bridge
  -> deterministic Runner and Judge
  -> path, source, and merge guards
  -> JSON/file helpers
```

## Important Functions

| Function | Responsibility |
|---|---|
| `safe_workspace_file` | allow only normal files under `WORKSPACE_ROOT`; reject internal tool files |
| `preflight_check` | validate file, goal, type hints, and preview before creating a job |
| `create_job` | snapshot original, create worktree, write `TASK.md` and `STATUS.json` |
| `build_builder_prompt` | create current-round Builder prompt |
| `run_builder_cli` | spawn local Claude CLI with API-key env stripped |
| `prepare_reviewer` | generate diff, run checks, create Reviewer prompt |
| `run_reviewer_cli` | spawn local Codex CLI with structured output |
| `save_review_and_judge` | save review JSON and decide next state |
| `finalize` | create `FINAL.md`, `FINAL.diff`, and `FINAL_REVIEW.md` |
| `merge_job` | human-triggered merge with backup and conflict guard |
| `abort_job` | mark a job abandoned while preserving files |

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/sparring` | UI |
| GET | `/api/health` | local CLI detection and roots |
| GET | `/api/jobs` | list jobs |
| GET | `/api/jobs/<id>` | job detail |
| GET | `/api/jobs/<id>/file?name=<path>` | read job artifact |
| GET | `/api/browse?path=<dir>` | workspace file browser |
| POST | `/api/preflight` | validate source and goal |
| POST | `/api/jobs` | create job |
| POST | `/api/jobs/<id>/after-builder` | advance to reviewer after manual Builder |
| POST | `/api/jobs/<id>/auto-run` | start auto loop |
| POST | `/api/jobs/<id>/review` | save manual Reviewer JSON |
| POST | `/api/jobs/<id>/retry-reviewer` | rerun Reviewer |
| POST | `/api/jobs/<id>/merge` | merge final output |
| POST | `/api/jobs/<id>/abort` | abandon job |

## State Machine

```text
WAIT_BUILDER
  -> WAIT_REVIEWER
  -> continue: WAIT_BUILDER
  -> stop: READY_FOR_HUMAN_MERGE
  -> escalate: ESCALATED
  -> MERGED or ABORTED by human action
```

## Security And Safety Notes

- The app is bound to `127.0.0.1` by default.
- Source file selection is limited by `WORKSPACE_ROOT`.
- Tool internals and job artifacts are rejected as source targets.
- `read_known_file` keeps artifact reads inside the job directory.
- `merge_job` backs up the original file before writing.
- `assert_source_unchanged_or_restore` restores accidental Builder writes to the source file.
- `_clean_env_no_anthropic_api` removes `ANTHROPIC_*` and `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`.

## Non-Goals

- remote server deployment
- API-key based orchestration
- multi-user collaboration
- persistent background queue
- multi-file rewrite engine
- automatic merge
