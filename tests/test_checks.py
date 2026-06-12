"""Runner 本地检查与模型输出 JSON 解析。"""
from __future__ import annotations

import unittest

from _helpers import GOOD_DOC, SparringTestCase, sc


class TestRunChecks(SparringTestCase):
    def test_clean_markdown_passes(self):
        work = self.workspace / "ok.md"
        work.write_text(GOOD_DOC, encoding="utf-8")
        log, failures = sc.run_checks(work)
        self.assertEqual(failures, 0)
        self.assertIn("PASS structure", log)

    def test_markdown_without_h1_fails(self):
        work = self.workspace / "nohead.md"
        work.write_text("只有正文，没有标题。\n", encoding="utf-8")
        log, failures = sc.run_checks(work)
        self.assertGreaterEqual(failures, 1)
        self.assertIn("FAIL structure_h1", log)

    def test_cya_language_fails(self):
        work = self.workspace / "cya.md"
        work.write_text("# 标题\n\n由于客观原因，这部分暂时无法提供。\n", encoding="utf-8")
        log, failures = sc.run_checks(work)
        self.assertGreaterEqual(failures, 1)
        self.assertIn("FAIL cya_check", log)

    def test_python_compile_check(self):
        good = self.workspace / "good.py"
        good.write_text("def main():\n    return 1\n", encoding="utf-8")
        _log, failures = sc.run_checks(good)
        self.assertEqual(failures, 0)
        bad = self.workspace / "bad.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        log, failures = sc.run_checks(bad)
        self.assertEqual(failures, 1)
        self.assertIn("FAIL py_compile", log)

    def test_unsupported_type_skipped(self):
        work = self.workspace / "data.csv"
        work.write_text("a,b\n1,2\n", encoding="utf-8")
        log, failures = sc.run_checks(work)
        self.assertEqual(failures, 0)
        self.assertIn("SKIP unsupported_type", log)


class TestExtractJsonObject(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(sc.extract_json_object('{"a": 1}'), {"a": 1})

    def test_object_wrapped_in_prose(self):
        text = '前面是闲聊。\n```json\n{"verdict": "accept", "note": "含 } 的字符串"}\n```\n后面还有话。'
        self.assertEqual(
            sc.extract_json_object(text),
            {"verdict": "accept", "note": "含 } 的字符串"},
        )

    def test_first_valid_object_wins(self):
        text = '{"first": true} 然后 {"second": true}'
        self.assertEqual(sc.extract_json_object(text), {"first": True})

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            sc.extract_json_object("完全不是 JSON")
        with self.assertRaises(ValueError):
            sc.extract_json_object("")


if __name__ == "__main__":
    unittest.main()
