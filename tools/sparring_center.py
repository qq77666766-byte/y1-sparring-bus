#!/usr/bin/env python3
"""Local web control center for Sparring Bus jobs.

This intentionally uses only the Python standard library so the local page can
run before any heavier framework choices are made. Jobs live under
`jobs/<job_id>/` with `mode: sparring`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = APP_ROOT  # Backward-compatible internal name used by older functions.
WORKSPACE_ROOT = Path(os.environ.get("SPARRING_WORKSPACE_ROOT", str(APP_ROOT.parent))).expanduser().resolve()
JOBS_ROOT = APP_ROOT / "jobs"
DEFAULT_PORT = 8765
DEFAULT_BUILDER_MODEL = "sonnet"
WARN_SOURCE_BYTES = 200_000
AUTO_THREADS: dict[str, threading.Thread] = {}
AUTO_LOCK = threading.Lock()


# 问题必须带证据：desc 说问题，evidence 是当前文件里的原文引用（用于机器核验），location 是大致位置。
REVIEWER_ISSUE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["desc", "evidence", "location"],
    "properties": {
        "desc": {"type": "string"},
        "evidence": {"type": "string"},
        "location": {"type": "string"},
    },
}

REVIEWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["round", "actor", "issues", "issue_resolutions", "scores", "verdict", "summary"],
    "properties": {
        "round": {"type": "integer"},
        "actor": {"type": "string", "enum": ["reviewer"]},
        "issues": {
            "type": "object",
            "additionalProperties": False,
            "required": ["p0", "p1", "p2"],
            "properties": {
                "p0": {"type": "array", "items": REVIEWER_ISSUE_ITEM},
                "p1": {"type": "array", "items": REVIEWER_ISSUE_ITEM},
                "p2": {"type": "array", "items": REVIEWER_ISSUE_ITEM},
            },
        },
        "issue_resolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "status", "note"],
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string", "enum": ["resolved", "persisting", "withdrawn"]},
                    "note": {"type": "string"},
                },
            },
        },
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "required": ["requirement_fit", "correctness", "clarity", "risk"],
            "properties": {
                "requirement_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                "correctness": {"type": "integer", "minimum": 0, "maximum": 100},
                "clarity": {"type": "integer", "minimum": 0, "maximum": 100},
                "risk": {"type": "integer", "minimum": 0, "maximum": 100},
            },
        },
        "verdict": {"type": "string", "enum": ["accept", "accept_with_minors", "needs_revision", "reject"]},
        "summary": {"type": "string"},
    },
}


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s.strip())
    return s.strip("-")[:48] or "file"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_ledger(job_dir: Path, event: str, **fields: Any) -> None:
    row = {"ts": now(), "event": event, **fields}
    with (job_dir / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def update_status(job_dir: Path, **fields: Any) -> dict[str, Any]:
    status_path = job_dir / "STATUS.json"
    status = read_json(status_path, {})
    status.update(fields)
    status["updated_at"] = now()
    write_json(status_path, status)
    return status


def file_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def source_path_from_status(status: dict[str, Any]) -> Path:
    raw = status.get("source_path", "")
    if not raw:
        raise ValueError("STATUS.json 缺少 source_path")
    return Path(raw).expanduser().resolve()


def validate_text_source(path: Path) -> None:
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("v1 只支持非空文本文件")
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "v1 只支持 UTF-8 文本文件；请先把 Word/PDF/Excel/二进制文件转成 .md/.txt 后再互搏"
        ) from exc


def assert_source_unchanged_or_restore(job_dir: Path, before: bytes, phase: str) -> None:
    """Protect the original file from accidental agent writes.

    The product promise is that agents only edit the isolated worktree copy.
    Claude CLI is not filesystem-sandboxed here, so we enforce that promise by
    checking the source file after each Builder subprocess and restoring it if
    it changed.
    """
    status = read_json(job_dir / "STATUS.json", {})
    source = source_path_from_status(status)
    after = file_bytes(source)
    if after == before:
        return
    violation = job_dir / f"ORIGINAL_WRITE_VIOLATION.{slug(phase)}.{source.name}"
    violation.write_bytes(after)
    source.write_bytes(before)
    append_ledger(
        job_dir,
        "source_write_violation_restored",
        phase=phase,
        source_path=str(source),
        violation_copy=str(violation),
    )
    raise RuntimeError(
        f"{phase} 试图修改原文件，系统已恢复原文件并停止自动运行；"
        f"误写内容已保存到 {violation.name}"
    )


def safe_workspace_file(raw_path: str) -> Path:
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = WORKSPACE_ROOT / p
    p = p.resolve()
    if not p.exists() or not p.is_file():
        raise ValueError(f"文件不存在或不是普通文件：{p}")
    try:
        p.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError(f"v1 只允许选择工作区根目录内的文件：{p}") from exc
    blocked_roots = [
        JOBS_ROOT,
        REVIEW_ROOT / "tools",
        REVIEW_ROOT / "scripts",
        REVIEW_ROOT / "docs",
        REVIEW_ROOT / "assets",
        REVIEW_ROOT / "screenshots",
        REVIEW_ROOT / ".git",
    ]
    if p.parent == REVIEW_ROOT:
        raise ValueError("不要选择工具安装目录根文件作为互搏目标")
    for blocked in blocked_roots:
        try:
            p.relative_to(blocked.resolve())
            raise ValueError("不要选择工具内部文件作为互搏目标")
        except ValueError as exc:
            if str(exc).startswith("不要选择"):
                raise
    return p


def cli_health() -> dict[str, Any]:
    claude = shutil.which("claude")
    codex = shutil.which("codex")
    app_codex = Path("/Applications/Codex.app/Contents/Resources/codex")
    if not codex and app_codex.exists():
        codex = str(app_codex)
    return {
        "workspace": str(WORKSPACE_ROOT),
        "app_root": str(REVIEW_ROOT),
        "review_root": str(REVIEW_ROOT),
        "jobs_root": str(JOBS_ROOT),
        "sample_path": str(REVIEW_ROOT / "examples" / "demo_proposal_zh.md"),
        "claude_cli": claude,
        "codex_cli": codex,
        "cli_detected": bool(claude and codex),
        "auto_mode_available": bool(claude and codex),
        "auto_mode_note": "检测到 Claude/Codex CLI 时可自动运行；失败时仍可回到手动接力。",
    }


def target_name(status: dict[str, Any]) -> str:
    return status.get("target_name") or Path(status.get("source_path", "target.md")).name


def job_dir_for(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", job_id):
        raise ValueError("非法 job_id")
    job_dir = JOBS_ROOT / job_id
    if not job_dir.exists():
        raise FileNotFoundError(job_id)
    return job_dir


def job_summary(job_dir: Path) -> dict[str, Any]:
    status = read_json(job_dir / "STATUS.json", {})
    rounds_dir = job_dir / "rounds"
    files = sorted(p.name for p in rounds_dir.glob("*")) if rounds_dir.exists() else []
    status["job_id"] = job_dir.name
    status["round_files"] = files
    status["has_final"] = (job_dir / "FINAL_REVIEW.md").exists()
    return status


def browse_dir(raw_path: str | None) -> dict[str, Any]:
    """服务端目录浏览：返回 path 下的子目录 + 文件清单，强制只能在工作区内。"""
    p = Path(raw_path).expanduser() if raw_path else WORKSPACE_ROOT
    if not p.is_absolute():
        p = WORKSPACE_ROOT / p
    p = p.resolve()
    try:
        p.relative_to(WORKSPACE_ROOT)
    except ValueError:
        p = WORKSPACE_ROOT
    if not p.is_dir():
        p = p.parent if p.parent.exists() else WORKSPACE_ROOT

    review_root_resolved = REVIEW_ROOT.resolve()
    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if child.name.startswith("."):
                continue
            try:
                child.relative_to(review_root_resolved)
                continue  # 屏蔽工具内部
            except ValueError:
                pass
            try:
                stat = child.stat()
            except OSError:
                continue
            entries.append({
                "name": child.name,
                "path": str(child),
                "is_dir": child.is_dir(),
                "size": stat.st_size if child.is_file() else None,
            })
    except PermissionError:
        pass

    parent = None
    if p != WORKSPACE_ROOT:
        try:
            p.parent.relative_to(WORKSPACE_ROOT)
            parent = str(p.parent)
        except ValueError:
            parent = str(WORKSPACE_ROOT)

    rel = ""
    try:
        rel = str(p.relative_to(WORKSPACE_ROOT))
        if rel == ".":
            rel = ""
    except ValueError:
        rel = ""

    return {
        "path": str(p),
        "rel": rel,
        "parent": parent,
        "workspace": str(WORKSPACE_ROOT),
        "entries": entries,
    }


def preflight_check(source_path: str, goal: str, content: str = "", title: str = "") -> dict[str, Any]:
    """开始互搏前的预检：文件 / 目标 / 一致性 / 内容预览。content 非空时走"贴文本"模式。"""
    checks: list[dict[str, Any]] = []
    preview = ""
    src: Path | None = None

    paste_mode = bool((content or "").strip())
    if paste_mode:
        text = content
        size = len(text.encode("utf-8"))
        checks.append({"item": "粘贴内容", "status": "pass", "detail": f"{size} bytes"})
        if size > WARN_SOURCE_BYTES:
            checks.append({"item": "内容大小", "status": "warn",
                           "detail": f"{size} bytes，长文本可能触发 Claude CLI 单轮保护阈值"})
        if not (title or "").strip():
            checks.append({"item": "标题", "status": "warn", "detail": "未填，将用 pasted 作为文件名"})
        else:
            checks.append({"item": "标题", "status": "pass", "detail": title.strip()[:60]})
        checks.append({"item": "落盘位置", "status": "pass",
                       "detail": f"{INBOX_DIRNAME}/（工作区内，自动创建）"})
        preview = text[:500]

    raw = (source_path or "").strip()
    if paste_mode:
        pass
    elif not raw:
        checks.append({"item": "文件路径", "status": "fail", "detail": "未填写"})
    else:
        try:
            src = safe_workspace_file(raw)
            size = src.stat().st_size
            checks.append({"item": "文件存在且可读", "status": "pass",
                           "detail": f"{src.name} · {size} bytes"})
            checks.append({"item": "在工作区内", "status": "pass",
                           "detail": str(src.relative_to(WORKSPACE_ROOT))})
            if size == 0:
                checks.append({"item": "文件非空", "status": "fail", "detail": "0 字节"})
            else:
                checks.append({"item": "文件非空", "status": "pass"})
                if size > WARN_SOURCE_BYTES:
                    checks.append({"item": "文件大小", "status": "warn",
                                   "detail": f"{size} bytes，长文件可能触发 Claude CLI 单轮保护阈值"})
                else:
                    checks.append({"item": "文件大小", "status": "pass",
                                   "detail": f"{size} bytes"})
                try:
                    preview = src.read_text(encoding="utf-8")[:500]
                except UnicodeDecodeError:
                    preview = "(二进制文件，v1 暂不支持)"
                    checks.append({"item": "文件可解码为文本", "status": "fail"})
                else:
                    checks.append({"item": "文件可解码为文本", "status": "pass"})
        except ValueError as exc:
            checks.append({"item": "文件路径合规", "status": "fail", "detail": str(exc)})

    g = (goal or "").strip()
    if not g:
        checks.append({"item": "目标已填", "status": "fail", "detail": "空"})
    elif len(g) < 8:
        checks.append({"item": "目标具体度", "status": "warn",
                       "detail": f"只有 {len(g)} 字，建议 ≥ 8"})
    else:
        checks.append({"item": "目标已填", "status": "pass",
                       "detail": f"{len(g)} 字"})

    # 一致性（启发式）：目标关键词 vs 文件扩展名
    if src and g:
        suffix = src.suffix.lower()
        code_kw = any(k in g for k in ["代码", "脚本", "重构", "函数", "API", "bug", "测试覆盖"])
        doc_kw = any(k in g for k in ["方案", "汇报", "复盘", "提案", "稿", "报告", "口径", "结论"])
        data_kw = any(k in g for k in ["表格", "数据集", "字段", "对账", "清洗"])
        code_ext = suffix in {".py", ".js", ".ts", ".html", ".css", ".sh", ".go", ".rs", ".rb", ".java"}
        doc_ext = suffix in {".md", ".markdown", ".txt", ".docx", ".rst"}
        data_ext = suffix in {".csv", ".tsv", ".xlsx", ".json"}
        if code_kw and not code_ext:
            checks.append({"item": "目标↔文件类型一致", "status": "warn",
                           "detail": f"目标含'代码/脚本'类词，但后缀是 {suffix or '(无)'}"})
        elif doc_kw and not doc_ext:
            checks.append({"item": "目标↔文件类型一致", "status": "warn",
                           "detail": f"目标含'方案/汇报'类词，但后缀是 {suffix or '(无)'}"})
        elif data_kw and not data_ext:
            checks.append({"item": "目标↔文件类型一致", "status": "warn",
                           "detail": f"目标含'数据/表格'类词，但后缀是 {suffix or '(无)'}"})
        else:
            checks.append({"item": "目标↔文件类型一致", "status": "pass"})

    has_fail = any(c["status"] == "fail" for c in checks)
    warns = [c for c in checks if c["status"] == "warn"]
    return {
        "ok": not has_fail,
        "checks": checks,
        "preview": preview,
        "warn_count": len(warns),
    }


INBOX_DIRNAME = "sparring-inbox"


def materialize_pasted_content(title: str, content: str) -> Path:
    """把用户粘贴的文本落盘到工作区 sparring-inbox/，作为互搏源文件。"""
    if not (content or "").strip():
        raise ValueError("粘贴内容不能为空")
    inbox = WORKSPACE_ROOT / INBOX_DIRNAME
    inbox.mkdir(parents=True, exist_ok=True)
    # 标题保留中文（slug 只认 ASCII，会把中文标题剥成空）
    safe_title = re.sub(r"[^\w一-鿿.-]+", "-", (title or "").strip()).strip("-")[:48] or "pasted"
    name = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe_title}.md"
    p = inbox / name
    p.write_text(content, encoding="utf-8")
    return p


def notify_user(title: str, message: str) -> None:
    """macOS 系统通知（osascript 自带，非 macOS / 失败静默跳过）。互搏一轮要几分钟，人多半走开了。"""
    osa = shutil.which("osascript")
    if not osa:
        return
    try:
        script = f"display notification {json.dumps(message[:180], ensure_ascii=False)} " \
                 f"with title {json.dumps(title[:80], ensure_ascii=False)} sound name \"Glass\""
        subprocess.run([osa, "-e", script], capture_output=True, timeout=10)
    except Exception:
        pass


def export_final(job_dir: Path) -> dict[str, Any]:
    """把最终稿另存为原文件旁边的副本，不动原文件。适合结果要贴去别处的场景。"""
    status, _snap, work_file, _rounds = current_paths(job_dir)
    final = job_dir / "FINAL.md"
    src_of_copy = final if final.exists() else work_file
    if not src_of_copy.exists():
        raise ValueError("还没有可导出的稿件（FINAL.md 和 worktree 都不存在）")
    source = source_path_from_status(status)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = source.suffix or ".md"
    dest = source.parent / f"{source.stem}.sparring-{ts}{suffix}"
    dest.write_text(file_text(src_of_copy), encoding="utf-8")
    append_ledger(job_dir, "final_exported_copy", dest=str(dest))
    return {"dest": str(dest), "job": job_summary(job_dir)}


def list_jobs() -> list[dict[str, Any]]:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for p in JOBS_ROOT.iterdir():
        if not p.is_dir():
            continue
        st = read_json(p / "STATUS.json", {})
        if st.get("mode") == "sparring":
            jobs.append(job_summary(p))
    return sorted(jobs, key=lambda x: x.get("created_at", ""), reverse=True)


def create_job(source_path: str, goal: str, max_rounds: int = 5, threshold: int = 85, auto_run: bool = False) -> dict[str, Any]:
    source = safe_workspace_file(source_path)
    validate_text_source(source)
    if not goal.strip():
        raise ValueError("目标不能为空")
    max_rounds = max(1, min(int(max_rounds), 8))
    threshold = max(50, min(int(threshold), 100))

    job_id = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-sparring-{slug(source.stem)}"
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    for child in ["INPUT_SNAPSHOT", "worktree", "rounds"]:
        (job_dir / child).mkdir()

    snap_file = job_dir / "INPUT_SNAPSHOT" / source.name
    work_file = job_dir / "worktree" / source.name
    shutil.copy2(source, snap_file)
    shutil.copy2(source, work_file)
    # 第一轮的 Builder 开始前基线 = 原文（用于 per-round diff）
    shutil.copy2(source, job_dir / "rounds" / f"r001.before_builder.{source.name}")
    try:
        os.chmod(snap_file, 0o444)
    except OSError:
        pass

    task = f"""# TASK

mode: sparring

## Source

- original: `{source}`
- worktree: `worktree/{source.name}`

## Goal

{goal.strip()}

## Acceptance

- requirement_fit >= {threshold}
- P0 = 0
- P1 = 0
- Runner checks have no blocking failure
- Scope stays inside `worktree/{source.name}`

## Roles

- Builder edits only the worktree copy.
- Reviewer reviews patch and current file; Reviewer does not edit.
- Judge is currently deterministic in v1: score + issue counts + round limit.

## Limits

