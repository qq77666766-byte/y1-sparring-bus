# Y1 Sparring Bus

> **Claude writes. Codex reviews. The rules decide when it is good enough. You decide whether to merge.**

Y1 Sparring Bus is a local AI sparring console for people who write proposals, reports, specs, prompts, and agent skills. It turns the messy back-and-forth of "rewrite this" and "review this again" into a visible, repeatable, human-controlled pipeline.

![banner](assets/banner.svg)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v1.0-black)](#v10)
[![macOS](https://img.shields.io/badge/macOS-local%20first-black)](#requirements)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](#quickstart)
[![No API Key](https://img.shields.io/badge/API%20keys-not%20used-green)](#why-it-matters)

## What It Does

Most AI editing workflows fail in the same way: one model rewrites, sounds confident, and leaves you guessing whether the result is actually better.

Y1 Sparring Bus adds a second mind and a stop rule:

```text
your file + one clear goal
  -> Claude Builder rewrites an isolated copy
  -> local Runner checks obvious risks
  -> Codex Reviewer scores and flags P0/P1/P2 issues
  -> deterministic Judge decides continue / stop / escalate
  -> you inspect FINAL_REVIEW + diff, then merge or abandon
```

The result is not just a better draft. It is a full audit trail of how the draft improved, what risks remain, and why the loop stopped.

## Built For

| Use case | What improves |
|---|---|
| Leadership reports | sharper conclusions, less defensive language, clearer evidence |
| Business proposals | stronger structure, cleaner value logic, less filler |
| Strategy notes | explicit assumptions, visible risks, action-oriented wording |
| Agent skills / prompts | clearer trigger boundaries, fewer vague instructions |
| Code or scripts | read-only review loop before human-controlled merge |

## Why It Matters

Y1 Sparring Bus is designed around one principle: **AI may iterate, but humans keep the final decision.**

- Original files are never edited directly.
- Every job creates a frozen snapshot and an isolated worktree.
- Every Builder prompt, patch, Runner log, Reviewer JSON, and Judge result is saved.
- Merge always requires explicit human confirmation.
- Claude child processes strip `ANTHROPIC_*` environment variables.
- Jobs are plain local files; there is no database, daemon, or cloud service.

## What You Get After A Run

```text
jobs/<job_id>/
  TASK.md                 # frozen goal and acceptance gates
  STATUS.json             # current state, round, score trend
  ledger.jsonl            # append-only event log
  INPUT_SNAPSHOT/<file>   # original frozen copy
  worktree/<file>         # AI-edited copy
  rounds/                 # prompts, patches, reviews, judge records
  FINAL.md                # final candidate
  FINAL.diff              # original vs final
  FINAL_REVIEW.md         # human decision brief
```

The most useful file is `FINAL_REVIEW.md`: it tells you what changed, what score it reached, what issues remain, and whether the system recommends merge, another round, or escalation.

## Quickstart

```bash
./scripts/doctor.sh
./scripts/start.sh
```

Open:

```text
http://127.0.0.1:8765/sparring
```

Choose a workspace root:

```bash
./scripts/start.sh 8765 ~/Documents
# or
SPARRING_WORKSPACE_ROOT=~/Documents ./scripts/start.sh
```

Stop:

```bash
./scripts/stop.sh
```

## Requirements

| Item | Requirement |
|---|---|
| OS | macOS |
| Python | 3.9+ |
| Builder | Claude Code CLI, logged in locally |
| Reviewer | Codex app CLI, logged in locally |
| Input | one UTF-8 text file |

Word, PDF, Excel, and binary files should be converted to `.md` or `.txt` first.

## v1.0

This first public version is intentionally narrow:

- single-file sparring
- local web console
- Claude Builder + Codex Reviewer
- deterministic Judge
- manual merge gate
- zero Python package dependencies

It does not try to be a cloud platform, multi-user collaboration tool, or autonomous deployment agent.

## Documentation

| Need | File |
|---|---|
| First run | [docs/QUICKSTART.md](docs/QUICKSTART.md) |
| Full manual | [docs/MANUAL.md](docs/MANUAL.md) |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Install notes | [INSTALL.md](INSTALL.md) |
| Agent skill entry | [SKILL.md](SKILL.md) |

## Design Reference

This project was inspired by the discipline of open agent-skill projects such as [alchaincyf/darwin-skill](https://github.com/alchaincyf/darwin-skill): visible loops, explicit rubrics, failure handling, and keep-or-revert checkpoints.

Y1 Sparring Bus applies that pattern to practical document and code collaboration.

## License

MIT
