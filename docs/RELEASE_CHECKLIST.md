# Release Checklist / 发布检查清单

Use this before tagging a public version.

公开发布新版本前，用这份清单检查。

## Local Checks / 本机检查

```bash
bash scripts/install.sh
bash scripts/smoke-test.sh
bash scripts/doctor.sh --strict
python3 -m py_compile tools/sparring_center.py examples/demo_python_script.py
bash -n scripts/*.sh
```

`doctor.sh --strict` may fail on machines without Claude/Codex login. That is expected for contributors who only run CI-style checks.

如果机器没有 Claude/Codex 登录，`doctor.sh --strict` 可能失败。这对只做 CI 检查的贡献者是正常的。

## Content Checks / 内容检查

- README states what works immediately and what needs local login.  
  README 说明哪些下载即用，哪些需要本机登录。
- Install docs include `install.sh`, `smoke-test.sh`, `doctor.sh --strict`, `start.sh`, and service scripts.  
  安装文档包含安装、自检、启动和后台服务脚本。
- Demo cases exist and are linked from README.  
  演示案例存在并从 README 链接。
- No private jobs, logs, API keys, tokens, cookies, or personal files are committed.  
  没有提交私人 job、日志、API key、token、cookie 或个人文件。

## GitHub Checks / GitHub 检查

- Repository visibility is public.  
  仓库可见性是 public。
- License is present.  
  有许可证。
- CI passes.  
  CI 通过。
- Release tag is created, for example `v1.0.0`.  
  创建发布 tag，例如 `v1.0.0`。
- Release notes mention that full auto mode requires local Claude/Codex login.  
  Release notes 说明完整自动模式需要本机 Claude/Codex 登录。

## Nice-To-Have / 可选增强

- Add screenshots or a short demo GIF.  
  增加截图或短 GIF。
- Add GitHub topics such as `ai`, `local-first`, `claude`, `codex`, `agent-tools`.  
  增加 GitHub topics。
- Add issues for future work: multi-file mode, better import/export, more runner checks.  
  建未来规划 issue：多文件、导入导出、更多检查规则。
