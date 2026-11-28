"""Build a bounded treemap while keeping the full folder size."""

import duckdb
import pandas as pd
import plotly.graph_objects as go

from analyzer import SCOPED, format_size

TREEMAP_FILE_LIMIT = 100

TREEMAP_SQL = SCOPED + """
, ranked AS (
    SELECT rest AS path, size,
        row_number() OVER (ORDER BY size DESC, rest) AS position
    FROM scoped
    WHERE size > 0
)
SELECT path, size::BIGINT AS size, 1::BIGINT AS file_count, false AS is_other
FROM ranked
WHERE position <= $limit
UNION ALL
SELECT '기타', sum(size)::BIGINT, count(*), true
FROM ranked
WHERE position > $limit
HAVING count(*) > 0
ORDER BY is_other, size DESC, path
"""


def treemap_frame(
    files: pd.DataFrame, folder: str = "", limit: int = TREEMAP_FILE_LIMIT
) -> pd.DataFrame:
    if limit < 1:
        raise ValueError("The treemap file limit must be positive.")
    prefix = f"{folder}/" if folder else ""
    with duckdb.connect() as con:
        con.register("all_files", files)
        return con.execute(
            TREEMAP_SQL,
            {"start": len(prefix) + 1, "prefix": prefix, "limit": limit},
        ).df()


def treemap_figure(
    frame: pd.DataFrame, root_label: str, total_file_count: int
) -> go.Figure:
    # 집계 항목과 실제 이름이 '기타'인 파일을 서로 다른 ID로 구분한다.
    ids = ["root"] + [
        "other" if row.is_other else f"file:{row.path}"
        for row in frame.itertuples(index=False)
    ]
    total_size = int(frame["size"].sum())
    details = [[format_size(total_size), total_file_count]] + [
        [format_size(row.size), int(row.file_count)]
        for row in frame.itertuples(index=False)
    ]
    figure = go.Figure(
        go.Treemap(
            ids=ids,
            labels=[root_label, *frame["path"].tolist()],
            parents=["", *(["root"] * len(frame))],
            values=[total_size, *frame["size"].tolist()],
            customdata=details,
            branchvalues="total",
            sort=False,
            textinfo="label+percent root",
            hovertemplate=(
                "<b>%{label}</b><br>크기: %{customdata[0]}"
                "<br>파일 수: %{customdata[1]:,}개<extra></extra>"
            ),
        )
    )
    figure.update_layout(height=500, margin=dict(t=30, l=0, r=0, b=0))
    return figure
