# Demo Cases / 演示案例

This page gives you ready-to-run demo cases for Y1 Sparring Bus. Each case includes a source file, a goal to paste into the UI, and the effect you should expect after the loop runs.

本页提供可直接运行的 Y1 Sparring Bus 演示案例。每个案例都包含源文件、可粘贴到页面里的目标，以及跑完后应该看到的效果。

## How To Run / 如何运行

1. Start the server. / 启动服务。

```bash
./scripts/start.sh
```

2. Open `http://127.0.0.1:8765/sparring`. / 打开页面。
3. Choose one file under `examples/`. / 选择 `examples/` 下的一个文件。
4. Paste the suggested goal. / 粘贴建议目标。
5. Start the job and inspect `FINAL_REVIEW.md` + `FINAL.diff`. / 启动任务，然后查看 `FINAL_REVIEW.md` 和 `FINAL.diff`。

## Case 1: Chinese Proposal Polish / 中文方案改稿

Source / 源文件：

```text
examples/demo_proposal_zh.md
```

Goal / 目标：

```text
把这份方案改成适合领导评审的版本：结论前置，删掉防御性表达，补清楚投入产出逻辑，不编造数据。
```

Expected effect / 预期效果：

- The vague opening becomes a clearer recommendation.  
  含糊开头会变成更明确的建议。
- Defensive phrases such as "由于客观原因" and "后续再补" should be removed or reframed.  
  “由于客观原因”“后续再补”等防御性表达会被移除或改写。
- Numbers should be treated as assumptions unless evidence is added.  
  数字会被处理为假设，而不是被包装成确定事实。

## Case 2: English Leadership Memo / 英文管理备忘

Source / 源文件：

```text
examples/demo_leadership_memo_en.md
```

Goal / 目标：

```text
Rewrite this into a crisp leadership memo: decision first, risks explicit, next actions concrete, no filler.
```

Expected effect / 预期效果：

- The memo should start with the decision needed.  
  备忘录应以待决策事项开头。
- Risks should become explicit instead of hidden in vague wording.  
  风险会从模糊表达里抽出来。
- Action owners and dates should become clearer, or be marked as missing.  
  行动负责人和时间会更清楚，缺失项会被标出。

## Case 3: Agent Skill Tightening / Skill 边界收紧

Source / 源文件：

```text
examples/demo_agent_skill.md
```

Goal / 目标：

```text
Improve this skill spec: clarify triggers, non-goals, safety boundaries, and failure handling. Keep it practical.
```

Expected effect / 预期效果：

- Trigger rules should become more concrete.  
  触发规则会更具体。
- Non-goals and safety boundaries should be easier to enforce.  
  非目标和安全边界会更容易执行。
- Failure handling should become operational, not aspirational.  
  失败处理会从口号变成可操作步骤。

## Case 4: Python Review / Python 代码审查

Source / 源文件：

```text
examples/demo_python_script.py
```

Goal / 目标：

```text
Review and improve this small script without changing its basic purpose. Fix correctness, clarity, and edge cases.
```

Expected effect / 预期效果：

- Input validation should improve.  
  输入校验会更稳。
- Edge cases such as empty files, malformed rows, or division by zero should be handled.  
  空文件、坏行、除零等边界情况会被处理。
- The script should remain small and easy to read.  
  脚本仍应保持小而清楚。

## Reading The Result / 如何看结果

After a demo finishes, read these files:

演示跑完后，重点看这些文件：

```text
FINAL_REVIEW.md
FINAL.diff
rounds/r001.reviewer.json
rounds/r001.judge.json
```

Use `FINAL_REVIEW.md` as the human decision brief. Use `FINAL.diff` to inspect the exact changes.

把 `FINAL_REVIEW.md` 当成人工决策简报，把 `FINAL.diff` 用来检查精确改动。
