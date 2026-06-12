# Y1 Sparring Bus v2 升级计划 / v2 Upgrade Plan

> 状态：草案 v0.1 · 待评审
> 一句话目标：**让普通人也能一键用起来，让“改了什么”一眼看懂，让界面配得上“顶级设计”，并为接入更多 AI 留好骨架。**

本文是 v2 的规划文档，不是最终代码。它先盘点 v1 现状，再针对你提的四个方向给出可落地的方案、交付物和验收标准，最后是分阶段路线图、兼容性与风险、以及明确的“非目标”。

---

## 0. 现状盘点 / Where v1 Stands

| 维度 | v1 现状 | 对 v2 的含义 |
|---|---|---|
| 形态 | 单文件 `tools/sparring_center.py`（约 2570 行）：Python 标准库 HTTP 服务 + 内嵌 HTML/CSS/JS 单页 | 零依赖、易分发是优点；但 UI 与逻辑揉在一起，做设计大改前要先理顺 |
| 引擎 | **写死**：Claude CLI = Builder，Codex CLI = Reviewer（`run_builder_cli` / `run_reviewer_cli` / `run_codex_builder_cli`）。可选 Builder 模型（默认 `sonnet`）；Claude 鉴权失败时回退给 Codex 改稿 | “支持更多 AI”需要先把引擎从函数里抽象成“适配器”，否则每加一个模型都要改主流程 |
| 安装 | `scripts/install.sh` 只建目录、修权限、跑 `doctor.sh`；**不安装、也不引导登录** Claude/Codex。Codex 路径硬编码 `/Applications/Codex.app/...` | 安装体验是最大采用门槛：要把“检测 + 引导 + 选引擎”做进流程，并去掉硬编码 |
| 平台 | 仅 macOS（`uname Darwin`、App bundle 路径、LaunchAgent） | 想扩大用户面需要至少让 Linux / WSL 跑通档位 1–3 |
| “改了什么” | `FINAL_REVIEW.md` 偏技术（分数轨迹 + Reviewer JSON 原文）；Builder 每轮写结构化 `changes[]`（位置/改了什么/为什么），但仍是给工程师看的 | 需要一份**大白话**摘要，给非技术用户当“第一眼” |
| 界面 | 克制的“报纸/Rams”风（直角、墨黑+纸白+单一蓝），已较有品味；但桌面优先，仅一个 980px 断点，无暗色、无明显加载/空态、无 i18n 切换 | 设计可以往“顶级”再推一档：信息层级、动效、响应式、可访问性、暗色 |
| 安全红线 | 只绑 `127.0.0.1`；工作区白名单；`assert_source_unchanged_or_restore` 防误写原文；`_clean_env_no_anthropic_api` 剥离 `ANTHROPIC_*` 强制走订阅 | 这些是产品的“魂”，v2 必须原样保留并随多引擎一起扩展 |
| 测试 | 仅 `scripts/smoke-test.sh`，无单元/端到端测试 | 大重构（引擎抽象、UI 拆分）前必须先补测试网，否则风险高 |

**结论**：v1 的核心闭环（Builder→Runner→Reviewer→Judge→人工合并）是扎实的，不需要推倒。v2 是在不破坏“本机优先、不用 API key、人来拍板”这三条魂的前提下，**把易用性、可读性、设计、可扩展性各抬一个台阶。**

---

## 1. 方向一：开箱即用 + 多 AI 引擎（装的时候就把引擎接进流程）

### 1.1 现状痛点
- 用户即使装了 Claude 和 Codex，仍要自己读文档、跑 `doctor.sh --strict`、手动确认 `~/.codex/auth.json`，门槛高。
- 引擎写死在主流程里，加第三个模型要改核心代码。
- Codex 路径、默认模型等硬编码，换机器/换平台就坏。

### 1.2 方案

**A. 引擎适配器层（最高杠杆的改动）**
把“某个 AI 怎么调”从主流程里抽出来，做成统一接口的适配器：

```text
EngineAdapter（接口）
  id            "claude" / "codex" / "gemini" / ...
  display_name  "Claude Code" / "Codex" / ...
  roles         {build, review}   # 这个引擎能当 Builder / Reviewer / 两者
  detect()      -> 路径或 None（取代写死的 which/App 路径）
  version()     -> 版本串
  login_state() -> ok / missing / unknown（+ 修复指引）
  build(job, round, prompt)   -> 改 worktree + 写 builder.json
  review(job, round, prompt)  -> 返回结构化 Reviewer JSON
  install_hint  安装命令 + 官方文档链接
```

