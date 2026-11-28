import shutil

import duckdb
import pandas as pd
import streamlit as st

from analyzer import analyze, files_frame, format_size
from history import compare_scans, list_scans, save_scan
from history_chart import CHANGE_GRAPH_LIMIT, change_figure
from scanner import ScanError, scan
from treemap import TREEMAP_FILE_LIMIT, treemap_figure, treemap_frame


def go_to(folder: str) -> None:
    # view 번호를 바꿔서 이전 폴더 표의 선택 상태가 새 화면에 남지 않게 한다
    st.session_state.current = folder
    st.session_state.view = st.session_state.get("view", 0) + 1


def ratio_column() -> st.column_config.ProgressColumn:
    return st.column_config.ProgressColumn(
        "비율", format="%.1f%%", min_value=0, max_value=100
    )


def signed_size(change: int) -> str:
    if change == 0:
        return "0 B"
    return f"{'+' if change > 0 else '-'}{format_size(abs(change))}"


st.set_page_config(page_title="Disk Analyzer", layout="wide")
st.title("Disk Analyzer")

with st.form("scan_folder"):
    folder = st.text_input("분석할 로컬 폴더", placeholder=r"C:\DiskAnalyzer-Test")
    submitted = st.form_submit_button("폴더 분석 시작", type="primary")

if submitted:
    st.session_state.pop("scan_result", None)
    st.session_state.pop("history_save_error", None)
    try:
        with st.spinner("파일 목록을 읽는 중…"):
            result = scan(folder)
        st.session_state.scan_result = result
        st.session_state.files = files_frame(result)
        go_to("")
        st.session_state.pop("history_before", None)
        st.session_state.pop("history_after", None)
        # 분석할 때마다 기록을 남겨 두어야 나중에 같은 폴더의 변화를 비교할 수 있다
        try:
            st.session_state.scan_id = save_scan(result, st.session_state.files)
        except (duckdb.Error, OSError) as exc:
            st.session_state.scan_id = None
            st.session_state.history_save_error = str(exc)
    except ScanError as exc:
        st.error(str(exc))

