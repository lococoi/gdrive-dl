from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from .config import AppConfig
from .infrastructure.chrome import (
    ChromeLocator,
    ChromeProcessAuthenticator,
    ChromeProfileRepository,
    SqliteCookieInspector,
)
from .infrastructure.fs import OutputDirectory
from .infrastructure.process import SubprocessRunner, SystemSleeper
from .infrastructure.yt_dlp import ErrorSanitizer, YtDlpDownloader, YtDlpLocator
from .ports import ProgressReporter
from .services import (
    DoctorService,
    DownloadService,
    LoginService,
    StatusService,
)


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    config: AppConfig
    login_service: LoginService
    download_service: DownloadService
    status_service: StatusService
    doctor_service: DoctorService


class ContainerFactory:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config
        self._logger = logger
        self._environment = environment

    def create(self, progress: ProgressReporter) -> ServiceContainer:
        runner = SubprocessRunner(self._logger)
        sessions = ChromeProfileRepository(
            self._config.profile_dir,
            SqliteCookieInspector(),
            self._logger,
        )
        chrome_locator = ChromeLocator(
            self._config.chrome_path,
            self._config.base_dir,
            self._environment,
        )
        authenticator = ChromeProcessAuthenticator(
            chrome_locator,
            runner,
            self._logger,
        )
        yt_dlp_locator = YtDlpLocator(
            self._config.base_dir,
            self._config.yt_dlp_command,
            runner,
            self._logger,
        )
        downloader = YtDlpDownloader(
            yt_dlp_locator,
            runner,
            self._config.profile_dir,
            progress,
            ErrorSanitizer(),
            self._logger,
        )
        directories = OutputDirectory()

        return ServiceContainer(
            config=self._config,
            login_service=LoginService(
                authenticator,
                sessions,
                self._config.login_timeout_seconds,
                self._logger,
            ),
            download_service=DownloadService(
                self._config,
                sessions,
                downloader,
                directories,
                SystemSleeper(),
                self._logger,
            ),
            status_service=StatusService(
                sessions,
                yt_dlp_locator,
                self._logger,
            ),
            doctor_service=DoctorService(
                self._config,
                sessions,
                yt_dlp_locator,
                chrome_locator,
                directories,
                self._logger,
            ),
        )
