# Run Modes / 可用模式

This project is local-first. "Download and run" has different meanings depending on what is already installed on the user's Mac.

这个项目是本机优先的。“下载后能用”取决于用户电脑上已经装好了哪些东西。

## The Honest Answer / 真实答案

After download, the repository can immediately provide docs, examples, local scripts, and a Python backend smoke test.

下载后，仓库本身立刻提供文档、演示文件、本机脚本和 Python 后端烟测。

Full automatic sparring needs local Claude Code CLI and Codex CLI login. The repo cannot and should not create those accounts or logins for the user.

完整自动互搏需要用户本机已经登录 Claude Code CLI 和 Codex CLI。仓库不能、也不应该替用户创建账号或登录。

## Capability Levels / 能力档位

| Level | Works after clone? | Requirements | What works | 档位 | 下载后是否可用 | 要求 | 可用能力 |
|---|---|---|---|---|---|---|---|
| 0 | yes | none | read docs and examples | 0 | 是 | 无 | 阅读文档和演示 |
| 1 | yes, if Python exists | Python 3.9+ | start local web backend, browse UI, run smoke test | 1 | 有 Python 即可 | Python 3.9+ | 启动本机页面、运行后端烟测 |
| 2 | partly | Python + any external LLM access | manual Builder/Reviewer handoff using generated prompts | 2 | 部分可用 | Python + 任意可用 LLM | 手动复制 prompt 接力 |
| 3 | yes, after login | Python + Claude Code CLI + Codex CLI | full automatic Claude Builder + Codex Reviewer loop | 3 | 登录后可用 | Python + Claude/Codex CLI | 完整自动互搏 |
| 4 | optional | level 1 or 3 | run local backend at login through LaunchAgent | 4 | 可选 | 1 或 3 | 开机后台启动 |

## Recommended First Run / 推荐首次运行

```bash
bash scripts/install.sh
bash scripts/smoke-test.sh
bash scripts/doctor.sh --strict
```

Interpretation / 如何理解：

- `install.sh` prepares local folders and checks the basic environment.  
  `install.sh` 准备本机目录并做基础检查。
- `smoke-test.sh` proves the local Python backend can start and answer requests.  
  `smoke-test.sh` 证明本机 Python 后端能启动并响应。
- `doctor.sh --strict` tells you whether full automatic sparring is ready.  
  `doctor.sh --strict` 判断完整自动互搏是否就绪。

## Why It May Feel Uncertain / 为什么会觉得不确定

The repo has no Python package dependencies, but it depends on external desktop tools for the full experience:

仓库没有 Python 第三方包依赖，但完整体验依赖外部桌面工具：

- Claude Code CLI must be installed and logged in locally.  
  Claude Code CLI 必须已安装并本机登录。
- Codex CLI must be available and logged in locally.  
  Codex CLI 必须可用并本机登录。
- The selected file must be a normal UTF-8 text file under the workspace root.  
  目标文件必须是工作区内的普通 UTF-8 文本文件。
- The backend binds to `127.0.0.1`, so it is a local backend, not a cloud backend.  
  后端绑定 `127.0.0.1`，所以它是本机后端，不是云端后端。

That uncertainty is intentional: credentials stay with the user's local tools, not inside this repository.

这种不确定性是有意保留的：账号凭证留在用户自己的本机工具里，而不是放进这个仓库。
