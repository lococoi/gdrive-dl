from __future__ import annotations

import contextlib
import importlib.util
import io
import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gdrive_dl.errors import (
    CookieDatabaseError,
    DownloadError,
    DownloadTimeoutError,
    LoginTimeoutError,
    OutputDirectoryError,
    ProcessTimeoutError,
    SessionExpiredError,
    ToolNotFoundError,
    UnsupportedUrlError,
)
from gdrive_dl.infrastructure.chrome import (
    ChromeLocator,
    ChromeProcessAuthenticator,
    ChromeProfileRepository,
    SqliteCookieInspector,
)
from gdrive_dl.infrastructure.embedded_ytdlp import EmbeddedYtDlp
from gdrive_dl.infrastructure.fs import OutputDirectory
from gdrive_dl.infrastructure.process import SubprocessRunner, TailBuffer
from gdrive_dl.infrastructure.progress import NullProgressReporter
from gdrive_dl.infrastructure.yt_dlp import (
    ErrorSanitizer,
    YtDlpDownloader,
    YtDlpLocator,
)
from gdrive_dl.models import DownloadStatus, DownloadUrl, ProcessResult
from gdrive_dl.ports import ProcessRunner

logging.getLogger("test").addHandler(logging.NullHandler())
logging.getLogger("test").propagate = False


class FakeRunner(ProcessRunner):
    def __init__(
        self,
        result: ProcessResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, *, timeout, capture=True, stdout_handler=None, stderr_handler=None, cwd=None):
        self.calls.append(tuple(argv))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("FakeRunner sin resultado")
        if stdout_handler is not None:
            for line in self.result.stdout.splitlines():
                stdout_handler(line)
        if stderr_handler is not None:
            for line in self.result.stderr.splitlines():
                stderr_handler(line)
        return self.result


class FakeLocator:
    def resolve(self) -> tuple[str, ...]:
        return ("yt-dlp.exe",)

    def version(self) -> str | None:
        return "test"


class YtDlpDownloaderTests(unittest.TestCase):
    def make_downloader(self, runner: FakeRunner) -> YtDlpDownloader:
        return YtDlpDownloader(
            FakeLocator(),
            runner,
            Path("C:/profile"),
            NullProgressReporter(),
            ErrorSanitizer(),
            logging.getLogger("test"),
        )

    def target(self) -> DownloadUrl:
        return DownloadUrl.parse(
            "https://drive.google.com/file/d/abc123/view",
            allowed_hosts=frozenset({"drive.google.com"}),
            allow_any_host=False,
        )

    def test_successful_download_builds_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            output_file = output_dir / "video.mp4"
            output_file.write_bytes(b"x")
            runner = FakeRunner(
                ProcessResult(
                    returncode=0,
                    stdout=f"[download] Destination: {output_file}\n",
                    stderr="",
                    duration_seconds=1.5,
                )
            )
            downloader = self.make_downloader(runner)

            result = downloader.download(self.target(), output_dir, 60)

            self.assertEqual(result.status, DownloadStatus.DOWNLOADED)
            self.assertEqual(result.output_path, output_file)
            command = runner.calls[0]
            self.assertIn("--cookies-from-browser", command)
            self.assertIn("--no-playlist", command)
            self.assertIn("--no-overwrites", command)
            self.assertIn(f"chrome:{Path('C:/profile')}", command)
            self.assertEqual(command[-2], "--")
            self.assertEqual(command[-1], self.target().value)

    def test_unsupported_url_is_classified(self) -> None:
        runner = FakeRunner(
            ProcessResult(
                returncode=1,
                stdout="",
                stderr="ERROR: Unsupported URL: https://example.com/video",
                duration_seconds=0.1,
            )
        )
        with self.assertRaises(UnsupportedUrlError):
            self.make_downloader(runner).download(self.target(), Path("."), 60)

    def test_cookie_error_is_classified_as_session_error(self) -> None:
        runner = FakeRunner(
            ProcessResult(
                returncode=1,
                stdout="",
                stderr="ERROR: could not find chrome cookies database",
                duration_seconds=0.1,
            )
        )
        with self.assertRaises(SessionExpiredError):
            self.make_downloader(runner).download(self.target(), Path("."), 60)

    def test_network_error_is_retryable(self) -> None:
        runner = FakeRunner(
            ProcessResult(
                returncode=1,
                stdout="",
                stderr="ERROR: unable to download video data: HTTP Error 503",
                duration_seconds=0.1,
            )
        )
        with self.assertRaises(DownloadError) as context:
            self.make_downloader(runner).download(self.target(), Path("."), 60)
        self.assertTrue(context.exception.retryable)

    def test_timeout_is_wrapped(self) -> None:
        runner = FakeRunner(
            error=ProcessTimeoutError("timeout", timeout_seconds=1)
        )
        with self.assertRaises(DownloadTimeoutError):
            self.make_downloader(runner).download(self.target(), Path("."), 1)


