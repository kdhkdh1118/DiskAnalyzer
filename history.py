"""Save scan results to DuckDB and compare two scans of the same folder."""

import os
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from scanner import ScanResult

DIRECT_FILES = "(이 폴더의 파일)"

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS scan_id_seq START 1;
CREATE TABLE IF NOT EXISTS scans (
    scan_id BIGINT PRIMARY KEY DEFAULT nextval('scan_id_seq'),
    scanned_at TIMESTAMP NOT NULL,
    root_path VARCHAR NOT NULL,
    total_size BIGINT NOT NULL,
    file_count BIGINT NOT NULL,
    is_partial BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    scan_id BIGINT NOT NULL,
    path VARCHAR NOT NULL,
    size BIGINT NOT NULL,
    modified_at VARCHAR
);
"""

# 기록 하나에서 현재 폴더 바로 아래 항목별 크기를 구한다.
# 하위 폴더 안의 파일은 첫 폴더 이름으로, 현재 폴더에 직접 있는 파일은 한 줄로 묶는다
ITEMS_SQL = """
SELECT
    CASE
        WHEN contains(rest, '/') THEN split_part(rest, '/', 1)
        ELSE $direct
    END AS name,
    sum(size)::BIGINT AS size
FROM (
    SELECT substr(path, $start) AS rest, size
    FROM files
    WHERE scan_id = $scan_id AND starts_with(path, $prefix)
)
GROUP BY name
"""

# 두 기록의 항목을 이름으로 맞춰 붙이고, 한쪽에만 있으면 새로 생김/사라짐으로 본다
COMPARE_SQL = f"""
WITH
    before AS ({ITEMS_SQL.replace("$scan_id", "$before_id")}),
    after AS ({ITEMS_SQL.replace("$scan_id", "$after_id")})
SELECT
    coalesce(after.name, before.name) AS name,
    coalesce(before.size, 0)::BIGINT AS before_size,
    coalesce(after.size, 0)::BIGINT AS after_size,
    (coalesce(after.size, 0) - coalesce(before.size, 0))::BIGINT AS change,
    CASE
        WHEN before.name IS NULL THEN '새로 생김'
        WHEN after.name IS NULL THEN '사라짐'
        WHEN after.size > before.size THEN '증가'
        WHEN after.size < before.size THEN '감소'
        ELSE '변화 없음'
    END AS status
FROM before
FULL OUTER JOIN after ON before.name = after.name
ORDER BY abs(change) DESC, name
"""


def default_db_path() -> Path:
    # 테스트에서는 환경 변수로 임시 DB를 지정해 실제 기록을 건드리지 않는다
    custom = os.environ.get("DISK_ANALYZER_DB")
    if custom:
        return Path(custom)
    return Path(__file__).parent / "data" / "disk_analyzer.duckdb"


def _connect(db_path: Path | None) -> duckdb.DuckDBPyConnection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def save_scan(
    result: ScanResult, files: pd.DataFrame, db_path: Path | None = None
) -> int:
    with _connect(db_path) as con:
        scan_id = con.execute(
            """
            INSERT INTO scans
                (scanned_at, root_path, total_size, file_count, is_partial)
            VALUES (?, ?, ?, ?, ?)
            RETURNING scan_id
            """,
            [
                datetime.now().replace(microsecond=0),
                str(result.root),
                result.total_bytes,
                len(result.files),
                result.is_partial,
            ],
        ).fetchone()[0]
        con.register("new_files", files)
        con.execute(
            "INSERT INTO files SELECT ?, path, size, modified_at FROM new_files",
            [scan_id],
        )
        return int(scan_id)


def list_scans(root: Path, db_path: Path | None = None) -> pd.DataFrame:
    with _connect(db_path) as con:
        return con.execute(
            """
            SELECT scan_id, scanned_at, total_size, file_count, is_partial
            FROM scans
            WHERE root_path = ?
            ORDER BY scanned_at DESC, scan_id DESC
            """,
            [str(root)],
        ).df()


def compare_scans(
    before_id: int, after_id: int, folder: str = "", db_path: Path | None = None
) -> pd.DataFrame:
    prefix = f"{folder}/" if folder else ""
    with _connect(db_path) as con:
        return con.execute(
            COMPARE_SQL,
            {
                "before_id": before_id,
                "after_id": after_id,
                "start": len(prefix) + 1,
                "prefix": prefix,
                "direct": DIRECT_FILES,
            },
        ).df()
