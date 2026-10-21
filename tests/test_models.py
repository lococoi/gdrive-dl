from __future__ import annotations

import unittest
from pathlib import Path

from gdrive_dl.errors import InvalidUrlError, UnsupportedUrlError
from gdrive_dl.models import DownloadUrl, SessionStatus


class DownloadUrlTests(unittest.TestCase):
    allowed = frozenset({"drive.google.com", "docs.google.com"})

    def parse(self, raw: str, *, allow_any_host: bool = False) -> DownloadUrl:
        return DownloadUrl.parse(
            raw,
            allowed_hosts=self.allowed,
            allow_any_host=allow_any_host,
        )

    def test_accepts_file_view_url(self) -> None:
        url = self.parse("https://drive.google.com/file/d/abc123/view?usp=sharing")
        self.assertEqual(url.host, "drive.google.com")
        self.assertEqual(url.google_file_id, "abc123")

    def test_accepts_open_id_url(self) -> None:
        url = self.parse("https://drive.google.com/open?id=abc123")
        self.assertEqual(url.google_file_id, "abc123")

    def test_redacts_query_string(self) -> None:
        url = self.parse("https://drive.google.com/file/d/abc123/view?token=secret")
        self.assertNotIn("secret", url.redacted)
        self.assertIn("<redacted>", url.redacted)

    def test_rejects_http(self) -> None:
        with self.assertRaises(InvalidUrlError):
            self.parse("http://drive.google.com/file/d/abc123/view")

    def test_rejects_credentials(self) -> None:
        with self.assertRaises(InvalidUrlError):
            self.parse("https://user:pass@drive.google.com/file/d/abc123/view")

    def test_rejects_localhost_and_private_ip(self) -> None:
        with self.assertRaises(InvalidUrlError):
            self.parse("https://localhost/file/d/abc123/view")
        with self.assertRaises(InvalidUrlError):
            self.parse("https://127.0.0.1/file/d/abc123/view")
        with self.assertRaises(InvalidUrlError):
            self.parse("https://192.168.1.10/file/d/abc123/view")

    def test_rejects_non_allowed_host(self) -> None:
        with self.assertRaises(UnsupportedUrlError):
            self.parse("https://example.com/video")

    def test_allows_public_host_when_enabled(self) -> None:
        url = self.parse("https://example.com/video", allow_any_host=True)
        self.assertEqual(url.host, "example.com")

    def test_rejects_option_like_url(self) -> None:
        with self.assertRaises(InvalidUrlError):
            self.parse("--exec=calc")

    def test_rejects_drive_folder(self) -> None:
        with self.assertRaises(UnsupportedUrlError):
            self.parse("https://drive.google.com/drive/folders/abc123")

    def test_rejects_control_characters(self) -> None:
        with self.assertRaises(InvalidUrlError):
            self.parse("https://drive.google.com/file/d/abc\n123/view")


class SessionStatusTests(unittest.TestCase):
    def test_available_requires_cookie_database_and_auth_cookies(self) -> None:
        self.assertTrue(
            SessionStatus(
                profile_dir=Path("profile"),
                cookie_db=Path("Cookies"),
                google_auth_cookie_count=1,
            ).available
        )
        self.assertFalse(
            SessionStatus(
                profile_dir=Path("profile"),
                cookie_db=None,
                google_auth_cookie_count=0,
            ).available
        )
        self.assertFalse(
            SessionStatus(
                profile_dir=Path("profile"),
                cookie_db=Path("Cookies"),
                google_auth_cookie_count=0,
            ).available
        )


if __name__ == "__main__":
    unittest.main()