- max_rounds: {max_rounds}
- final merge requires explicit human confirmation.
"""
    (job_dir / "TASK.md").write_text(task, encoding="utf-8")

    status = {
        "job_id": job_id,
        "mode": "sparring",
        "state": "WAIT_BUILDER",
        "round": 1,
        "max_rounds": max_rounds,
        "threshold": threshold,
        "source_path": str(source),
        "target_name": source.name,
        "goal": goal.strip(),
        "created_at": now(),
        "updated_at": now(),
        "scores_trend": [],
        "manual_mode": not auto_run,
        "auto_requested": bool(auto_run),
        "auto_running": False,
    }
    write_json(job_dir / "STATUS.json", status)
    append_ledger(job_dir, "job_created", source_path=str(source), goal=goal.strip())
    build_builder_prompt(job_dir)
    return job_summary(job_dir)


def file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "(binary file not shown)"
    except FileNotFoundError:
        return ""


def current_paths(job_dir: Path) -> tuple[dict[str, Any], Path, Path, Path]:
    status = read_json(job_dir / "STATUS.json", {})
    name = target_name(status)
    return status, job_dir / "INPUT_SNAPSHOT" / name, job_dir / "worktree" / name, job_dir / "rounds"


def build_builder_prompt(job_dir: Path) -> Path:
    status, _snap, work_file, rounds = current_paths(job_dir)
    r = int(status.get("round", 1))
    previous_review = file_text(rounds / f"r{r-1:03d}.reviewer.json") if r > 1 else "(first round)"
    previous_judge = file_text(rounds / f"r{r-1:03d}.judge.json") if r > 1 else "(first round)"
    ledger_brief = issue_ledger_brief(load_issues(job_dir))
    prompt = f"""你是 Y1 Sparring Bus 的 Builder。

你的任务：只修改隔离副本，不碰原文件。

必须读取：
- 任务说明：{job_dir / "TASK.md"}
- 目标文件：{work_file}

当前轮次：Round {r}

## 待闭环问题台账（必须逐条处理）

{ledger_brief}

对每一条 open 问题，你只有两种处理方式：
1. 修复它（在 builder.json 的 addressed_issues 里写上它的 ID）；
2. 有理有据地反驳它（在 builder.json 的 disputes 里写 ID + 理由）。
   标记"必须修，不可再反驳"的问题不允许反驳，只能修。
不允许无视任何 open 问题。反驳会交给 Reviewer 仲裁：Reviewer 撤回则问题关闭；
Reviewer 坚持 {DISPUTE_UPHOLD_LIMIT} 次后问题升级为"必须修"。

上一轮 Reviewer：
```json
{previous_review}
```

上一轮 Judge：
```json
{previous_judge}
```

硬规则：
- 只允许修改 `{work_file}`。
- 不要修改原文件 `{status.get("source_path")}`。
- 不要改工具目录 `{REVIEW_ROOT}` 下除本 job `rounds` 记录以外的任何文件。
- 不要扩大任务范围。
- 不要编造数据来源。
- 结论前置，删掉空话和防御性表达。

完成后，把本轮说明写入：
{rounds / f"r{r:03d}.builder.json"}

JSON 格式：
{{
  "round": {r},
  "actor": "builder",
  "changes_summary": "一句话说明本轮改了什么",
  "changes": [
    {{"location": "位置", "what": "改了什么", "why": "为什么改"}}
  ],
  "addressed_issues": ["修复了的问题 ID，例如 R1-P1-1"],
  "disputes": [
    {{"id": "要反驳的问题 ID", "reason": "为什么这个问题不成立（引用原文或任务目标）"}}
  ],
  "remaining_concerns": []
}}

如果你无法直接写文件，就把修改后的全文输出给用户，让用户手动替换 `{work_file}`。
"""
    out = rounds / f"r{r:03d}.builder.prompt.md"
    out.write_text(prompt, encoding="utf-8")
    update_status(job_dir, state="WAIT_BUILDER")
    return out


def run_checks(work_file: Path) -> tuple[str, int]:
    suffix = work_file.suffix.lower()
    text = file_text(work_file)
    lines = [f"# Runner checks - {work_file.name}", ""]
    failures = 0

    if suffix in {".md", ".markdown", ".txt"}:
        if suffix in {".md", ".markdown"} and not re.search(r"^#\s+\S", text, re.M):
            failures += 1
            lines.append("- FAIL structure_h1: Markdown 缺少 H1 标题")
        else:
            lines.append("- PASS structure")

        cya = []
        for pat in [r"我们?不做", r"我们?不能", r"由于客观原因", r"出于(?:成本|时间|资源)考虑", r"暂时无法"]:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                cya.append(f"line {line}: {m.group(0)}")
        if cya:
            failures += 1
            lines.append("- FAIL cya_check: 命中防御性表达")
            lines.extend(f"  - {x}" for x in cya[:12])
        else:
            lines.append("- PASS cya_check")

        suspicious = []
        for m in re.finditer(r"\d+(?:\.\d+)?\s?(?:%|％|万|亿|倍|人|元)", text):
            win = text[max(0, m.start() - 30): min(len(text), m.end() + 40)]
            if not re.search(r"(来源|出处|口径|数据|20\d{2}|平台|后台|生意经)", win):
                line = text[: m.start()].count("\n") + 1
                suspicious.append(f"line {line}: {m.group(0)}")
        if suspicious:
            lines.append("- WARN number_sources: 部分数字疑似缺出处")
            lines.extend(f"  - {x}" for x in suspicious[:12])
        else:
            lines.append("- PASS number_sources")
    elif suffix == ".py":
        proc = subprocess.run([sys.executable, "-m", "py_compile", str(work_file)], capture_output=True, text=True)
        if proc.returncode:
            failures += 1
            lines.append("- FAIL py_compile")
            lines.append(proc.stderr.strip())
        else:
            lines.append("- PASS py_compile")
    else:
        lines.append(f"- SKIP unsupported_type: {suffix or '(none)'}")

    lines.append("")
    lines.append(f"Summary: {failures} failure(s)")
    return "\n".join(lines), failures


def prepare_reviewer(job_dir: Path) -> dict[str, Any]:
    status, snap_file, work_file, rounds = current_paths(job_dir)
    if status.get("state") != "WAIT_BUILDER":
        raise ValueError(
            f"当前 state={status.get('state')}，只能在 WAIT_BUILDER 才能切到 Reviewer"
        )
    r = int(status.get("round", 1))

    # 硬前置：Builder 必须留下 builder.json 自述
    builder_json_path = rounds / f"r{r:03d}.builder.json"
    if not builder_json_path.exists():
        raise ValueError(
            f"Builder 未留下 r{r:03d}.builder.json（修改理由）；请回去补一份再继续"
        )

    # 本轮 diff：从"本轮 Builder 开始前"的 baseline 算起
    baseline_path = rounds / f"r{r:03d}.before_builder.{work_file.name}"
    if not baseline_path.exists():
        # 老 job 或第一轮缺失时回落到 INPUT_SNAPSHOT
        baseline_path = snap_file
    original = file_text(baseline_path).splitlines(keepends=True)
    current = file_text(work_file).splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(
        original, current,
        fromfile=f"baseline/{work_file.name}",
        tofile=f"worktree/{work_file.name}",
    ))
    if not diff:
        diff = "(no diff)"
    patch_path = rounds / f"r{r:03d}.builder.patch"
    patch_path.write_text(diff, encoding="utf-8")

    checks_log, failures = run_checks(work_file)
    runner_path = rounds / f"r{r:03d}.runner.log"
    runner_path.write_text(checks_log, encoding="utf-8")

    # Builder 可能反驳了台账里的问题：先登记，交给 Reviewer 仲裁
    disputes = apply_builder_disputes(job_dir, r)
    ledger_brief = issue_ledger_brief(load_issues(job_dir))
    dispute_brief = "\n".join(
        f"- [{d['id']}] Builder 反驳理由：{d['reason']}" for d in disputes
    ) if disputes else "(本轮 Builder 没有反驳任何问题)"

    builder_json = file_text(rounds / f"r{r:03d}.builder.json") or "(builder json missing)"
    prompt = f"""你是 Y1 Sparring Bus 的 Reviewer。你只审查，不修改文件。

必须读取：
- TASK: {job_dir / "TASK.md"}
- 当前文件: {work_file}
- 本轮 diff: {patch_path}
- Runner log: {runner_path}
- Builder 自述: {rounds / f"r{r:03d}.builder.json"}

## 待闭环问题台账（每条都必须表态）

{ledger_brief}

## Builder 本轮的反驳（需要你仲裁）

{dispute_brief}

对台账里每一条 open 问题，你必须在 issue_resolutions 里给出一条裁定：
- "resolved"：你核对当前文件后确认已修好；
- "persisting"：还没修好（或反驳不成立），说明理由；
- "withdrawn"：你撤回这个问题（Builder 反驳成立，或你重新判断后认为不成立）。
不要把台账里已有的问题重新写进 issues 的新问题列表。

新问题的硬要求：每条必须带 evidence —— 从当前文件里逐字引用一段原文作为证据
（系统会机器核验引用是否真实存在；引用不存在的 P0/P1 会被标记为"无证据"并公示）。
不允许只凭印象打分或凭空造问题。

本轮 Builder 自述：
```json
{builder_json}
```

本轮 diff：
```diff
{diff[:12000]}
```

Runner 结果：
```text
{checks_log}
```

请按 P0/P1/P2 审查。P0 是阻断，P1 是必须修，P2 是可选增强。

只输出 JSON，不要写长解释。JSON 格式：
{{
  "round": {r},
  "actor": "reviewer",
  "issues": {{
    "p0": [{{"desc": "问题描述", "evidence": "当前文件原文引用", "location": "大致位置"}}],
    "p1": [],
    "p2": []
  }},
  "issue_resolutions": [
    {{"id": "台账问题 ID，如 R1-P1-1", "status": "resolved | persisting | withdrawn", "note": "一句话理由"}}
  ],
  "scores": {{
    "requirement_fit": 0,
    "correctness": 0,
    "clarity": 0,
    "risk": 0
  }},
  "verdict": "accept | accept_with_minors | needs_revision | reject",
  "summary": "两句话：什么对了，什么还没对"
}}

如果你能写文件，也可以把 JSON 写到：
{rounds / f"r{r:03d}.reviewer.json"}
"""
    prompt_path = rounds / f"r{r:03d}.reviewer.prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    update_status(job_dir, state="WAIT_REVIEWER", runner_failures=failures)
    append_ledger(job_dir, "reviewer_prompt_prepared", round=r, runner_failures=failures)
    return {"prompt": prompt, "diff": diff, "runner_log": checks_log}


def issue_count(issues: Any, key: str) -> int:
    if not isinstance(issues, dict):
        return 0
    value = issues.get(key, [])
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int):
        return value
    return 0


# ---------------------------------------------------------------------------
# 问题闭环台账（ISSUES.json）
#
# 互搏的"闭环"由它承载：Reviewer 提出的每个问题拿到唯一 ID，之后每一轮都必须
# 有明确去向 —— 被 Builder 修掉（resolved）、被 Builder 反驳且 Reviewer 撤回
# （withdrawn）、或坚持存在（persisting）。Judge 只认台账里的 open 问题，
# 不再单看 Reviewer 当轮报了几条。
# ---------------------------------------------------------------------------

ISSUE_OPEN_STATES = {"open", "must_fix"}
DISPUTE_UPHOLD_LIMIT = 2  # Builder 反驳后 Reviewer 坚持 2 次 → 定为 must_fix，不再可反驳


def load_issues(job_dir: Path) -> list[dict[str, Any]]:
    data = read_json(job_dir / "ISSUES.json", [])
    return data if isinstance(data, list) else []


def save_issues(job_dir: Path, issues: list[dict[str, Any]]) -> None:
    write_json(job_dir / "ISSUES.json", issues)


def open_issue_list(issues: list[dict[str, Any]], severities: tuple[str, ...] = ("p0", "p1", "p2")) -> list[dict[str, Any]]:
    return [i for i in issues if i.get("status") in ISSUE_OPEN_STATES and i.get("severity") in severities]


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def evidence_found_in(evidence: str, text: str) -> bool:
    """证据必须是目标文件里的原文引用（忽略空白差异）。太短的引用不算证据。"""
    ev = _norm_text(evidence)
    if len(ev) < 6:
        return False
    return ev[:400] in _norm_text(text)


def normalize_issue_item(raw: Any) -> dict[str, str]:
    """兼容手动接力时贴回来的纯字符串问题。"""
    if isinstance(raw, dict):
        return {
            "desc": str(raw.get("desc", "") or "")[:500],
            "evidence": str(raw.get("evidence", "") or "")[:600],
            "location": str(raw.get("location", "") or "")[:120],
        }
    return {"desc": str(raw)[:500], "evidence": "", "location": ""}


def apply_builder_disputes(job_dir: Path, r: int) -> list[dict[str, Any]]:
    """读取本轮 builder.json 的 disputes，把被反驳的 open 问题标记为待仲裁。

    must_fix（已被 Reviewer 两次驳回反驳）不可再反驳。返回本轮生效的反驳列表。
    """
    builder = read_json(job_dir / "rounds" / f"r{r:03d}.builder.json", {})
    disputes = builder.get("disputes") if isinstance(builder, dict) else None
    if not isinstance(disputes, list) or not disputes:
        return []
    issues = load_issues(job_dir)
    by_id = {i.get("id"): i for i in issues}
    applied = []
    for d in disputes:
        if not isinstance(d, dict):
            continue
        issue = by_id.get(str(d.get("id", "")))
        if not issue or issue.get("status") != "open":
            continue
        issue["disputed_pending"] = True
        issue["disputed_round"] = r
        issue["dispute_reason"] = str(d.get("reason", "") or "")[:500]
        applied.append({"id": issue["id"], "reason": issue["dispute_reason"]})
    if applied:
        save_issues(job_dir, issues)
        append_ledger(job_dir, "builder_disputed_issues", round=r,
                      ids=[a["id"] for a in applied])
    return applied


def register_review_round(job_dir: Path, r: int, review: dict[str, Any], work_text: str) -> dict[str, Any]:
    """把本轮 Reviewer 结果写进台账：先按 issue_resolutions 闭环旧问题，再登记新问题。"""
    issues = load_issues(job_dir)
    by_id = {i.get("id"): i for i in issues}
    resolved = withdrawn = persisting = upheld = 0

    resolutions = review.get("issue_resolutions")
    if isinstance(resolutions, list):
        for res in resolutions:
            if not isinstance(res, dict):
                continue
            issue = by_id.get(str(res.get("id", "")))
            if not issue or issue.get("status") not in ISSUE_OPEN_STATES:
                continue
            status = str(res.get("status", ""))
            note = str(res.get("note", "") or "")[:300]
            was_disputed = bool(issue.pop("disputed_pending", False))
            if status == "resolved":
                issue["status"] = "resolved"
                issue["closed_round"] = r
                issue["close_note"] = note
                resolved += 1
            elif status == "withdrawn":
                issue["status"] = "withdrawn"
                issue["closed_round"] = r
                issue["close_note"] = note or ("Reviewer 接受 Builder 反驳" if was_disputed else "")
                withdrawn += 1
            else:  # persisting
                persisting += 1
                if was_disputed:
                    issue["uphold_count"] = int(issue.get("uphold_count", 0)) + 1
                    upheld += 1
                    if issue["uphold_count"] >= DISPUTE_UPHOLD_LIMIT:
                        issue["status"] = "must_fix"
    # 反驳了但 Reviewer 没表态的：视为 persisting，反驳不成立一次
    for issue in issues:
        if issue.pop("disputed_pending", False):
            issue["uphold_count"] = int(issue.get("uphold_count", 0)) + 1
            if issue["uphold_count"] >= DISPUTE_UPHOLD_LIMIT and issue.get("status") == "open":
                issue["status"] = "must_fix"

    # 登记新问题（按 desc 去重，防止 Reviewer 把旧问题重新报一遍）
    open_desc_keys = {_norm_text(i.get("desc", ""))[:80] for i in issues if i.get("status") in ISSUE_OPEN_STATES}
    new_ids: list[str] = []
    unverified = 0
    raw_issues = review.get("issues", {}) if isinstance(review.get("issues"), dict) else {}
    for sev in ("p0", "p1", "p2"):
        items = raw_issues.get(sev, [])
        if not isinstance(items, list):
            continue
        n = 0
        for raw in items:
            item = normalize_issue_item(raw)
            if not item["desc"].strip():
                continue
            key = _norm_text(item["desc"])[:80]
            if key in open_desc_keys:
                continue  # 已在台账里开着，不重复登记
            open_desc_keys.add(key)
            n += 1
            verified = evidence_found_in(item["evidence"], work_text)
            if not verified and sev in ("p0", "p1"):
                unverified += 1
            record = {
                "id": f"R{r}-{sev.upper()}-{n}",
                "severity": sev,
                "desc": item["desc"],
                "evidence": item["evidence"],
                "location": item["location"],
                "evidence_verified": verified,
                "status": "open",
                "opened_round": r,
                "uphold_count": 0,
            }
            issues.append(record)
            new_ids.append(record["id"])

    save_issues(job_dir, issues)
    open_p0 = len(open_issue_list(issues, ("p0",)))
    open_p1 = len(open_issue_list(issues, ("p1",)))
    open_p2 = len(open_issue_list(issues, ("p2",)))
    summary = {
        "resolved": resolved, "withdrawn": withdrawn, "persisting": persisting,
        "upheld_disputes": upheld, "new_ids": new_ids, "unverified_new_p0p1": unverified,
        "open_p0": open_p0, "open_p1": open_p1, "open_p2": open_p2,
    }
    append_ledger(job_dir, "issue_ledger_updated", round=r, **summary)
    return summary


def issue_ledger_brief(issues: list[dict[str, Any]]) -> str:
    """给 Builder / Reviewer prompt 用的台账摘要（只列 open / must_fix）。"""
    lines = []
    for i in open_issue_list(issues):
        tag = "必须修，不可再反驳" if i.get("status") == "must_fix" else "可修复或反驳"
        ev = f"｜证据: {i.get('evidence', '')[:120]}" if i.get("evidence") else "｜⚠ 无证据引用"
        loc = f"｜位置: {i.get('location')}" if i.get("location") else ""
        dispute = f"｜Builder 已反驳: {i.get('dispute_reason', '')[:120]}" if i.get("disputed_pending") else ""
        lines.append(f"- [{i['id']}] ({i['severity'].upper()}·{tag}) {i.get('desc', '')}{loc}{ev}{dispute}")
    return "\n".join(lines) if lines else "(台账当前没有未闭环问题)"


def save_review_and_judge(job_dir: Path, reviewer_payload: str) -> dict[str, Any]:
    status, _snap, work_file, rounds = current_paths(job_dir)
    if status.get("state") != "WAIT_REVIEWER":
        raise ValueError(
            f"当前 state={status.get('state')}，只能在 WAIT_REVIEWER 接受 Reviewer JSON"
        )
    r = int(status.get("round", 1))
    try:
        review = json.loads(reviewer_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Reviewer JSON 无法解析：{exc}") from exc
    if not isinstance(review, dict):
        raise ValueError("Reviewer JSON 必须是 object")

    # 台账快照：重跑 Reviewer 时从这里回滚，避免同一轮的问题被重复登记
    issues_before_path = rounds / f"r{r:03d}.issues_before.json"
    write_json(issues_before_path, load_issues(job_dir))

    (rounds / f"r{r:03d}.reviewer.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    scores = review.get("scores", {})
    score = int(scores.get("requirement_fit", 0) or 0)
    issues = review.get("issues", {})
    p0 = issue_count(issues, "p0")
    p1 = issue_count(issues, "p1")
    verdict = review.get("verdict", "")
    runner_failures = int(status.get("runner_failures", 0) or 0)

    # 更新问题闭环台账：闭环旧问题、登记新问题（含证据机器核验）
    ledger_summary = register_review_round(job_dir, r, review, file_text(work_file))
    open_p0 = ledger_summary["open_p0"]
    open_p1 = ledger_summary["open_p1"]

    threshold = int(status.get("threshold", 85))
    max_rounds = int(status.get("max_rounds", 5))
    trend = list(status.get("scores_trend", []))
    trend.append(score)

    # 僵局检测：评分不升、阻断问题（台账 open P0+P1）不减 → 连续 2 轮就提前升级，不空烧轮数
    blockers = open_p0 + open_p1
    blockers_trend = list(status.get("blockers_trend", []))
    prev_blockers = blockers_trend[-1] if blockers_trend else None
    blockers_trend.append(blockers)
    improved = (len(trend) < 2 or trend[-1] > trend[-2]) or (prev_blockers is None or blockers < prev_blockers)
    stall_rounds = 0 if improved else int(status.get("stall_rounds", 0)) + 1

    # Judge 只认台账闭环：Reviewer 当轮报 0 条不算数，台账里的 open P0/P1 必须清零
    if score >= threshold and open_p0 == 0 and open_p1 == 0 and runner_failures == 0 and verdict in {"accept", "accept_with_minors"}:
        decision = "stop"
        reason = "达到验收阈值，问题台账 P0/P1 全部闭环"
    elif r >= max_rounds:
        decision = "escalate"
        reason = "达到最大轮数，交给人判断"
    elif stall_rounds >= 2:
        decision = "escalate"
        reason = f"连续 {stall_rounds} 轮评分未升、阻断问题未减（僵局），提前交给人判断"
    else:
        decision = "continue"
        reason = "未达到验收条件，进入下一轮"

    judge = {
        "round": r,
        "actor": "judge",
        "decision": decision,
        "reason": reason,
        "score": score,
        "p0": p0,
        "p1": p1,
        "open_p0": open_p0,
        "open_p1": open_p1,
        "resolved_this_round": ledger_summary["resolved"],
        "withdrawn_this_round": ledger_summary["withdrawn"],
        "new_issues": len(ledger_summary["new_ids"]),
        "unverified_new_p0p1": ledger_summary["unverified_new_p0p1"],
        "stall_rounds": stall_rounds,
        "runner_failures": runner_failures,
        "next_round_hint": "" if decision == "stop" else "逐条闭环台账里的 open P0/P1（修复或反驳），保持改动范围不扩大。",
    }
    (rounds / f"r{r:03d}.judge.json").write_text(json.dumps(judge, ensure_ascii=False, indent=2), encoding="utf-8")
    append_ledger(job_dir, "judge_decision", round=r, decision=decision, score=score,
                  p0=p0, p1=p1, open_p0=open_p0, open_p1=open_p1, stall_rounds=stall_rounds)

    if decision == "stop":
        update_status(job_dir, state="READY_FOR_HUMAN_MERGE", scores_trend=trend,
                      blockers_trend=blockers_trend, stall_rounds=stall_rounds)
        finalize(job_dir, "stop")
    elif decision == "escalate":
        update_status(job_dir, state="ESCALATED", scores_trend=trend,
                      blockers_trend=blockers_trend, stall_rounds=stall_rounds)
        finalize(job_dir, "escalate")
    else:
        # 进入下一轮前，把当前 worktree 作为新一轮的"本轮 Builder 开始前"基线
        next_r = r + 1
        baseline = rounds / f"r{next_r:03d}.before_builder.{work_file.name}"
        try:
            shutil.copy2(work_file, baseline)
        except OSError:
            pass
        update_status(job_dir, state="WAIT_BUILDER", round=next_r, scores_trend=trend,
                      blockers_trend=blockers_trend, stall_rounds=stall_rounds)
        build_builder_prompt(job_dir)

    return {"judge": judge, "job": job_summary(job_dir)}


def finalize(job_dir: Path, reason: str) -> None:
    status, snap_file, work_file, _rounds = current_paths(job_dir)
    final = job_dir / "FINAL.md"
    final.write_text(file_text(work_file), encoding="utf-8")
    diff = "".join(difflib.unified_diff(file_text(snap_file).splitlines(keepends=True), file_text(work_file).splitlines(keepends=True), fromfile=f"original/{snap_file.name}", tofile=f"final/{work_file.name}"))
    (job_dir / "FINAL.diff").write_text(diff or "(no diff)", encoding="utf-8")
    trend = status.get("scores_trend", [])
    review = ""
    for p in sorted((job_dir / "rounds").glob("r*.reviewer.json"), reverse=True):
        review = file_text(p)
        if review:
            break

    # 问题闭环账目：开了多少、闭环多少、还开着什么
    issues = load_issues(job_dir)
    n_resolved = sum(1 for i in issues if i.get("status") == "resolved")
    n_withdrawn = sum(1 for i in issues if i.get("status") == "withdrawn")
    still_open = open_issue_list(issues)
    open_lines = "\n".join(
        f"- [{i['id']}] ({i['severity'].upper()}{'·必须修' if i.get('status') == 'must_fix' else ''}"
        f"{'' if i.get('evidence_verified') else '·无证据'}) {i.get('desc', '')}"
        for i in still_open
    ) or "- (无，全部闭环)"

    report = f"""# FINAL REVIEW

