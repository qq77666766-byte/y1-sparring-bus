# Y1 Sparring Bus v1.0 Manual / 使用手册

## Concept / 概念

Y1 Sparring Bus is a local file-based workflow for making drafts stronger without handing final control to AI.

Y1 Sparring Bus 是一个本机文件型工作流，用来让文稿变得更强，同时不把最终控制权交给 AI。

```text
one file + one goal
  -> Claude Builder edits an isolated copy
  -> Runner performs deterministic checks
  -> Codex Reviewer critiques the diff
  -> Judge decides continue / stop / escalate
  -> human merges or abandons
```

It is a writing and review pipeline, not an autonomous deployment system. The goal is to produce a better final candidate plus a readable explanation of why it improved.

它是写作和审查流水线，不是自动部署系统。目标是产出一个更好的候选稿，并解释为什么变好、还剩什么风险。

## Start And Stop / 启动与停止

```bash
./scripts/start.sh
./scripts/start.sh 8765 ~/Documents
./scripts/stop.sh
```

Manual equivalent / 手动启动等价命令：

```bash
python3 tools/sparring_center.py --host 127.0.0.1 --port 8765 --workspace-root ~/Documents
```

Open / 打开 `http://127.0.0.1:8765/sparring`。

## Job States / 任务状态

| State | Meaning | 含义 |
|---|---|---|
| `WAIT_BUILDER` | Builder should edit the isolated worktree copy | 等 Builder 修改隔离副本 |
| `WAIT_REVIEWER` | Reviewer should return structured review JSON | 等 Reviewer 返回结构化 JSON |
| `READY_FOR_HUMAN_MERGE` | Stop gates passed; human decision required | 已达停止门槛，等待人工合并 |
| `ESCALATED` | Round limit reached before gates passed | 到达最大轮数但未完全达标 |
| `MERGED` | Human merged `FINAL.md` into the original file | 人工已合并 |
| `ABORTED` | Human abandoned the job | 人工放弃 |

## Stop Rules / 停止规则

Judge returns `stop` only when all conditions pass:

只有同时满足以下条件，Judge 才会返回 `stop`：

- `requirement_fit >= threshold`
- `p0 = 0`
- `p1 = 0`
- `runner_failures = 0`
- reviewer verdict is `accept` or `accept_with_minors`

Judge returns `escalate` when max rounds are reached before stop conditions pass.

如果达到最大轮数但还没通过停止门槛，Judge 返回 `escalate`。

Everything else returns `continue`.

其他情况返回 `continue`。

## Job Folder / 任务目录

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

## The Main Effect / 核心效果

The app improves a draft in three ways:

这个应用主要通过三件事改善稿件：

1. It separates rewriting from reviewing, so one model does not grade its own work.  
   把“改稿”和“审稿”分开，避免一个模型自己给自己打分。
2. It records each round, so improvements and regressions are visible.  
   每轮都留痕，进步和退步都能看见。
3. It stops only when explicit score and issue gates pass, or when the round limit forces escalation.  
   只有评分和问题门槛通过才停止，否则到最大轮数交给人判断。

The most important output for humans is `FINAL_REVIEW.md`. Read it before merging.

最重要的输出是 `FINAL_REVIEW.md`。合并前先看它。

## Manual Builder Fallback / 手动 Builder 兜底

If auto Builder fails / 如果自动 Builder 失败：

1. Open or copy `rounds/rNNN.builder.prompt.md`.  
   打开或复制 `rounds/rNNN.builder.prompt.md`。
2. Paste it into Claude.  
   粘贴到 Claude。
3. Claude edits only `worktree/<filename>`.  
   Claude 只修改 `worktree/<filename>`。
4. Claude writes `rounds/rNNN.builder.json`.  
   Claude 写入 `rounds/rNNN.builder.json`。
5. Click "Builder complete" in the UI.  
   在页面点击 Builder complete。

## Manual Reviewer Fallback / 手动 Reviewer 兜底

If auto Reviewer fails / 如果自动 Reviewer 失败：

1. Open or copy `rounds/rNNN.reviewer.prompt.md`.  
   打开或复制 `rounds/rNNN.reviewer.prompt.md`。
2. Paste it into Codex.  
   粘贴到 Codex。
3. Keep only the JSON object in the output.  
   只保留输出里的 JSON 对象。
4. Paste it into the UI.  
   粘贴回页面。

Expected JSON shape / JSON 格式：

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

## Runner Checks / Runner 检查

| Check | Markdown | Python | Effect | 效果 |
|---|---|---|---|---|
| H1 exists | yes | no | warning/fail signal | 标题结构检查 |
| CYA phrases | yes | no | blocking fail | 防御性表达检查 |
| Suspicious unsourced numbers | yes | no | warning | 无来源数字提醒 |
| `py_compile` | no | yes | blocking fail | Python 语法阻断 |

## Safety Boundaries / 安全边界

- Builder may edit only `worktree/<filename>`.  
  Builder 只能修改 `worktree/<filename>`。
- Reviewer may not edit files.  
  Reviewer 不修改文件。
- The source file is checked after Builder execution; accidental writes are restored and recorded.  
  Builder 后会检查原文件，误写会恢复并记录。
- Merge is blocked if the original file changed since the snapshot.  
  如果原文件在快照后被外部修改，合并会被阻止。
- Job IDs and file reads are path-validated.  
  Job ID 和文件读取都有路径校验。
- Logs are append-only.  
  日志只追加。
- Claude child processes run with `ANTHROPIC_*` and `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` stripped.  
  Claude 子进程会移除 `ANTHROPIC_*` 和 `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`。

## Troubleshooting / 排查

| Symptom | Fix | 现象 | 处理 |
|---|---|---|---|
| Page does not open | Check port 8765 and rerun `scripts/start.sh` | 页面打不开 | 检查 8765 端口并重启 |
| Claude not detected | Install/login to Claude Code CLI and rerun `scripts/doctor.sh` | 找不到 Claude | 安装/登录 Claude Code CLI 后重跑体检 |
| Codex not detected | Check the Codex app CLI path and local login | 找不到 Codex | 检查 Codex App CLI 路径和登录状态 |
| Reviewer JSON fails | Remove prose before/after the JSON object and retry | Reviewer JSON 失败 | 删除 JSON 前后的解释文字再贴回 |
| Job never stops | Read latest reviewer JSON, tighten the goal, or accept escalation | 一直继续 | 看最新 reviewer JSON，收紧目标或接受升级 |
| Merge blocked | Compare current source file with `INPUT_SNAPSHOT` and decide manually | 合并被阻止 | 对比当前原文件与快照后再决定 |

## Limits / 限制

- v1 supports one UTF-8 text file per job.  
  v1 每个任务只支持一个 UTF-8 文本文件。
- No direct Word/PDF/Excel handling.  
  不直接处理 Word/PDF/Excel。
- No cloud deployment.  
  不做云端部署。
- No multi-user server.  
  不做多人服务器。
- No automatic merge.  
  不自动合并。
