from __future__ import annotations

import importlib.util
import logging
import shutil
import sys
import threading
import time
from dataclasses import replace

from . import __version__
from .config import AppConfig
from .errors import (
    ConcurrencyLimitError,
    DownloadError,
    GdriveError,
    LoginVerificationError,
    SessionNotFoundError,
)
from .infrastructure.chrome import ChromeLocator
from .models import (
    DoctorCheck,
    DoctorReport,
    DownloadResult,
    DownloadUrl,
    SessionStatus,
    SystemStatus,
)
from .ports import (
    Authenticator,
    DirectoryPreparer,
    Downloader,
    SessionRepository,
    Sleeper,
    ToolVersionProvider,
)


class LoginService:
    def __init__(
        self,
        authenticator: Authenticator,
        sessions: SessionRepository,
        timeout_seconds: float,
        logger: logging.Logger,
    ) -> None:
        self._authenticator = authenticator
        self._sessions = sessions
        self._timeout_seconds = timeout_seconds
        self._logger = logger

    def login(self) -> SessionStatus:
        self._logger.info("Iniciando autenticación con Chrome.")
        self._authenticator.authenticate(
            self._sessions.profile_dir,
            self._timeout_seconds,
        )
        status = self._sessions.inspect()
        if not status.available:
            raise LoginVerificationError(
                "No se pudo verificar la sesión de Google después del login.",
                hint=status.reason
                or "Asegúrate de iniciar sesión y cerrar la ventana de Chrome.",
            )
        self._logger.info(
            "Sesión verificada con %s cookies de Google.",
            status.google_auth_cookie_count,
        )
        return status