- job: `{job_dir.name}`
- mode: `sparring`
- source: `{status.get("source_path")}`
- goal: {status.get("goal")}
- exit_reason: {reason}
- round: {status.get("round")} / {status.get("max_rounds")}
- scores_trend: {trend}

## Issue Closed Loop / 问题闭环账目

- 共提出 {len(issues)} 条 · 已修复 {n_resolved} · 反驳成立撤回 {n_withdrawn} · 仍开放 {len(still_open)}

仍开放的问题：

{open_lines}

## Last Reviewer JSON

```json
{review or "{}"}
```

## Human Decision

- [ ] 合并到原文件
- [ ] 放弃
- [ ] 继续人工修改

## Files

- final: `FINAL.md`
- diff: `FINAL.diff`
"""
    (job_dir / "FINAL_REVIEW.md").write_text(report, encoding="utf-8")
    update_status(job_dir, state="READY_FOR_HUMAN_MERGE" if reason == "stop" else "ESCALATED", finalized_at=now())


def merge_job(job_dir: Path) -> dict[str, Any]:
    status, snap_file, work_file, _rounds = current_paths(job_dir)
    if status.get("state") not in {"READY_FOR_HUMAN_MERGE", "ESCALATED"}:
        raise ValueError(
            f"当前 state={status.get('state')}，只能在 READY_FOR_HUMAN_MERGE 或 ESCALATED 合并"
        )
    source = source_path_from_status(status)
    if not source.exists():
        raise ValueError("原文件不存在，不能合并")
    if file_bytes(source) != file_bytes(snap_file):
        conflict = job_dir / f"MERGE_BLOCKED_CURRENT_SOURCE.{source.name}"
        shutil.copy2(source, conflict)
        append_ledger(
            job_dir,
            "merge_blocked_source_changed",
            source_path=str(source),
            current_copy=str(conflict),
        )
        raise ValueError(
            "原文件已不同于任务开始时的快照。为避免覆盖你后来的修改，"
            f"本次合并已阻止；当前原文件副本已保存到 {conflict.name}"
        )
    backup = job_dir / f"ORIGINAL_BEFORE_MERGE.{source.name}"
    shutil.copy2(source, backup)
    shutil.copy2(work_file, source)
    append_ledger(job_dir, "merged_to_source", source_path=str(source), backup=str(backup))
    update_status(job_dir, state="MERGED", merged_at=now(), merge_backup=str(backup))
    return job_summary(job_dir)


def _parse_ts(s: str) -> float:
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def _ledger_iter(job_dir: Path):
    p = job_dir / "ledger.jsonl"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


# 粗估单价（人民币元）。token 不可得时按"每段固定值"兜底。
# 来源：Sonnet ≈ $3/$15 per 1M(in/out)，Codex(gpt-5)≈$5/$15。3 倍人民币 ≈ ¥0.03/¥0.15 per K out。
COST_PER_BUILDER_ROUND_DEFAULT_CNY = 0.6   # Claude builder 单轮粗估
COST_PER_REVIEWER_ROUND_DEFAULT_CNY = 0.4  # Codex reviewer 单轮粗估


def _round_durations_and_cost(job_dir: Path) -> dict[int, dict[str, Any]]:
    """从 ledger 抽出每轮 builder / reviewer 各自耗时（秒）+ 粗估成本。"""
    starts: dict[tuple[int, str], float] = {}
    result: dict[int, dict[str, Any]] = {}
    for ev in _ledger_iter(job_dir):
        name = ev.get("event", "")
        r = ev.get("round")
        if not isinstance(r, int):
            continue
        ts = _parse_ts(ev.get("ts", ""))
        if not ts:
            continue
        bucket = result.setdefault(r, {})
        if name in ("auto_builder_start", "auto_builder_codex_fallback_start"):
            starts[(r, "builder")] = ts
        elif name in ("auto_builder_done", "auto_builder_codex_fallback_done"):
            t0 = starts.get((r, "builder"))
            if t0:
                bucket["builder_sec"] = round(ts - t0, 1)
                bucket["cost_cny"] = round(bucket.get("cost_cny", 0)
                                          + COST_PER_BUILDER_ROUND_DEFAULT_CNY, 2)
        elif name == "auto_reviewer_start":
            starts[(r, "reviewer")] = ts
        elif name == "auto_reviewer_done":
            t0 = starts.get((r, "reviewer"))
            if t0:
                bucket["reviewer_sec"] = round(ts - t0, 1)
                bucket["cost_cny"] = round(bucket.get("cost_cny", 0)
                                          + COST_PER_REVIEWER_ROUND_DEFAULT_CNY, 2)
        elif name == "judge_decision":
            bucket["finished_at"] = ev.get("ts", "")
    for r, b in result.items():
        b_sec = b.get("builder_sec", 0)
        r_sec = b.get("reviewer_sec", 0)
        b["total_sec"] = round(b_sec + r_sec, 1)
    return result


def _fmt_secs(sec: float) -> str:
    if not sec or sec <= 0:
        return ""
    if sec < 60:
        return f"{sec:.0f}s"
    m = int(sec // 60); s = int(sec - m*60)
    return f"{m}m{s:02d}s"


def collect_rounds(job_dir: Path) -> list[dict[str, Any]]:
    """汇总每一轮 reviewer/judge 的关键字段，供前端时间线渲染。"""
    out = []
    rounds_dir = job_dir / "rounds"
    if not rounds_dir.exists():
        return out
    nums = set()
    for p in rounds_dir.glob("r???.reviewer.json"):
        if p.stem[1:4].isdigit():
            nums.add(int(p.stem[1:4]))
    for p in rounds_dir.glob("r???.judge.json"):
        if p.stem[1:4].isdigit():
            nums.add(int(p.stem[1:4]))
    durations = _round_durations_and_cost(job_dir)
    for n in sorted(nums):
        item: dict[str, Any] = {"round": n}
        rv = read_json(rounds_dir / f"r{n:03d}.reviewer.json", None)
        if isinstance(rv, dict):
            issues = rv.get("issues", {}) or {}
            item["scores"] = rv.get("scores", {}) or {}
            item["verdict"] = rv.get("verdict", "") or ""
            item["summary"] = rv.get("summary", "") or ""
            item["p0"] = issue_count(issues, "p0")
            item["p1"] = issue_count(issues, "p1")
            item["p2"] = issue_count(issues, "p2")
            for k in ("p0", "p1", "p2"):
                v = issues.get(k, [])
                if isinstance(v, list):
                    item[f"{k}_items"] = [normalize_issue_item(x)["desc"][:200] for x in v[:6]]
            res = rv.get("issue_resolutions", [])
            if isinstance(res, list):
                item["resolutions"] = [
                    {"id": str(x.get("id", "")), "status": str(x.get("status", "")),
                     "note": str(x.get("note", "") or "")[:160]}
                    for x in res[:12] if isinstance(x, dict)
                ]
        bj = read_json(rounds_dir / f"r{n:03d}.builder.json", None)
        if isinstance(bj, dict):
            item["changes_summary"] = str(bj.get("changes_summary", "") or "")[:200]
            disputes = bj.get("disputes", [])
            if isinstance(disputes, list):
                item["disputes"] = [
                    {"id": str(x.get("id", "")), "reason": str(x.get("reason", "") or "")[:160]}
                    for x in disputes[:8] if isinstance(x, dict)
                ]
        jd = read_json(rounds_dir / f"r{n:03d}.judge.json", None)
        if isinstance(jd, dict):
            item["decision"] = jd.get("decision", "")
            item["reason"] = jd.get("reason", "")
            item["open_p0"] = jd.get("open_p0")
            item["open_p1"] = jd.get("open_p1")
        # 耗时 + 成本
        d = durations.get(n, {})
        item["builder_sec"] = d.get("builder_sec", 0)
        item["reviewer_sec"] = d.get("reviewer_sec", 0)
        item["total_sec"] = d.get("total_sec", 0)
        item["total_label"] = _fmt_secs(item["total_sec"])
        item["cost_cny"] = d.get("cost_cny", 0)
        out.append(item)
    return out


def abort_job(job_dir: Path, reason: str = "user_abort") -> dict[str, Any]:
    status = read_json(job_dir / "STATUS.json", {})
    if status.get("state") in {"MERGED", "ABORTED"}:
        raise ValueError(f"当前 state={status.get('state')}，不能再放弃")
    append_ledger(job_dir, "job_aborted", reason=reason)
    update_status(job_dir, state="ABORTED", auto_running=False, aborted_at=now(), abort_reason=reason)
    return job_summary(job_dir)


def retry_reviewer(job_dir: Path) -> dict[str, Any]:
    """重跑最新一轮的 Reviewer。把当前 reviewer/judge 备份后重新调 Codex 出评分。

    允许在 WAIT_REVIEWER / READY_FOR_HUMAN_MERGE / ESCALATED 三种状态下使用：
    - WAIT_REVIEWER 时直接重跑
    - 终态会先回退到 WAIT_REVIEWER（备份 FINAL_* 文件）
    """
    status = read_json(job_dir / "STATUS.json", {})
    state = status.get("state")
    if state not in {"WAIT_REVIEWER", "READY_FOR_HUMAN_MERGE", "ESCALATED"}:
        raise ValueError(f"当前 state={state}，不支持重跑 Reviewer（只能在 WAIT_REVIEWER / READY_FOR_HUMAN_MERGE / ESCALATED）")
    r = int(status.get("round", 1))
    rounds = job_dir / "rounds"
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backed = []
    for name in [f"r{r:03d}.reviewer.json", f"r{r:03d}.reviewer.raw",
                 f"r{r:03d}.reviewer.json.codex-output", f"r{r:03d}.judge.json"]:
        p = rounds / name
        if p.exists():
            bak = rounds / f"{name}.retry-{ts}.bak"
            shutil.copy2(p, bak)
            backed.append(bak.name)
    # 回滚问题台账到本轮 Reviewer 评审前的快照，避免重跑时重复登记/重复闭环
    issues_before = rounds / f"r{r:03d}.issues_before.json"
    if issues_before.exists():
        bak = job_dir / f"ISSUES.json.retry-{ts}.bak"
        if (job_dir / "ISSUES.json").exists():
            shutil.copy2(job_dir / "ISSUES.json", bak)
            backed.append(bak.name)
        shutil.copy2(issues_before, job_dir / "ISSUES.json")
    # 终态：备份 FINAL_*
    if state in {"READY_FOR_HUMAN_MERGE", "ESCALATED"}:
        for name in ["FINAL.md", "FINAL.diff", "FINAL_REVIEW.md"]:
            p = job_dir / name
            if p.exists():
                bak = job_dir / f"{name}.retry-{ts}.bak"
                shutil.copy2(p, bak)
                backed.append(bak.name)
        # 修剪 scores_trend 最后一项（要被重新评分覆盖）
        trend = list(status.get("scores_trend", []))
        if trend:
            trend = trend[:-1]
        update_status(job_dir, state="WAIT_REVIEWER", scores_trend=trend,
                      auto_running=False, auto_phase=None, auto_error=None, finalized_at=None)
    append_ledger(job_dir, "reviewer_retry", round=r, backed_up=backed)
    # 触发自动 Reviewer
    return start_auto_run(job_dir, status.get("builder_model") or DEFAULT_BUILDER_MODEL)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output."""
    text = text.strip()
    if not text:
        raise ValueError("模型没有返回内容")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    raise ValueError("无法从模型输出中解析 JSON object")


