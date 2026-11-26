# DiskAnalyzer
오픈소스 SW 팀 프로젝트 - 디스크 저장 공간 분석 프로그램

## 저장 공간 분석 초안 실행

Python 3.10 이상과 Rclone이 필요합니다. Rclone을 설치한 뒤 터미널에서
`rclone version`이 실행되는지 확인하세요.

저장소 폴더에서 다음 명령을 실행합니다.

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

브라우저에서 `http://localhost:8501`을 열고, 이 프로그램을 실행 중인
컴퓨터의 폴더 경로를 입력한 뒤 **폴더 분석 시작**을 누릅니다.
선택한 폴더 아래의 파일 수와 파일 크기 합계를 표시합니다.

`scanner.scan(폴더 경로)`는 분석 폴더, 파일별 상대경로·크기·수정 시각,
부분 스캔 여부를 반환합니다. 일반 스캔에서는 파일 해시를 계산하지 않습니다.
