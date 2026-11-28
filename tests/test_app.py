import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from scanner import FileEntry, ScanError, ScanResult

APP = Path(__file__).resolve().parents[1] / "app.py"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        db = tempfile.TemporaryDirectory()
        self.addCleanup(db.cleanup)
        test_db = str(Path(db.name) / "test.duckdb")
        patcher = patch.dict(os.environ, {"DISK_ANALYZER_DB": test_db})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=20).run()

    def submit(self):
        self.app.text_input[0].set_value(str(self.root))
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)

    @unittest.skipUnless(shutil.which("rclone"), "Rclone is not installed")
    def test_real_empty_folder_shows_zero_and_explanation(self):
        self.submit()
        metrics = {metric.label: metric.value for metric in self.app.metric}
        self.assertEqual(metrics["파일 수"], "0개")
        self.assertEqual(metrics["파일 크기 합계"], "0 B")
        self.assertTrue(any("분석할 파일이 없습니다" in item.value for item in self.app.info))
        self.assertFalse(self.app.error)
        self.assertFalse(self.app.warning)
        self.assertFalse(self.app.get("plotly_chart"))

    @unittest.skipUnless(shutil.which("rclone"), "Rclone is not installed")
    def test_real_zero_byte_file_is_counted_with_chart_explanation(self):
        (self.root / "empty.txt").touch()
        self.submit()
        metrics = {metric.label: metric.value for metric in self.app.metric}
        self.assertEqual(metrics["파일 수"], "1개")
        self.assertEqual(metrics["파일 크기 합계"], "0 B")
        self.assertTrue(any("모두 0 B" in item.value for item in self.app.info))
        self.assertFalse(self.app.get("plotly_chart"))

    @unittest.skipUnless(shutil.which("rclone"), "Rclone is not installed")
    def test_real_large_folder_renders_bounded_chart_with_full_metrics(self):
        for index in range(103):
            (self.root / f"file_{index:03d}.txt").write_bytes(b"x" * (index + 1))
        self.submit()
        metrics = {metric.label: metric.value for metric in self.app.metric}
        self.assertEqual(metrics["파일 수"], "103개")
        self.assertEqual(metrics["파일 크기 합계"], "5.2 KB")
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        trace = json.loads(self.app.get("plotly_chart")[0].proto.spec)["data"][0]
        self.assertEqual(len(trace["ids"]) - 1, 101)
        self.assertEqual(trace["values"][0], 5356)
        self.assertEqual(sum(trace["values"][1:]), 5356)
        self.assertIn("other", trace["ids"])

    def test_partial_scan_warns_that_totals_are_incomplete(self):
        result = ScanResult(self.root, (FileEntry("readable.txt", 4, ""),), True)
        with patch("scanner.scan", return_value=result):
            self.submit()
        self.assertEqual(len(self.app.warning), 1)
        self.assertIn("전체 용량보다 작게", self.app.warning[0].value)
        self.assertIn("읽기 권한", self.app.warning[0].value)
        self.assertEqual(len(self.app.get("plotly_chart")), 1)

    def test_failed_rescan_removes_previous_results_and_shows_guidance(self):
        result = ScanResult(self.root, (FileEntry("old.txt", 4, ""),), False)
        with patch("scanner.scan", return_value=result):
            self.submit()
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        with patch("scanner.scan", side_effect=ScanError("폴더의 읽기 권한을 확인해 주세요.")):
            self.submit()
        self.assertEqual(len(self.app.error), 1)
        self.assertIn("읽기 권한", self.app.error[0].value)
        self.assertFalse(self.app.metric)
        self.assertFalse(self.app.get("plotly_chart"))


if __name__ == "__main__":
    unittest.main()
