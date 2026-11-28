import tempfile
import unittest
from pathlib import Path

from analyzer import files_frame
from history import DIRECT_FILES, compare_scans, list_scans, save_scan
from scanner import FileEntry, ScanResult


def make_result(root, *entries, partial=False):
    files = tuple(FileEntry(path, size, "") for path, size in entries)
    return ScanResult(Path(root), files, partial)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "history.duckdb"

    def save(self, result):
        return save_scan(result, files_frame(result), self.db)

    def test_scans_are_listed_newest_first_per_folder(self):
        first = self.save(make_result("/data/a", ("x.txt", 1)))
        self.save(make_result("/data/b", ("y.txt", 2)))
        second = self.save(make_result("/data/a", ("x.txt", 1), ("z.txt", 3)))

        scans = list_scans(Path("/data/a"), self.db)
        self.assertEqual(scans["scan_id"].tolist(), [second, first])
        self.assertEqual(scans["total_size"].tolist(), [4, 1])
        self.assertEqual(scans["file_count"].tolist(), [2, 1])

    def test_compare_reports_growth_new_and_removed_folders(self):
        before = self.save(
            make_result(
                "/data/a",
                ("Games/a.bin", 100),
                ("Old/b.bin", 50),
                ("Docs/c.txt", 10),
                ("root.txt", 5),
            )
        )
        after = self.save(
            make_result(
                "/data/a",
                ("Games/a.bin", 100),
                ("Games/sub/new.bin", 400),
                ("Docs/c.txt", 10),
                ("Video/v.mp4", 300),
                ("root.txt", 5),
            )
        )

        diff = compare_scans(before, after, db_path=self.db).set_index("name")
        self.assertEqual(diff.loc["Games", "change"], 400)
        self.assertEqual(diff.loc["Games", "status"], "증가")
        self.assertEqual(diff.loc["Video", "status"], "새로 생김")
        self.assertEqual(diff.loc["Video", "before_size"], 0)
        self.assertEqual(diff.loc["Old", "status"], "사라짐")
        self.assertEqual(diff.loc["Old", "change"], -50)
        self.assertEqual(diff.loc["Docs", "status"], "변화 없음")
        self.assertEqual(diff.loc[DIRECT_FILES, "after_size"], 5)
        self.assertEqual(diff["before_size"].sum(), 165)
        self.assertEqual(diff["after_size"].sum(), 815)
        self.assertEqual(diff.index[0], "Games")

    def test_compare_inside_subfolder_excludes_similar_prefixes(self):
        before = self.save(
            make_result("/data/a", ("Games/Steam/a", 10), ("Games2/b", 7))
        )
        after = self.save(
            make_result("/data/a", ("Games/Steam/a", 30), ("Games2/b", 9))
        )

        diff = compare_scans(before, after, "Games", self.db)
        self.assertEqual(diff["name"].tolist(), ["Steam"])
        self.assertEqual(diff["change"].tolist(), [20])

    def test_empty_scans_compare_to_empty_table(self):
        before = self.save(make_result("/data/empty"))
        after = self.save(make_result("/data/empty"))
        self.assertTrue(compare_scans(before, after, db_path=self.db).empty)


if __name__ == "__main__":
    unittest.main()