class DownloadService:
    def __init__(
        self,
        config: AppConfig,
        sessions: SessionRepository,
        downloader: Downloader,
        directories: DirectoryPreparer,
        sleeper: Sleeper,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._sessions = sessions
        self._downloader = downloader
        self._directories = directories
        self._sleeper = sleeper
        self._logger = logger
        self._limiter = threading.BoundedSemaphore(config.max_concurrent_downloads)

    def download(self, raw_url: str) -> DownloadResult:
        target = DownloadUrl.parse(
            raw_url,
            allowed_hosts=self._config.allowed_hosts,
            allow_any_host=self._config.allow_any_host,
        )

        status = self._sessions.inspect()
        if not status.available:
            raise SessionNotFoundError(
                "No hay una sesión de Google válida para descargar.",
                hint=status.reason or "Ejecuta 'login' primero.",
            )

        if not self._limiter.acquire(blocking=False):
            raise ConcurrencyLimitError(
                "Hay demasiadas descargas en curso.",
                hint="Espera a que termine una descarga o aumenta max_concurrent_downloads.",
                retryable=True,
            )

        started = time.monotonic()
        attempts = 0
        try:
            status = self._sessions.inspect()
            if not status.available:
                raise SessionNotFoundError(
                    "La sesión de Google dejó de ser válida.",
                    hint=status.reason or "Ejecuta 'login' de nuevo.",
                )

            output_dir = self._directories.prepare(self._config.output_dir)
            max_attempts = self._config.retries + 1
            for attempts in range(1, max_attempts + 1):
                try:
                    result = self._downloader.download(
                        target,
                        output_dir,
                        self._config.download_timeout_seconds,
                    )
                    return replace(
                        result,
                        url=target.redacted,
                        attempts=attempts,
                        duration_seconds=time.monotonic() - started,
                    )
                except DownloadError as exc:
                    if not exc.retryable or attempts >= max_attempts:
                        raise
                    delay = self._config.retry_backoff_seconds * (2 ** (attempts - 1))
                    self._logger.warning(
                        "Intento %s/%s falló: %s. Reintentando en %.1fs.",
                        attempts,
                        max_attempts,
                        exc,
                        delay,
                    )
                    self._sleeper.sleep(delay)
            raise DownloadError("La descarga no se completó.")
        finally:
            self._limiter.release()


class StatusService:
    def __init__(
        self,
        sessions: SessionRepository,
        yt_dlp_locator: ToolVersionProvider,
        logger: logging.Logger,
    ) -> None:
        self._sessions = sessions
        self._yt_dlp_locator = yt_dlp_locator
        self._logger = logger

    def snapshot(self) -> SystemStatus:
        session = self._sessions.inspect()
        version = self._yt_dlp_locator.version()
        return SystemStatus(
            session=session,
            yt_dlp_available=version is not None,
            yt_dlp_version=version,
            app_version=__version__,
        )


class DoctorService:
    def __init__(
        self,
        config: AppConfig,
        sessions: SessionRepository,
        yt_dlp_locator: ToolVersionProvider,
        chrome_locator: ChromeLocator,
        directories: DirectoryPreparer,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._sessions = sessions
        self._yt_dlp_locator = yt_dlp_locator
        self._chrome_locator = chrome_locator
        self._directories = directories
        self._logger = logger

    def run(self) -> DoctorReport:
        checks = (
            self._check_python(),
            self._check_yt_dlp(),
            self._check_chrome(),
            self._check_session(),
            self._check_output(),
            self._check_api_dependencies(),
            self._check_api_security(),
            self._check_disk_space(),
        )
        return DoctorReport(checks=checks)

    def _check_python(self) -> DoctorCheck:
        version = (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        healthy = sys.version_info >= (3, 11)
        return DoctorCheck(
            name="Python",
            healthy=healthy,
            detail=f"{version} (se requiere 3.11+)",
        )

    def _check_yt_dlp(self) -> DoctorCheck:
        version = self._yt_dlp_locator.version()
        if version is None:
            return DoctorCheck(
                name="yt-dlp",
                healthy=False,
                detail="No se encontró o no se pudo ejecutar.",
            )
        return DoctorCheck(
            name="yt-dlp",
            healthy=True,
            detail=version,
        )

    def _check_chrome(self) -> DoctorCheck:
        try:
            path = self._chrome_locator.resolve()
        except GdriveError as exc:
            return DoctorCheck(
                name="Chrome",
                healthy=False,
                detail=str(exc),
            )
        return DoctorCheck(
            name="Chrome",
            healthy=True,
            detail=str(path),
        )

    def _check_session(self) -> DoctorCheck:
        status = self._sessions.inspect()
        if status.available:
            return DoctorCheck(
                name="Sesión de Google",
                healthy=True,
                detail=f"{status.google_auth_cookie_count} cookies de autenticación.",
            )
        return DoctorCheck(
            name="Sesión de Google",
            healthy=False,
            detail=status.reason or "Sesión no disponible.",
        )

    def _check_output(self) -> DoctorCheck:
        try:
            path = self._directories.prepare(self._config.output_dir)
        except GdriveError as exc:
            return DoctorCheck(
                name="Carpeta de descargas",
                healthy=False,
                detail=str(exc),
            )
        return DoctorCheck(
            name="Carpeta de descargas",
            healthy=True,
            detail=str(path),
        )

    def _check_api_dependencies(self) -> DoctorCheck:
        missing = [
            module
            for module in ("fastapi", "uvicorn", "pydantic")
            if not self._module_available(module)
        ]
        if missing:
            return DoctorCheck(
                name="Dependencias de la API",
                healthy=False,
                detail=f"Faltan: {', '.join(missing)}. Instala requirements.txt.",
                critical=False,
            )
        return DoctorCheck(
            name="Dependencias de la API",
            healthy=True,
            detail="fastapi, uvicorn y pydantic disponibles.",
            critical=False,
        )

    def _check_api_security(self) -> DoctorCheck:
        if AppConfig.is_loopback_host(self._config.api_host) or self._config.api_token:
            return DoctorCheck(
                name="Seguridad de la API",
                healthy=True,
                detail=(
                    f"Escucha en {self._config.api_host} "
                    f"(token {'configurado' if self._config.api_token else 'no requerido'})."
                ),
            )
        return DoctorCheck(
            name="Seguridad de la API",
            healthy=False,
            detail="La API no es local y no tiene token.",
        )

    def _check_disk_space(self) -> DoctorCheck:
        try:
            usage = shutil.disk_usage(self._config.output_dir)
        except OSError as exc:
            return DoctorCheck(
                name="Espacio en disco",
                healthy=False,
                detail=f"No se pudo consultar: {exc}",
                critical=False,
            )
        free_gib = usage.free / (1024**3)
        return DoctorCheck(
            name="Espacio en disco",
            healthy=free_gib >= 0.5,
            detail=f"{free_gib:.1f} GiB libres.",
            critical=False,
        )

    @staticmethod
    def _module_available(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False
