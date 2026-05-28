# Y1 Sparring Bus

> Local AI sparring for writing, proposals, specs, and skills: **Claude builds, Codex reviews, deterministic rules decide whether another round is needed, and a human decides whether to merge.**

![banner](assets/banner.svg)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-local%20only-black)](#requirements)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](#quickstart)
[![No API Key](https://img.shields.io/badge/API%20keys-not%20used-green)](#why-local)

Y1 Sparring Bus turns the manual "ask one AI to rewrite, ask another AI to critique" loop into an auditable local workflow.

You select one UTF-8 text file, write a one-line goal, and start a job. The tool creates an isolated worktree copy, calls local Claude CLI as Builder, calls local Codex CLI as Reviewer, runs deterministic checks, and stops only when the score and issue gates pass or the round limit is reached.

The original file is not changed until you explicitly click merge.

## Why Local

- Uses your local Claude Code CLI and Codex app login state.
- Strips `ANTHROPIC_*` environment variables before spawning Claude.
- Stores jobs as plain files under `jobs/`.
- Uses only the Python standard library.
- Does not run a cloud server, daemon, queue, database, or API-key service.

## Requirements

| Item | Requirement |
|---|---|
| OS | macOS |
| Python | 3.9+ |
| Builder | Claude Code CLI, logged in locally |
| Reviewer | Codex app CLI, logged in locally |
| Input | One UTF-8 text file (`.md`, `.txt`, `.py`, `.js`, etc.) |

Word, PDF, Excel, and binary files should be converted to text first.

## Quickstart

```bash
./scripts/doctor.sh
./scripts/start.sh
```

Open:

```text
http://127.0.0.1:8765/sparring
```

Optional: limit selectable files to a specific workspace:

```bash
./scripts/start.sh 8765 ~/Documents
# or
SPARRING_WORKSPACE_ROOT=~/Documents ./scripts/start.sh
```

Stop:

```bash
./scripts/stop.sh
```

## What It Produces

Each job is a self-contained audit folder:

```text
jobs/<job_id>/
  TASK.md
  STATUS.json
  ledger.jsonl
  INPUT_SNAPSHOT/<file>
  worktree/<file>
  rounds/
    r001.builder.prompt.md
    r001.builder.patch
    r001.runner.log
    r001.reviewer.prompt.md
    r001.reviewer.json
    r001.judge.json
  FINAL.md
  FINAL.diff
  FINAL_REVIEW.md
```

## Design Rules

1. Builder edits only the isolated worktree copy.
2. Reviewer is read-only.
3. Judge is deterministic: score, P0/P1 issues, runner failures, and max rounds.
4. Merge is always human-confirmed.
5. Logs are append-only.
6. No Anthropic API key is used or forwarded.
7. The tool stays local-first and dependency-light.

## Not Goals

| Not planned for v1 | Reason |
|---|---|
| Cloud deployment | Local OAuth credentials do not belong on a server |
| Multi-user collaboration | v1 is a single-machine tool |
| Whole-directory rewrites | Single-file scope keeps attribution clear |
| AI Judge | Deterministic stop rules are cheaper and easier to audit |
| Direct Word/PDF/Excel handling | Convert to text first |

## Documentation

| Need | File |
|---|---|
| First run | [docs/QUICKSTART.md](docs/QUICKSTART.md) |
| Full manual | [docs/MANUAL.md](docs/MANUAL.md) |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Install notes | [INSTALL.md](INSTALL.md) |
| Agent skill entry | [SKILL.md](SKILL.md) |

## Design References

This project borrows the same high-level product discipline seen in open agent-skill projects such as [alchaincyf/darwin-skill](https://github.com/alchaincyf/darwin-skill): clear install path, visible rubric, human checkpoints, failure blacklists, and a ratchet-like preference for keeping only improvements.

Y1 Sparring Bus applies that thinking to **document/code collaboration**, not skill optimization.

## License

MIT
