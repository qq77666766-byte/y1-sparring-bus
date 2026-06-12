"""config.json 加载/合并、引擎注册表初始化、STATUS schema 迁移。"""
from __future__ import annotations

import json

from _helpers import SparringTestCase, sc


class TestLoadConfig(SparringTestCase):
    def test_defaults_when_file_missing(self):
        config = sc.load_config(self.tmp / "missing.json")
        self.assertEqual(config, sc.DEFAULT_CONFIG)
        self.assertIsNot(config["engines"], sc.DEFAULT_CONFIG["engines"])  # 必须是深拷贝

    def test_user_overrides_deep_merge(self):
        path = self.tmp / "config.json"
        path.write_text(
            json.dumps({"default_reviewer": "claude", "engines": {"claude": {"timeout_sec": 60}}}),
            encoding="utf-8",
        )
        config = sc.load_config(path)
        self.assertEqual(config["default_reviewer"], "claude")
        self.assertEqual(config["default_builder"], "claude")
        self.assertEqual(config["engines"]["claude"]["timeout_sec"], 60)
        # 没覆盖的键保持默认
        self.assertEqual(config["engines"]["claude"]["default_model"], "sonnet")
        self.assertTrue(config["engines"]["codex"]["enabled"])

    def test_invalid_json_falls_back_to_defaults(self):
        path = self.tmp / "config.json"
        path.write_text("{broken", encoding="utf-8")
        self.assertEqual(sc.load_config(path), sc.DEFAULT_CONFIG)


class TestInitEngines(SparringTestCase):
    def test_disabled_engine_excluded(self):
        try:
            sc.init_engines({"engines": {"codex": {"enabled": False}}})
            self.assertIn("claude", sc.ENGINES)
            self.assertNotIn("codex", sc.ENGINES)
        finally:
            sc.init_engines(sc.CONFIG)

    def test_engine_options_passed_through(self):
        try:
            sc.init_engines({"engines": {"claude": {"timeout_sec": 120}}})
            self.assertEqual(sc.ENGINES["claude"].timeout(), 120)
        finally:
            sc.init_engines(sc.CONFIG)


class TestStatusMigration(SparringTestCase):
    def test_v1_status_gains_engine_fields(self):
        status = {"job_id": "x", "mode": "sparring", "state": "WAIT_BUILDER"}
        migrated, changed = sc.migrate_status_dict(status)
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], sc.STATUS_SCHEMA_VERSION)
        self.assertEqual(migrated["builder_engine"], "claude")
        self.assertEqual(migrated["reviewer_engine"], "codex")

    def test_migration_is_idempotent(self):
        status = {"job_id": "x", "mode": "sparring"}
        migrated, _ = sc.migrate_status_dict(status)
        _again, changed = sc.migrate_status_dict(migrated)
        self.assertFalse(changed)

    def test_existing_engine_values_preserved(self):
        status = {"job_id": "x", "mode": "sparring", "builder_engine": "codex"}
        migrated, _ = sc.migrate_status_dict(status)
        self.assertEqual(migrated["builder_engine"], "codex")

    def test_migrate_jobs_rewrites_old_job(self):
        old_job = self.jobs / "20250101-000000-000000-sparring-old"
        old_job.mkdir()
        sc.write_json(
            old_job / "STATUS.json",
            {"job_id": old_job.name, "mode": "sparring", "state": "MERGED"},
        )
        sc.migrate_jobs()
        status = sc.read_json(old_job / "STATUS.json", {})
        self.assertEqual(status["schema_version"], sc.STATUS_SCHEMA_VERSION)
        self.assertEqual(status["builder_engine"], "claude")
        events = self.ledger_events(old_job)
        self.assertIn("status_schema_migrated", events)
        # 再跑一次不应重复迁移
        sc.migrate_jobs()
        self.assertEqual(self.ledger_events(old_job).count("status_schema_migrated"), 1)

    def test_new_jobs_created_with_current_schema(self):
        job_dir = self.create_job()
        status = sc.read_json(job_dir / "STATUS.json", {})
        self.assertEqual(status["schema_version"], sc.STATUS_SCHEMA_VERSION)
        self.assertEqual(status["builder_engine"], "claude")
        self.assertEqual(status["reviewer_engine"], "codex")


if __name__ == "__main__":
    import unittest

    unittest.main()
