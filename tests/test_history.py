import shutil
import tempfile
import unittest
from pathlib import Path

from analyzer import files_frame
from history import DIRECT_FILES, compare_scans, list_scans, save_scan
from scanner import FileEntry, ScanResult, scan


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


@unittest.skipUnless(shutil.which("rclone"), "Rclone is not installed")
class RcloneHistoryTests(unittest.TestCase):
    def setUp(self):
        target = tempfile.TemporaryDirectory()
        self.addCleanup(target.cleanup)
        database = tempfile.TemporaryDirectory()
        self.addCleanup(database.cleanup)
        self.root = Path(target.name).resolve()
        self.db = Path(database.name).resolve() / "history.duckdb"

    def write(self, path, size):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * size)

    def save(self):
        result = scan(str(self.root))
        self.assertFalse(result.is_partial)
        self.assertNotIn(self.root, self.db.parents)
        self.assertFalse(any("duckdb" in entry.relative_path for entry in result.files))
        return save_scan(result, files_frame(result), self.db)

    def test_real_rescan_tracks_all_changes_and_scoped_totals(self):
        before_files = {
            "Grow/base.bin": 10,
            "Grow/nested/keep.bin": 20,
            "Shrink/keep.bin": 90,
            "Shrink/removed.bin": 10,
            "Gone/file.bin": 30,
            "Unchanged/deep/file.bin": 7,
            "root.bin": 5,
            "Grow2/unrelated.bin": 1000,
        }
        for path, size in before_files.items():
            self.write(path, size)
        before = self.save()

        (self.root / "Shrink/removed.bin").unlink()
        (self.root / "Gone/file.bin").unlink()
        self.write("Grow/nested/new.bin", 40)
        self.write("Shrink/keep.bin", 25)
        self.write("New/deep/new.bin", 60)
        self.write("root.bin", 15)
        self.write("Grow2/unrelated.bin", 1200)
        after = self.save()

        scans = list_scans(self.root, self.db)
        self.assertEqual(scans["scan_id"].tolist(), [after, before])
        self.assertEqual(scans["total_size"].tolist(), [1377, 1172])
        self.assertEqual(scans["file_count"].tolist(), [8, 8])
        self.assertEqual(scans["is_partial"].tolist(), [False, False])

        diff = compare_scans(before, after, db_path=self.db).set_index("name")
        expected = {
            "Grow": (30, 70, 40, "증가"),
            "Shrink": (100, 25, -75, "감소"),
            "Gone": (30, 0, -30, "사라짐"),
            "New": (0, 60, 60, "새로 생김"),
            "Unchanged": (7, 7, 0, "변화 없음"),
            DIRECT_FILES: (5, 15, 10, "증가"),
            "Grow2": (1000, 1200, 200, "증가"),
        }
        self.assertEqual(set(diff.index), set(expected))
        for name, values in expected.items():
            with self.subTest(name=name):
                self.assertEqual(
                    tuple(diff.loc[name, ["before_size", "after_size", "change", "status"]]),
                    values,
                )
        self.assertEqual(int(diff["before_size"].sum()), 1172)
        self.assertEqual(int(diff["after_size"].sum()), 1377)
        self.assertEqual(int(diff["change"].sum()), 205)

        scoped = compare_scans(before, after, "Grow", self.db).set_index("name")
        self.assertEqual(set(scoped.index), {DIRECT_FILES, "nested"})
        self.assertEqual(scoped.loc["nested", "before_size"], 20)
        self.assertEqual(scoped.loc["nested", "after_size"], 60)
        self.assertEqual(scoped.loc[DIRECT_FILES, "change"], 0)
        self.assertEqual(int(scoped["before_size"].sum()), 30)
        self.assertEqual(int(scoped["after_size"].sum()), 70)
        nested = compare_scans(before, after, "Grow/nested", self.db)
        self.assertEqual(nested["name"].tolist(), [DIRECT_FILES])
        self.assertEqual(nested["change"].tolist(), [40])
        self.assertTrue(compare_scans(before, after, "missing", self.db).empty)

    def test_real_empty_history_and_zero_byte_addition_and_removal(self):
        self.assertTrue(list_scans(self.root, self.db).empty)
        before = self.save()
        self.write("New/empty.txt", 0)
        added = self.save()
        (self.root / "New/empty.txt").unlink()
        removed = self.save()

        scans = list_scans(self.root, self.db)
        self.assertEqual(scans["scan_id"].tolist(), [removed, added, before])
        self.assertEqual(scans["total_size"].tolist(), [0, 0, 0])
        self.assertEqual(scans["file_count"].tolist(), [0, 1, 0])
        new = compare_scans(before, added, db_path=self.db)
        self.assertEqual(new["name"].tolist(), ["New"])
        self.assertEqual(new["status"].tolist(), ["새로 생김"])
        self.assertEqual(new["change"].tolist(), [0])
        gone = compare_scans(added, removed, db_path=self.db)
        self.assertEqual(gone["name"].tolist(), ["New"])
        self.assertEqual(gone["status"].tolist(), ["사라짐"])
        self.assertEqual(gone["change"].tolist(), [0])
        self.assertTrue(compare_scans(before, removed, db_path=self.db).empty)

    def test_real_folder_named_like_direct_files_stays_separate(self):
        self.write("root.txt", 3)
        self.write(f"{DIRECT_FILES}/inside.txt", 7)
        before = self.save()
        (self.root / "root.txt").unlink()
        self.write(f"{DIRECT_FILES}/inside.txt", 11)
        after = self.save()

        compared = compare_scans(before, after, db_path=self.db)
        self.assertEqual(
            compared.columns.tolist(),
            ["name", "before_size", "after_size", "change", "status"],
        )
        diff = compared.set_index("name")
        self.assertEqual(set(diff.index), {DIRECT_FILES, f"{DIRECT_FILES}/"})
        self.assertEqual(
            tuple(diff.loc[DIRECT_FILES]), (3, 0, -3, "사라짐")
        )
        self.assertEqual(
            tuple(diff.loc[f"{DIRECT_FILES}/"]), (7, 11, 4, "증가")
        )
        self.assertEqual(int(diff["before_size"].sum()), 10)
        self.assertEqual(int(diff["after_size"].sum()), 11)
        inside = compare_scans(before, after, DIRECT_FILES, self.db)
        self.assertEqual(inside["name"].tolist(), [DIRECT_FILES])
        self.assertEqual(inside["before_size"].tolist(), [7])
        self.assertEqual(inside["after_size"].tolist(), [11])


if __name__ == "__main__":
    unittest.main()
