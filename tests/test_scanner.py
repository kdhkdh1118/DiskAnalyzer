import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scanner import ScanError, scan


class ScannerErrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def result(self, stdout="[]", stderr="", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    @patch("scanner.subprocess.run")
    def test_successful_empty_listing_is_not_partial(self, run):
        run.return_value = self.result()
        result = scan(str(self.root))
        self.assertEqual(result.files, ())
        self.assertEqual(result.total_bytes, 0)
        self.assertFalse(result.is_partial)

    @patch("scanner.subprocess.run")
    def test_failed_empty_listing_reports_permissions(self, run):
        run.return_value = self.result(stderr="open folder: permission denied", returncode=6)
        with self.assertRaisesRegex(ScanError, "접근 권한"):
            scan(str(self.root))

    @patch("scanner.subprocess.run")
    def test_failed_invalid_output_reports_permissions_before_json_error(self, run):
        run.return_value = self.result(stdout="[", stderr="Access is denied", returncode=6)
        with self.assertRaisesRegex(ScanError, "접근 권한") as error:
            scan(str(self.root))
        self.assertNotIn("유효한 파일 목록", str(error.exception))

    @patch("scanner.subprocess.run")
    def test_failed_invalid_output_reports_scan_failure(self, run):
        run.return_value = self.result(stdout="", stderr="failed to lsjson: device error", returncode=1)
        with self.assertRaisesRegex(ScanError, "스캔에 실패") as error:
            scan(str(self.root))
        self.assertIn("device error", str(error.exception))

    @patch("scanner.subprocess.run")
    def test_successful_invalid_output_reports_invalid_listing(self, run):
        run.return_value = self.result(stdout="not json")
        with self.assertRaisesRegex(ScanError, "유효한 파일 목록"):
            scan(str(self.root))

    @patch("scanner.subprocess.run")
    def test_files_from_failed_scan_are_preserved_as_partial(self, run):
        run.return_value = self.result(
            stdout=json.dumps([{"Path": "readable.txt", "Size": 9}]),
            stderr="denied folder: permission denied", returncode=6,
        )
        result = scan(str(self.root))
        self.assertTrue(result.is_partial)
        self.assertEqual(result.files[0].relative_path, "readable.txt")
        self.assertEqual(result.total_bytes, 9)

    @patch("scanner.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_rclone_explains_installation(self, run):
        with self.assertRaisesRegex(ScanError, "Rclone을 설치"):
            scan(str(self.root))

    @patch("scanner.subprocess.run", side_effect=OSError("cannot execute"))
    def test_subprocess_error_has_korean_guidance(self, run):
        with self.assertRaisesRegex(ScanError, "Rclone을 실행"):
            scan(str(self.root))


@unittest.skipUnless(shutil.which("rclone"), "Rclone is not installed")
class RcloneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def denied_folder(self):
        if os.name != "posix" or os.geteuid() == 0:
            self.skipTest("Permission checks require an unprivileged POSIX user")
        denied = self.root / "denied"
        denied.mkdir()
        (denied / "hidden.txt").write_bytes(b"hidden")
        denied.chmod(0)
        self.addCleanup(denied.chmod, 0o700)
        return denied

    def test_real_empty_folder(self):
        result = scan(str(self.root))
        self.assertEqual(result.files, ())
        self.assertFalse(result.is_partial)

    @unittest.skipUnless(os.name == "posix", "Requires POSIX filenames")
    def test_real_trailing_space_in_folder_name_is_preserved(self):
        ordinary = self.root / "data"
        ordinary.mkdir()
        (ordinary / "wrong.txt").write_bytes(b"wrong")
        spaced = self.root / "data "
        spaced.mkdir()
        (spaced / "correct.txt").write_bytes(b"correct")
        result = scan(str(spaced))
        self.assertEqual(result.root, spaced)
        self.assertEqual([entry.relative_path for entry in result.files], ["correct.txt"])

    def test_real_inaccessible_root_is_not_an_empty_folder(self):
        denied = self.denied_folder()
        with self.assertRaisesRegex(ScanError, "접근 권한"):
            scan(str(denied))

    def test_real_inaccessible_ancestor_explains_permissions(self):
        denied = self.denied_folder()
        with self.assertRaisesRegex(ScanError, "상위 폴더의 읽기 권한"):
            scan(str(denied / "hidden.txt"))

    def test_real_ancestor_without_traverse_permission_has_access_guidance(self):
        denied = self.denied_folder()
        denied.chmod(0o600)
        with self.assertRaisesRegex(ScanError, "읽기 권한과 접근 권한"):
            scan(str(denied / "hidden.txt"))

    def test_real_inaccessible_child_without_readable_files_is_an_error(self):
        self.denied_folder()
        with self.assertRaisesRegex(ScanError, "접근 권한"):
            scan(str(self.root))

    def test_real_inaccessible_child_preserves_readable_files(self):
        self.denied_folder()
        (self.root / "readable.txt").write_bytes(b"available")
        result = scan(str(self.root))
        self.assertTrue(result.is_partial)
        self.assertEqual([entry.relative_path for entry in result.files], ["readable.txt"])
        self.assertEqual(result.total_bytes, 9)


if __name__ == "__main__":
    unittest.main()
