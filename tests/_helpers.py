"""Shared test scaffolding: temp workspace/jobs roots and fake engines.

测试公共脚手架：临时工作区 / jobs 根目录，以及不开子进程的假引擎。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import sparring_center as sc  # noqa: E402


GOOD_DOC = "# 方案标题\n\n结论先行：建议立项。\n\n理由是团队已经完成验证。\n"


class SparringTestCase(unittest.TestCase):
    """Creates an isolated workspace + jobs root and restores globals after."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sparring-test-"))
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()
        self.jobs = self.tmp / "jobs"
        self.jobs.mkdir()
        self._saved_roots = (sc.WORKSPACE_ROOT, sc.JOBS_ROOT)
        sc.WORKSPACE_ROOT = self.workspace
        sc.JOBS_ROOT = self.jobs
        self.sample = self.workspace / "draft.md"
        self.sample.write_text(GOOD_DOC, encoding="utf-8")

    def tearDown(self) -> None:
        sc.WORKSPACE_ROOT, sc.JOBS_ROOT = self._saved_roots
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create_job(self, **kwargs) -> Path:
        params = dict(
            source_path=str(self.sample),
            goal="把结论说得更清楚，删掉空话。",
            max_rounds=3,
            threshold=85,
        )
        params.update(kwargs)
        job = sc.create_job(**params)
        return sc.JOBS_ROOT / job["job_id"]

    def write_builder_round(self, job_dir: Path, text: str | None = None) -> int:
        """模拟 Builder：改 worktree 并写本轮 builder.json。"""
        status = sc.read_json(job_dir / "STATUS.json", {})
        r = int(status.get("round", 1))
        work = job_dir / "worktree" / sc.target_name(status)
        work.write_text(
            text if text is not None else (GOOD_DOC + f"\n第 {r} 轮补充：证据已经核对。\n"),
            encoding="utf-8",
        )
        (job_dir / "rounds" / f"r{r:03d}.builder.json").write_text(
            json.dumps(
                {
                    "round": r,
                    "actor": "builder",
                    "changes_summary": "测试轮",
                    "changes": [],
                    "addressed_issues": [],
                    "remaining_concerns": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return r

    def review_payload(self, r: int, score: int = 92, p0=None, p1=None, verdict: str = "accept") -> str:
        return json.dumps(
            {
                "round": r,
                "actor": "reviewer",
                "issues": {"p0": p0 or [], "p1": p1 or [], "p2": []},
                "scores": {
                    "requirement_fit": score,
                    "correctness": score,
                    "clarity": score,
                    "risk": max(0, 100 - score),
                },
                "verdict": verdict,
                "summary": "测试评审",
            },
            ensure_ascii=False,
        )

    def ledger_events(self, job_dir: Path) -> list[str]:
        return [row.get("event", "") for row in sc._ledger_iter(job_dir)]


class FakeClaude(sc.EngineAdapter):
    """假 Claude Builder：进程内直接改 worktree，不开子进程。"""

    id = "claude"
    display_name = "Fake Claude"
    can_build = True
    can_review = False

    def __init__(self, fail_auth: bool = False) -> None:
        super().__init__({})
        self.fail_auth = fail_auth
        self.build_calls = 0

    def detect(self) -> str | None:
        return "/bin/true"

    def build(self, job_dir, r, prompt, before, model=None) -> None:
        self.build_calls += 1
        if self.fail_auth:
            raise sc.EngineAuthError("fake auth failure")
        _status, _snap, work_file, rounds = sc.current_paths(job_dir)
        sc.append_ledger(job_dir, "auto_builder_start", round=r, model=model or "fake")
        text = work_file.read_text(encoding="utf-8")
        work_file.write_text(text + f"\n第 {r} 轮（fake builder）：结论更聚焦。\n", encoding="utf-8")
        (rounds / f"r{r:03d}.builder.json").write_text(
            json.dumps(
                {
                    "round": r,
                    "actor": "builder",
                    "changes_summary": f"fake round {r}",
                    "changes": [],
                    "addressed_issues": [],
                    "remaining_concerns": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        sc.finish_builder_round(job_dir, r, work_file, before, "fake stdout", "Fake")


class FakeCodex(sc.EngineAdapter):
    """假 Codex：可当回退 Builder，也可按脚本逐轮出 Reviewer 评分。"""

    id = "codex"
    display_name = "Fake Codex"
    can_build = True
    can_review = True

    def __init__(self, reviews=None) -> None:
        super().__init__({})
        self.reviews = list(reviews or [])
        self.build_calls = 0
        self.review_calls = 0

    def detect(self) -> str | None:
        return "/bin/true"

    def build(self, job_dir, r, prompt, before, model=None) -> None:
        self.build_calls += 1
        _status, _snap, work_file, rounds = sc.current_paths(job_dir)
        sc.append_ledger(job_dir, "auto_builder_codex_fallback_start", round=r)
        text = work_file.read_text(encoding="utf-8")
        work_file.write_text(text + f"\n第 {r} 轮（fake codex builder）。\n", encoding="utf-8")
        (rounds / f"r{r:03d}.builder.json").write_text(
            json.dumps(
                {
                    "round": r,
                    "actor": "builder",
                    "changes_summary": f"codex fallback round {r}",
                    "changes": [],
                    "addressed_issues": [],
                    "remaining_concerns": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        sc.finish_builder_round(job_dir, r, work_file, before, "fake stdout", "Codex")

    def review(self, job_dir, r, prompt) -> dict:
        self.review_calls += 1
        sc.append_ledger(job_dir, "auto_reviewer_start", round=r)
        review = dict(self.reviews.pop(0)) if self.reviews else {}
        review.setdefault("round", r)
        review.setdefault("actor", "reviewer")
        review.setdefault("issues", {"p0": [], "p1": [], "p2": []})
        review.setdefault("scores", {"requirement_fit": 90, "correctness": 90, "clarity": 90, "risk": 10})
        review.setdefault("verdict", "accept")
        review.setdefault("summary", "fake review")
        return review


class EnginePatch:
    """临时替换全局引擎注册表，退出时恢复。"""

    def __init__(self, engines: dict) -> None:
        self.engines = engines

    def __enter__(self) -> "EnginePatch":
        self._saved = dict(sc.ENGINES)
        sc.ENGINES.clear()
        sc.ENGINES.update(self.engines)
        return self

    def __exit__(self, *exc) -> bool:
        sc.ENGINES.clear()
        sc.ENGINES.update(self._saved)
        return False
