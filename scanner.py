"""List local files using Rclone without reading their contents."""

import json
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


def _with_detail(message: str, stderr: str | None) -> str:
    # Rclone이 남긴 마지막 오류 줄을 붙여서 실패 원인이 화면에 보이게 한다
    lines = [line for line in (stderr or "").splitlines() if line.strip()]
    return f"{message}\n\n{lines[-1]}" if lines else message


def _scan_failure(stderr: str | None) -> str:
    detail = (stderr or "").lower()
    if "permission denied" in detail or "access is denied" in detail or "access denied" in detail:
        message = (
            "폴더 접근 권한이 없어 파일 목록을 읽지 못했습니다."
            " 폴더의 읽기 권한과 접근 권한을 확인해 주세요."
        )
    else:
        message = "폴더 스캔에 실패했습니다. 경로와 접근 권한을 확인해 주세요."
    return _with_detail(message, stderr)


def _unquote(folder: str) -> str:
    # 탐색기 "경로로 복사"처럼 앞뒤에 따옴표가 붙은 경로만 따옴표를 벗긴다
    text = folder.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return folder


def scan(folder: str) -> ScanResult:
    folder = _unquote(folder)
    if not folder.strip():
        raise ScanError("분석할 폴더 경로를 입력해 주세요.")

    try:
        root = Path(folder).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ScanError("폴더 경로를 입력해 주세요.")
    except PermissionError as exc:
        raise ScanError(
            "폴더 접근 권한이 없어 열 수 없습니다."
            " 폴더와 상위 폴더의 읽기 권한과 접근 권한을 확인해 주세요."
        ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise ScanError("폴더를 찾거나 열 수 없습니다. 경로와 접근 권한을 확인해 주세요.") from exc

    try:
        # 설정 파일 경로를 빈 문자열로 주면 Windows와 Linux 모두 설정 없이 동작한다
        process = subprocess.run(
            [
                "rclone", "lsjson", "--recursive", "--files-only", "--skip-links",
                "--config", "", str(root),
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
        if process.returncode != 0:
            raise ScanError(_scan_failure(process.stderr)) from exc
        message = "Rclone이 유효한 파일 목록을 반환하지 못했습니다."
        raise ScanError(_with_detail(message, process.stderr)) from exc

    if process.returncode != 0 and not files:
        raise ScanError(_scan_failure(process.stderr))
    return ScanResult(root, files, process.returncode != 0)
