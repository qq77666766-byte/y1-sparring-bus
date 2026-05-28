---
name: y1-sparring-bus
description: "Operate Y1 Sparring Bus v1.0: a bilingual local AI sparring console where Claude rewrites an isolated copy, Codex reviews the diff, deterministic rules decide whether to continue, and a human chooses merge or abandon."
---

# Y1 Sparring Bus Skill / Skill 入口

This skill helps operate **Y1 Sparring Bus v1.0**, a bilingual local human-in-the-loop AI editing pipeline.

这个 Skill 用来操作 **Y1 Sparring Bus v1.0**：一个中英双语、本机运行、人在回路中的 AI 改稿与审稿流水线。

The product promise is simple: Claude improves the draft, Codex challenges it, deterministic gates decide whether another round is needed, and the user keeps the final merge decision.

产品承诺很简单：Claude 改稿，Codex 挑刺，确定性规则判断是否继续，最终由用户决定是否合并。

## When To Use / 何时使用

Use this skill when the user asks to:

当用户需要以下事情时使用：

1. Start or stop the local web console. / 启动或停止本机网页控制台。
2. Run a sparring loop on a proposal, report, strategy note, code file, prompt, or `SKILL.md`. / 对方案、报告、策略备忘、代码、提示词或 `SKILL.md` 跑互搏。
3. Explain what the app does and what effect it has on drafts. / 解释应用作用和改稿效果。
4. Run or explain the demo cases. / 运行或讲解演示案例。
5. Inspect `TASK.md`, `STATUS.json`, `FINAL_REVIEW.md`, `FINAL.diff`, and round artifacts. / 检查任务工件。
6. Troubleshoot Claude/Codex CLI detection, auth errors, structured JSON failures, or stuck states. / 排查 CLI、认证、JSON 或卡住状态。

## Do Not Use / 不要用于

Do not use this skill to:

不要用它来：

1. Rewrite whole folders or multi-file projects in v1. / v1 阶段重写整个目录或多文件项目。
2. Process Word, PDF, Excel, or binary files directly. / 直接处理 Word、PDF、Excel 或二进制文件。
3. Auto-merge without explicit user confirmation. / 未经用户确认自动合并。
4. Forward, store, print, or request API keys, tokens, cookies, or passwords. / 转发、保存、打印或索要 API key、token、cookie、密码。
5. Launch a long-running background service unless the user asked to start the local server. / 未经用户要求启动长期后台服务。
6. Deploy the tool to a remote server. / 部署到远程服务器。

## Quick Commands / 快速命令

From the repository root / 在仓库根目录：

```bash
./scripts/doctor.sh
./scripts/start.sh
./scripts/stop.sh
```

Use a specific workspace root / 指定工作区根目录：

```bash
./scripts/start.sh 8765 ~/Documents
```

Open / 打开：

```text
http://127.0.0.1:8765/sparring
```

## Demo Cases / 演示案例

Suggested demo files:

建议演示文件：

- `examples/demo_proposal_zh.md`
- `examples/demo_leadership_memo_en.md`
- `examples/demo_agent_skill.md`
- `examples/demo_python_script.py`

Read `docs/DEMO_CASES.md` for goals and expected effects.

查看 `docs/DEMO_CASES.md` 获取目标填写方式和预期效果。

## Workflow / 工作流

1. Confirm the target is one UTF-8 text file. / 确认目标是单个 UTF-8 文本文件。
2. Turn the user's intent into one concrete improvement goal. / 把用户意图转成一个具体改进目标。
3. Start the local server only if requested. / 只在用户需要时启动本机服务。
4. Create a job from the web UI. / 从网页创建 job。
5. Let the auto loop run, or use manual Builder/Reviewer fallback from generated prompts. / 自动运行，或用生成的 prompt 手动兜底。
6. Inspect `FINAL_REVIEW.md` and `FINAL.diff`. / 检查 `FINAL_REVIEW.md` 和 `FINAL.diff`。
7. Ask the user to choose merge, abandon, or manual follow-up. / 让用户选择合并、放弃或继续手动处理。

## Failure Handling / 失败处理

| Symptom | Action | 现象 | 处理 |
|---|---|---|---|
| Claude not found | Ask the user to install/login to Claude Code CLI, then rerun `scripts/doctor.sh`. | 找不到 Claude | 安装/登录 Claude Code CLI 后重跑体检 |
| Codex not found | Check `/Applications/Codex.app/Contents/Resources/codex` and `~/.codex/auth.json`. | 找不到 Codex | 检查 Codex CLI 路径和 auth 文件 |
| Claude 401 | Ensure the child process strips `ANTHROPIC_*`; use local OAuth login, not API keys. | Claude 401 | 使用本机 OAuth 登录，不走 API key |
| Reviewer JSON parse fails | Open the raw reviewer output and keep only the JSON object. | Reviewer JSON 解析失败 | 只保留 JSON 对象 |
| Job keeps continuing | Read latest `rNNN.reviewer.json`; tighten the goal or accept escalation. | 一直继续 | 看最新审查结果，收紧目标或接受升级 |
| Merge is blocked | Original file changed since snapshot; compare blocked copy before deciding. | 合并阻塞 | 原文件已变化，先对比再决策 |

## Invariants / 不变量

1. Builder edits only `worktree/<file>`. / Builder 只改 `worktree/<file>`。
2. Reviewer never edits files. / Reviewer 不改文件。
3. Judge is deterministic in v1. / v1 的 Judge 是确定性规则。
4. Original file changes only on explicit merge. / 原文件只在明确合并时改变。
5. Every job leaves an audit trail in `jobs/<job_id>/`. / 每个 job 都在 `jobs/<job_id>/` 留痕。
6. No API key is required or forwarded. / 不需要也不转发 API key。
