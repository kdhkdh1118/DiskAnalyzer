import streamlit as st

from scanner import ScanError, scan


st.set_page_config(page_title="Disk Analyzer")
st.title("Disk Analyzer")

with st.form("scan_folder"):
    folder = st.text_input("분석할 로컬 폴더", placeholder=r"C:\DiskAnalyzer-Test")
    submitted = st.form_submit_button("폴더 분석 시작", type="primary")

if submitted:
    st.session_state.pop("scan_result", None)
    try:
        with st.spinner("파일 목록을 읽는 중…"):
            st.session_state.scan_result = scan(folder)
    except ScanError as exc:
        st.error(str(exc))

result = st.session_state.get("scan_result")
if result is not None:
    st.text(str(result.root))
    if result.is_partial:
        st.warning("일부 파일이나 폴더를 읽지 못했습니다. 읽을 수 있는 항목만 집계했습니다.")
    count, total = st.columns(2)
    count.metric("파일 수", f"{len(result.files):,}개")
    total.metric("파일 크기 합계", f"{result.total_bytes:,} B")
