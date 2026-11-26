import shutil

import pandas as pd
import streamlit as st

from analyzer import analyze, files_frame, format_size
from scanner import ScanError, scan


def go_to(folder: str) -> None:
    # view 번호를 바꿔서 이전 폴더 표의 선택 상태가 새 화면에 남지 않게 한다
    st.session_state.current = folder
    st.session_state.view = st.session_state.get("view", 0) + 1


def ratio_column() -> st.column_config.ProgressColumn:
    return st.column_config.ProgressColumn(
        "비율", format="%.1f%%", min_value=0, max_value=100
    )


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
    except ScanError as exc:
        st.error(str(exc))

result = st.session_state.get("scan_result")
if result is not None:
    if result.is_partial:
        st.warning(
            "일부 파일이나 폴더를 읽지 못했습니다. 읽을 수 있는 항목만 집계했습니다."
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

    st.markdown("**하위 폴더** · 폴더를 클릭하면 안으로 들어갑니다")
    if view.folders.empty:
        st.caption("하위 폴더가 없습니다.")
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
