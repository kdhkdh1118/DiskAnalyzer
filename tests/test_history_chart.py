import unittest

import pandas as pd

from history_chart import CHANGE_GRAPH_LIMIT, change_figure


COLUMNS = ["name", "before_size", "after_size", "change", "status"]


def comparison(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


class HistoryChartTests(unittest.TestCase):
    def test_increase_decrease_new_deleted_and_unchanged(self):
        diff = comparison([
            ("사진/여행", 500, 650, 150, "증가"),
            ("문서", 100, 20, -80, "감소"),
            ("새 폴더", 0, 120, 120, "새로 생김"),
            ("삭제된 폴더", 200, 0, -200, "사라짐"),
            ("그대로", 55, 55, 0, "변화 없음"),
        ])
        figure = change_figure(diff)
        bars = figure.data[0]
        self.assertEqual(list(bars.y), ["삭제된 폴더", "사진/여행", "새 폴더", "문서"])
        self.assertEqual(list(bars.x), [-200, 150, 120, -80])
        self.assertEqual(bars.orientation, "h")
        self.assertEqual(bars.marker.color[0], bars.marker.color[3])
        self.assertEqual(bars.marker.color[1], bars.marker.color[2])
        self.assertNotEqual(bars.marker.color[0], bars.marker.color[1])
        self.assertEqual(list(bars.customdata[0]), ["200 B", "0 B", "-200 B", "사라짐"])
        self.assertEqual(list(bars.customdata[1]), ["500 B", "650 B", "+150 B", "증가"])
        self.assertEqual(list(bars.customdata[2]), ["0 B", "120 B", "+120 B", "새로 생김"])
        self.assertIn("%{y}", bars.hovertemplate)
        self.assertIn("%{customdata[3]}", bars.hovertemplate)
        self.assertTrue(figure.layout.xaxis.zeroline)
        self.assertEqual(figure.layout.yaxis.autorange, "reversed")
        self.assertEqual(list(figure.layout.yaxis.categoryarray), list(bars.y))

    def test_empty_and_all_zero_have_no_bars(self):
        for diff in (
            comparison([]),
            comparison([("빈 폴더", 0, 0, 0, "새로 생김")]),
            comparison([("같은 폴더", 123, 123, 0, "변화 없음")]),
        ):
            with self.subTest(diff=diff):
                figure = change_figure(diff)
                self.assertEqual(len(figure.data[0].x), 0)
                self.assertEqual(len(figure.data[0].y), 0)
                self.assertEqual(figure.layout.xaxis.title.text, "증감 (B)")

    def test_top_twenty_and_ties_are_independent_of_input_order(self):
        rows = [
            (f"폴더_{index:02d}", 100, 100 + (-1 if index % 2 else 1) * (index % 6 + 1),
             (-1 if index % 2 else 1) * (index % 6 + 1), "감소" if index % 2 else "증가")
            for index in range(45)
        ]
        diff = comparison(rows)
        expected = sorted(rows, key=lambda row: (-abs(row[3]), row[0]))[:20]
        for seed in (0, 1, 27):
            with self.subTest(seed=seed):
                bars = change_figure(diff.sample(frac=1, random_state=seed)).data[0]
                self.assertEqual(len(bars.y), CHANGE_GRAPH_LIMIT)
                self.assertEqual(list(bars.y), [row[0] for row in expected])
                self.assertEqual(list(bars.x), [row[3] for row in expected])
                self.assertEqual(len(bars.customdata), CHANGE_GRAPH_LIMIT)

    def test_axis_unit_uses_largest_absolute_change(self):
        cases = [
            (1, "B", 1),
            (1023, "B", 1),
            (1024, "KB", 1024),
            (1024 ** 2 - 1, "KB", 1024),
            (1024 ** 2, "MB", 1024 ** 2),
            (1024 ** 3, "GB", 1024 ** 3),
            (1024 ** 4, "GB", 1024 ** 3),
        ]
        for size, unit, scale in cases:
            with self.subTest(size=size):
                diff = comparison([
                    ("큰 감소", size, 0, -size, "사라짐"),
                    ("작은 증가", 0, 1, 1, "새로 생김"),
                ])
                figure = change_figure(diff)
                self.assertEqual(figure.layout.xaxis.title.text, f"증감 ({unit})")
                values = dict(zip(figure.data[0].y, figure.data[0].x))
                self.assertEqual(values["큰 감소"], -size / scale)
                self.assertEqual(values["작은 증가"], 1 / scale)

    def test_original_data_is_preserved(self):
        diff = comparison([
            ("한글 경로/사진 '모음'_%", 12, 1024, 1012, "증가"),
            ("유지", 0, 0, 0, "변화 없음"),
            ("먼저", 1000, 0, -1000, "사라짐"),
        ])
        original = diff.copy(deep=True)
        figure = change_figure(diff)
        pd.testing.assert_frame_equal(diff, original)
        self.assertEqual(figure.data[0].y[0], "한글 경로/사진 '모음'_%")
        self.assertNotIn("magnitude", diff.columns)

    def test_numeric_and_date_folder_names_remain_categories(self):
        for names in (
            ["001", "1", "1000"],
            ["2024-03-01", "2024-01-01", "2024-02-01"],
        ):
            with self.subTest(names=names):
                diff = comparison([
                    (name, 0, size, size, "새로 생김")
                    for name, size in zip(names, [300, 100, 200])
                ])
                figure = change_figure(diff)
                expected = [names[0], names[2], names[1]]
                self.assertEqual(figure.layout.yaxis.type, "category")
                self.assertEqual(list(figure.data[0].y), expected)
                self.assertEqual(list(figure.layout.yaxis.categoryarray), expected)
                self.assertEqual(list(figure.data[0].x), [300, 200, 100])


if __name__ == "__main__":
    unittest.main()
