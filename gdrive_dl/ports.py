from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path

from .models import DownloadResult, DownloadUrl, ProcessResult, SessionStatus


class SessionRepository(ABC):
    @property
    @abstractmethod
    def profile_dir(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    def inspect(self) -> SessionStatus:
        raise NotImplementedError


class CookieInspector(ABC):
    @abstractmethod
    def count_google_auth_cookies(self, db_path: Path) -> int:
        raise NotImplementedError


class Authenticator(ABC):
    @abstractmethod
    def authenticate(self, profile_dir: Path, timeout_seconds: float) -> None:
        raise NotImplementedError


class Downloader(ABC):
    @abstractmethod
    def download(
        self,
        target: DownloadUrl,
        output_dir: Path,
        timeout_seconds: float,
    ) -> DownloadResult:
        raise NotImplementedError


class DirectoryPreparer(ABC):
    @abstractmethod
    def prepare(self, path: Path) -> Path:
        raise NotImplementedError


class ProcessRunner(ABC):
    @abstractmethod
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None,
        capture: bool = True,
        stdout_handler: Callable[[str], None] | None = None,
        stderr_handler: Callable[[str], None] | None = None,
        cwd: Path | None = None,
    ) -> ProcessResult:
        raise NotImplementedError


class Sleeper(ABC):
    @abstractmethod
    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


class ToolVersionProvider(ABC):
    @abstractmethod
    def version(self) -> str | None:
        raise NotImplementedError


class ProgressReporter(ABC):
    @property
    @abstractmethod
    def enabled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def report(self, line: str) -> None:
        raise NotImplementedError
