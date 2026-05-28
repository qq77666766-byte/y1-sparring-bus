# Y1 Sparring Bus v1.0 Architecture / 架构说明

Y1 Sparring Bus is intentionally small. The product is a local AI sparring loop, not a general automation platform.

Y1 Sparring Bus 故意保持很小。它是一个本机 AI 互搏循环，不是通用自动化平台。

- one Python stdlib web server / 一个 Python 标准库 Web server
- one embedded HTML/CSS/JS page / 一个内嵌 HTML/CSS/JS 页面
- one file-based job store / 一个文件型 job 存储
- local subprocess calls to Claude and Codex / 本机子进程调用 Claude 和 Codex

There is no database, queue, web framework, or remote agent service.

没有数据库、队列、Web 框架或远程 Agent 服务。

The architecture protects four promises:

这套架构保护四个承诺：

1. Builder can improve drafts quickly.  
   Builder 能快速改稿。
2. Reviewer can challenge the patch independently.  
   Reviewer 能独立挑战改动。
3. Judge can explain why the loop stopped.  
   Judge 能解释为什么停止。
4. Human merge remains the final gate.  
   人工合并仍是最后一道门。

## Directory Layout / 目录结构

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
    DEMO_CASES.md
    MANUAL.md
    ARCHITECTURE.md
  examples/
    demo_proposal_zh.md
    demo_leadership_memo_en.md
    demo_agent_skill.md
    demo_python_script.py
  jobs/
    <created at runtime>
```

## Runtime Roots / 运行时根目录

| Name | Meaning | 含义 |
|---|---|---|
| `APP_ROOT` | repository or extracted package root | 应用根目录 |
| `JOBS_ROOT` | `APP_ROOT/jobs` | job 存储目录 |
| `WORKSPACE_ROOT` | file browser and source-file allowlist root | 文件浏览和源文件白名单根目录 |

`WORKSPACE_ROOT` defaults to `SPARRING_WORKSPACE_ROOT` if set, otherwise the parent of `APP_ROOT`.

`WORKSPACE_ROOT` 默认读取 `SPARRING_WORKSPACE_ROOT`，否则使用 `APP_ROOT` 的父目录。

```bash
python3 tools/sparring_center.py --workspace-root ~/Documents
```

## Layers / 分层

```text
HTTP API + embedded UI
  -> job state functions
  -> Builder / Reviewer subprocess bridge
  -> deterministic Runner and Judge
  -> path, source, and merge guards
  -> JSON/file helpers
```

## Important Functions / 关键函数

| Function | Responsibility | 职责 |
|---|---|---|
| `safe_workspace_file` | allow only normal files under `WORKSPACE_ROOT`; reject internal tool files | 限定源文件只能来自工作区，拒绝工具内部文件 |
| `preflight_check` | validate file, goal, type hints, and preview before creating a job | 创建任务前做文件、目标、预览检查 |
| `create_job` | snapshot original, create worktree, write `TASK.md` and `STATUS.json` | 创建快照、worktree 和任务状态 |
| `build_builder_prompt` | create current-round Builder prompt | 生成 Builder prompt |
| `run_builder_cli` | spawn local Claude CLI with API-key env stripped | 调用 Claude CLI，并移除 API-key 环境变量 |
| `prepare_reviewer` | generate diff, run checks, create Reviewer prompt | 生成 diff、运行检查、生成 Reviewer prompt |
| `run_reviewer_cli` | spawn local Codex CLI with structured output | 调用 Codex CLI 生成结构化审查 |
| `save_review_and_judge` | save review JSON and decide next state | 保存审查结果并判定下一状态 |
| `finalize` | create `FINAL.md`, `FINAL.diff`, and `FINAL_REVIEW.md` | 生成最终候选稿、diff 和决策简报 |
| `merge_job` | human-triggered merge with backup and conflict guard | 人工触发合并，带备份和冲突保护 |
| `abort_job` | mark a job abandoned while preserving files | 标记放弃并保留文件 |

## API / 接口

| Method | Path | Purpose | 用途 |
|---|---|---|---|
| GET | `/sparring` | UI | 页面 |
| GET | `/api/health` | local CLI detection and roots | CLI 和根目录检测 |
| GET | `/api/jobs` | list jobs | job 列表 |
| GET | `/api/jobs/<id>` | job detail | job 详情 |
| GET | `/api/jobs/<id>/file?name=<path>` | read job artifact | 读取 job 工件 |
| GET | `/api/browse?path=<dir>` | workspace file browser | 工作区文件浏览 |
| POST | `/api/preflight` | validate source and goal | 预检源文件和目标 |
| POST | `/api/jobs` | create job | 创建 job |
| POST | `/api/jobs/<id>/after-builder` | advance after manual Builder | 手动 Builder 后推进 |
| POST | `/api/jobs/<id>/auto-run` | start auto loop | 启动自动循环 |
| POST | `/api/jobs/<id>/review` | save manual Reviewer JSON | 保存手动 Reviewer JSON |
| POST | `/api/jobs/<id>/retry-reviewer` | rerun Reviewer | 重跑 Reviewer |
| POST | `/api/jobs/<id>/merge` | merge final output | 合并最终稿 |
| POST | `/api/jobs/<id>/abort` | abandon job | 放弃 job |

## State Machine / 状态机

```text
WAIT_BUILDER
  -> WAIT_REVIEWER
  -> continue: WAIT_BUILDER
  -> stop: READY_FOR_HUMAN_MERGE
  -> escalate: ESCALATED
  -> MERGED or ABORTED by human action
```

## Security And Safety Notes / 安全说明

- The app is bound to `127.0.0.1` by default.  
  默认只绑定 `127.0.0.1`。
- Source file selection is limited by `WORKSPACE_ROOT`.  
  源文件选择受 `WORKSPACE_ROOT` 限制。
- Tool internals and job artifacts are rejected as source targets.  
  工具内部文件和 job 工件不能作为源文件。
- `read_known_file` keeps artifact reads inside the job directory.  
  `read_known_file` 保证读取范围在 job 目录内。
- `merge_job` backs up the original file before writing.  
  `merge_job` 写入前会备份原文件。
- `assert_source_unchanged_or_restore` restores accidental Builder writes to the source file.  
  `assert_source_unchanged_or_restore` 会恢复 Builder 对原文件的误写。
- `_clean_env_no_anthropic_api` removes `ANTHROPIC_*` and `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`.  
  `_clean_env_no_anthropic_api` 会移除 `ANTHROPIC_*` 和 `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`。

## Non-Goals / 非目标

- remote server deployment / 远程服务器部署
- API-key based orchestration / 基于 API key 的编排
- multi-user collaboration / 多人协作
- persistent background queue / 常驻后台队列
- multi-file rewrite engine / 多文件重写引擎
- automatic merge / 自动合并
