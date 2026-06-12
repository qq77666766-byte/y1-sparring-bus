"""引擎适配器与编排层：注册表、引擎解析、鉴权回退，以及假引擎端到端闭环。"""
from __future__ import annotations

from _helpers import EnginePatch, FakeClaude, FakeCodex, SparringTestCase, sc


class TestEngineRegistry(SparringTestCase):
    def test_default_registry_has_claude_and_codex(self):
        self.assertIsInstance(sc.ENGINES.get("claude"), sc.ClaudeAdapter)
        self.assertIsInstance(sc.ENGINES.get("codex"), sc.CodexAdapter)
        self.assertTrue(sc.ENGINES["claude"].can_build)
        self.assertFalse(sc.ENGINES["claude"].can_review)
        self.assertTrue(sc.ENGINES["codex"].can_review)

    def test_engine_resolution_from_status(self):
        with EnginePatch({"claude": FakeClaude(), "codex": FakeCodex()}):
            status = {"builder_engine": "claude", "reviewer_engine": "codex"}
            self.assertEqual(sc.builder_engine_for(status).id, "claude")
            self.assertEqual(sc.reviewer_engine_for(status).id, "codex")
            # 缺字段时回落到 config 默认
            self.assertEqual(sc.builder_engine_for({}).id, "claude")

    def test_unavailable_engine_rejected(self):
        with EnginePatch({"claude": FakeClaude()}):
            with self.assertRaises(ValueError):
                sc.reviewer_engine_for({"reviewer_engine": "codex"})
        with EnginePatch({"codex": FakeCodex()}):
            # claude 不在注册表里时 Builder 解析失败
            with self.assertRaises(ValueError):
                sc.builder_engine_for({"builder_engine": "claude"})

    def test_cli_health_reports_engines(self):
        with EnginePatch({"claude": FakeClaude(), "codex": FakeCodex()}):
            health = sc.cli_health()
            self.assertTrue(health["auto_mode_available"])
            self.assertEqual(health["claude_cli"], "/bin/true")
            ids = {e["id"] for e in health["engines"]}
            self.assertEqual(ids, {"claude", "codex"})


class TestAuthFallback(SparringTestCase):
    def test_claude_auth_failure_falls_back_to_codex(self):
        claude = FakeClaude(fail_auth=True)
        codex = FakeCodex()
        with EnginePatch({"claude": claude, "codex": codex}):
            job_dir = self.create_job()
            sc.run_builder_cli(job_dir)
        self.assertEqual(claude.build_calls, 1)
        self.assertEqual(codex.build_calls, 1)
        self.assertTrue((job_dir / "rounds" / "r001.builder.json").exists())
        events = self.ledger_events(job_dir)
        self.assertIn("auto_builder_claude_auth_failed_fallback_codex", events)

    def test_auth_failure_without_fallback_raises(self):
        claude = FakeClaude(fail_auth=True)
        with EnginePatch({"claude": claude}):
            job_dir = self.create_job()
            with self.assertRaises(sc.EngineAuthError):
                sc.run_builder_cli(job_dir)


class TestFakeEngineEndToEnd(SparringTestCase):
    def test_two_round_loop_reaches_human_merge_gate(self):
        reviews = [
            {  # 第一轮：不及格 → continue
                "issues": {"p0": [], "p1": ["结论还不够前置"], "p2": []},
                "scores": {"requirement_fit": 70, "correctness": 80, "clarity": 75, "risk": 30},
                "verdict": "needs_revision",
                "summary": "还差一轮",
            },
            {  # 第二轮：达标 → stop
                "issues": {"p0": [], "p1": [], "p2": ["小建议"]},
                "scores": {"requirement_fit": 92, "correctness": 90, "clarity": 91, "risk": 8},
                "verdict": "accept",
                "summary": "可以合并",
            },
        ]
        claude = FakeClaude()
        codex = FakeCodex(reviews=reviews)
        with EnginePatch({"claude": claude, "codex": codex}):
            job_dir = self.create_job(max_rounds=3)
            sc.auto_run_job(job_dir)

        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["state"], "READY_FOR_HUMAN_MERGE")
        self.assertEqual(status["scores_trend"], [70, 92])
        self.assertFalse(status["auto_running"])
        self.assertEqual(claude.build_calls, 2)
        self.assertEqual(codex.review_calls, 2)
        # 全套留痕：每轮 prompt/patch/runner/reviewer/judge + 终稿三件套
        rounds = job_dir / "rounds"
        for r in (1, 2):
            for suffix in ["builder.prompt.md", "builder.json", "builder.patch",
                           "runner.log", "reviewer.json", "judge.json"]:
                self.assertTrue((rounds / f"r{r:03d}.{suffix}").exists(), f"r{r:03d}.{suffix}")
        for name in ["FINAL.md", "FINAL.diff", "FINAL_REVIEW.md"]:
            self.assertTrue((job_dir / name).exists(), name)
        events = self.ledger_events(job_dir)
        self.assertIn("auto_run_started", events)
        self.assertIn("auto_run_finished", events)
        # 原文件在合并前必须保持原样
        self.assertEqual(self.sample.read_text(encoding="utf-8").startswith("# 方案标题"), True)

        # 人工合并后，原文件才被更新
        worktree_text = (job_dir / "worktree" / "draft.md").read_text(encoding="utf-8")
        sc.merge_job(job_dir)
        self.assertEqual(self.sample.read_text(encoding="utf-8"), worktree_text)

    def test_escalation_after_max_rounds(self):
        low = {
            "issues": {"p0": [], "p1": ["仍不达标"], "p2": []},
            "scores": {"requirement_fit": 60, "correctness": 70, "clarity": 65, "risk": 40},
            "verdict": "needs_revision",
            "summary": "不行",
        }
        with EnginePatch({"claude": FakeClaude(), "codex": FakeCodex(reviews=[dict(low), dict(low)])}):
            job_dir = self.create_job(max_rounds=2)
            sc.auto_run_job(job_dir)
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["state"], "ESCALATED")
        self.assertEqual(status["scores_trend"], [60, 60])

    def test_builder_error_recorded_and_loop_stops(self):
        class BrokenBuilder(FakeClaude):
            def build(self, job_dir, r, prompt, before, model=None):
                raise sc.EngineError("builder exploded")

        with EnginePatch({"claude": BrokenBuilder(), "codex": FakeCodex()}):
            job_dir = self.create_job()
            sc.auto_run_job(job_dir)
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["auto_phase"], "error")
        self.assertIn("builder exploded", status["auto_error"])
        self.assertTrue((job_dir / "AUTO_ERROR.log").exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
