"""Aggregate scanned files by folder and extension with DuckDB."""

from dataclasses import dataclass

import duckdb
import pandas as pd

from scanner import ScanResult

UNITS = ("B", "KB", "MB", "GB", "TB")

# 현재 폴더 아래의 파일만 남기고, 현재 폴더 기준 경로(rest)로 바꾼다
SCOPED = """
WITH scoped AS (
    SELECT substr(path, $start) AS rest, size, modified_at
    FROM all_files
    WHERE starts_with(path, $prefix)
)
"""

TOTAL_SQL = SCOPED + "SELECT coalesce(sum(size), 0)::BIGINT, count(*) FROM scoped"

# 경로에 '/'가 남아 있으면 하위 폴더 안의 파일이므로 첫 폴더 이름으로 묶는다
FOLDERS_SQL = SCOPED + """
SELECT
    split_part(rest, '/', 1) AS name,
    sum(size)::BIGINT AS size,
    count(*) AS file_count
FROM scoped
WHERE contains(rest, '/')
GROUP BY name
ORDER BY size DESC, name
"""

FILES_SQL = SCOPED + """
SELECT rest AS name, size, modified_at
FROM scoped
WHERE NOT contains(rest, '/')
ORDER BY size DESC, name
LIMIT $limit
"""

# 파일 이름의 마지막 점 뒤를 확장자로 보고, 없으면 '(없음)'으로 묶는다
EXTENSIONS_SQL = SCOPED + """
SELECT
    coalesce(
        nullif(
            lower(regexp_extract(regexp_extract(rest, '[^/]+$'), '^.+\\.([^.]+)$', 1)),
            ''
        ),
        '(없음)'
    ) AS extension,
    sum(size)::BIGINT AS size,
    count(*) AS file_count
FROM scoped
GROUP BY extension
ORDER BY size DESC, extension
LIMIT $limit
"""


@dataclass(frozen=True)
class FolderAnalysis:
    total_size: int
    file_count: int
    folders: pd.DataFrame
    files: pd.DataFrame
    extensions: pd.DataFrame


def format_size(size: int) -> str:
    value = float(size)
    for unit in UNITS[:-1]:
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {UNITS[-1]}"


def files_frame(result: ScanResult) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "path": [file.relative_path for file in result.files],
            "size": [file.size for file in result.files],
            "modified_at": [file.modified_at for file in result.files],
        }
    ).astype({"path": "string", "size": "int64", "modified_at": "string"})


def analyze(files: pd.DataFrame, folder: str = "", limit: int = 200) -> FolderAnalysis:
    # 스캔은 한 번만 하고, 폴더를 옮길 때마다 메모리의 DuckDB로 다시 집계한다
    prefix = f"{folder}/" if folder else ""
    params = {"start": len(prefix) + 1, "prefix": prefix}

    with duckdb.connect() as con:
        con.register("all_files", files)
        total_size, file_count = con.execute(TOTAL_SQL, params).fetchone()
        return FolderAnalysis(
            total_size=int(total_size),
            file_count=int(file_count),
            folders=con.execute(FOLDERS_SQL, params).df(),
            files=con.execute(FILES_SQL, {**params, "limit": limit}).df(),
            extensions=con.execute(EXTENSIONS_SQL, {**params, "limit": limit}).df(),
        )
