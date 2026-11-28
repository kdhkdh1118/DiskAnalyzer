import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
from streamlit.testing.v1 import AppTest

from analyzer import files_frame
from history import save_scan
from scanner import FileEntry, ScanResult

APP = Path(__file__).resolve().parents[1] / "app.py"


class HistoryAppTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        database = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(database.cleanup)
        self.root = Path(folder.name)
        self.db = Path(database.name) / "history.duckdb"
        environment = patch.dict(os.environ, {"DISK_ANALYZER_DB": str(self.db)})
        environment.start()
        self.addCleanup(environment.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=20).run()

    def result(self, *entries, partial=False):
        return ScanResult(
            self.root,
            tuple(FileEntry(path, size, "") for path, size in entries),
            partial,
        )

    def save(self, result):
        return save_scan(result, files_frame(result), self.db)

    def submit(self, result):
        with patch("scanner.scan", return_value=result):
            self.app.text_input[0].set_value(str(self.root))
            self.app.button[0].click().run()
        self.assertFalse(self.app.exception)

    def metrics(self):
        return {metric.label: metric.value for metric in self.app.metric}

    def bars(self):
        traces = [
            json.loads(chart.proto.spec)["data"][0]
            for chart in self.app.get("plotly_chart")
        ]
        return [trace for trace in traces if trace["type"] == "bar"]

    def test_select_both_records_and_reset_invalid_before_choice(self):
        first = self.save(self.result(("A/a", 100), ("B/b", 20), ("root", 10)))
        second = self.save(self.result(("A/a", 150), ("B/b", 20), ("C/c", 30), ("root", 10)))
        third = self.save(self.result(("A/a", 120), ("C/c", 30), ("root", 5)))
        self.submit(self.result(("A/a", 200), ("C/c", 30), ("D/d", 40), ("root", 5)))
        latest = self.app.selectbox(key="history_after").value
        self.assertEqual(self.app.selectbox(key="history_before").value, third)
        self.assertEqual(self.metrics()["증감"], "+120 B")

        self.app.selectbox(key="history_before").select(first).run()
        self.assertEqual(self.metrics()["이전 크기"], "130 B")
        self.assertEqual(self.metrics()["이후 크기"], "275 B")
        self.app.selectbox(key="history_after").select(third).run()
        self.assertEqual(self.metrics()["이후 크기"], "155 B")
        self.assertEqual(self.metrics()["증감"], "+25 B")
        changes = dict(zip(self.bars()[0]["y"], self.bars()[0]["x"]))
        self.assertEqual(changes["A"], 20)
        self.assertEqual(changes["B"], -20)
        self.assertEqual(changes["C"], 30)

        self.app.selectbox(key="history_before").select(second).run()
        self.assertEqual(self.metrics()["증감"], "-55 B")
        self.app.selectbox(key="history_after").select(second).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.selectbox(key="history_before").value, first)
        self.assertEqual(self.metrics()["증감"], "+80 B")

        self.submit(self.result(("A/a", 300)))
        self.assertGreater(self.app.selectbox(key="history_after").value, latest)
        self.assertEqual(self.app.selectbox(key="history_before").value, latest)

    def test_other_folders_are_not_selectable_and_folder_navigation_keeps_selection(self):
        first = self.save(self.result(("A/a", 100), ("B/b", 20)))
        unrelated = ScanResult(self.root / "other", (FileEntry("elsewhere", 999, ""),), False)
        unrelated_id = self.save(unrelated)
        self.save(self.result(("A/a", 150)))
        self.submit(self.result(("A/a", 200), ("B/b", 40)))
        after_id = self.app.selectbox(key="history_after").value
        self.app.selectbox(key="history_before").select(first).run()
        self.assertFalse(any(f"#{unrelated_id} ·" in option for box in self.app.selectbox for option in box.options))
        self.app.session_state["current"] = "A"
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.selectbox(key="history_before").value, first)
        self.assertEqual(self.app.selectbox(key="history_after").value, after_id)
        self.assertEqual(self.metrics()["이전 크기"], "100 B")
        self.assertEqual(self.metrics()["이후 크기"], "200 B")

    def test_selected_partial_record_shows_warning(self):
        partial = self.save(self.result(("A/a", 10), partial=True))
        complete = self.save(self.result(("A/a", 20)))
        self.submit(self.result(("A/a", 30)))
        self.assertFalse(self.app.warning)
        self.app.selectbox(key="history_before").select(partial).run()
        self.assertTrue(any("선택한 기록에 일부 파일만" in item.value for item in self.app.warning))
        self.app.selectbox(key="history_before").select(complete).run()
        self.assertFalse(self.app.warning)

    def test_empty_records_show_zero_without_a_change_chart(self):
        self.save(self.result())
        self.submit(self.result())
        self.assertEqual(len(self.app.selectbox), 2)
        self.assertEqual(self.metrics()["증감"], "0 B")
        self.assertFalse(self.bars())
        self.assertTrue(any("비교할 항목이 없습니다" in item.value for item in self.app.caption))

    def test_failed_comparison_keeps_scan_results_visible(self):
        self.save(self.result(("A/a", 10)))
        with patch("history.compare_scans", side_effect=duckdb.IOException("read failed")):
            self.submit(self.result(("A/a", 20)))
        self.assertTrue(any("선택한 기록을 비교하지 못했습니다" in item.value for item in self.app.warning))
        self.assertEqual(self.metrics()["파일 수"], "1개")
        self.assertFalse(self.bars())

    def test_failed_save_still_allows_comparing_existing_records(self):
        self.save(self.result(("A/a", 10)))
        self.save(self.result(("A/a", 20)))
        with patch("history.save_scan", side_effect=duckdb.IOException("write failed")):
            self.submit(self.result(("A/a", 30), ("B/b", 10)))
        self.assertTrue(any("이번 분석 결과를 기록에 저장하지 못했습니다" in item.value for item in self.app.warning))
        self.assertEqual(self.metrics()["파일 수"], "2개")
        self.assertEqual(self.metrics()["이전 크기"], "10 B")
        self.assertEqual(self.metrics()["이후 크기"], "20 B")
        self.assertEqual(self.metrics()["증감"], "+10 B")
        self.app.session_state["current"] = "A"
        self.app.run()
        self.assertTrue(any("기록에 저장하지 못했습니다" in item.value for item in self.app.warning))
        self.submit(self.result(("A/a", 40)))
        self.assertFalse(any("기록에 저장하지 못했습니다" in item.value for item in self.app.warning))

    def test_missing_record_error_keeps_scan_results_visible(self):
        self.save(self.result(("A/a", 10)))
        with patch("history.compare_scans", side_effect=ValueError("선택한 스캔 기록을 찾을 수 없습니다.")):
            self.submit(self.result(("A/a", 20)))
        self.assertTrue(any("기록을 찾을 수 없습니다" in item.value for item in self.app.warning))
        self.assertEqual(self.metrics()["파일 수"], "1개")
        self.assertFalse(self.bars())


if __name__ == "__main__":
    unittest.main()
