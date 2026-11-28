import shutil

import duckdb
import pandas as pd
import streamlit as st

from analyzer import analyze, files_frame, format_size
from history import compare_scans, list_scans, save_scan
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
    try:
        with st.spinner("파일 목록을 읽는 중…"):
            result = scan(folder)
        st.session_state.scan_result = result
        st.session_state.files = files_frame(result)
        go_to("")
        # 분석할 때마다 기록을 남겨 두어야 나중에 같은 폴더의 변화를 비교할 수 있다
        try:
            st.session_state.scan_id = save_scan(result, st.session_state.files)
        except (duckdb.Error, OSError) as exc:
            st.session_state.scan_id = None
            st.warning(
                "스캔 기록을 저장하지 못했습니다."
                f" 비교 기능 없이 결과만 표시합니다. ({exc})"
            )
    except ScanError as exc:
        st.error(str(exc))

result = st.session_state.get("scan_result")
if result is not None:
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
        "같은 폴더의 바로 이전 기록과 지금 기록을 현재 폴더 기준으로 비교합니다."
    )
    scan_id = st.session_state.get("scan_id")
    try:
        scans = list_scans(result.root) if scan_id else pd.DataFrame()
    except (duckdb.Error, OSError):
        scans = pd.DataFrame()
    earlier = scans[scans["scan_id"] < scan_id] if not scans.empty else scans
    if scans.empty:
        st.caption("저장된 스캔 기록이 없습니다.")
    elif earlier.empty:
        st.caption(
            "이 폴더의 첫 기록입니다."
            " 나중에 같은 폴더를 다시 분석하면 변화를 비교할 수 있습니다."
        )
    else:
        before = earlier.iloc[0]
        now = scans[scans["scan_id"] == scan_id].iloc[0]
        st.caption(
            f"이전 기록 {before['scanned_at']:%Y-%m-%d %H:%M}"
            f" → 현재 기록 {now['scanned_at']:%Y-%m-%d %H:%M}"
        )
        diff = compare_scans(int(before["scan_id"]), scan_id, current)
        before_total, after_total = diff["before_size"].sum(), diff["after_size"].sum()
        was, is_now, change = st.columns(3)
        was.metric("이전 크기", format_size(before_total))
        is_now.metric("현재 크기", format_size(after_total))
        change.metric("증감", signed_size(after_total - before_total))
        if diff.empty:
            st.caption("비교할 항목이 없습니다.")
        else:
            st.dataframe(
                pd.DataFrame(
                    {
                        "항목": diff["name"],
                        "이전": diff["before_size"].map(format_size),
                        "현재": diff["after_size"].map(format_size),
                        "증감": diff["change"].map(signed_size),
                        "상태": diff["status"],
                    }
                ),
                hide_index=True,
            )
