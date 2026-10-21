from __future__ import annotations

import logging
import tempfile
import threading
import unittest
from pathlib import Path

logging.getLogger("test").addHandler(logging.NullHandler())
logging.getLogger("test").propagate = False

from gdrive_dl.config import AppConfig
from gdrive_dl.errors import (
    ConcurrencyLimitError,
    DownloadError,
    GdriveError,
    InvalidUrlError,
    LoginVerificationError,
    SessionNotFoundError,
)
from gdrive_dl.models import (
    DownloadResult,
    DownloadStatus,
    DownloadUrl,
    SessionStatus,
)
from gdrive_dl.ports import (
    Authenticator,
    DirectoryPreparer,
    Downloader,
    SessionRepository,
    Sleeper,
    ToolVersionProvider,
)
from gdrive_dl.services import DownloadService, LoginService, StatusService


class FakeSessionRepository(SessionRepository):
    def __init__(self, status: SessionStatus) -> None:
        self.status = status
        self.inspections = 0

    @property
    def profile_dir(self) -> Path:
        return self.status.profile_dir

    def inspect(self) -> SessionStatus:
        self.inspections += 1
        return self.status


class FakeAuthenticator(Authenticator):
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Path, float]] = []

    def authenticate(self, profile_dir: Path, timeout_seconds: float) -> None:
        self.calls.append((profile_dir, timeout_seconds))
        if self.error is not None:
            raise self.error


class FakeDownloader(Downloader):
    def __init__(self, outcomes: list[DownloadResult | Exception]) -> None:
        self.outcomes = outcomes
        self.targets: list[DownloadUrl] = []

    def download(
        self,
        target: DownloadUrl,
        output_dir: Path,
        timeout_seconds: float,
    ) -> DownloadResult:
        self.targets.append(target)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class BlockingDownloader(Downloader):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def download(
        self,
        target: DownloadUrl,
        output_dir: Path,
        timeout_seconds: float,
    ) -> DownloadResult:
        self.started.set()
        self.release.wait(timeout=5)
        return DownloadResult(
            status=DownloadStatus.DOWNLOADED,
            url=target.redacted,
            output_path=None,
            attempts=1,
            duration_seconds=0.1,
            message="ok",
        )


class FakeDirectoryPreparer(DirectoryPreparer):
    def prepare(self, path: Path) -> Path:
        return path


class FakeSleeper(Sleeper):
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class FakeVersionProvider(ToolVersionProvider):
    def __init__(self, version: str | None) -> None:
        self._version = version

    def version(self) -> str | None:
        return self._version