def command_path(name: str, fallback: str | None = None) -> str:
    found = shutil.which(name)
    if found:
        return found
    if fallback and Path(fallback).exists():
        return fallback
    raise ValueError(f"未检测到 {name} CLI")


def finish_builder_round(
    job_dir: Path,
    r: int,
    work_file: Path,
    before: bytes,
    stdout: str,
    engine: str,
) -> None:
    rounds = job_dir / "rounds"
    builder_json_path = rounds / f"r{r:03d}.builder.json"
    after = work_file.read_bytes() if work_file.exists() else b""
    if not builder_json_path.exists():
        if before == after:
            append_ledger(job_dir, "auto_builder_no_change", round=r, engine=engine)
            raise RuntimeError(f"{engine} Builder 未修改 worktree，也未生成 builder.json")
        fallback = {
            "round": r,
            "actor": "builder",
            "changes_summary": f"{engine} 已修改 worktree，但未按要求写 builder.json；系统用 stdout 生成兜底记录。",
            "changes": [{"location": work_file.name, "what": "见本轮 diff", "why": f"{engine} 自动修改"}],
            "addressed_issues": [],
            "remaining_concerns": ["Builder 未提供结构化修改说明，需 Reviewer 重点核查"],
            "stdout_excerpt": (stdout or "")[:1200],
        }
        builder_json_path.write_text(json.dumps(fallback, ensure_ascii=False, indent=2), encoding="utf-8")
        append_ledger(job_dir, "auto_builder_json_fallback", round=r, engine=engine)
    append_ledger(job_dir, "auto_builder_done", round=r, engine=engine)


def run_codex_builder_cli(job_dir: Path, r: int, prompt: str, before: bytes) -> None:
    status, _snap, work_file, rounds = current_paths(job_dir)
    source_before = file_bytes(source_path_from_status(status))
    codex = command_path("codex", "/Applications/Codex.app/Contents/Resources/codex")
    append_ledger(job_dir, "auto_builder_codex_fallback_start", round=r)
    update_status(job_dir, auto_running=True, auto_phase=f"builder_codex_r{r}", auto_error=None)
    builder_prompt = prompt + """

# 自动执行要求

你现在作为 Builder 自动执行。必须直接修改 worktree 里的目标文件，并写入本轮 builder.json。
不要等待用户确认，不要只给建议。只允许在本 job 目录内写文件。
"""
    cmd = [
        codex,
        "exec",
        "-C",
        str(job_dir),
        "-s",
        "workspace-write",
        "--skip-git-repo-check",
        "--ignore-rules",
        "-",
    ]
    proc = subprocess.run(
        cmd,
        input=builder_prompt,
        capture_output=True,
        text=True,
        timeout=900,
    )
    (rounds / f"r{r:03d}.builder.codex.stdout").write_text(proc.stdout or "", encoding="utf-8")
    (rounds / f"r{r:03d}.builder.codex.stderr").write_text(proc.stderr or "", encoding="utf-8")
    assert_source_unchanged_or_restore(job_dir, source_before, "Codex Builder")
    if proc.returncode != 0:
        append_ledger(job_dir, "auto_builder_codex_fallback_failed", round=r, returncode=proc.returncode)
        raise RuntimeError(f"Codex Builder 失败 rc={proc.returncode}: {(proc.stderr or proc.stdout)[:800]}")
    finish_builder_round(job_dir, r, work_file, before, proc.stdout or "", "Codex")


def _clean_env_no_anthropic_api() -> dict:
    """硬红线：不让 claude 子进程读到任何 ANTHROPIC_* 环境变量，强制走 OAuth/keychain。
    用户明令不允许使用 Anthropic API key（会走计费），必须用本地 Claude 客户端订阅授权。"""
    env = os.environ.copy()
    stripped = []
    for k in list(env.keys()):
        if k.startswith("ANTHROPIC_") or k == "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST":
            env.pop(k, None)
            stripped.append(k)
    if stripped:
        env["_SPARRING_STRIPPED_ENV"] = ",".join(stripped)
    return env


def run_builder_cli(job_dir: Path, model: str = DEFAULT_BUILDER_MODEL) -> None:
    status, _snap, work_file, rounds = current_paths(job_dir)
    if status.get("state") != "WAIT_BUILDER":
        raise ValueError(f"当前 state={status.get('state')}，不能运行 Builder")
    r = int(status.get("round", 1))
    prompt_path = rounds / f"r{r:03d}.builder.prompt.md"
    if not prompt_path.exists():
        build_builder_prompt(job_dir)
    prompt = file_text(prompt_path)
    builder_json_path = rounds / f"r{r:03d}.builder.json"
    before = work_file.read_bytes() if work_file.exists() else b""
    source_before = file_bytes(source_path_from_status(status))

    claude = command_path("claude")
    append_ledger(job_dir, "auto_builder_start", round=r, model=model)
    update_status(job_dir, auto_running=True, auto_phase=f"builder_r{r}", auto_error=None)
    cmd = [
        claude,
        "-p",
        prompt,
        "--model",
        model,
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Read,Edit,Write",
        "--max-budget-usd",
        "1.00",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(job_dir),
        capture_output=True,
        text=True,
        timeout=900,
        env=_clean_env_no_anthropic_api(),  # 硬红线：禁用 ANTHROPIC_API_KEY，强制 OAuth
    )
    (rounds / f"r{r:03d}.builder.stdout").write_text(proc.stdout or "", encoding="utf-8")
    (rounds / f"r{r:03d}.builder.stderr").write_text(proc.stderr or "", encoding="utf-8")
    assert_source_unchanged_or_restore(job_dir, source_before, "Claude Builder")
    if proc.returncode != 0:
        err_text = (proc.stderr or proc.stdout or "")
        if "Failed to authenticate" in err_text or "401" in err_text:
            append_ledger(job_dir, "auto_builder_claude_auth_failed_fallback_codex", round=r)
            run_codex_builder_cli(job_dir, r, prompt, before)
            return
        append_ledger(job_dir, "auto_builder_failed", round=r, returncode=proc.returncode)
        raise RuntimeError(f"Claude Builder 失败 rc={proc.returncode}: {err_text[:800]}")

    finish_builder_round(job_dir, r, work_file, before, proc.stdout or "", "Claude")


def run_reviewer_cli(job_dir: Path) -> str:
    status, _snap, _work_file, rounds = current_paths(job_dir)
    if status.get("state") != "WAIT_REVIEWER":
        raise ValueError(f"当前 state={status.get('state')}，不能运行 Reviewer")
    r = int(status.get("round", 1))
    prompt_path = rounds / f"r{r:03d}.reviewer.prompt.md"
    prompt = file_text(prompt_path)
    if not prompt:
        raise ValueError(f"缺少 Reviewer prompt: {prompt_path}")

    schema_path = rounds / f"r{r:03d}.reviewer.schema.json"
    schema_path.write_text(json.dumps(REVIEWER_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_path = rounds / f"r{r:03d}.reviewer.raw"
    codex = command_path("codex", "/Applications/Codex.app/Contents/Resources/codex")
    append_ledger(job_dir, "auto_reviewer_start", round=r)
    update_status(job_dir, auto_running=True, auto_phase=f"reviewer_r{r}", auto_error=None)
    cmd = [
        codex,
        "exec",
        "-C",
        str(job_dir),
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
        "-o",
        str(raw_path),
        "--ignore-rules",
        "-",
    ]
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=900,
    )
    (rounds / f"r{r:03d}.reviewer.stdout").write_text(proc.stdout or "", encoding="utf-8")
    (rounds / f"r{r:03d}.reviewer.stderr").write_text(proc.stderr or "", encoding="utf-8")
    if proc.returncode != 0:
        append_ledger(job_dir, "auto_reviewer_failed", round=r, returncode=proc.returncode)
        raise RuntimeError(f"Codex Reviewer 失败 rc={proc.returncode}: {(proc.stderr or proc.stdout)[:800]}")

    raw = file_text(raw_path) or proc.stdout or ""
    review = extract_json_object(raw)
    # Normalize required fields enough for deterministic judge.
    review.setdefault("round", r)
    review.setdefault("actor", "reviewer")
    review.setdefault("issues", {"p0": [], "p1": [], "p2": []})
    review.setdefault("issue_resolutions", [])
    review.setdefault("scores", {"requirement_fit": 0, "correctness": 0, "clarity": 0, "risk": 100})
    review.setdefault("verdict", "needs_revision")
    review.setdefault("summary", "")
    payload = json.dumps(review, ensure_ascii=False)
    append_ledger(job_dir, "auto_reviewer_done", round=r)
    return payload


def auto_run_job(job_dir: Path, builder_model: str = DEFAULT_BUILDER_MODEL) -> None:
    job_id = job_dir.name
    try:
        append_ledger(job_dir, "auto_run_started", builder_model=builder_model)
        update_status(job_dir, auto_running=True, manual_mode=False, auto_error=None)
        while True:
            status = read_json(job_dir / "STATUS.json", {})
            state = status.get("state")
            if state == "WAIT_BUILDER":
                run_builder_cli(job_dir, builder_model)
                prepare_reviewer(job_dir)
                review_payload = run_reviewer_cli(job_dir)
                save_review_and_judge(job_dir, review_payload)
            elif state == "WAIT_REVIEWER":
                review_payload = run_reviewer_cli(job_dir)
                save_review_and_judge(job_dir, review_payload)
            elif state in {"READY_FOR_HUMAN_MERGE", "ESCALATED", "MERGED", "ABORTED"}:
                break
            else:
                raise RuntimeError(f"未知状态，无法自动运行：{state}")
        final_state = read_json(job_dir / "STATUS.json", {}).get("state")
        append_ledger(job_dir, "auto_run_finished", state=final_state)
        update_status(job_dir, auto_running=False, auto_phase="idle")
        target = read_json(job_dir / "STATUS.json", {}).get("target_name", job_id)
        if final_state == "READY_FOR_HUMAN_MERGE":
            notify_user("Y1 互搏完成 ✓ 待你合并", f"{target} 已达标，去页面看 FINAL_REVIEW 决定是否合并")
        elif final_state == "ESCALATED":
            notify_user("Y1 互搏升级 ⚠ 需要你判断", f"{target} 未收敛（超轮数或僵局），去页面看剩余问题")
    except Exception as exc:
        tb = traceback.format_exc()
        (job_dir / "AUTO_ERROR.log").write_text(tb, encoding="utf-8")
        append_ledger(job_dir, "auto_run_error", error=str(exc))
        update_status(job_dir, auto_running=False, auto_phase="error", auto_error=str(exc))
        notify_user("Y1 互搏中断 ✗", str(exc)[:160])
    finally:
        AUTO_THREADS.pop(job_id, None)


def start_auto_run(job_dir: Path, builder_model: str = DEFAULT_BUILDER_MODEL) -> dict[str, Any]:
    job_id = job_dir.name
    with AUTO_LOCK:
        t = AUTO_THREADS.get(job_id)
        if t and t.is_alive():
            return job_summary(job_dir)
        health = cli_health()
        if not health.get("auto_mode_available"):
            raise ValueError("未检测到 Claude/Codex CLI，不能自动运行")
        status = read_json(job_dir / "STATUS.json", {})
        if status.get("state") not in {"WAIT_BUILDER", "WAIT_REVIEWER"}:
            raise ValueError(f"当前 state={status.get('state')}，不能启动自动运行")
        thread = threading.Thread(target=auto_run_job, args=(job_dir, builder_model), daemon=True)
        AUTO_THREADS[job_id] = thread
        update_status(job_dir, auto_running=True, manual_mode=False, auto_phase="queued", auto_error=None)
        thread.start()
    return job_summary(job_dir)


def reset_stale_auto_runs() -> None:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    for job_dir in JOBS_ROOT.iterdir():
        if not job_dir.is_dir():
            continue
        status = read_json(job_dir / "STATUS.json", {})
        if status.get("mode") != "sparring" or not status.get("auto_running"):
            continue
        if status.get("state") in {"READY_FOR_HUMAN_MERGE", "ESCALATED", "MERGED", "ABORTED"}:
            update_status(job_dir, auto_running=False, auto_phase="idle")
            continue
        append_ledger(job_dir, "auto_run_marked_stale_after_server_start")
        update_status(
            job_dir,
            auto_running=False,
            auto_phase="error",
            auto_error="服务重启后未发现对应自动线程；可点击继续自动跑。",
        )


def read_known_file(job_dir: Path, name: str) -> str:
    target = (job_dir / name).resolve()
    try:
        target.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise ValueError("非法文件路径")
    if not target.exists() or target.is_dir():
        raise FileNotFoundError(name)
    return file_text(target)


HTML_PAGE = r"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Y1 左右互搏 Bus</title>
<style>
:root{
  --ink:#1a1a1a;--ink-2:#4a4a4a;--muted:#6e6e6e;--rule:#e6e6e6;--rule-2:#f0f0f0;
  --bg:#f5f5f4;--paper:#fff;--paper-2:#fafafa;
  --accent:#1f5fbf;--accent-bg:#eef3fa;
  --pass:#2a6e3d;--pass-bg:#e8f3ea;
  --warn:#b6731c;--warn-bg:#fff2dd;
  --fail:#a83232;--fail-bg:#fbeaea;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue","Source Han Sans CN",sans-serif;background:var(--bg);color:var(--ink)}

header{background:var(--paper);border-bottom:1px solid var(--rule);padding:14px 32px;display:flex;justify-content:space-between;align-items:baseline}
h1{font-size:15px;font-weight:600;margin:0;letter-spacing:.3px}
h1 .sub{color:var(--muted);font-weight:400;margin-left:10px;font-size:13px}
.health{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.health .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--pass);margin-right:4px;vertical-align:1px}
.health .dot.off{background:var(--fail)}
.health b{color:var(--ink-2);font-weight:500}

main{max-width:1280px;margin:0 auto;padding:22px 32px 72px;display:grid;grid-template-columns:360px 1fr;gap:20px}
@media (max-width:980px){main{grid-template-columns:1fr;padding:16px}}

.panel{background:var(--paper);border:1px solid var(--rule);padding:18px 20px}
.panel + .panel{margin-top:16px}
.panel h2{margin:0 0 14px;font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--ink-2);font-weight:600;padding-bottom:8px;border-bottom:1px solid var(--rule)}

label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-2);margin:12px 0 5px;font-weight:500}
input[type=text],input:not([type]),textarea{
  width:100%;font:inherit;font-size:14px;padding:8px 10px;
  border:1px solid var(--rule);background:#fff;color:var(--ink);
  border-radius:0;outline:none;transition:border-color .15s
}
input:focus,textarea:focus{border-color:var(--ink-2)}
textarea{min-height:64px;resize:vertical}
.row{display:flex;gap:10px}.row>*{flex:1}