class YtDlpLocatorTests(unittest.TestCase):
    def test_prefers_bundled_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            executable = base / "yt-dlp.exe"
            executable.write_bytes(b"fake")
            locator = YtDlpLocator(
                base,
                None,
                FakeRunner(
                    ProcessResult(0, "2026.08.19\n", "", 0.1)
                ),
                logging.getLogger("test"),
            )
            self.assertEqual(locator.resolve(), (str(executable.resolve()),))
            self.assertEqual(locator.version(), "2026.08.19")

    def test_missing_configured_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator = YtDlpLocator(
                Path(temporary),
                ("missing-yt-dlp",),
                FakeRunner(),
                logging.getLogger("test"),
            )
            with self.assertRaises(ToolNotFoundError):
                locator.resolve()

    def test_prefers_binary_extracted_by_pyinstaller(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundled = base / "yt-dlp.exe"
            bundled.write_bytes(b"fake")
            locator = YtDlpLocator(
                base / "work",
                None,
                FakeRunner(),
                logging.getLogger("test"),
            )
            with patch.object(sys, "_MEIPASS", str(base), create=True):
                self.assertEqual(locator.resolve(), (str(bundled.resolve()),))

    def test_frozen_build_uses_embedded_python_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "gdrive-dl.exe"
            locator = YtDlpLocator(
                Path(temporary),
                None,
                FakeRunner(),
                logging.getLogger("test"),
            )
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys,
                "executable",
                str(executable),
            ), patch(
                "gdrive_dl.infrastructure.yt_dlp.importlib.util.find_spec",
                return_value=object(),
            ):
                self.assertEqual(
                    locator.resolve(),
                    (str(executable), EmbeddedYtDlp.COMMAND),
                )


