"""路径白名单、原文件防误写、合并冲突保护等安全守卫。"""
from __future__ import annotations

from _helpers import SparringTestCase, sc


class TestWorkspaceGuards(SparringTestCase):
    def test_accepts_relative_path_inside_workspace(self):
        self.assertEqual(sc.safe_workspace_file("draft.md"), self.sample.resolve())

    def test_rejects_file_outside_workspace(self):
        outside = self.tmp / "outside.md"
        outside.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            sc.safe_workspace_file(str(outside))

    def test_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            sc.safe_workspace_file(str(self.workspace / "nope.md"))

    def test_validate_text_source_rejects_empty_and_binary(self):
        empty = self.workspace / "empty.md"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            sc.validate_text_source(empty)
        binary = self.workspace / "blob.md"
        binary.write_bytes(b"\xff\xfe\x00\x01")
        with self.assertRaises(ValueError):
            sc.validate_text_source(binary)

    def test_job_dir_for_rejects_traversal_ids(self):
        with self.assertRaises(ValueError):
            sc.job_dir_for("../evil")
        with self.assertRaises(FileNotFoundError):
            sc.job_dir_for("20990101-000000-000000-sparring-nope")


class TestJobArtifactGuards(SparringTestCase):
    def test_read_known_file_stays_inside_job_dir(self):
        job_dir = self.create_job()
        self.assertIn("# TASK", sc.read_known_file(job_dir, "TASK.md"))
        with self.assertRaises(ValueError):
            sc.read_known_file(job_dir, "../../../etc/hosts")

    def test_source_write_violation_restored(self):
        job_dir = self.create_job()
        before = self.sample.read_bytes()
        self.sample.write_text("被 Builder 误写的内容", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            sc.assert_source_unchanged_or_restore(job_dir, before, "Claude Builder")
        self.assertEqual(self.sample.read_bytes(), before)
        violations = list(job_dir.glob("ORIGINAL_WRITE_VIOLATION.*"))
        self.assertEqual(len(violations), 1)
        self.assertIn("source_write_violation_restored", self.ledger_events(job_dir))


class TestMergeGuards(SparringTestCase):
    def drive_to_ready(self, job_dir):
        self.write_builder_round(job_dir)
        sc.prepare_reviewer(job_dir)
        sc.save_review_and_judge(job_dir, self.review_payload(1, score=92, verdict="accept"))

    def test_merge_requires_terminal_state(self):
        job_dir = self.create_job()
        with self.assertRaises(ValueError):
            sc.merge_job(job_dir)

    def test_merge_writes_backup_and_source(self):
        job_dir = self.create_job()
        self.drive_to_ready(job_dir)
        worktree_text = (job_dir / "worktree" / "draft.md").read_text(encoding="utf-8")
        result = sc.merge_job(job_dir)
        self.assertEqual(result["state"], "MERGED")
        self.assertEqual(self.sample.read_text(encoding="utf-8"), worktree_text)
        self.assertTrue((job_dir / "ORIGINAL_BEFORE_MERGE.draft.md").exists())
        # 已合并的任务不能再次合并
        with self.assertRaises(ValueError):
            sc.merge_job(job_dir)

    def test_merge_blocked_when_source_changed_after_snapshot(self):
        job_dir = self.create_job()
        self.drive_to_ready(job_dir)
        self.sample.write_text("# 用户合并前自己改过\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            sc.merge_job(job_dir)
        # 用户的修改不能被覆盖，且要留一份当前原文件副本
        self.assertEqual(self.sample.read_text(encoding="utf-8"), "# 用户合并前自己改过\n")
        self.assertTrue((job_dir / "MERGE_BLOCKED_CURRENT_SOURCE.draft.md").exists())
        self.assertIn("merge_blocked_source_changed", self.ledger_events(job_dir))

    def test_abort_is_terminal(self):
        job_dir = self.create_job()
        result = sc.abort_job(job_dir, "test")
        self.assertEqual(result["state"], "ABORTED")
        with self.assertRaises(ValueError):
            sc.abort_job(job_dir)


if __name__ == "__main__":
    import unittest

    unittest.main()
