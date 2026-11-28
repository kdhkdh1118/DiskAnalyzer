import unittest
from pathlib import Path

from analyzer import analyze, files_frame
from scanner import FileEntry, ScanResult
from treemap import treemap_figure, treemap_frame


def scanned_files(entries):
    return files_frame(
        ScanResult(
            Path("/example"),
            tuple(FileEntry(path, size, "") for path, size in entries),
            False,
        )
    )


class TreemapTests(unittest.TestCase):
    def test_limit_boundary_and_other_preserve_all_bytes(self):
        for count in (0, 1, 100, 101, 10_000):
            with self.subTest(count=count):
                files = scanned_files(
                    (f"file_{index:05d}.bin", index + 1)
                    for index in range(count)
                )
                chart = treemap_frame(files)
                total = count * (count + 1) // 2
                self.assertEqual(len(chart), min(count, 100) + (count > 100))
                self.assertEqual(int(chart["size"].sum()), total)
                self.assertEqual(int(chart["file_count"].sum()), count)
                self.assertEqual(analyze(files).total_size, total)
                self.assertEqual(analyze(files).file_count, count)
                if count > 100:
                    shown = chart.loc[~chart["is_other"]]
                    other = chart.loc[chart["is_other"]].iloc[0]
                    self.assertEqual(shown["size"].tolist(), list(range(count, count - 100, -1)))
                    self.assertEqual(other["file_count"], count - 100)
                    self.assertEqual(other["size"], (count - 100) * (count - 99) // 2)
                    figure = treemap_figure(chart, "example", count).data[0]
                    # 컨테이너인 root를 제외한 사각형은 최대 101개다.
                    self.assertEqual(len(figure.ids) - 1, 101)
                    self.assertEqual(figure.values[0], total)
                    self.assertEqual(sum(figure.values[1:]), total)

    def test_current_folder_includes_descendants_and_excludes_similar_prefixes(self):
        folder = "자료'_%"
        files = scanned_files(
            [
                (f"{folder}/file.txt", 4),
                (f"{folder}/nested/file.txt", 6),
                (f"{folder}2/wrong.txt", 100),
                ("elsewhere.txt", 200),
            ]
        )
        chart = treemap_frame(files, folder)
        self.assertEqual(chart["path"].tolist(), ["nested/file.txt", "file.txt"])
        self.assertEqual(int(chart["size"].sum()), 10)
        self.assertEqual(treemap_frame(files, "missing").shape[0], 0)

    def test_ties_have_stable_order_and_real_other_filename_has_unique_id(self):
        files = scanned_files([("z.txt", 10), ("기타", 20), ("a.txt", 10)])
        chart = treemap_frame(files, limit=2)
        self.assertEqual(chart["path"].tolist(), ["기타", "a.txt", "기타"])
        figure = treemap_figure(chart, "root", 3).data[0]
        self.assertEqual(len(set(figure.ids)), len(figure.ids))
        self.assertIn("file:기타", figure.ids)
        self.assertIn("other", figure.ids)

    def test_zero_byte_files_are_counted_but_have_no_chart_area(self):
        files = scanned_files([("empty.txt", 0), ("data.txt", 8)])
        chart = treemap_frame(files)
        self.assertEqual(chart["path"].tolist(), ["data.txt"])
        self.assertEqual(analyze(files).file_count, 2)
        self.assertEqual(analyze(files).total_size, 8)
        figure = treemap_figure(chart, "example", analyze(files).file_count).data[0]
        self.assertEqual(figure.customdata[0][1], 2)
        self.assertEqual(figure.customdata[1][1], 1)
        self.assertTrue(treemap_frame(scanned_files([("empty.txt", 0)])).empty)


if __name__ == "__main__":
    unittest.main()