- v1 的三个函数重构为 `ClaudeAdapter` / `CodexAdapter`，**行为不变**（默认仍是 Claude 改、Codex 审、Claude 鉴权失败回退 Codex）。
- 新增能力：**Builder 与 Reviewer 引擎都可在新建任务时选择**，默认值保持现状。这样“左右互搏”可以是任意两个模型，而不只是 Claude×Codex。
- 用一个 `config.json`（或 `engines.json`）取代硬编码：启用了哪些引擎、各自路径、默认模型、超时、单价估算。

**B. 把引擎接入做进安装流程**
- `scripts/install.sh` 升级为**引导式安装向导**：检测 OS → 检查 Python → 逐个已知引擎做 `detect + version + login` → 缺哪个就打印**精确的安装/登录命令 + 官方文档链接** → 让用户勾选启用哪些引擎 → 写入 `config.json`。
- 新增**浏览器内首次运行向导**（First-run wizard）：第一次打开页面时，用同一套检查清单以可视化卡片呈现，带“复制命令”“重新检测”“跳过”按钮——让不熟悉终端的用户也能在网页里完成配置。
- `doctor.sh` 改为读取 `config.json`，按“已启用的引擎”而不是写死的 Claude+Codex 来体检。

**C. 跨平台**
- 把 macOS 专属逻辑（Codex App 路径、LaunchAgent）收敛到适配器/平台模块；Linux 与 WSL 至少跑通档位 1–3（本机页面 + 手动接力 + 自动互搏）。后台自启在非 macOS 上降级为说明文档。

### 1.3 交付物
- `tools/engines/`（或同文件内的适配器类）+ `config.json` schema + 迁移默认值。
- 升级版 `scripts/install.sh`（引导式）+ 浏览器首次运行向导。
- 至少**接入第三个引擎**（建议 Gemini CLI 或一个“OpenAI 兼容 CLI”）作为适配器抽象成立的证据。
- `docs/ENGINES.md`：如何新增一个引擎（给贡献者）。

### 1.4 验收
- 在干净的 macOS 与 Linux 上，跟着向导 10 分钟内从零到跑通一轮自动互搏。
- 在 UI 里可以把 Reviewer 从 Codex 换成第三个引擎并成功出分。
- 删掉任意一个引擎的硬编码路径后，仍能通过 `config.json` 找到它。

---

## 2. 方向二：大白话「改了什么」明细 / Plain-Language Change Digest

### 2.1 现状痛点
`FINAL_REVIEW.md` 给的是分数轨迹和 Reviewer JSON，普通用户看不懂“到底动了我什么”。Builder 的 `changes[]` 虽结构化，但措辞仍偏工程。

### 2.2 方案
- 终态时新增一份 `CHANGES_PLAIN.md`（“人话版变更说明”），并在 UI 详情页作为**第一屏的主卡片**呈现，技术细节（diff / JSON）折叠在“展开看细节”里。
- 内容用**大白话 + 分条**，从已有结构化数据聚合而成，例如：

  > 这次主要做了 3 件事：
  > 1. 把结论提到了开头，先说“建议立项”，再讲理由。
  > 2. 删掉了 5 处空话和甩锅式表达（比如“由于客观原因暂时无法……”）。
  > 3. 标出了 2 个没写来源的数字，已请你确认或补来源。
  >
  > 还剩 1 个小问题：第 3 节的预算口径建议再核对一下。
  > 系统建议：可以合并。

- **生成方式（推荐分两层）**：
  1. **确定性模板兜底**（默认、免费、稳定）：把每轮 Builder `changes[]`、被解决的 Reviewer P0/P1、Runner 命中的防御性表达/缺出处数字，映射成口语化条目。
  2. **可选 LLM 润色**：在已启用引擎里挑一个做一次“把上面整理成更顺的人话”，失败则回落到模板。**绝不**因为润色失败而让用户看不到摘要。
- 同时给一个“**改动体量**”一眼指标：影响了几段、加了/删了多少字、修复了几个风险、本次大约花了多少钱/多长时间（成本与耗时 v1 已部分采集）。

