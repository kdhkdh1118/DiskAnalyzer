"""Draw folder size changes between two saved scans."""

import pandas as pd
import plotly.graph_objects as go

from analyzer import format_size

CHANGE_GRAPH_LIMIT = 20


def change_figure(diff: pd.DataFrame) -> go.Figure:
    changed = diff.loc[diff["change"] != 0].copy()
    changed["magnitude"] = changed["change"].abs()
    shown = changed.sort_values(
        ["magnitude", "name"], ascending=[False, True]
    ).head(CHANGE_GRAPH_LIMIT)

    largest = int(shown["magnitude"].max()) if not shown.empty else 0
    scale, unit = 1, "B"
    for next_unit in ("KB", "MB", "GB"):
        if largest < scale * 1024:
            break
        scale *= 1024
        unit = next_unit

    names = shown["name"].tolist()
    changes = [int(value) for value in shown["change"]]
    hover_data = [
        [
            format_size(row.before_size),
            format_size(row.after_size),
            ("+" if row.change > 0 else "-") + format_size(abs(row.change)),
            row.status,
        ]
        for row in shown.itertuples(index=False)
    ]
    figure = go.Figure(
        go.Bar(
            x=[change / scale for change in changes],
            y=names,
            orientation="h",
            marker_color=["#d62728" if change > 0 else "#1f77b4" for change in changes],
            customdata=hover_data,
            hovertemplate=(
                "<b>%{y}</b><br>이전: %{customdata[0]}"
                "<br>이후: %{customdata[1]}<br>증감: %{customdata[2]}"
                "<br>상태: %{customdata[3]}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        height=max(280, len(shown) * 28 + 100),
        margin=dict(l=0, r=20, t=20, b=40),
        showlegend=False,
        xaxis=dict(
            title=f"증감 ({unit})", rangemode="tozero",
            zeroline=True, zerolinecolor="#666666", zerolinewidth=1,
        ),
        yaxis=dict(
            type="category", autorange="reversed",
            categoryorder="array", categoryarray=names,
            automargin=True,
        ),
    )
    return figure
