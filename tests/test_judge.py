"""确定性 Judge 的判定逻辑：stop / continue / escalate 与各阻断条件。"""
from __future__ import annotations

import json

from _helpers import SparringTestCase, sc


class TestJudgeDecisions(SparringTestCase):
    def drive_one_round(self, job_dir, payload):
        self.write_builder_round(job_dir)
        sc.prepare_reviewer(job_dir)
        return sc.save_review_and_judge(job_dir, payload)

    def test_stop_when_score_and_issues_clear(self):
        job_dir = self.create_job()
        result = self.drive_one_round(job_dir, self.review_payload(1, score=92, verdict="accept"))
        self.assertEqual(result["judge"]["decision"], "stop")
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["state"], "READY_FOR_HUMAN_MERGE")
        self.assertEqual(status["scores_trend"], [92])
        for name in ["FINAL.md", "FINAL.diff", "FINAL_REVIEW.md"]:
            self.assertTrue((job_dir / name).exists(), name)
        judge = sc.read_json(job_dir / "rounds" / "r001.judge.json", {})
        self.assertEqual(judge["decision"], "stop")

    def test_continue_when_below_threshold(self):
        job_dir = self.create_job()
        result = self.drive_one_round(
            job_dir, self.review_payload(1, score=70, verdict="needs_revision")
        )
        self.assertEqual(result["judge"]["decision"], "continue")
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["state"], "WAIT_BUILDER")
        self.assertEqual(status["round"], 2)
        # 下一轮的"开始前基线"和 Builder prompt 都应已就位
        self.assertTrue((job_dir / "rounds" / "r002.before_builder.draft.md").exists())
        self.assertTrue((job_dir / "rounds" / "r002.builder.prompt.md").exists())

    def test_escalate_at_max_rounds(self):
        job_dir = self.create_job(max_rounds=1)
        result = self.drive_one_round(
            job_dir, self.review_payload(1, score=70, verdict="needs_revision")
        )
        self.assertEqual(result["judge"]["decision"], "escalate")
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["state"], "ESCALATED")
        self.assertTrue((job_dir / "FINAL_REVIEW.md").exists())

    def test_p1_blocks_stop(self):
        job_dir = self.create_job()
        result = self.drive_one_round(
            job_dir, self.review_payload(1, score=95, p1=["有一处必须修"], verdict="accept")
        )
        self.assertEqual(result["judge"]["decision"], "continue")

    def test_p0_blocks_stop(self):
        job_dir = self.create_job()
        result = self.drive_one_round(
            job_dir, self.review_payload(1, score=95, p0=["阻断问题"], verdict="accept")
        )
        self.assertEqual(result["judge"]["decision"], "continue")

    def test_runner_failure_blocks_stop(self):
        job_dir = self.create_job()
        # 没有 H1 的 Markdown 会触发 Runner 的 structure_h1 FAIL
        self.write_builder_round(job_dir, text="没有标题，只有一段普通文字。\n")
        sc.prepare_reviewer(job_dir)
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertGreaterEqual(int(status.get("runner_failures", 0)), 1)
        result = sc.save_review_and_judge(job_dir, self.review_payload(1, score=95, verdict="accept"))
        self.assertEqual(result["judge"]["decision"], "continue")

    def test_reject_verdict_blocks_stop(self):
        job_dir = self.create_job()
        result = self.drive_one_round(
            job_dir, self.review_payload(1, score=95, verdict="reject")
        )
        self.assertEqual(result["judge"]["decision"], "continue")

    def test_save_review_requires_wait_reviewer_state(self):
        job_dir = self.create_job()
        with self.assertRaises(ValueError):
            sc.save_review_and_judge(job_dir, self.review_payload(1))

    def test_bad_reviewer_json_rejected(self):
        job_dir = self.create_job()
        self.write_builder_round(job_dir)
        sc.prepare_reviewer(job_dir)
        with self.assertRaises(ValueError):
            sc.save_review_and_judge(job_dir, "not json at all")
        with self.assertRaises(ValueError):
            sc.save_review_and_judge(job_dir, json.dumps(["not", "an", "object"]))

    def test_prepare_reviewer_requires_builder_json(self):
        job_dir = self.create_job()
        with self.assertRaises(ValueError):
            sc.prepare_reviewer(job_dir)


if __name__ == "__main__":
    import unittest

    unittest.main()
