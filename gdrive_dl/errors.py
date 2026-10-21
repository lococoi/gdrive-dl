from __future__ import annotations


class GdriveError(Exception):
    code = "gdrive_error"

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.retryable = retryable

    def __str__(self) -> str:
        return self.message


class UsageError(GdriveError):
    code = "usage_error"


class ConfigurationError(GdriveError):
    code = "configuration_error"


class DependencyUnavailableError(GdriveError):
    code = "dependency_unavailable"


class ToolNotFoundError(GdriveError):
    code = "tool_not_found"


class InvalidUrlError(GdriveError):
    code = "invalid_url"


class UnsupportedUrlError(GdriveError):
    code = "unsupported_url"


class SessionError(GdriveError):
    code = "session_error"


class SessionNotFoundError(SessionError):
    code = "session_not_found"


class SessionExpiredError(SessionError):
    code = "session_expired"


class LoginTimeoutError(SessionError):
    code = "login_timeout"


class LoginVerificationError(SessionError):
    code = "login_verification_failed"


class CookieDatabaseError(SessionError):
    code = "cookie_database_error"


class BrowserError(SessionError):
    code = "browser_error"


class DownloadError(GdriveError):
    code = "download_error"


class DownloadTimeoutError(DownloadError):
    code = "download_timeout"


class ConcurrencyLimitError(DownloadError):
    code = "concurrency_limit"


class OutputDirectoryError(DownloadError):
    code = "output_directory_error"


class ProcessError(GdriveError):
    code = "process_error"


class ProcessTimeoutError(ProcessError):
    code = "process_timeout"

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.stdout = stdout
        self.stderr = stderr