### 2.3 交付物 / 验收
- `finalize()` 产出 `CHANGES_PLAIN.md`；UI 详情页“人话摘要”主卡片。
- 验收：让一个没看过本工具的人只读这张卡片，能复述出“改了哪几件事、还剩什么、能不能合并”。

---

## 3. 方向三：召唤“顶级设计”，升级交互与 UI，做浏览器适配

> 把 “jonylev” 理解为 **Jony Ive 式的设计标准**：克制、清晰、有呼吸感、每个状态都被照顾到。当前 UI 已有底子，v2 把它从“干净”推到“讲究”。

### 3.1 交互升级
- 强化“三步心智模型”：**① 选文件 → ② 定目标 → ③ 看结果**，首页用一条清晰主线引导，弱化次要选项。
- 把轮次时间线讲成“一个故事”：每轮“改了什么 / 审出什么 / 判了什么”，配进度态与实时刷新（自动跑时）。
- 错误恢复更有“出口感”：鉴权失败、引擎超时、合并冲突，都给出“下一步该点哪”的明确按钮，而不是只抛红字。
- 细节：键盘可达、一键复制 prompt、空态/加载态/成功态都有专门设计、`FINAL_REVIEW` 的人话卡片做主角。

### 3.2 视觉与设计系统
- 保留单色 + 单一强调色的克制基调，扩展现有 CSS 变量为一套**设计 token**（字阶、间距节奏、圆角、阴影层级、动效时长）。
- 决策卡（verdict card）作为终态视觉重心继续强化；推荐/谨慎/驳回三态色彩语义更清晰。
- 新增**暗色模式**与对比度达标（WCAG AA），补全 focus ring、modal 的 ARIA 语义。

### 3.3 浏览器适配 / 响应式
- 现状仅一个 980px 断点、桌面优先。v2 做**移动 / 平板 / 小窗**的真响应式（在小窗或手机上也可读可用）。
- 跨浏览器：Safari / Chrome / Firefox 实测；保持纯原生（无构建链）以延续“零依赖、易分发”。
- **工程权衡（需决策）**：是否把巨大的内嵌 HTML/CSS/JS 拆成 `tools/web/` 下的独立静态资源，便于做设计大改与维护。
  - 倾向：拆分为独立文件，但仍由标准库服务、随仓库一起分发，**不引入打包工具**，保住单仓库零依赖的优点。

### 3.4 交付物 / 验收
- 重做后的单页（响应式 + 暗色 + a11y），设计 token 文档化。
- 验收：在手机宽度、桌面宽度、Safari/Chrome/Firefox 下，核心流程都顺；Lighthouse 可访问性 ≥ 90。

---

## 4. 方向四：站在使用者与未来的建议 / Recommendations

1. **守住魂，不要长成云平台。** README 已明确列出非目标（云端、多人、自动合并、多文件引擎）。v2 应**加深**本机优先、不用 API key、人来拍板这三条，而不是稀释它们。把“它不是什么”写清楚，是这个项目最大的信任资产。
2. **先补测试网，再做大重构。** 引擎抽象和 UI 拆分都是高风险改动。建议先为 Judge 判定、diff、各路径/合并守卫、源文件防误写写单元测试，并用一个“假引擎适配器”跑端到端，让重构有安全网。
3. **给 job 数据加版本号。** `STATUS.json` 加 `schema_version` 并写一个迁移器，保证 v1 跑出来的旧任务在 v2 里仍能正确渲染。
4. **分发方式是采用率的关键。** 目前最大门槛是“要开终端”。建议提供更傻瓜的入口：`curl | bash` 一键脚本、`pipx`/`brew tap`，或一个**菜单栏小程序 / 双击启动器**。这一步对非技术用户的拉新可能是 10 倍量级。
5. **把适配器抽象当成未来的地基。** 它一次性解锁三件事：接入更多 AI（方向一）、让 Builder/Reviewer 任意组合、以及未来的“评审团”模式（多个 Reviewer 投票，进一步降低单模型偏差）。
6. **让成本与耗时对用户可见。** v1 已部分采集每轮耗时与粗估成本，v2 在结果页给一句“本次约 ¥X、用时 Y 分钟”，建立掌控感。
7. **i18n 做成真切换。** 当前中英是写死并排，v2 把语言做成可切换、文案可外置，为更多语言留口子。
8. **可恢复的自动运行。** 现在自动跑是 daemon 线程，服务重启即标记 stale。可考虑让运行状态可恢复/可续跑，提升长任务可靠性。