class ServiceTests(unittest.TestCase):
    def make_config(self, base: Path, **overrides: object) -> AppConfig:
        values = {
            "base_dir": base,
            "profile_dir": base / "profile",
            "output_dir": base / "downloads",
            "login_timeout_seconds": 10.0,
            "download_timeout_seconds": 10.0,
            "retries": 2,
            "retry_backoff_seconds": 0.1,
            "max_concurrent_downloads": 1,
        }
        values.update(overrides)
        return AppConfig(**values)

    def available_status(self, profile: Path) -> SessionStatus:
        return SessionStatus(
            profile_dir=profile,
            cookie_db=profile / "Cookies",
            google_auth_cookie_count=9,
        )

    def result(self) -> DownloadResult:
        return DownloadResult(
            status=DownloadStatus.DOWNLOADED,
            url="https://drive.google.com/file/d/abc/view",
            output_path=Path("video.mp4"),
            attempts=1,
            duration_seconds=0.5,
            message="ok",
        )

    def test_login_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile"
            sessions = FakeSessionRepository(self.available_status(profile))
            authenticator = FakeAuthenticator()
            service = LoginService(
                authenticator,
                sessions,
                12.0,
                logging.getLogger("test"),
            )
            status = service.login()
            self.assertTrue(status.available)
            self.assertEqual(authenticator.calls, [(profile, 12.0)])

    def test_login_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile"
            sessions = FakeSessionRepository(
                SessionStatus(
                    profile_dir=profile,
                    cookie_db=None,
                    google_auth_cookie_count=0,
                    problem="sin cookies",
                )
            )
            service = LoginService(
                FakeAuthenticator(),
                sessions,
                12.0,
                logging.getLogger("test"),
            )
            with self.assertRaises(LoginVerificationError):
                service.login()

    def test_invalid_url_fails_before_session_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            sessions = FakeSessionRepository(self.available_status(base / "profile"))
            service = DownloadService(
                self.make_config(base),
                sessions,
                FakeDownloader([]),
                FakeDirectoryPreparer(),
                FakeSleeper(),
                logging.getLogger("test"),
            )
            with self.assertRaises(InvalidUrlError):
                service.download("ftp://drive.google.com/file")
            self.assertEqual(sessions.inspections, 0)

    def test_missing_session_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            sessions = FakeSessionRepository(
                SessionStatus(
                    profile_dir=base / "profile",
                    cookie_db=None,
                    google_auth_cookie_count=0,
                    problem="no hay sesión",
                )
            )
            service = DownloadService(
                self.make_config(base),
                sessions,
                FakeDownloader([]),
                FakeDirectoryPreparer(),
                FakeSleeper(),
                logging.getLogger("test"),
            )
            with self.assertRaises(SessionNotFoundError):
                service.download("https://drive.google.com/file/d/abc/view")

    def test_download_success_replaces_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            downloader = FakeDownloader([self.result()])
            service = DownloadService(
                self.make_config(base),
                FakeSessionRepository(self.available_status(base / "profile")),
                downloader,
                FakeDirectoryPreparer(),
                FakeSleeper(),
                logging.getLogger("test"),
            )
            result = service.download("https://drive.google.com/file/d/abc/view")
            self.assertEqual(result.attempts, 1)
            self.assertEqual(len(downloader.targets), 1)

    def test_retries_retryable_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            downloader = FakeDownloader(
                [
                    DownloadError("temporal", retryable=True),
                    self.result(),
                ]
            )
            sleeper = FakeSleeper()
            service = DownloadService(
                self.make_config(base),
                FakeSessionRepository(self.available_status(base / "profile")),
                downloader,
                FakeDirectoryPreparer(),
                sleeper,
                logging.getLogger("test"),
            )
            result = service.download("https://drive.google.com/file/d/abc/view")
            self.assertEqual(result.attempts, 2)
            self.assertEqual(sleeper.sleeps, [0.1])

    def test_does_not_retry_non_retryable_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            downloader = FakeDownloader([DownloadError("permanente")])
            sleeper = FakeSleeper()
            service = DownloadService(
                self.make_config(base),
                FakeSessionRepository(self.available_status(base / "profile")),
                downloader,
                FakeDirectoryPreparer(),
                sleeper,
                logging.getLogger("test"),
            )
            with self.assertRaises(DownloadError):
                service.download("https://drive.google.com/file/d/abc/view")
            self.assertEqual(sleeper.sleeps, [])

    def test_concurrency_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            downloader = BlockingDownloader()
            service = DownloadService(
                self.make_config(base, max_concurrent_downloads=1),
                FakeSessionRepository(self.available_status(base / "profile")),
                downloader,
                FakeDirectoryPreparer(),
                FakeSleeper(),
                logging.getLogger("test"),
            )
            errors: list[BaseException] = []

            def first_call() -> None:
                try:
                    service.download("https://drive.google.com/file/d/abc/view")
                except GdriveError as exc:
                    errors.append(exc)

            thread = threading.Thread(target=first_call)
            thread.start()
            self.assertTrue(downloader.started.wait(timeout=5))
            with self.assertRaises(ConcurrencyLimitError):
                service.download("https://drive.google.com/file/d/abc/view")
            downloader.release.set()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])

    def test_status_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            service = StatusService(
                FakeSessionRepository(self.available_status(base / "profile")),
                FakeVersionProvider("2026.08.19"),
                logging.getLogger("test"),
            )
            snapshot = service.snapshot()
            self.assertTrue(snapshot.session.available)
            self.assertTrue(snapshot.yt_dlp_available)
            self.assertEqual(snapshot.yt_dlp_version, "2026.08.19")


if __name__ == "__main__":
    unittest.main()