.btn{font:inherit;font-size:13px;padding:8px 14px;border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer;border-radius:0;transition:opacity .12s;white-space:nowrap}
.btn:hover{opacity:.88}
.btn:disabled{opacity:.32;cursor:not-allowed}
.btn.secondary{background:#fff;color:var(--ink);border-color:var(--rule)}
.btn.secondary:hover{background:var(--rule-2);opacity:1}
.btn.danger{background:var(--fail);border-color:var(--fail);color:#fff}
.btn.warn{background:var(--warn);border-color:var(--warn);color:#fff}
.btn.ghost{background:transparent;color:var(--muted);border:1px solid transparent;padding:6px 10px}
.btn.ghost:hover{color:var(--ink);background:var(--rule-2)}
.btn.sm{padding:4px 10px;font-size:12px}

/* —— File picker modal —— */
.modal-mask{position:fixed;inset:0;background:rgba(20,20,20,.4);display:none;z-index:50;align-items:center;justify-content:center}
.modal-mask.open{display:flex}
.modal{background:var(--paper);width:min(720px,92vw);max-height:80vh;display:flex;flex-direction:column;border:1px solid var(--ink)}
.modal header{display:flex;justify-content:space-between;align-items:center;padding:12px 18px;border-bottom:1px solid var(--rule)}
.modal header h3{margin:0;font-size:14px;font-weight:600}
.modal header .close{background:none;border:0;font-size:18px;cursor:pointer;color:var(--muted)}
.breadcrumb{padding:10px 18px;font-family:var(--mono);font-size:12px;color:var(--muted);border-bottom:1px solid var(--rule);overflow-x:auto;white-space:nowrap}
.breadcrumb a{color:var(--accent);text-decoration:none;cursor:pointer}
.breadcrumb a:hover{text-decoration:underline}
.fileinfo{padding:6px 18px;font-size:11px;color:var(--muted);font-family:var(--mono);border-bottom:1px solid var(--rule)}
.entries{flex:1;overflow:auto;padding:4px 0}
.entries .row{display:flex;justify-content:space-between;align-items:baseline;padding:6px 18px;cursor:pointer;font-size:13px;gap:12px}
.entries .row:hover{background:var(--paper-2)}
.entries .row .icon{font-family:var(--mono);width:18px;display:inline-block;color:var(--muted)}
.entries .row .size{color:var(--muted);font-family:var(--mono);font-size:11px;font-variant-numeric:tabular-nums}
.entries .row.dir .name{font-weight:500}
.entries .empty{padding:24px;text-align:center;color:var(--muted);font-size:12px}

/* —— Preflight modal —— */
.preflight-modal{width:min(640px,92vw)}
.preflight-list{padding:14px 18px;margin:0;list-style:none}
.preflight-list li{display:flex;gap:10px;align-items:baseline;padding:5px 0;font-size:13px;border-bottom:1px solid var(--rule-2)}
.preflight-list li:last-child{border-bottom:0}
.preflight-list .mk{font-family:var(--mono);font-weight:600;width:22px;flex-shrink:0}
.preflight-list .mk.pass{color:var(--pass)}
.preflight-list .mk.warn{color:var(--warn)}
.preflight-list .mk.fail{color:var(--fail)}
.preflight-list .item{flex:1;color:var(--ink)}
.preflight-list .detail{color:var(--muted);font-size:11px;font-family:var(--mono);margin-top:2px}
.preflight-preview{padding:0 18px 14px}
.preflight-preview h4{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-2);margin:8px 0 6px;font-weight:600}
.preflight-preview pre{max-height:140px;background:var(--paper-2)}
.modal footer{padding:12px 18px;border-top:1px solid var(--rule);display:flex;gap:8px;justify-content:flex-end}

.hint{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.5}
.error{color:var(--fail);font-size:12px;margin-top:8px;font-family:var(--mono)}
.actions-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.checkline{display:flex;align-items:center;gap:8px;margin:12px 0 0;font-size:12px;color:var(--ink-2);text-transform:none;letter-spacing:0}
.checkline input{width:auto}

.jobs{display:flex;flex-direction:column;gap:6px}
.job-row{padding:11px 12px;background:var(--paper);border:1px solid var(--rule);cursor:pointer;transition:border-color .12s,background .12s}
.job-row:hover{border-color:var(--ink-2);background:var(--paper-2)}
.job-row.active{border-color:var(--ink);background:var(--paper-2)}
.job-row .row1{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.job-row .title{font-weight:500;font-size:13px;letter-spacing:.2px;word-break:break-all}
.job-row .row2{font-size:11px;color:var(--muted);margin-top:4px;font-variant-numeric:tabular-nums;display:flex;justify-content:space-between;gap:8px}
.job-row .trend{font-family:var(--mono);color:var(--accent)}

.state{display:inline-block;padding:1px 7px;font-size:10px;letter-spacing:.6px;font-family:var(--mono);text-transform:uppercase;border:1px solid transparent;white-space:nowrap}
.state-WAIT_BUILDER,.state-WAIT_REVIEWER{background:var(--accent-bg);color:var(--accent);border-color:#cdd9eb}
.state-READY_FOR_HUMAN_MERGE,.state-MERGED{background:var(--pass-bg);color:var(--pass);border-color:#bcd9c3}
.state-ESCALATED{background:var(--warn-bg);color:var(--warn);border-color:#e5c79a}
.state-ABORTED{background:var(--fail-bg);color:var(--fail);border-color:#f5b5b5}
.state-INIT{background:var(--rule-2);color:var(--muted);border-color:var(--rule)}

.detail-head{display:flex;justify-content:space-between;gap:16px;padding-bottom:14px;border-bottom:1px solid var(--rule);margin-bottom:18px;flex-wrap:wrap}
.err-banner{background:var(--fail-bg);border:1px solid var(--fail);color:var(--fail);padding:10px 14px;margin:0 0 14px;display:flex;justify-content:space-between;align-items:center;gap:14px;font-size:13px}

/* —— Verdict 决策卡（最高优先级，终态时占据视觉重心） —— */
.verdict-card{border:2px solid var(--ink);background:var(--paper);padding:18px 22px;margin:0 0 24px;position:relative}
.verdict-card.recommend{border-color:var(--pass);background:linear-gradient(180deg,#f6fbf7 0%,var(--paper) 60%)}
.verdict-card.caution{border-color:var(--warn);background:linear-gradient(180deg,#fffaf0 0%,var(--paper) 60%)}
.verdict-card.reject{border-color:var(--fail);background:linear-gradient(180deg,#fdf5f5 0%,var(--paper) 60%)}
.verdict-card .top-row{display:flex;justify-content:space-between;align-items:baseline;gap:14px;flex-wrap:wrap}
.verdict-card .verdict-label{font-size:11px;text-transform:uppercase;letter-spacing:.18em;color:var(--ink-2);font-weight:600;margin-bottom:6px}
.verdict-card .verdict-title{font-size:22px;font-weight:700;letter-spacing:.5px;line-height:1.2}
.verdict-card.recommend .verdict-title{color:var(--pass)}
.verdict-card.caution .verdict-title{color:var(--warn)}
.verdict-card.reject .verdict-title{color:var(--fail)}
.verdict-card .score-tag{font-family:var(--mono);font-size:32px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--ink)}
.verdict-card .score-tag .thr{font-size:14px;color:var(--muted);margin-left:6px;font-weight:400}
.verdict-card .reviewer-quote{background:var(--paper-2);border-left:3px solid var(--ink-2);padding:10px 14px;margin:14px 0;font-style:italic;color:var(--ink-2);line-height:1.6;font-size:13px}
.verdict-card .risk-row{display:flex;gap:10px;align-items:center;margin:12px 0;font-size:12px;color:var(--muted)}
.verdict-card .risk-row .pill{font-size:11px;padding:2px 8px}
.verdict-card .big-actions{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap}
.verdict-card .big-actions .btn{padding:10px 18px;font-size:14px;font-weight:500;letter-spacing:.5px}
.verdict-card .big-actions .btn-merge{background:var(--pass);border-color:var(--pass)}
.verdict-card .big-actions .btn-merge:hover{background:#236031}
.verdict-card .big-actions .btn-reject{background:#fff;color:var(--fail);border-color:var(--fail)}
.verdict-card .big-actions .btn-reject:hover{background:var(--fail-bg)}

/* —— 筛选 chips（任务列表上方） —— */
.filter-chips{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.chip{font:inherit;font-size:11px;letter-spacing:.5px;padding:4px 10px;border:1px solid var(--rule);background:#fff;color:var(--ink-2);cursor:pointer;border-radius:0;font-family:var(--mono);text-transform:uppercase}
.chip:hover{border-color:var(--ink-2)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.chip .count{opacity:.6;margin-left:4px;font-weight:600}

/* —— 目标模板按钮 —— */
.tpl-row{display:flex;gap:5px;margin:6px 0;flex-wrap:wrap}
.tpl-row .chip{font-family:inherit;text-transform:none;letter-spacing:.2px;font-size:11px}

/* —— 左右对照视图 —— */
.compare-view{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}
.compare-view .col{display:flex;flex-direction:column;border:1px solid var(--rule);background:var(--paper)}
.compare-view .col h5{margin:0;padding:8px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-2);font-weight:600;background:var(--paper-2);border-bottom:1px solid var(--rule)}
.compare-view .col h5 .meta{float:right;color:var(--muted);font-family:var(--mono);font-weight:400;font-size:10px}
.compare-view .col .body{padding:12px 14px;max-height:520px;overflow:auto;font:12px/1.6 var(--mono);white-space:pre-wrap;word-break:break-word;color:var(--ink)}
.view-toggle{display:flex;gap:0;margin:0 0 8px;border-bottom:1px solid var(--rule)}
.view-toggle button{background:transparent;border:none;padding:7px 14px;cursor:pointer;font:inherit;font-size:12px;color:var(--muted);border-bottom:2px solid transparent;border-radius:0}
.view-toggle button.on{color:var(--ink);border-bottom-color:var(--ink);font-weight:500}
@media (max-width:760px){
  .compare-view{grid-template-columns:1fr}
}

/* —— 轮次行 summary（折叠时也显示一行） —— */
.round-row .summary-collapsed{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.err-banner strong{font-weight:600}
.diff-view{background:var(--paper-2);border:1px solid var(--rule);padding:0;max-height:440px;overflow:auto;margin:0;font:12px/1.55 var(--mono)}
.diff-view .ln{display:block;padding:0 12px;white-space:pre-wrap;word-break:break-word}
.diff-view .ln.add{background:#e6f4ea;color:#15662a}
.diff-view .ln.del{background:#fce8e6;color:#92210e}
.diff-view .ln.hunk{background:#eef3fa;color:var(--accent);font-weight:500}
.diff-view .ln.meta{color:var(--muted)}
.detail-title{font-size:17px;font-weight:600;letter-spacing:.2px}
.detail-meta{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.6}
.detail-meta b{color:var(--ink-2);font-weight:500}
.detail-meta .sep{margin:0 6px;color:var(--rule)}

.next-action{border:1px solid var(--accent);background:var(--accent-bg);padding:16px 18px;margin:0 0 22px}
.next-action.done{border-color:var(--pass);background:var(--pass-bg)}
.next-action.escalated{border-color:var(--warn);background:var(--warn-bg)}
.next-action.terminal{border-color:var(--rule);background:var(--paper-2)}
.next-action .label{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--ink-2);margin-bottom:4px;font-weight:600}
.next-action .title{font-size:15px;font-weight:600;margin-bottom:6px;color:var(--ink)}
.next-action .desc{font-size:13px;color:var(--ink-2);margin-bottom:14px;line-height:1.6}
.next-action .step-list{font-size:12px;color:var(--ink-2);margin:0 0 12px 18px;padding:0;line-height:1.7}
.next-action .step-list li{margin:0}
.next-action .actions-row{margin-top:0}

.section{margin:22px 0}
.section h3{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--ink-2);font-weight:600;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid var(--rule)}

.chart-wrap{padding:8px 0 22px 36px;height:170px;position:relative}
.chart-wrap svg{width:100%;height:100%;display:block}
.gridline{position:absolute;left:36px;right:0;font-size:10px;color:var(--muted);border-top:1px dotted var(--rule);pointer-events:none}
.gridline span{position:absolute;left:-32px;top:-8px;font-variant-numeric:tabular-nums}
.gridline.threshold{border-top-style:dashed;border-top-color:var(--accent)}
.gridline.threshold span{color:var(--accent)}
.chart-empty{padding:40px 0;text-align:center;color:var(--muted);font-size:13px}

.timeline{margin:8px 0 0}
.round-row{border-bottom:1px solid var(--rule);padding:12px 0;cursor:pointer;transition:background .1s}
.round-row:hover{background:var(--paper-2)}
.round-row .head{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.round-row .head-left{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
.round-row .num{font-family:var(--mono);font-size:13px;color:var(--muted);min-width:28px}
.round-row .score{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--ink);min-width:32px}
.round-row .pills-inline{display:inline-flex;gap:4px}
.round-row .verdict{font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:1px 7px;font-family:var(--mono);border:1px solid transparent}
.round-row .verdict.accept,.round-row .verdict.accept_with_minors{background:var(--pass-bg);color:var(--pass);border-color:#bcd9c3}
.round-row .verdict.needs_revision{background:var(--warn-bg);color:var(--warn);border-color:#e5c79a}
.round-row .verdict.reject{background:var(--fail-bg);color:var(--fail);border-color:#f5b5b5}
.round-row .right{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;font-family:var(--mono);text-transform:uppercase;letter-spacing:.5px}
.round-row .right.stop{color:var(--pass)}
.round-row .right.escalate{color:var(--warn)}
.round-row .body{display:none;padding-top:10px;font-size:12.5px;color:var(--ink-2)}
.round-row.open .body{display:block}
.round-row .summary{margin:6px 0 8px;font-style:italic;color:var(--ink-2);line-height:1.6}
.round-row .issues{margin:0;padding:0;list-style:none}
.round-row .issues li{padding:3px 0;line-height:1.5;font-size:12px}
.round-row .issues li .tag{display:inline-block;width:24px;font-family:var(--mono);font-size:10px;color:var(--ink-2);text-align:center;border:1px solid var(--rule);margin-right:6px;font-weight:600;padding:1px 0}
.round-row .issues li.p0 .tag{background:var(--fail-bg);color:var(--fail);border-color:#f5b5b5}
.round-row .issues li.p1 .tag{background:var(--warn-bg);color:var(--warn);border-color:#e5c79a}
.round-row .issues li.p2 .tag{background:var(--accent-bg);color:var(--accent);border-color:#cdd9eb}

.pill{display:inline-block;padding:0 6px;font-size:10px;margin-right:3px;font-family:var(--mono);border:1px solid transparent;line-height:18px;letter-spacing:.3px}
.pill.p0{background:var(--fail-bg);color:var(--fail);border-color:#f5b5b5}
.pill.p1{background:var(--warn-bg);color:var(--warn);border-color:#e5c79a}
.pill.p2{background:var(--accent-bg);color:var(--accent);border-color:#cdd9eb}
.pill.zero{opacity:.35}

/* —— 闭环流程图：左右互搏工作流的可视化主线 —— */
.loop-flow{border:1px solid var(--rule);background:var(--paper-2);padding:14px 16px 10px;margin:0 0 20px}
.lf-track{display:flex;align-items:stretch;overflow-x:auto;padding-bottom:2px}
.lf-node{flex:1;min-width:92px;text-align:center;padding:8px 6px;border:1px solid var(--rule);background:#fff;position:relative}
.lf-node+.lf-node{margin-left:24px}
.lf-node+.lf-node::before{content:"→";position:absolute;left:-19px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:13px}
.lf-node .t{font-size:12px;font-weight:600;color:var(--ink-2);white-space:nowrap}
.lf-node .s{font-size:10px;color:var(--muted);margin-top:3px;line-height:1.4}
.lf-node.done{border-color:#bcd9c3;background:var(--pass-bg)}
.lf-node.done .t{color:var(--pass)}
.lf-node.active{border-color:var(--accent);background:var(--accent-bg);box-shadow:0 0 0 1px var(--accent)}
.lf-node.active .t{color:var(--accent)}
.lf-node.warn-active{border-color:var(--warn);background:var(--warn-bg);box-shadow:0 0 0 1px var(--warn)}
.lf-node.warn-active .t{color:var(--warn)}
.lf-node.dim{opacity:.45}
.lf-return{margin-top:10px;display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted);font-family:var(--mono)}
.lf-return .line{flex:1;border-top:1px dashed #b9c6da;position:relative}
.lf-return .line::before{content:"◂";position:absolute;left:-2px;top:-8px;color:#8ba3c7}
.lf-return b{color:var(--accent);font-weight:600}

/* —— 问题闭环台账 —— */
.issue-table{width:100%;border-collapse:collapse;font-size:12.5px}
.issue-table th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--rule)}
.issue-table td{padding:7px 8px;border-bottom:1px solid var(--rule-2);vertical-align:top}
.issue-table tr.closed td{opacity:.55}
.issue-table .iid{font-family:var(--mono);font-size:11px;color:var(--ink-2);white-space:nowrap}
.issue-table .ev{font-size:11px;color:var(--muted);font-family:var(--mono);margin-top:3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.issue-table .rr{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}
.ist{display:inline-block;padding:1px 7px;font-size:10px;font-family:var(--mono);border:1px solid transparent;white-space:nowrap}
.ist.open{background:var(--warn-bg);color:var(--warn);border-color:#e5c79a}
.ist.must_fix{background:var(--fail-bg);color:var(--fail);border-color:#f5b5b5}
.ist.resolved{background:var(--pass-bg);color:var(--pass);border-color:#bcd9c3}
.ist.withdrawn{background:var(--rule-2);color:var(--muted);border-color:var(--rule)}
.mini-h{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:600;margin:10px 0 4px}
.round-row .issues li.dispute .tag{background:#efe6fa;color:#6b3fa0;border-color:#d4bfef;width:auto;padding:1px 5px}
.round-row .issues li.res-resolved .tag,.round-row .issues li.res-withdrawn .tag,.round-row .issues li.res-persisting .tag{width:auto;padding:1px 5px}
.round-row .issues li.res-resolved .tag{background:var(--pass-bg);color:var(--pass);border-color:#bcd9c3}
.round-row .issues li.res-withdrawn .tag{background:var(--rule-2);color:var(--muted)}
.round-row .issues li.res-persisting .tag{background:var(--warn-bg);color:var(--warn);border-color:#e5c79a}

.tabs{display:flex;gap:0;margin-bottom:0;border-bottom:1px solid var(--rule);overflow-x:auto}
.tabs button{background:transparent;color:var(--muted);border:none;padding:8px 14px;font:inherit;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;border-radius:0;white-space:nowrap}
.tabs button.on{color:var(--ink);border-bottom-color:var(--ink)}
.tabs button:hover{color:var(--ink)}
.file-tools{display:flex;justify-content:space-between;align-items:center;padding:8px 0;font-size:11px;color:var(--muted)}
.file-tools .path{font-family:var(--mono)}
pre{white-space:pre-wrap;word-break:break-word;background:var(--paper-2);border:1px solid var(--rule);padding:14px;max-height:440px;overflow:auto;margin:0;font:12px/1.55 var(--mono);color:var(--ink)}

.paste-box{margin:16px 0 0;padding:14px 16px;background:var(--paper-2);border:1px solid var(--rule)}
.paste-box label{margin-top:0}
.paste-box textarea{min-height:160px;font-family:var(--mono);font-size:12px}

.empty{color:var(--muted);padding:48px 24px;text-align:center;font-size:13px;line-height:1.7}
.empty .big{font-size:14px;color:var(--ink-2);margin-bottom:6px;font-weight:500}

.toast{position:fixed;bottom:24px;right:24px;background:var(--ink);color:#fff;padding:10px 18px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:99;letter-spacing:.3px}
.toast.show{opacity:1}

footer{text-align:center;color:var(--muted);font-size:11px;padding:18px 0;font-family:var(--mono)}
</style>
</head>
<body>

<header>
  <h1>Y1 Sparring Bus<span class="sub">local · mode: sparring</span></h1>
  <div class="health" id="health">检测中…</div>
</header>

<main>
  <!-- 左：创建 + 列表 -->
  <div>
    <section class="panel">
      <h2>创建任务</h2>
      <div class="view-toggle" style="margin-bottom:4px">
        <button id="cm-file" class="on" onclick="setCreateMode('file')" type="button">选文件</button>
        <button id="cm-paste" onclick="setCreateMode('paste')" type="button">贴文本</button>
      </div>
      <div id="createFileMode">
        <label>文件路径（工作区内）</label>
        <div style="display:flex;gap:6px">
          <input id="source" placeholder="点右侧浏览，或粘绝对路径" style="flex:1">
          <button class="btn secondary" onclick="openBrowser()" type="button" title="打开文件浏览器">浏览…</button>
        </div>
      </div>
      <div id="createPasteMode" style="display:none">
        <label>标题（用于生成文件名）</label>
        <input id="pasteTitle" placeholder="例如：Q3 业务汇报">
        <label>粘贴全文</label>
        <textarea id="pasteContent" style="min-height:150px" placeholder="把要互搏的全文直接贴进来；开始后会自动存到工作区 sparring-inbox/ 下"></textarea>
      </div>
      <label>一句话目标</label>
      <div class="tpl-row">
        <button class="chip" type="button" onclick="applyTpl('汇报稿')">汇报稿</button>
        <button class="chip" type="button" onclick="applyTpl('方案页')">方案页</button>
        <button class="chip" type="button" onclick="applyTpl('Skill')">Skill</button>
        <button class="chip" type="button" onclick="applyTpl('法务')">法务</button>
      </div>
      <textarea id="goal" placeholder="例如：改得更适合给集团总裁汇报，结论前置，保留关键数据"></textarea>
      <div class="row">
        <div><label>最大轮数</label><input id="maxRounds" value="5"></div>
        <div><label>验收分</label><input id="threshold" value="85"></div>
        <div><label>Builder 模型</label>
          <select id="builderModel" style="width:100%;font:inherit;font-size:14px;padding:8px 10px;border:1px solid var(--rule);background:#fff;color:var(--ink);border-radius:0">
            <option value="sonnet">Sonnet（默认，便宜稳）</option>
            <option value="opus">Opus（贵 5x 但写得更好）</option>
            <option value="haiku">Haiku（最便宜，简单任务用）</option>
          </select>
        </div>
      </div>
      <label class="checkline"><input id="autoRun" type="checkbox" checked> 自动调用本机 Claude / Codex 跑完整轮次</label>
      <div class="actions-row">
        <button class="btn" onclick="startCreate()">开始互搏</button>
        <button class="btn secondary" onclick="fillSample()">填测试稿</button>
      </div>
      <div class="hint">点"开始互搏"会先做预检：文件存在、目标具体、文件类型一致 —— 都过了才真正创建 job。</div>
      <div class="error" id="createError"></div>
    </section>

    <!-- 文件浏览器 modal -->
    <div class="modal-mask" id="browserMask">
      <div class="modal">
        <header>
          <h3>选择文件</h3>
          <button class="close" onclick="closeBrowser()" type="button">×</button>
        </header>
        <div class="breadcrumb" id="browserCrumb"></div>
        <div class="fileinfo" id="browserInfo"></div>
        <div class="entries" id="browserEntries"></div>
      </div>
    </div>

    <!-- 预检 modal -->
    <div class="modal-mask" id="preflightMask">
      <div class="modal preflight-modal">
        <header>
          <h3>开始前预检</h3>
          <button class="close" onclick="closePreflight()" type="button">×</button>
        </header>
        <ul class="preflight-list" id="preflightList"></ul>
        <div class="preflight-preview" id="preflightPreviewWrap" style="display:none">
          <h4>文件前 500 字</h4>
          <pre id="preflightPreview"></pre>
        </div>
        <footer>
          <button class="btn secondary" onclick="closePreflight()" type="button">回去修改</button>
          <button class="btn" id="preflightConfirm" onclick="confirmCreate()" type="button">确认开始</button>
        </footer>
      </div>
    </div>

    <section class="panel">
      <h2>任务列表</h2>
      <div class="filter-chips" id="filter-chips"></div>
      <div id="jobs" class="jobs"></div>
    </section>
  </div>

  <!-- 右：详情 -->
  <section class="panel" id="detail" style="min-height:60vh">
    <div class="empty">
      <div class="big">选择左侧任务，或新建一个开始</div>
      <div>闭环工作流：Builder 修改隔离副本 → Runner 体检 → Reviewer 引证审查 → Judge 闭环判定 → 未达标回炉重来。<br>每个问题必须被修复或被反驳成立后撤回，台账 P0/P1 清零才轮到你决定合并。</div>
    </div>
  </section>
</main>

<footer id="footer-info">v1.1 · 本地控制中台 · 闭环互搏</footer>
<div class="toast" id="toast"></div>

<script>
const $=s=>document.querySelector(s);
let jobs=[], current=null, currentData=null, activeFile='TASK.md', openRounds=new Set(), healthData=null;

function esc(s){return (s==null?'':String(s)).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function pad3(n){return String(n).padStart(3,'0')}
function toast(msg, ms=2200){const t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(t._tmo);t._tmo=setTimeout(()=>t.classList.remove('show'),ms)}

async function api(path, opts={}){
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  const txt = await res.text();
  let data;try{data=txt?JSON.parse(txt):{}}catch(e){data={error:txt}}
  if(!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function loadHealth(){
  try{
    const h=await api('/api/health');
    healthData = h;
    const c=h.claude_cli, x=h.codex_cli;
    $('#health').innerHTML=
      `<span class="dot${c?'':' off'}"></span><b>Claude</b> ${c?'OK':'未检测'}` +
      `&nbsp;&nbsp;<span class="dot${x?'':' off'}"></span><b>Codex</b> ${x?'OK':'未检测'}` +
      `&nbsp;&nbsp;<span style="opacity:.5">·</span>&nbsp;&nbsp;${h.auto_mode_available?'自动可用':'手动接力'}`;
  }catch(e){$('#health').innerHTML='<span class="dot off"></span>server 失联'}
}

let jobFilter = 'pending';  // pending | merged | running | today | all

function isToday(iso){
  if(!iso) return false;
  const d = new Date(iso); if(isNaN(d)) return false;
  const n = new Date();
  return d.getFullYear()===n.getFullYear() && d.getMonth()===n.getMonth() && d.getDate()===n.getDate();
}

function classifyJob(j){
  const s = j.state || '';
  if(['READY_FOR_HUMAN_MERGE','ESCALATED'].includes(s)) return 'pending';
  if(s === 'MERGED') return 'merged';
  if(['WAIT_BUILDER','WAIT_REVIEWER'].includes(s)) return 'running';
  return 'other';
}

function applyJobFilter(all){
  if(jobFilter === 'all') return all;
  if(jobFilter === 'today') return all.filter(j => isToday(j.created_at));
  return all.filter(j => classifyJob(j) === jobFilter);
}

function renderFilterChips(all){
  const counts = {pending:0, merged:0, running:0, today:0, all:all.length};
  for(const j of all){
    const cls = classifyJob(j);
    if(cls in counts) counts[cls]++;
    if(isToday(j.created_at)) counts.today++;
  }
  const items = [
    {k:'pending', label:'待处理'},
    {k:'running', label:'进行中'},
    {k:'merged', label:'已合并'},
    {k:'today', label:'今天'},
    {k:'all', label:'全部'},
  ];
  $('#filter-chips').innerHTML = items.map(it =>
    `<button class="chip ${jobFilter===it.k?'on':''}" onclick="setJobFilter('${it.k}')">${esc(it.label)}<span class="count">${counts[it.k]||0}</span></button>`
  ).join('');
}

function setJobFilter(k){
  jobFilter = k;
  loadJobs();
}

async function loadJobs(){
  try{
    jobs = await api('/api/jobs');
    renderFilterChips(jobs);
    const filtered = applyJobFilter(jobs);
    const box=$('#jobs');
    if(!filtered.length){
      box.innerHTML='<div class="empty" style="padding:20px 0;font-size:12px">'+(jobs.length?'当前筛选下没有任务':'暂无 sparring job')+'</div>';
      return;
    }
    box.innerHTML=filtered.map(j=>{
      const trend=(j.scores_trend||[]).join(' → ')||'—';
      return `<div class="job-row ${j.job_id===current?'active':''}" onclick="selectJob('${esc(j.job_id)}')">
        <div class="row1">
          <div class="title">${esc(j.target_name||j.job_id)}</div>
          <span class="state state-${esc(j.state)}">${esc(j.state||'')}</span>
        </div>
        <div class="row2">
          <span>R ${esc(j.round)}/${esc(j.max_rounds)}</span>
          <span class="trend">${esc(trend)}</span>
        </div>
      </div>`;
    }).join('');
  }catch(e){/* ignore poll error */}
}

/* —— 创建模式：选文件 / 贴文本 —— */
let createMode = 'file';
function setCreateMode(m){
  createMode = m;
  $('#cm-file').classList.toggle('on', m==='file');
  $('#cm-paste').classList.toggle('on', m==='paste');
  $('#createFileMode').style.display = m==='file' ? '' : 'none';
  $('#createPasteMode').style.display = m==='paste' ? '' : 'none';
}
function createPayloadBase(){
  const p = {goal: goal.value};
  if(createMode==='paste'){
    p.content = ($('#pasteContent')||{}).value || '';
    p.title = ($('#pasteTitle')||{}).value || '';
  } else {
    p.source_path = source.value;
  }
  return p;
}

/* —— 预检 + 创建：startCreate → preflight 弹窗 → confirmCreate —— */
async function startCreate(){
  $('#createError').textContent='';
  try{
    const pre = await api('/api/preflight', {method:'POST', body:JSON.stringify(createPayloadBase())});
    renderPreflight(pre);
    $('#preflightMask').classList.add('open');
  }catch(e){ $('#createError').textContent=e.message }
}

function renderPreflight(pre){
  const list = $('#preflightList');
  list.innerHTML = pre.checks.map(c => {
    const mk = c.status === 'pass' ? '✓' : (c.status === 'warn' ? '⚠' : '✗');
    return `<li>
      <span class="mk ${c.status}">${mk}</span>
      <div class="item">${esc(c.item)}
        ${c.detail ? `<div class="detail">${esc(c.detail)}</div>` : ''}
      </div>
    </li>`;
  }).join('');
  if(pre.preview){
    $('#preflightPreview').textContent = pre.preview;
    $('#preflightPreviewWrap').style.display = 'block';
  } else {
    $('#preflightPreviewWrap').style.display = 'none';
  }
  const btn = $('#preflightConfirm');
  btn.disabled = !pre.ok;
  btn.textContent = pre.ok
    ? (pre.warn_count ? `仍要开始（有 ${pre.warn_count} 处提示）` : '确认开始')
    : '不通过，无法开始';
}

function closePreflight(){ $('#preflightMask').classList.remove('open') }

async function confirmCreate(){
  closePreflight();
  try{
    const payload={...createPayloadBase(), max_rounds:maxRounds.value, threshold:threshold.value, auto_run:autoRun.checked, builder_model:(document.getElementById('builderModel')||{}).value||'sonnet'};
    const j=await api('/api/jobs',{method:'POST',body:JSON.stringify(payload)});
    current=j.job_id; openRounds.clear();
    await loadJobs(); await selectJob(current);
    toast('Job 已创建：'+j.job_id);
  }catch(e){$('#createError').textContent=e.message}
}

/* —— 文件浏览器 —— */
let browserCwd = null;

async function openBrowser(){
  // 起点：当前 input 的目录（如果是有效目录），否则 workspace 根
  const seed = source.value && source.value.includes('/') ? source.value.replace(/\/[^/]*$/, '') : null;
  await loadBrowser(seed);
  $('#browserMask').classList.add('open');
}
function closeBrowser(){ $('#browserMask').classList.remove('open') }

async function loadBrowser(path){
  try{
    const url = path ? '/api/browse?path=' + encodeURIComponent(path) : '/api/browse';
    const d = await api(url);
    browserCwd = d.path;
    // breadcrumb：把 workspace 之内的相对路径切成可点击的段
    const workspace = d.workspace;
    const rel = d.rel || '';
    const segs = rel ? rel.split('/').filter(Boolean) : [];
    const crumbs = ['<a onclick="loadBrowser(\''+esc(workspace)+'\')">Workspace</a>'];
    let cum = workspace;
    segs.forEach(s=>{
      cum = cum + '/' + s;
      crumbs.push(' / <a onclick="loadBrowser(\''+esc(cum)+'\')">'+esc(s)+'</a>');
    });
    $('#browserCrumb').innerHTML = crumbs.join('');
    $('#browserInfo').textContent = d.path;
    if(!d.entries.length){
      $('#browserEntries').innerHTML = '<div class="empty">（这个文件夹是空的，或者全是隐藏文件）</div>';
      return;
    }
    $('#browserEntries').innerHTML = d.entries.map(e=>{
      const icon = e.is_dir ? '▸' : '·';
      const size = e.is_dir ? '' : ((e.size||0).toLocaleString() + ' B');
      const cls = e.is_dir ? 'dir' : 'file';
      const action = e.is_dir
        ? `loadBrowser('${esc(e.path)}')`
        : `pickFile('${esc(e.path)}')`;
      return `<div class="row ${cls}" onclick="${action}">
        <span><span class="icon">${icon}</span><span class="name">${esc(e.name)}</span></span>
        <span class="size">${size}</span>
      </div>`;
    }).join('');
  }catch(e){
    $('#browserEntries').innerHTML = '<div class="empty" style="color:var(--fail)">'+esc(e.message)+'</div>';
  }
}

function pickFile(path){
  source.value = path;
  closeBrowser();
  toast('已选：'+path.split('/').pop());
}

const GOAL_TEMPLATES = {
  '汇报稿': '改成给领导汇报版：结论前置，每段第一句即判断；压缩废话、删 CYA 推责句；数字必有年份/口径/出处；保留关键模块完整性。',
  '方案页': '改成对外提案版：逻辑链更强（先判断 → 后证据 → 再动作）；标题更锋利、可读；减少空话和铺垫；保留所有数字依据。',
  'Skill':  '改成 Claude Skill 规范：触发边界写清楚（什么时候用 / 什么时候不用）；步骤可执行、可验证；防误触；避免开放式哲学指令。',
  '法务':   '改成法务材料版：事实、证据、诉求三段分离；事实只陈述无评论；证据有来源；诉求具体可衡量；禁含义模糊语。',
};
function applyTpl(name){
  const t = GOAL_TEMPLATES[name];
  if(!t) return;
  const el = document.getElementById('goal');
  if(!el) return;
  el.value = t;
  el.focus();
  toast('已套用模板："'+name+'"，可在此基础上微调');
}

function fillSample(){
  setCreateMode('file');
  source.value=(healthData && healthData.sample_path) || 'examples/demo_proposal_zh.md';
  goal.value='改得更适合给省厅领导汇报，结论前置，删除防御性表达，保留核心业务模块';
}

async function selectJob(id){
  current=id; activeFile='TASK.md';
  currentData=await api('/api/jobs/'+id);
  await loadJobs();
  renderDetail();
}

/* —— 闭环流程图：把左右互搏的工作流画成一条带回环的主线 —— */
function renderLoopFlow(j){
  const nodes=[
    {t:'快照冻结', s:'原文只读'},
    {t:'Builder', s:'修复 / 反驳'},
    {t:'Runner', s:'规则体检'},
    {t:'Reviewer', s:'引证审查 · 仲裁'},
    {t:'Judge', s:'闭环判定'},
    {t:'人工决策', s:'合并 / 放弃'},
  ];
  const st=j.state;
  let activeIdx=-1, doneUpto=0, humanCls='active';
  if(st==='WAIT_BUILDER'){activeIdx=1;doneUpto=1}
  else if(st==='WAIT_REVIEWER'){activeIdx=(j.auto_phase||'').startsWith('reviewer')?3:2;doneUpto=activeIdx}
  else if(st==='READY_FOR_HUMAN_MERGE'){activeIdx=5;doneUpto=5}
  else if(st==='ESCALATED'){activeIdx=5;doneUpto=5;humanCls='warn-active'}
  else if(st==='MERGED'){activeIdx=-1;doneUpto=6}
  const aborted = st==='ABORTED';
  const html=nodes.map((n,i)=>{
    let cls='';
    if(aborted) cls='dim';
    else if(i===activeIdx) cls=(i===5?humanCls:'active');
    else if(i<doneUpto) cls='done';
    return `<div class="lf-node ${cls}"><div class="t">${esc(n.t)}</div><div class="s">${esc(n.s)}</div></div>`;
  }).join('');
  const loopLabel = aborted
    ? '已放弃 · 循环终止'
    : (st==='MERGED'
      ? '已合并 · 闭环完成'
      : `↺ 未达标回到 Builder　·　Round <b>${esc(j.round)}</b>/${esc(j.max_rounds)}　·　验收 ≥${esc(j.threshold||85)} 且台账 P0/P1 清零`);
  return `<div class="loop-flow">
    <div class="lf-track">${html}</div>
    <div class="lf-return"><span class="line"></span><span>${loopLabel}</span></div>
  </div>`;
}

/* —— 问题闭环台账：每个问题从提出到闭环的全生命周期 —— */
function renderIssueLedger(issues){
  if(!issues || !issues.length) return '';
  const OPEN=['open','must_fix'];
  const sevRank={p0:0,p1:1,p2:2};
  const sorted=[...issues].sort((a,b)=>{
    const ao=OPEN.includes(a.status)?0:1, bo=OPEN.includes(b.status)?0:1;
    if(ao!==bo) return ao-bo;
    if((sevRank[a.severity]??3)!==(sevRank[b.severity]??3)) return (sevRank[a.severity]??3)-(sevRank[b.severity]??3);
    return (a.opened_round||0)-(b.opened_round||0);
  });
  const stLabel={open:'开放中',must_fix:'必须修',resolved:'已闭环',withdrawn:'已撤回'};
  const nOpen=issues.filter(i=>OPEN.includes(i.status)).length;
  const nClosed=issues.length-nOpen;
  const rows=sorted.map(i=>{
    const closed=!OPEN.includes(i.status);
    const ev = i.evidence
      ? `<div class="ev" title="${esc(i.evidence)}">“${esc(i.evidence.slice(0,160))}”${i.evidence_verified?'':' <span style="color:var(--warn)">⚠ 引用未在文中找到</span>'}</div>`
      : `<div class="ev" style="color:var(--warn)">⚠ 无证据引用</div>`;
    const dispute = i.dispute_reason ? `<div class="ev" style="color:#6b3fa0">Builder 反驳：${esc(i.dispute_reason.slice(0,120))}</div>` : '';
    const note = i.close_note ? `<div class="ev">${esc(i.close_note.slice(0,120))}</div>` : '';
    const rr = `R${i.opened_round||'?'} → ${closed?('R'+(i.closed_round||'?')):'…'}`;
    return `<tr class="${closed?'closed':''}">
      <td class="iid">${esc(i.id||'')}</td>
      <td><span class="pill ${esc(i.severity||'p2')}">${esc((i.severity||'').toUpperCase())}</span></td>
      <td>${esc(i.desc||'')}${ev}${dispute}${note}</td>
      <td><span class="ist ${esc(i.status||'open')}">${esc(stLabel[i.status]||i.status||'')}</span></td>
      <td class="rr">${rr}</td>
    </tr>`;
  }).join('');
  return `<div class="section">
    <h3>问题闭环台账 · 开放 ${nOpen} · 已闭环 ${nClosed}</h3>
    <div style="overflow-x:auto"><table class="issue-table">
      <tr><th>ID</th><th>级</th><th>问题 / 证据 / 反驳</th><th>状态</th><th>轮次</th></tr>
      ${rows}
    </table></div>
    <div class="hint" style="margin-top:6px">闭环规则：每条问题必须被 <b>修复</b> 或被 <b>反驳成立后撤回</b>；Builder 反驳、Reviewer 坚持 2 次后升级为"必须修"。Judge 只在台账 P0/P1 全部闭环后才放行。</div>
  </div>`;
}

/* —— Next-action 横幅：state 决定下一步该看到什么 —— */
/* —— 决策卡：终态时给最强视觉重心 —— */
function renderVerdictCard(j, rounds, issues){
  const isTerminal = ['READY_FOR_HUMAN_MERGE','ESCALATED'].includes(j.state);
  if(!isTerminal) return '';
  const last = (rounds||[]).slice(-1)[0] || {};
  const score = (last.scores||{}).requirement_fit;
  const threshold = j.threshold || 85;
  // 风险口径 = 问题闭环台账（open/must_fix），不是 Reviewer 当轮报数；老 job 没台账时回退旧口径
  const OPEN=['open','must_fix'];
  const ledger=(issues||[]).filter(i=>OPEN.includes(i.status));
  const hasLedger=(issues||[]).length>0;
  const p0 = hasLedger ? ledger.filter(i=>i.severity==='p0').length : (last.p0||0);
  const p1 = hasLedger ? ledger.filter(i=>i.severity==='p1').length : (last.p1||0);
  const p2 = hasLedger ? ledger.filter(i=>i.severity==='p2').length : (last.p2||0);
  const verdict = last.verdict || '';
  const summary = last.summary || '';
  // 综合判断：可合并 / 建议再跑 / 不建议合并
  let cls, title, sub;
  if(j.state === 'READY_FOR_HUMAN_MERGE' && p0 === 0 && p1 === 0){
    cls = 'recommend';
    title = '✓ 可以合并';
    sub = `${verdict==='accept'?'Reviewer 给出 accept':'Reviewer 接受改动，仅余可选优化'}`;
  } else if(p0 > 0){
    cls = 'reject';
    title = '✗ 不建议合并';
    sub = `仍有 ${p0} 个阻断性 P0 问题未解决`;
  } else if(p1 > 0){
    cls = 'caution';
    title = '⚠ 建议再跑一轮';
    sub = `台账仍有 ${p1} 个 P1 未闭环；可点"重跑 Reviewer"或自行权衡后合并`;
  } else {
    cls = 'caution';
    title = '⚠ 由你最终决定';
    sub = '未达阈值但已无 P0/P1，自行权衡';
  }
  return `<div class="verdict-card ${cls}">
    <div class="top-row">
      <div>
        <div class="verdict-label">人工决策</div>
        <div class="verdict-title">${esc(title)}</div>
        <div style="color:var(--muted);font-size:13px;margin-top:4px">${esc(sub)}</div>
      </div>
      <div style="text-align:right">
        <div class="verdict-label" style="margin-bottom:2px">最终评分</div>
        <div class="score-tag">${score==null?'—':score}<span class="thr">/ ${threshold}</span></div>
      </div>
    </div>
    ${summary?`<div class="reviewer-quote">"${esc(summary)}"</div>`:''}
    <div class="risk-row">
      <span>剩余风险：</span>
      <span class="pill p0 ${p0?'':'zero'}">P0 × ${p0}</span>
      <span class="pill p1 ${p1?'':'zero'}">P1 × ${p1}</span>
      <span class="pill p2 ${p2?'':'zero'}">P2 × ${p2}</span>
    </div>
    <div class="big-actions">
      <button class="btn" onclick="showCompareView()">看改稿对照</button>
      <button class="btn" onclick="showFile('FINAL.diff')">看完整 diff</button>
      <button class="btn btn-merge" onclick="mergeJob()">合并到原文件</button>
      <button class="btn secondary" onclick="copyFinalDoc()">复制最终稿</button>
      <button class="btn secondary" onclick="exportFinal()">另存副本</button>
      <button class="btn btn-reject" onclick="abortJob()">放弃</button>
    </div>
  </div>`;
}

function renderNextAction(j){
  const r=pad3(j.round);
  const builderPrompt=`rounds/r${r}.builder.prompt.md`;
  const reviewerPrompt=`rounds/r${r}.reviewer.prompt.md`;
  if(j.auto_running){
    return {tone:'',label:`自动运行中 · ${esc(j.auto_phase||'queued')}`,
      title:'后台正在调用本机 Claude / Codex',
      steps:['不要关闭本机服务进程','页面会自动刷新状态','如果失败，会显示 AUTO_ERROR.log 并允许手动接力或重新自动跑'],
      primary:null,
      secondary:[
        {label:'看 STATUS',fn:`showFile('STATUS.json')`},
        {label:'看 ledger',fn:`showFile('ledger.jsonl')`},
      ]};
  }
  if(j.auto_error && (j.state==='WAIT_BUILDER' || j.state==='WAIT_REVIEWER')){
    return {tone:'escalated',label:'自动运行失败',
      title:j.auto_error,
      steps:['可以点“继续自动跑”重试','也可以复制当前轮指令，手动交给 Claude/Codex'],
      primary:{label:'继续自动跑',cls:'warn',fn:'startAuto()'},
      secondary:[
        {label:'看 AUTO_ERROR',fn:`showFile('AUTO_ERROR.log')`},
        {label:'看当前指令',fn:`showFile('${j.state==='WAIT_BUILDER'?builderPrompt:reviewerPrompt}')`},
      ]};
  }
  switch(j.state){
    case 'WAIT_BUILDER':
      return {tone:'',label:`下一步 · Round ${j.round} · Builder`,
        title:'自动调用 Claude 进入 Builder 阶段',
        steps:['点“自动跑”会由后台调用 claude CLI','Claude 只修改 worktree 副本并写 builder.json','失败时可切回手动复制指令'],
        primary:{label:'自动跑',cls:'warn',fn:'startAuto()'},
        secondary:[
          {label:'复制 Builder 指令',fn:`copyFile('${builderPrompt}','Builder 指令已复制 → 去贴给 Claude')`},
          {label:'看 Builder 指令',fn:`showFile('${builderPrompt}')`},
          {label:'Builder 完成后 →',cls:'warn',fn:'afterBuilder()'},
        ]};
    case 'WAIT_REVIEWER':
      return {tone:'',label:`下一步 · Round ${j.round} · Reviewer`,
        title:'自动调用 Codex 审查本轮 diff',
        steps:['点“自动跑”会由后台调用 codex exec','Codex 只读审查并返回 JSON','Judge 会自动判断 continue / stop / escalate'],
        primary:{label:'自动跑',cls:'warn',fn:'startAuto()'},
        secondary:[
          {label:'复制 Reviewer 指令',fn:`copyFile('${reviewerPrompt}','Reviewer 指令已复制 → 去 Codex')`},
          {label:'看 Reviewer 指令',fn:`showFile('${reviewerPrompt}')`},
          {label:'粘贴 JSON →',cls:'warn',fn:'showPasteReview()'},
        ]};
    case 'READY_FOR_HUMAN_MERGE':
      return {tone:'done',label:'已收敛',
        title:'AI 评分达到阈值，由你决定要不要合并',
        steps:['看 FINAL_REVIEW.md（核心改动 + 剩余 P2）','看 FINAL.diff（完整差异）','合并：覆盖原文件，自动留备份','放弃：什么都不动，文件留作审计'],
        primary:{label:'确认合并到原文件',cls:'warn',fn:'mergeJob()'},
        secondary:[
          {label:'看 FINAL_REVIEW',fn:`showFile('FINAL_REVIEW.md')`},
          {label:'看 FINAL.diff',fn:`showFile('FINAL.diff')`},
          {label:'放弃此 job',cls:'secondary',fn:'abortJob()'},
        ]};
    case 'ESCALATED':
      return {tone:'escalated',label:'未达标 · 已升级给你',
        title:'跑完轮数仍未通过阈值，由你最终决定',
        steps:['看 FINAL_REVIEW 里 Reviewer 还未解决的问题','可以仍然合并（带备份），可以放弃，也可以手动改 worktree 再合并'],
        primary:{label:'看 FINAL_REVIEW',fn:`showFile('FINAL_REVIEW.md')`},
        secondary:[
          {label:'看 FINAL.diff',fn:`showFile('FINAL.diff')`},
          {label:'强行合并',cls:'warn',fn:'mergeJob()'},
          {label:'放弃',cls:'secondary',fn:'abortJob()'},
        ]};
    case 'MERGED':
      return {tone:'terminal',label:'已合并',
        title:'FINAL 已覆盖回原文件，备份留在 ORIGINAL_BEFORE_MERGE',
        steps:[],
        primary:null,
        secondary:[
          {label:'看 FINAL.diff',fn:`showFile('FINAL.diff')`},
          {label:'复制最终稿',fn:'copyFinalDoc()'},
          {label:'另存副本',fn:'exportFinal()'},
        ]};
    case 'ABORTED':
      return {tone:'terminal',label:'已放弃',
        title:'此 job 已终止，所有文件保留供审计',
        steps:[],primary:null,secondary:[]};
    default:
      return {tone:'terminal',label:j.state,title:'未知状态',steps:[],primary:null,secondary:[]};
  }
}

function renderScoreChart(trend, threshold){
  if(!trend || !trend.length){
    return '<div class="chart-empty">尚无评分</div>';
  }
  // 单点情况：折线图没意义，换成大字结果卡
  if(trend.length === 1){
    const v = trend[0];
    const pass = v >= threshold;
    return `<div class="chart-empty" style="display:flex;align-items:baseline;gap:14px;justify-content:flex-start;padding:18px 36px">
      <span style="font-size:36px;font-weight:600;color:${pass?'var(--pass)':'var(--warn)'};font-variant-numeric:tabular-nums">${v}</span>
      <span style="color:var(--muted)">/ ${threshold}（阈值）</span>
      <span style="color:${pass?'var(--pass)':'var(--warn)'};font-size:13px">${pass?'✓ 达标':'未达标'}</span>
      <span style="color:var(--muted);font-size:12px;margin-left:auto">单轮收敛，多跑几轮才看得到曲线</span>
    </div>`;
  }
  const w=300, h=120, pad=4;
  const max=Math.max(...trend, threshold||85, 100);
  const min=Math.min(...trend, 50);
  const yScale = v => h - ((v - 50) / (100 - 50)) * (h - 8);
  const n=trend.length;
  const xs=trend.map((_,i)=> n===1 ? w/2 : pad + (w-2*pad) * i/(n-1));
  const ys=trend.map(v => yScale(Math.max(50, Math.min(100, v))));
  const pts=xs.map((x,i)=>`${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const circles=xs.map((x,i)=>`
    <circle cx="${x.toFixed(1)}" cy="${ys[i].toFixed(1)}" r="3" fill="var(--accent)"/>
    <text x="${x.toFixed(1)}" y="${(ys[i]-8).toFixed(1)}" font-size="10" fill="var(--accent)" text-anchor="middle" font-family="var(--mono)">${trend[i]}</text>
    <text x="${x.toFixed(1)}" y="${h+12}" font-size="10" fill="var(--muted)" text-anchor="middle" font-family="var(--mono)">R${i+1}</text>
  `).join('');
  const thresholdY = yScale(threshold).toFixed(1);
  return `<div class="chart-wrap">
    <div class="gridline" style="top:${yScale(100).toFixed(1)}px"><span>100</span></div>
    <div class="gridline threshold" style="top:${thresholdY}px"><span>${threshold}</span></div>
    <div class="gridline" style="top:${yScale(75).toFixed(1)}px"><span>75</span></div>
    <div class="gridline" style="top:${yScale(50).toFixed(1)}px"><span>50</span></div>
    <svg viewBox="0 0 ${w} ${h+18}" preserveAspectRatio="xMidYMid meet" style="max-width:480px">
      <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>
      ${circles}
    </svg></div>`;
}

function renderRoundTimeline(rounds){
  if(!rounds || !rounds.length){
    return '<div class="empty" style="padding:24px 0">尚无完成的轮次</div>';
  }
  return rounds.map(r=>{
    const sc = r.scores||{};
    const verdict=r.verdict||'';
    const dec=r.decision||'';
    const open = openRounds.has(r.round);
    const items=[];
    (r.p0_items||[]).forEach(s=>items.push(`<li class="p0"><span class="tag">P0</span>${esc(s)}</li>`));
    (r.p1_items||[]).forEach(s=>items.push(`<li class="p1"><span class="tag">P1</span>${esc(s)}</li>`));
    (r.p2_items||[]).forEach(s=>items.push(`<li class="p2"><span class="tag">P2</span>${esc(s)}</li>`));
    const disputes=(r.disputes||[]).map(d=>`<li class="dispute"><span class="tag">反驳</span>[${esc(d.id)}] ${esc(d.reason)}</li>`);
    const resLabel={resolved:'✓ 已修复',withdrawn:'↩ 撤回',persisting:'✗ 仍在'};
    const resols=(r.resolutions||[]).map(x=>`<li class="res-${esc(x.status)}"><span class="tag">${resLabel[x.status]||esc(x.status)}</span>[${esc(x.id)}] ${esc(x.note||'')}</li>`);
    return `<div class="round-row ${open?'open':''}" onclick="toggleRound(${r.round})">
      <div class="head">
        <div class="head-left">
          <span class="num">R${r.round}</span>
          <span class="score">${sc.requirement_fit||'—'}</span>
          <span class="pills-inline">
            <span class="pill p0 ${(r.p0||0)?'':'zero'}">P0 ${r.p0||0}</span>
            <span class="pill p1 ${(r.p1||0)?'':'zero'}">P1 ${r.p1||0}</span>
            <span class="pill p2 ${(r.p2||0)?'':'zero'}">P2 ${r.p2||0}</span>
          </span>
          ${verdict?`<span class="verdict ${esc(verdict)}">${esc(verdict)}</span>`:''}
        </div>
        <div class="right ${dec==='stop'?'stop':(dec==='escalate'?'escalate':'')}">
          ${r.open_p0!=null?`<span style="opacity:.7;margin-right:8px">台账开放 P0 ${r.open_p0}·P1 ${r.open_p1}</span>`:''}
          ${r.total_label?`<span style="opacity:.7;margin-right:8px">${esc(r.total_label)}</span>`:''}
          ${r.cost_cny?`<span style="opacity:.7;margin-right:8px">¥${r.cost_cny.toFixed(1)}</span>`:''}
          ${esc(dec||'')}
        </div>
      </div>
      ${r.summary && !open ? `<div class="summary-collapsed">${esc(r.summary)}</div>` : ''}
      <div class="body">
        ${r.summary?`<div class="summary">${esc(r.summary)}</div>`:''}
        ${r.changes_summary?`<div class="mini-h">Builder 本轮</div><div style="font-size:12px;color:var(--ink-2)">${esc(r.changes_summary)}</div>`:''}
        ${disputes.length?`<div class="mini-h">Builder 反驳（待 Reviewer 仲裁）</div><ul class="issues">${disputes.join('')}</ul>`:''}
        ${resols.length?`<div class="mini-h">Reviewer 闭环裁定</div><ul class="issues">${resols.join('')}</ul>`:''}
        ${items.length?`<div class="mini-h">新提出的问题</div><ul class="issues">${items.join('')}</ul>`:'<div class="hint">(本轮无新问题)</div>'}
        <div style="margin-top:10px;display:flex;gap:6px">
          <button class="btn ghost sm" onclick="event.stopPropagation();retryReviewer(${r.round})" title="把当前 Reviewer 评分丢掉重跑一次（备份旧的）">重跑 Reviewer</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

function toggleRound(n){
  if(openRounds.has(n)) openRounds.delete(n);
  else openRounds.add(n);
  // 仅重渲染时间线，避免抖动
  const wrap = document.getElementById('timeline-wrap');
  if(wrap && currentData) wrap.innerHTML = renderRoundTimeline(currentData.rounds||[]);
}

function renderDetail(){
  const j=currentData.status;
  const next=renderNextAction(j);
  const trend=j.scores_trend||[];
  const threshold=j.threshold||85;
  const created=esc(j.created_at||'');
  const updated=esc(j.updated_at||'');
  const goal=esc(j.goal||'');
  const target=esc(j.target_name||'');
  const stateEl=`<span class="state state-${esc(j.state)}">${esc(j.state||'')}</span>`;
  const nextBtns = [];
  if(next.primary) nextBtns.push(`<button class="btn ${next.primary.cls||''}" onclick="${next.primary.fn}">${esc(next.primary.label)}</button>`);
  (next.secondary||[]).forEach(b=>nextBtns.push(`<button class="btn ${b.cls||'secondary'}" onclick="${b.fn}">${esc(b.label)}</button>`));

  const errBanner = (j.auto_error || j.auto_phase==='error')
    ? `<div class="err-banner">
         <div><strong>自动运行失败</strong>　·　${esc(j.auto_phase||'')}　·　${esc((j.auto_error||'未知错误').slice(0,200))}</div>
         <button class="btn sm secondary" onclick="showFile('AUTO_ERROR.log')">看完整 traceback</button>
       </div>`
    : '';
  const isTerminal = ['READY_FOR_HUMAN_MERGE','ESCALATED'].includes(j.state);
  const verdictCard = renderVerdictCard(j, currentData.rounds||[], currentData.issues||[]);
  // 终态下 next-action 块降级为弱辅助；非终态保持原来的位置
  const nextActionBlock = isTerminal ? '' : `
    <div class="next-action ${next.tone||''}">
      <div class="label">${esc(next.label)}</div>
      <div class="title">${esc(next.title)}</div>
      ${next.steps && next.steps.length?`<ol class="step-list">${next.steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol>`:''}
      <div class="actions-row">${nextBtns.join('')}</div>
    </div>`;

  $('#detail').innerHTML = `
    <div class="detail-head">
      <div>
        <div class="detail-title">${target}</div>
        <div class="detail-meta">${stateEl}<span class="sep">·</span>R ${esc(j.round)}/${esc(j.max_rounds)}<span class="sep">·</span>阈值 ${esc(threshold)}<span class="sep">·</span>更新于 ${updated}</div>
        <div class="detail-meta" style="margin-top:4px"><b>目标</b> ${goal}</div>
      </div>
    </div>
    ${renderLoopFlow(j)}
    ${errBanner}
    ${verdictCard}
    ${nextActionBlock}

    <div id="paste-mount"></div>

    <div class="section">
      <h3>评分轨迹 · 阈值 ${threshold}</h3>
      ${renderScoreChart(trend, threshold)}
    </div>

    ${renderIssueLedger(currentData.issues||[])}

    <div class="section">
      <h3>轮次明细 · ${(currentData.rounds||[]).length} 轮已完成</h3>
      <div class="timeline" id="timeline-wrap">${renderRoundTimeline(currentData.rounds||[])}</div>
    </div>

    <div class="section">
      <h3>文件 / 改稿对照</h3>
      <div id="file-viewer-mount"></div>
      <div class="hint" style="margin-top:8px">Job 目录：<span style="font-family:var(--mono)">${esc(currentData.job_dir||'')}</span></div>
      <div class="error" id="detailError"></div>
    </div>
  `;
  // 终态默认打开"改稿对照"，否则默认"文件浏览"
  fileViewMode = isTerminal ? 'compare' : 'tabs';
  renderFileViewer();
}

function renderFileTabs(j){
  const r=pad3(j.round);
  const tabs=['TASK.md','STATUS.json','ledger.jsonl'];
  // 当前轮的工件
  if(j.round){
    tabs.push(`rounds/r${r}.builder.prompt.md`);
    tabs.push(`rounds/r${r}.builder.json`);
    tabs.push(`rounds/r${r}.runner.log`);
    tabs.push(`rounds/r${r}.reviewer.prompt.md`);
    tabs.push(`rounds/r${r}.reviewer.json`);
    tabs.push(`rounds/r${r}.judge.json`);
  }
  if(j.has_final){tabs.push('FINAL_REVIEW.md');tabs.push('FINAL.diff');tabs.push('FINAL.md')}
  if(j.auto_error){tabs.push('AUTO_ERROR.log')}
  const el=$('#file-tabs');
  el.innerHTML=tabs.map(n=>{
    const short=n.split('/').pop();
    return `<button class="${activeFile===n?'on':''}" title="${esc(n)}" onclick="showFile('${esc(n)}')">${esc(short)}</button>`;
  }).join('');
}

async function showFile(name, quiet=false){
  activeFile=name;
  $('#file-path') && ($('#file-path').textContent=name);
  document.querySelectorAll('#file-tabs button').forEach(b=>{
    b.classList.toggle('on', b.title===name || b.textContent===name.split('/').pop());
  });
  try{
    const d=await api('/api/jobs/'+current+'/file?name='+encodeURIComponent(name));
    const box=$('#fileBox'); if(!box) return;
    // .diff 文件用 GitHub 风格高亮
    if(/\.diff$/i.test(name)){
      const lines = (d.content||'').split('\n').map(line=>{
        let cls = '';
        if(line.startsWith('+++') || line.startsWith('---')) cls='meta';
        else if(line.startsWith('@@')) cls='hunk';
        else if(line.startsWith('+')) cls='add';
        else if(line.startsWith('-')) cls='del';
        return '<span class="ln '+cls+'">'+esc(line||' ')+'</span>';
      });
      box.outerHTML = '<div id="fileBox" class="diff-view">'+lines.join('')+'</div>';
    } else {
      // 之前可能被换成 diff-view，要换回 pre
      if(box.tagName !== 'PRE'){
        box.outerHTML = '<pre id="fileBox">'+esc(d.content||'(空)')+'</pre>';
      } else {
        box.textContent = d.content||'(空)';
      }
    }
  }catch(e){if(!quiet){const er=$('#detailError'); if(er) er.textContent=e.message}}
}

/* —— 左右对照视图：原文 / 最终 + Reviewer 总结 —— */
let fileViewMode = 'tabs';  // 'tabs' | 'compare'

async function showCompareView(){
  fileViewMode = 'compare';
  // 滚到文件浏览区
  const box = document.getElementById('fileBox');
  if(box) box.scrollIntoView({behavior:'smooth', block:'start'});
  renderFileViewer();
}
function showTabsView(){
  fileViewMode = 'tabs';
  renderFileViewer();
}

async function renderFileViewer(){
  // 由 renderDetail 后注入两套视图切换
  const mount = document.getElementById('file-viewer-mount');
  if(!mount) return;
  const j = currentData.status;
  const targetName = j.target_name || 'file';
  const lastReviewer = (currentData.rounds||[]).slice(-1)[0] || {};

  if(fileViewMode === 'compare'){
    // fetch 原文 + 最终
    let orig='(读取失败)', final='(读取失败)';
    try{
      const a = await api('/api/jobs/'+current+'/file?name='+encodeURIComponent('INPUT_SNAPSHOT/'+targetName));
      orig = a.content || '(空)';
    }catch{}
    try{
      const b = await api('/api/jobs/'+current+'/file?name='+encodeURIComponent('worktree/'+targetName));
      final = b.content || '(空)';
    }catch{}
    const origLines = orig.split('\n').length;
    const finalLines = final.split('\n').length;
    mount.innerHTML = `
      <div class="view-toggle">
        <button onclick="showTabsView()">文件浏览</button>
        <button class="on" onclick="showCompareView()">改稿对照</button>
      </div>
      ${lastReviewer.summary?`<div class="reviewer-quote" style="background:var(--paper-2);border-left:3px solid var(--accent);padding:10px 14px;margin:0 0 10px;font-style:italic;color:var(--ink-2);font-size:13px">Reviewer："${esc(lastReviewer.summary)}"</div>`:''}
      <div class="compare-view">
        <div class="col">
          <h5>原文 INPUT_SNAPSHOT/${esc(targetName)}<span class="meta">${origLines} 行</span></h5>
          <div class="body">${esc(orig)}</div>
        </div>
        <div class="col">
          <h5>最终 worktree/${esc(targetName)}<span class="meta">${finalLines} 行</span></h5>
          <div class="body">${esc(final)}</div>
        </div>
      </div>
      <div class="hint" style="margin-top:8px">提示：滚动各栏独立浏览；想看精确字符级差异点 <a onclick="showTabsView();setTimeout(()=>showFile('FINAL.diff'),50);return false" style="cursor:pointer;color:var(--accent)">完整 diff</a>。</div>
    `;
  } else {
    // 标准 tabs view
    mount.innerHTML = `
      <div class="view-toggle">
        <button class="on" onclick="showTabsView()">文件浏览</button>
        <button onclick="showCompareView()">改稿对照</button>
      </div>
      <div class="tabs" id="file-tabs"></div>
      <div class="file-tools">
        <span class="path" id="file-path">${esc(activeFile)}</span>
        <button class="btn ghost sm" onclick="copyActiveFile()">复制全文</button>
      </div>
      <pre id="fileBox">${esc(currentData.preview||'')}</pre>
    `;
    renderFileTabs(j);
    showFile(activeFile, true);
  }
}

async function retryReviewer(round){
  if(!confirm('重跑 Round '+round+' 的 Reviewer？\n旧的 reviewer/judge 会被备份成 .bak 文件。终态 job 会回退到 WAIT_REVIEWER。')) return;
  try{
    await api('/api/jobs/'+current+'/retry-reviewer',{method:'POST',body:'{}'});
    toast('已触发重跑 Reviewer，约 30-60s 出新结果');
    setTimeout(()=>selectJob(current).catch(()=>{}), 1500);
  }catch(e){ toast('重跑失败：'+e.message) }
}

async function copyActiveFile(){
  try{
    const d=await api('/api/jobs/'+current+'/file?name='+encodeURIComponent(activeFile));
    await navigator.clipboard.writeText(d.content||'');
    toast('已复制 '+activeFile.split('/').pop());
  }catch(e){toast('复制失败：'+e.message)}
}

async function copyFile(name, msg){
  try{
    const d=await api('/api/jobs/'+current+'/file?name='+encodeURIComponent(name));
    await navigator.clipboard.writeText(d.content||'');
    toast(msg || ('已复制 '+name));
  }catch(e){toast('复制失败：'+e.message)}
}

async function afterBuilder(){
  try{
    await api('/api/jobs/'+current+'/after-builder',{method:'POST',body:'{}'});
    await selectJob(current); toast('已切到 Reviewer 阶段');
  }catch(e){$('#detailError') && ($('#detailError').textContent=e.message); toast('失败：'+e.message)}
}

async function startAuto(){
  try{
    await api('/api/jobs/'+current+'/auto-run',{method:'POST',body:JSON.stringify({builder_model:'sonnet'})});
    toast('自动运行已启动');
    await selectJob(current);
  }catch(e){$('#detailError') && ($('#detailError').textContent=e.message); toast('自动启动失败：'+e.message)}
}

function showPasteReview(){
  const mount=$('#paste-mount');
  if(!mount) return;
  if(mount.dataset.open==='1'){mount.innerHTML='';mount.dataset.open='';return}
  mount.dataset.open='1';
  mount.innerHTML=`<div class="paste-box">
    <label>粘贴 Reviewer JSON</label>
    <textarea id="reviewJson" placeholder='{ "round": ..., "actor": "reviewer", "issues": {...}, "scores": {...}, "verdict": "...", "summary": "..." }'></textarea>
    <div class="actions-row">
      <button class="btn" onclick="saveReview()">保存并 Judge 判定</button>
      <button class="btn secondary" onclick="document.getElementById('paste-mount').innerHTML='';document.getElementById('paste-mount').dataset.open=''">取消</button>
    </div></div>`;
  setTimeout(()=>$('#reviewJson') && $('#reviewJson').focus(), 30);
}

async function saveReview(){
  const txt=$('#reviewJson') ? $('#reviewJson').value : '';
  try{
    const r=await api('/api/jobs/'+current+'/review',{method:'POST',body:JSON.stringify({reviewer_json:txt})});
    const dec=r && r.judge && r.judge.decision;
    toast('Judge: '+(dec||'?'));
    await selectJob(current);
  }catch(e){$('#detailError') && ($('#detailError').textContent=e.message); toast('保存失败：'+e.message)}
}

async function copyFinalDoc(){
  const j=currentData && currentData.status; if(!j) return;
  const name=j.has_final ? 'FINAL.md' : ('worktree/'+(j.target_name||''));
  await copyFile(name, '最终稿已复制到剪贴板');
}

async function exportFinal(){
  try{
    const r=await api('/api/jobs/'+current+'/export',{method:'POST',body:'{}'});
    toast('已另存副本：'+(r.dest||'').split('/').pop(), 3500);
  }catch(e){toast('导出失败：'+e.message)}
}

async function mergeJob(){
  if(!confirm('确认把 FINAL 覆盖回原文件？系统会在 job 目录留 ORIGINAL_BEFORE_MERGE 备份。')) return;
  try{await api('/api/jobs/'+current+'/merge',{method:'POST',body:'{}'}); toast('已合并'); await selectJob(current)}
  catch(e){toast('合并失败：'+e.message)}
}

async function abortJob(){
  if(!confirm('确认放弃此 job？只改 STATUS，文件留作审计。')) return;
  try{await api('/api/jobs/'+current+'/abort',{method:'POST',body:'{}'}); toast('已放弃'); await selectJob(current)}
  catch(e){toast('失败：'+e.message)}
}

// 键盘快捷键：c 新建焦点、esc 关粘贴框
window.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT' || e.target.tagName==='TEXTAREA') return;
  if(e.key==='c'){source && source.focus(); e.preventDefault()}
  if(e.key==='Escape'){const m=$('#paste-mount'); if(m && m.dataset.open==='1'){m.innerHTML='';m.dataset.open=''}}
});

loadHealth(); loadJobs();
setInterval(()=>{loadJobs(); if(current) selectJob(current).catch(()=>{})}, 5000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "Y1SparringCenter/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (now(), fmt % args))

    def send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: Any, status: int = 200) -> None:
        self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def read_body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length", "0") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def handle_error(self, exc: Exception) -> None:
        code = HTTPStatus.BAD_REQUEST
        if isinstance(exc, FileNotFoundError):
            code = HTTPStatus.NOT_FOUND
        self.send_json({"error": str(exc)}, int(code))

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path in {"/", "/sparring"}:
                self.send(200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/health":
                self.send_json(cli_health())
            elif path == "/api/jobs":
                self.send_json(list_jobs())
            elif path == "/api/browse":
                self.send_json(browse_dir(parse_qs(parsed.query).get("path", [None])[0]))
            elif path.startswith("/api/jobs/") and path.endswith("/file"):
                parts = path.split("/")
                job_id = parts[3]
                name = parse_qs(parsed.query).get("name", ["TASK.md"])[0]
                job_dir = job_dir_for(job_id)
                self.send_json({"content": read_known_file(job_dir, name)})
            elif path.startswith("/api/jobs/"):
                job_id = path.split("/")[3]
                job_dir = job_dir_for(job_id)
                self.send_json({
                    "status": job_summary(job_dir),
                    "job_dir": str(job_dir),
                    "preview": file_text(job_dir / "TASK.md"),
                    "rounds": collect_rounds(job_dir),
                    "issues": load_issues(job_dir),
                })
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.handle_error(exc)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in {"/", "/sparring"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            body = self.read_body()
            if path == "/api/preflight":
                self.send_json(preflight_check(
                    body.get("source_path", ""), body.get("goal", ""),
                    content=body.get("content", ""), title=body.get("title", ""),
                ))
                return
            if path == "/api/jobs":
                builder_model = body.get("builder_model") or DEFAULT_BUILDER_MODEL
                source_path = body.get("source_path", "")
                if (body.get("content") or "").strip():
                    source_path = str(materialize_pasted_content(body.get("title", ""), body["content"]))
                job = create_job(
                    source_path,
                    body.get("goal", ""),
                    body.get("max_rounds", 5),
                    body.get("threshold", 85),
                    bool(body.get("auto_run", False)),
                )
                update_status(job_dir_for(job["job_id"]), builder_model=builder_model)
                if body.get("auto_run"):
                    job = start_auto_run(job_dir_for(job["job_id"]), builder_model)
                self.send_json(job)
            elif path.startswith("/api/jobs/") and path.endswith("/after-builder"):
                job_id = path.split("/")[3]
                self.send_json(prepare_reviewer(job_dir_for(job_id)))
            elif path.startswith("/api/jobs/") and path.endswith("/auto-run"):
                job_id = path.split("/")[3]
                self.send_json(start_auto_run(job_dir_for(job_id), body.get("builder_model") or DEFAULT_BUILDER_MODEL))
            elif path.startswith("/api/jobs/") and path.endswith("/review"):
                job_id = path.split("/")[3]
                self.send_json(save_review_and_judge(job_dir_for(job_id), body.get("reviewer_json", "")))
            elif path.startswith("/api/jobs/") and path.endswith("/merge"):
                job_id = path.split("/")[3]
                self.send_json(merge_job(job_dir_for(job_id)))
            elif path.startswith("/api/jobs/") and path.endswith("/abort"):
                job_id = path.split("/")[3]
                reason = (body.get("reason") if isinstance(body, dict) else None) or "user_abort"
                self.send_json(abort_job(job_dir_for(job_id), reason))
            elif path.startswith("/api/jobs/") and path.endswith("/retry-reviewer"):
                job_id = path.split("/")[3]
                self.send_json(retry_reviewer(job_dir_for(job_id)))
            elif path.startswith("/api/jobs/") and path.endswith("/export"):
                job_id = path.split("/")[3]
                self.send_json(export_final(job_dir_for(job_id)))
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.handle_error(exc)


def main() -> None:
    global WORKSPACE_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument(
        "--workspace-root",
        default=None,
        help="Directory that the file browser and source-file allowlist are limited to. "
        "Defaults to SPARRING_WORKSPACE_ROOT or the parent of this app directory.",
    )
    args = ap.parse_args()
    if args.workspace_root:
        WORKSPACE_ROOT = Path(args.workspace_root).expanduser().resolve()
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    reset_stale_auto_runs()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Y1 Sparring Bus running at http://{args.host}:{args.port}/sparring", flush=True)
    print(f"Workspace root: {WORKSPACE_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