class EmbeddedYtDlpTests(unittest.TestCase):
    def test_invocation_detection(self) -> None:
        self.assertTrue(EmbeddedYtDlp.is_invocation(["gdrive-dl", "__yt-dlp"]))
        self.assertFalse(EmbeddedYtDlp.is_invocation(["gdrive-dl", "status"]))

    @unittest.skipUnless(
        importlib.util.find_spec("yt_dlp") is not None,
        "yt-dlp Python package is not installed",
    )
    def test_reports_embedded_version(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = EmbeddedYtDlp().run(["--version"])
        self.assertEqual(result, 0)
        self.assertTrue(output.getvalue().strip())


class ProcessRunnerTests(unittest.TestCase):
    def test_captures_stdout(self) -> None:
        runner = SubprocessRunner(logging.getLogger("test"))
        result = runner.run(
            [sys.executable, "-c", "print('hola')"],
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("hola", result.stdout)

    def test_invokes_handler(self) -> None:
        runner = SubprocessRunner(logging.getLogger("test"))
        lines: list[str] = []
        result = runner.run(
            [sys.executable, "-c", "print('uno'); print('dos')"],
            timeout=10,
            stdout_handler=lines.append,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(any("uno" in line for line in lines))

    def test_timeout_kills_process(self) -> None:
        runner = SubprocessRunner(logging.getLogger("test"))
        with self.assertRaises(ProcessTimeoutError):
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.5,
            )

    def test_missing_executable(self) -> None:
        runner = SubprocessRunner(logging.getLogger("test"))
        with self.assertRaises(ToolNotFoundError):
            runner.run(["definitely-not-a-real-executable-xyz"], timeout=1)

    def test_tail_buffer_keeps_tail(self) -> None:
        buffer = TailBuffer(max_chars=5)
        buffer.append("123456789")
        self.assertEqual(buffer.getvalue(), "56789")


class CookieInspectorTests(unittest.TestCase):
    def test_counts_google_auth_cookies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "Cookies"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
            connection.execute(
                "INSERT INTO cookies VALUES (?, ?)",
                (".google.com", "SID"),
            )
            connection.execute(
                "INSERT INTO cookies VALUES (?, ?)",
                ("example.com", "SID"),
            )
            connection.commit()
            connection.close()

            inspector = SqliteCookieInspector()
            self.assertEqual(inspector.count_google_auth_cookies(database), 1)

    def test_missing_database_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inspector = SqliteCookieInspector()
            with self.assertRaises(CookieDatabaseError):
                inspector.count_google_auth_cookies(Path(temporary) / "missing")


class ChromeProfileRepositoryTests(unittest.TestCase):
    def test_profile_with_google_cookie_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            cookie_db = profile / "Default" / "Network" / "Cookies"
            cookie_db.parent.mkdir(parents=True)
            connection = sqlite3.connect(cookie_db)
            connection.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
            connection.execute(
                "INSERT INTO cookies VALUES (?, ?)",
                (".google.com", "SID"),
            )
            connection.commit()
            connection.close()

            repository = ChromeProfileRepository(
                profile,
                SqliteCookieInspector(),
                logging.getLogger("test"),
            )
            status = repository.inspect()
            self.assertTrue(status.available)
            self.assertEqual(status.google_auth_cookie_count, 1)

    def test_missing_profile_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = ChromeProfileRepository(
                Path(temporary) / "missing",
                SqliteCookieInspector(),
                logging.getLogger("test"),
            )
            status = repository.inspect()
            self.assertFalse(status.available)
            self.assertIsNotNone(status.reason)


class OutputDirectoryTests(unittest.TestCase):
    def test_creates_and_checks_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "downloads"
            prepared = OutputDirectory().prepare(path)
            self.assertEqual(prepared, path)
            self.assertTrue(path.is_dir())

    def test_rejects_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "file"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(OutputDirectoryError):
                OutputDirectory().prepare(path)


class ChromeLocatorTests(unittest.TestCase):
    def test_configured_chrome_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            chrome = Path(temporary) / "chrome.exe"
            chrome.write_bytes(b"fake")
            locator = ChromeLocator(chrome, Path(temporary), environment={})
            self.assertEqual(locator.resolve(), chrome.resolve())
            self.assertTrue(locator.is_available())

    def test_authenticator_launches_isolated_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            chrome = Path(temporary) / "chrome.exe"
            chrome.write_bytes(b"fake")
            profile = Path(temporary) / "profile"
            runner = FakeRunner(ProcessResult(0, "", "", 0.1))
            authenticator = ChromeProcessAuthenticator(
                ChromeLocator(chrome, Path(temporary), environment={}),
                runner,
                logging.getLogger("test"),
            )
            authenticator.authenticate(profile, 30)
            command = runner.calls[0]
            self.assertIn(f"--user-data-dir={profile}", command)
            self.assertIn("https://accounts.google.com/", command)

    def test_authenticator_maps_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            chrome = Path(temporary) / "chrome.exe"
            chrome.write_bytes(b"fake")
            authenticator = ChromeProcessAuthenticator(
                ChromeLocator(chrome, Path(temporary), environment={}),
                FakeRunner(error=ProcessTimeoutError("timeout", timeout_seconds=1)),
                logging.getLogger("test"),
            )
            with self.assertRaises(LoginTimeoutError):
                authenticator.authenticate(Path(temporary) / "profile", 1)


class ErrorSanitizerTests(unittest.TestCase):
    def test_redacts_query_and_ansi(self) -> None:
        sanitizer = ErrorSanitizer()
        cleaned = sanitizer.sanitize(
            "\x1b[31mERROR: https://drive.google.com/file/d/x?token=secret\x1b[0m"
        )
        self.assertNotIn("secret", cleaned)
        self.assertNotIn("\x1b", cleaned)
        self.assertIn("<redacted>", cleaned)


if __name__ == "__main__":
    unittest.main()
