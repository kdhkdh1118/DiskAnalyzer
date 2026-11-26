"""List local files using Rclone without reading their contents."""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ScanError(Exception):
    """The requested folder could not be scanned."""


@dataclass(frozen=True)
class FileEntry:
    relative_path: str
    size: int
    modified_at: str


@dataclass(frozen=True)
class ScanResult:
    root: Path
    files: tuple[FileEntry, ...]
    is_partial: bool

    @property
    def total_bytes(self) -> int:
        return sum(file.size for file in self.files)


def scan(folder: str) -> ScanResult:
    if not folder.strip():
        raise ScanError("분석할 폴더 경로를 입력해 주세요.")

    try:
        root = Path(folder.strip()).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ScanError("폴더 경로를 입력해 주세요.")
    except (OSError, RuntimeError, ValueError) as exc:
        raise ScanError("폴더를 찾거나 열 수 없습니다.") from exc

    try:
        process = subprocess.run(
            [
                "rclone", "lsjson", "--recursive", "--files-only", "--skip-links",
                "--config", os.devnull, str(root),
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as exc:
        raise ScanError("Rclone을 설치하고 PATH에 추가해 주세요.") from exc
    except (OSError, UnicodeError) as exc:
        raise ScanError("Rclone을 실행하거나 결과를 읽을 수 없습니다.") from exc

    try:
        listing = json.loads(process.stdout)
        if not isinstance(listing, list):
            raise ValueError("Expected a file list")
        files = tuple(
            FileEntry(item["Path"], item["Size"], item.get("ModTime", ""))
            for item in listing
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ScanError("Rclone이 유효한 파일 목록을 반환하지 못했습니다.") from exc

    if process.returncode != 0 and not files:
        raise ScanError("폴더에서 파일 목록을 읽지 못했습니다.")
    return ScanResult(root, files, process.returncode != 0)
