# Y1 Sparring Bus v1.0 Quickstart / 快速开始

Y1 Sparring Bus is a local AI sparring console. You give it one file and one goal; Claude rewrites an isolated copy, Codex reviews the diff, local rules decide whether to continue, and you decide whether to merge.

Y1 Sparring Bus 是一个本机 AI 左右互搏控制台。你给它一个文件和一个目标；Claude 修改隔离副本，Codex 审查 diff，本地规则判断是否继续，最后由你决定是否合并。

## 1. Check The Local Environment / 检查本机环境

```bash
./scripts/doctor.sh
```

Required / 需要：

- macOS
- Python 3.9+
- Claude Code CLI available as `claude` / `claude` 命令可用
- Codex CLI available as `codex` or `/Applications/Codex.app/Contents/Resources/codex` / Codex CLI 可用
- Local login already completed for both tools / 两个工具都已完成本机登录

## 2. Start The Server / 启动服务

```bash
./scripts/start.sh
```

Open / 打开：

```text
http://127.0.0.1:8765/sparring
```

Limit the file browser to a workspace / 限定文件浏览根目录：

```bash
./scripts/start.sh 8765 ~/Documents
```

## 3. Run A Demo / 先跑一个演示

Pick one demo file:

选择一个演示文件：

```text
examples/demo_proposal_zh.md
examples/demo_leadership_memo_en.md
examples/demo_agent_skill.md
examples/demo_python_script.py
```

Open [docs/DEMO_CASES.md](DEMO_CASES.md) for suggested goals and expected effects.

打开 [docs/DEMO_CASES.md](DEMO_CASES.md) 查看每个案例建议填写的目标和预期效果。

## 4. Create A Job / 创建任务

In the web page / 在网页里：

1. Pick one UTF-8 text file.  
   选择一个 UTF-8 文本文件。
2. Write a concrete goal, for example: "make this proposal sharper for a leadership review, with conclusions first and no filler."  
   填一个具体目标，例如：“把这份方案改成适合领导评审的版本，结论前置，删掉空话。”
3. Set max rounds and threshold.  
   设置最大轮数和验收分。
4. Keep auto mode enabled unless you want manual handoff.  
   除非你想手动接力，否则保持自动模式。
5. Start the job after the preflight passes.  
   预检通过后开始任务。

The tool creates / 系统会创建：

```text
jobs/<job_id>/
  TASK.md
  STATUS.json
  INPUT_SNAPSHOT/
  worktree/
  rounds/
  ledger.jsonl
```

## 5. Let The Loop Run / 等互搏跑完

The auto loop performs / 自动循环会执行：

```text
Claude Builder
  -> Runner checks
  -> Codex Reviewer
  -> deterministic Judge
  -> continue / stop / escalate
```

If auto mode fails, use the generated Builder or Reviewer prompt from the UI and paste the result back.

如果自动调用失败，可以使用页面生成的 Builder / Reviewer prompt 手动接力，再把结果贴回页面。

## 6. Review The Effect / 查看效果

When the job reaches `READY_FOR_HUMAN_MERGE` or `ESCALATED`, inspect:

当任务进入 `READY_FOR_HUMAN_MERGE` 或 `ESCALATED`，查看：

```text
FINAL_REVIEW.md
FINAL.diff
```

`FINAL_REVIEW.md` is the decision brief. It summarizes the improvement, score, unresolved issues, and recommended action.

`FINAL_REVIEW.md` 是给人看的决策简报，会总结改进点、分数、剩余问题和建议动作。

Then decide / 然后选择：

- merge to the original file / 合并回原文件
- abandon the job / 放弃任务
- manually edit the worktree and continue outside the tool / 手动接着改

## 7. Stop The Server / 停止服务

```bash
./scripts/stop.sh
```

## Safety Rules / 安全规则

- The original file is never changed until human merge.  
  人工合并前，原文件不会被覆盖。
- `jobs/` is the audit trail.  
  `jobs/` 是审计留痕目录。
- API keys, tokens, cookies, and passwords are not stored.  
  不保存 API key、token、cookie 或密码。
- Claude child processes strip `ANTHROPIC_*` environment variables.  
  Claude 子进程会移除 `ANTHROPIC_*` 环境变量。
- v1 is single-file only.  
  v1 只支持单文件。