---

## 5. 路线图 / Roadmap（建议分 5 阶段）

| 阶段 | 主题 | 内容 | 对应方向 |
|---|---|---|---|
| P0 | 地基（先降风险） | 测试网、`config.json`、引擎适配器重构（**行为不变**）、`STATUS.json` 加 `schema_version` + 迁移器 | 方向 4 / 1 |
| P1 | 开箱即用 | 引导式 `install.sh` + 浏览器首次运行向导 + 多引擎检测/登录引导 + 跨平台路径 + 接入第三个引擎 | 方向 1 |
| P2 | 看得懂 | `CHANGES_PLAIN.md` + UI 人话主卡片 + 改动体量/成本耗时指标 | 方向 2 |
| P3 | 配得上的设计 | UI 拆分为静态资源、设计 token、响应式 + 跨浏览器 + 暗色 + a11y + i18n 切换 | 方向 3 |
| P4 | 收尾发布 | 文档全面更新到 v2、`RELEASE_CHECKLIST` 刷新、演示案例更新、版本号升到 v2.0、README 徽章更新 | 全部 |

> 每个阶段独立可发、可回滚；P0 必须先于 P1/P3，因为它给后面的重构兜底。

---

## 6. 兼容性与风险 / Compatibility & Risks

| 风险 | 说明 | 缓解 |
|---|---|---|
| 重构破坏现有闭环 | 引擎抽象触及核心流程 | P0 先补测试；适配器默认行为与 v1 完全一致 |
| 旧 job 无法渲染 | 数据结构演进 | `schema_version` + 迁移器，旧任务只读兼容 |
| UI 大改引入回归 | 拆分 + 响应式 | 保留纯原生、无构建链；分支灰度；核心流程截图对照 |
| 多引擎扩大攻击面 | 新子进程/新凭证 | 沿用工作区白名单、源文件防误写、`ANTHROPIC_*` 剥离；每引擎超时与“总开关” |
| 范围蔓延 | 容易被“顺手加功能”带偏 | 严守第 7 节非目标 |

---

## 7. v2 明确的非目标 / Non-Goals（防蔓延）

- **不**做云端部署、不做多人协作、不做自动合并（人来拍板这条不动）。
- **不**引入前端构建工具/重框架（保零依赖、易分发）。
- **不**默认改成 API-key 编排（继续走本机订阅授权）。
- 多文件 / 整目录重写是 **v2.x 远期议题**，不进 v2.0 主线。

---

## 8. 成功度量 / Success Metrics

- 新用户从克隆到跑通第一轮自动互搏 ≤ 10 分钟（macOS 与 Linux 各一次）。
- 非技术用户只读“人话摘要”即可独立决定是否合并（可用走廊测试验证）。
- 至少 3 个可互换引擎在 UI 中可选并跑通。
- 移动 + 桌面 + 三大浏览器核心流程通过；可访问性 ≥ 90。
- 旧版 job 在 v2 中 100% 可正常打开。

---

## 附录 A：引擎适配器接口草案（示意，非最终）

```python
class EngineAdapter:
    id: str                      # "claude" / "codex" / "gemini"
    display_name: str
    can_build: bool
    can_review: bool

    def detect(self) -> str | None: ...        # 返回可执行路径，取代写死的 which/App 路径
    def version(self) -> str: ...
    def login_state(self) -> dict: ...          # {"ok": bool, "hint": "...", "doc_url": "..."}
    def build(self, job_dir, round, prompt) -> None: ...   # 改 worktree + 写 builder.json
    def review(self, job_dir, round, prompt) -> dict: ...  # 返回符合 REVIEWER_SCHEMA 的 JSON
    install_hint: dict           # {"cmd": "...", "doc_url": "..."}
```

## 附录 B：config.json 草案（示意）

```json
{
  "schema_version": 2,
  "default_builder": "claude",
  "default_reviewer": "codex",
  "engines": {
    "claude": { "enabled": true,  "path": null, "default_model": "sonnet", "timeout_sec": 900 },
    "codex":  { "enabled": true,  "path": null, "timeout_sec": 900 },
    "gemini": { "enabled": false, "path": null, "timeout_sec": 900 }
  },
  "ui": { "theme": "auto", "lang": "zh" }
}
```
