from __future__ import annotations

import importlib.util
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from ..errors import (
    DownloadError,
    DownloadTimeoutError,
    GdriveError,
    ProcessTimeoutError,
    SessionExpiredError,
    ToolNotFoundError,
    UnsupportedUrlError,
)
from ..models import DownloadResult, DownloadStatus, DownloadUrl, ProcessResult
from ..ports import Downloader, ProcessRunner, ProgressReporter, ToolVersionProvider
from .embedded_ytdlp import EmbeddedYtDlp
from .text import AnsiStripper

_VERSION_UNSET = object()


class YtDlpLocator(ToolVersionProvider):
    def __init__(
        self,
        base_dir: Path,
        configured: tuple[str, ...] | None,
        runner: ProcessRunner,
        logger: logging.Logger,
    ) -> None:
        self._base_dir = base_dir
        self._configured = configured
        self._runner = runner
        self._logger = logger
        self._version: str | None | object = _VERSION_UNSET

    def resolve(self) -> tuple[str, ...]:
        if self._configured is not None:
            configured = tuple(str(part) for part in self._configured)
            first = Path(configured[0]).expanduser()
            candidate = first if first.is_absolute() else self._base_dir / first
            if candidate.is_file():
                return (str(candidate.resolve()), *configured[1:])
            found = shutil.which(configured[0])
            if found:
                return (found, *configured[1:])
            raise ToolNotFoundError(
                f"No se encontró yt-dlp en la ruta configurada: {configured[0]}",
                hint="Corrige GDRIVE_YTDLP o instala yt-dlp.",
            )

        bundled_candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled_candidates.append(Path(meipass) / "yt-dlp.exe")
        if getattr(sys, "frozen", False):
            bundled_candidates.append(
                Path(sys.executable).resolve().parent / "yt-dlp.exe"
            )
        for candidate in bundled_candidates:
            if candidate.is_file():
                return (str(candidate.resolve()),)

        if getattr(sys, "frozen", False):
            try:
                embedded_available = importlib.util.find_spec("yt_dlp") is not None
            except (ImportError, ValueError):
                embedded_available = False
            if embedded_available:
                return (sys.executable, EmbeddedYtDlp.COMMAND)

        for filename in ("yt-dlp.exe", "yt-dlp"):
            candidate = self._base_dir / filename
            if candidate.is_file():
                return (str(candidate.resolve()),)

        found = shutil.which("yt-dlp")
        if found:
            return (found,)

        try:
            module_available = importlib.util.find_spec("yt_dlp") is not None
        except (ImportError, ValueError):
            module_available = False
        if module_available:
            return (sys.executable, "-m", "yt_dlp")

        raise ToolNotFoundError(
            "No se encontró yt-dlp.",
            hint="Coloca yt-dlp.exe junto a gdrive-dl.py o instala yt-dlp con pip.",
        )

    def version(self) -> str | None:
        if self._version is not _VERSION_UNSET:
            return cast(str | None, self._version)
        try:
            prefix = self.resolve()
            result = self._runner.run(
                (*prefix, "--version"),
                timeout=15.0,
                capture=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip().splitlines()[-1]
            else:
                version = None
        except GdriveError as exc:
            self._logger.debug("No se pudo obtener la versión de yt-dlp: %s", exc)
            version = None
        self._version = version
        return version


class ErrorSanitizer:
    _URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")

    def sanitize(self, text: str, *, max_chars: int = 2000, max_lines: int = 20) -> str:
        cleaned = AnsiStripper.strip(text)
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        tail = lines[-max_lines:]
        joined = "\n".join(tail)
        joined = self._URL_PATTERN.sub(self._redact_url, joined)
        if len(joined) > max_chars:
            joined = "…" + joined[-max_chars:]
        return joined or "yt-dlp falló sin salida de error."

    @staticmethod
    def _redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
        except ValueError:
            return "<url-redacted>"
        netloc = parts.netloc.rsplit("@", 1)[-1]
        query = "<redacted>" if parts.query else ""
        return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


class YtDlpDownloader(Downloader):
    def __init__(
        self,
        locator: YtDlpLocator,
        runner: ProcessRunner,
        profile_dir: Path,
        progress: ProgressReporter,
        sanitizer: ErrorSanitizer,
        logger: logging.Logger,
    ) -> None:
        self._locator = locator
        self._runner = runner
        self._profile_dir = profile_dir
        self._progress = progress
        self._sanitizer = sanitizer
        self._logger = logger

    def download(
        self,
        target: DownloadUrl,
        output_dir: Path,
        timeout_seconds: float,
    ) -> DownloadResult:
        prefix = self._locator.resolve()
        options = [
            "--cookies-from-browser",
            f"chrome:{self._profile_dir}",
            "--no-playlist",
            "--continue",
            "--no-overwrites",
            "--windows-filenames",
            "--trim-filenames",
            "180",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--socket-timeout",
            "30",
            "--newline",
            "--no-color",
            "--progress" if self._progress.enabled else "--no-progress",
            "--paths",
            str(output_dir),
            "--output",
            "%(title)s [%(id)s].%(ext)s",
            "--",
            target.value,
        ]
        argv = (*prefix, *options)
        self._logger.info("Descargando %s", target.redacted)

        try:
            result = self._runner.run(
                argv,
                timeout=timeout_seconds,
                capture=True,
                stdout_handler=self._progress.report if self._progress.enabled else None,
                stderr_handler=self._progress.report if self._progress.enabled else None,
            )
        except ProcessTimeoutError as exc:
            raise DownloadTimeoutError(
                f"La descarga excedió el tiempo límite de {timeout_seconds:.0f} segundos.",
                hint="Aumenta --timeout o GDRIVE_DOWNLOAD_TIMEOUT.",
            ) from exc

        if result.returncode == 0:
            return self._successful_result(target, output_dir, result)

        raise self._classify_failure(target, result)

    def _successful_result(
        self,
        target: DownloadUrl,
        output_dir: Path,
        result: ProcessResult,
    ) -> DownloadResult:
        output_path = self._extract_output_path(result.stdout, output_dir)
        lowered = f"{result.stdout}\n{result.stderr}".lower()
        skipped = (
            "has already been downloaded" in lowered
            or "has already been recorded in the archive" in lowered
        )
        status = DownloadStatus.SKIPPED if skipped else DownloadStatus.DOWNLOADED
        message = (
            "El archivo ya existía; se omitió la descarga."
            if skipped
            else "Descarga completada."
        )
        return DownloadResult(
            status=status,
            url=target.redacted,
            output_path=output_path,
            attempts=1,
            duration_seconds=result.duration_seconds,
            message=message,
        )

    def _classify_failure(self, target: DownloadUrl, result: ProcessResult) -> GdriveError:
        lowered = f"{result.stderr}\n{result.stdout}".lower()
        clean = self._sanitizer.sanitize(f"{result.stderr}\n{result.stdout}")

        if "no module named 'yt_dlp.extractor." in lowered:
            return UnsupportedUrlError(
                "Esta build slim no incluye el extractor para este sitio.",
                hint=(
                    "El ejecutable incluye Google Drive y extractores genéricos. "
                    "Ejecuta desde el código fuente para el conjunto completo de yt-dlp."
                ),
            )
        if "unsupported url" in lowered:
            return UnsupportedUrlError(
                f"yt-dlp no soporta esta URL: {target.redacted}",
                hint="Verifica que sea un enlace de archivo de Google Drive.",
            )
        if any(
            marker in lowered
            for marker in (
                "could not find chrome cookies database",
                "failed to decrypt",
                "cookie database",
                "sign in to confirm",
                "login required",
                "authentication required",
            )
        ):
            return SessionExpiredError(
                "No se pudo usar la sesión de Google guardada.",
                hint="Ejecuta 'login' de nuevo y cierra Chrome antes de descargar.",
            )
        if "http error 403" in lowered or "forbidden" in lowered:
            return DownloadError(
                "Google Drive denegó el acceso (HTTP 403).",
                hint="Verifica que la cuenta tenga permiso sobre el archivo.",
            )
        if any(
            marker in lowered
            for marker in (
                "http error 5",
                "timed out",
                "timeout",
                "connection reset",
                "connection aborted",
                "temporary failure",
                "unable to download",
                "read timed out",
                "network is unreachable",
            )
        ):
            return DownloadError(
                f"Fallo temporal de descarga: {clean}",
                retryable=True,
            )
        return DownloadError(
            f"yt-dlp terminó con código {result.returncode}: {clean}",
            retryable=False,
        )

    @staticmethod
    def _extract_output_path(stdout: str, output_dir: Path) -> Path | None:
        cleaned = AnsiStripper.strip(stdout)
        patterns = (
            re.compile(r"\[download\] Destination: (.+)"),
            re.compile(r"\[Merger\] Merging formats into \"(.+)\""),
            re.compile(r"\[download\] (.+) has already been downloaded"),
        )
        for pattern in patterns:
            for raw_path in reversed(pattern.findall(cleaned)):
                candidate = Path(raw_path.strip().strip('"'))
                if not candidate.is_absolute():
                    candidate = output_dir / candidate
                try:
                    if candidate.exists():
                        return candidate
                except OSError:
                    continue
        return None