result = st.session_state.get("scan_result")
if result is not None:
    save_error = st.session_state.get("history_save_error")
    if save_error is not None:
        st.warning(f"이번 분석 결과를 기록에 저장하지 못했습니다. ({save_error})")
    if result.is_partial:
        st.warning(
            "일부 파일이나 폴더를 읽지 못했습니다. 읽을 수 있는 항목만 집계했습니다."
            " 전체 용량보다 작게 표시될 수 있습니다."
            " 폴더의 읽기 권한과 접근 권한, 파일 상태를 확인한 뒤 다시 분석해 주세요."
        )

    # 드라이브 전체 상황과 분석한 폴더의 파일 크기 합계를 나눠서 보여준다
    try:
        disk = shutil.disk_usage(result.root)
        st.subheader("디스크 사용 현황")
        total, used, free = st.columns(3)
        total.metric("디스크 전체", format_size(disk.total))
        used.metric("사용 중", format_size(disk.used))
        free.metric("남은 공간", format_size(disk.free))
    except OSError:
        st.caption("디스크 전체 용량을 확인하지 못했습니다.")

    st.subheader("분석한 폴더")
    count, size = st.columns(2)
    count.metric("파일 수", f"{len(result.files):,}개")
    size.metric("파일 크기 합계", format_size(result.total_bytes))

    current = st.session_state.get("current", "")
    view = analyze(st.session_state.files, current)
    shown = result.root.joinpath(*current.split("/")) if current else result.root

    st.divider()
    st.subheader(f"📁 {shown}")
    st.caption(f"{format_size(view.total_size)} · 파일 {view.file_count:,}개")
    if current:
        parent = current.rsplit("/", 1)[0] if "/" in current else ""
        st.button("⬆ 상위 폴더", on_click=go_to, args=(parent,))

    st.markdown("**파일 용량 트리맵** · 현재 폴더와 하위 폴더 전체 기준")
    if view.file_count == 0:
        st.info("분석할 파일이 없습니다. 파일이 있는 폴더인지 확인해 주세요.")
    elif view.total_size == 0:
        st.info("파일 크기가 모두 0 B여서 트리맵을 표시할 수 없습니다.")
    else:
        chart_files = treemap_frame(st.session_state.files, current)
        st.plotly_chart(
            treemap_figure(chart_files, shown.name or str(shown), view.file_count),
            key=f"treemap_{st.session_state.get('view', 0)}",
        )
        st.caption(
            f"용량이 큰 파일 최대 {TREEMAP_FILE_LIMIT}개를 표시하고,"
            " 나머지는 '기타'로 합칩니다. 전체 용량과 파일 수는 모든 파일 기준입니다."
            " 0 B 파일은 면적이 없어 트리맵에 표시하지 않습니다."
        )

    st.markdown("**하위 폴더** · 왼쪽 체크박스로 폴더를 선택하면 안으로 들어갑니다")
    if view.folders.empty:
        st.caption("분석된 파일이 있는 하위 폴더가 없습니다.")
    else:
        folders = pd.DataFrame(
            {
                "폴더": view.folders["name"],
                "크기": view.folders["size"].map(format_size),
                "비율": view.folders["size"] / max(view.total_size, 1) * 100,
                "파일 수": view.folders["file_count"],
            }
        )
        event = st.dataframe(
            folders,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"folders_{st.session_state.get('view', 0)}",
            column_config={"비율": ratio_column()},
        )
        # 클릭한 폴더로 이동하면 다시 스캔하지 않고 바로 하위 폴더 용량을 보여준다
        if event.selection.rows:
            name = view.folders["name"].iloc[event.selection.rows[0]]
            go_to(f"{current}/{name}" if current else name)
            st.rerun()

    st.markdown("**이 폴더에 직접 있는 파일** · 크기 순 최대 200개")
    if view.files.empty:
        st.caption("이 폴더에 직접 있는 파일이 없습니다.")
    else:
        st.dataframe(
            pd.DataFrame(
                {
                    "파일": view.files["name"],
                    "크기": view.files["size"].map(format_size),
                    "수정 시각": view.files["modified_at"]
                    .str.slice(0, 16)
                    .str.replace("T", " "),
                }
            ),
            hide_index=True,
        )

    st.markdown("**확장자별 크기** · 현재 폴더와 하위 폴더 전체 기준")
    if not view.extensions.empty:
        st.dataframe(
            pd.DataFrame(
                {
                    "확장자": view.extensions["extension"],
                    "크기": view.extensions["size"].map(format_size),
                    "비율": view.extensions["size"] / max(view.total_size, 1) * 100,
                    "파일 수": view.extensions["file_count"],
                }
            ),
            hide_index=True,
            column_config={"비율": ratio_column()},
        )

    st.divider()
    st.subheader("스캔 기록 비교")
    st.caption(
        "같은 폴더의 기록 두 개를 골라 현재 열어 둔 폴더 기준으로 비교합니다."
    )
    try:
        scans = list_scans(result.root)
    except (duckdb.Error, OSError) as exc:
        scans = None
        st.warning(f"스캔 기록을 불러오지 못했습니다. ({exc})")
    if scans is None:
        pass
    elif scans.empty:
        st.caption("저장된 스캔 기록이 없습니다.")
    elif len(scans) == 1:
        st.caption(
            "이 폴더의 첫 기록입니다."
            " 나중에 같은 폴더를 다시 분석하면 변화를 비교할 수 있습니다."
        )
    else:
        records = {int(row.scan_id): row for row in scans.itertuples(index=False)}
        scan_ids = sorted(records, reverse=True)

        def record_label(record_id: int) -> str:
            row = records[record_id]
            partial = " · 일부만 읽음" if row.is_partial else ""
            return (
                f"#{record_id} · {row.scanned_at:%Y-%m-%d %H:%M:%S}"
                f" · {format_size(row.total_size)} · {row.file_count:,}개{partial}"
            )

        before_column, after_column = st.columns(2)
        after_options = scan_ids[:-1]
        after_choice = st.session_state.get("history_after")
        st.session_state.history_after = (
            after_choice if after_choice in after_options else after_options[0]
        )
        after_id = after_column.selectbox(
            "이후 기록", after_options, format_func=record_label, key="history_after"
        )
        before_options = [record_id for record_id in scan_ids if record_id < after_id]
        before_choice = st.session_state.get("history_before")
        # Streamlit 1.40에서도 목록 변경 시 유효한 선택을 유지한다.
        st.session_state.history_before = (
            before_choice if before_choice in before_options else before_options[0]
        )
        before_id = before_column.selectbox(
            "이전 기록", before_options, format_func=record_label, key="history_before"
        )
        if records[before_id].is_partial or records[after_id].is_partial:
            st.warning(
                "선택한 기록에 일부 파일만 읽은 결과가 포함되어 있습니다."
                " 실제 용량 변화와 다를 수 있습니다."
            )
        st.caption("아래 값은 선택한 기록의 값으로, 위 분석 결과와 시점이 다를 수 있습니다.")
        try:
            diff = compare_scans(before_id, after_id, current)
        except (duckdb.Error, OSError, ValueError) as exc:
            st.warning(f"선택한 기록을 비교하지 못했습니다. ({exc})")
        else:
            before_total = int(diff["before_size"].sum())
            after_total = int(diff["after_size"].sum())
            was, is_after, change = st.columns(3)
            was.metric("이전 크기", format_size(before_total))
            is_after.metric("이후 크기", format_size(after_total))
            change.metric("증감", signed_size(after_total - before_total))
            if diff.empty:
                st.caption("비교할 항목이 없습니다.")
            else:
                st.dataframe(
                    pd.DataFrame(
                        {
                            "항목": diff["name"],
                            "이전": diff["before_size"].map(format_size),
                            "이후": diff["after_size"].map(format_size),
                            "증감": diff["change"].map(signed_size),
                            "상태": diff["status"],
                        }
                    ),
                    hide_index=True,
                )
                changed_count = int((diff["change"] != 0).sum())
                if changed_count:
                    st.markdown("**하위 폴더별 증감** · 증가(+) / 감소(-)")
                    st.plotly_chart(
                        change_figure(diff),
                        key=f"history_change_{before_id}_{after_id}_{st.session_state.get('view', 0)}",
                    )
                    if changed_count > CHANGE_GRAPH_LIMIT:
                        st.caption(
                            f"그래프는 증감이 큰 {CHANGE_GRAPH_LIMIT}개 항목만 표시합니다."
                            " 위 표와 전체 합계에는 모든 항목이 포함됩니다."
                        )
                else:
                    st.caption("용량 변화가 없어 증감 그래프를 표시하지 않습니다.")
