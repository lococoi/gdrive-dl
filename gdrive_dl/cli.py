from __future__ import annotations

import argparse
import json
import logging
import sys
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from enum import IntEnum
from pathlib import Path
from typing import TextIO

from . import __version__
from .api import ApiServer
from .config import AppConfig, ConfigFactory, ConfigOverrides
from .container import ContainerFactory, ServiceContainer
from .errors import (
    ConfigurationError,
    DependencyUnavailableError,
    DownloadError,
    GdriveError,
    InvalidUrlError,
    ProcessError,
    SessionError,
    ToolNotFoundError,
    UnsupportedUrlError,
    UsageError,
)
from .infrastructure.logging import LoggingConfigurator
from .infrastructure.progress import StreamProgressReporter
from .models import DoctorReport, DownloadResult, SessionStatus, SystemStatus
from .services import DoctorService, DownloadService, LoginService, StatusService


class ExitCode(IntEnum):
    OK = 0
    FAILURE = 1
    USAGE = 2
    CONFIG = 3
    SESSION = 4
    DOWNLOAD = 5
    DEPENDENCY = 6
    INTERRUPTED = 130


class ExitCodeMapper:
    @staticmethod
    def map(exc: BaseException) -> ExitCode:
        if isinstance(exc, (UsageError, InvalidUrlError, UnsupportedUrlError)):
            return ExitCode.USAGE
        if isinstance(exc, ConfigurationError):
            return ExitCode.CONFIG
        if isinstance(exc, SessionError):
            return ExitCode.SESSION
        if isinstance(exc, (DownloadError, ProcessError)):
            return ExitCode.DOWNLOAD
        if isinstance(exc, (ToolNotFoundError, DependencyUnavailableError)):
            return ExitCode.DEPENDENCY
        return ExitCode.FAILURE


class ConsolePresenter:
    def __init__(
        self,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        *,
        json_mode: bool = False,
    ) -> None:
        self._stdout = stdout if stdout is not None else sys.stdout
        self._stderr = stderr if stderr is not None else sys.stderr
        self._json_mode = json_mode

    def info(self, message: str) -> None:
        self._write(self._stdout, message)

    def success(self, message: str) -> None:
        self._write(self._stdout, f"[OK] {message}")

    def warning(self, message: str) -> None:
        self._write(self._stderr, f"[AVISO] {message}")

    def error(self, exc: GdriveError) -> None:
        if self._json_mode:
            self._write(
                self._stdout,
                json.dumps(
                    {
                        "error": str(exc),
                        "code": exc.code,
                        "hint": exc.hint,
                        "retryable": exc.retryable,
                    },
                    ensure_ascii=False,
                ),
            )
            return
        self._write(self._stderr, f"[ERROR] {exc}")
        if exc.hint:
            self._write(self._stderr, f"  Pista: {exc.hint}")

    def unexpected_error(self) -> None:
        if self._json_mode:
            self._write(
                self._stdout,
                json.dumps(
                    {
                        "error": "Error inesperado.",
                        "code": "internal_error",
                        "hint": "Revisa logs/gdrive-dl.log.",
                        "retryable": False,
                    },
                    ensure_ascii=False,
                ),
            )
            return
        self._write(
            self._stderr,
            "[ERROR] Error inesperado. Revisa logs/gdrive-dl.log para más detalles.",
        )

    def login_success(self, status: SessionStatus) -> None:
        self.success(
            "Sesión verificada: "
            f"{status.google_auth_cookie_count} cookies de Google en "
            f"{status.profile_dir}"
        )

    def download_result(self, result: DownloadResult) -> None:
        self.success(result.message)
        if result.output_path is not None:
            self.info(f"  Archivo: {result.output_path}")
        self.info(
            f"  Intentos: {result.attempts} | "
            f"Duración: {result.duration_seconds:.1f}s"
        )

    def system_status(self, status: SystemStatus) -> None:
        if self._json_mode:
            payload = {
                "app_version": status.app_version,
                "session": {
                    "available": status.session.available,
                    "profile_dir": str(status.session.profile_dir),
                    "cookie_db": (
                        str(status.session.cookie_db)
                        if status.session.cookie_db
                        else None
                    ),
                    "google_auth_cookie_count": (
                        status.session.google_auth_cookie_count
                    ),
                    "reason": status.session.reason,
                },
                "yt_dlp": {
                    "available": status.yt_dlp_available,
                    "version": status.yt_dlp_version,
                },
            }
            self._write(self._stdout, json.dumps(payload, ensure_ascii=False))
            return

        availability = "disponible" if status.session.available else "no disponible"
        self.info(f"Aplicación: {status.app_version}")
        self.info(
            f"Sesión: {availability} "
            f"({status.session.google_auth_cookie_count} cookies de Google)"
        )
        self.info(f"Perfil: {status.session.profile_dir}")
        if status.session.cookie_db is not None:
            self.info(f"Cookies: {status.session.cookie_db}")
        if status.session.reason:
            self.info(f"Motivo: {status.session.reason}")
        yt_dlp = status.yt_dlp_version or "no disponible"
        self.info(f"yt-dlp: {yt_dlp}")

    def doctor_report(self, report: DoctorReport) -> None:
        if self._json_mode:
            payload = {
                "healthy": report.healthy,
                "checks": [
                    {
                        "name": check.name,
                        "healthy": check.healthy,
                        "critical": check.critical,
                        "detail": check.detail,
                    }
                    for check in report.checks
                ],
            }
            self._write(self._stdout, json.dumps(payload, ensure_ascii=False))
            return

        for check in report.checks:
            if check.healthy:
                marker = "[OK]"
            elif check.critical:
                marker = "[FALLO]"
            else:
                marker = "[AVISO]"
            self._write(self._stdout, f"{marker} {check.name}: {check.detail}")

        failed = report.failed
        critical_failed = tuple(check for check in failed if check.critical)
        if critical_failed:
            self._write(
                self._stdout,
                f"Resultado: {len(critical_failed)} fallo(s) crítico(s).",
            )
        elif failed:
            self._write(
                self._stdout,
                f"Resultado: lo crítico está correcto; {len(failed)} aviso(s).",
            )
        else:
            self._write(self._stdout, "Resultado: todo correcto.")

    def print_help(self, parser: argparse.ArgumentParser) -> None:
        parser.print_help(self._stdout)

    def _write(self, stream: TextIO, message: str) -> None:
        stream.write(f"{message}\n")
        stream.flush()


class ArgumentParserFactory:
    def create(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="gdrive-dl",
            description=(
                "Descarga archivos de Google Drive usando una sesión de Chrome "
                "aislada."
            ),
        )
        parser.add_argument(
            "-V",
            "--version",
            action="version",
            version=f"%(prog)s {__version__}",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Activa logs de depuración.",
        )
        parser.add_argument(
            "--log-level",
            choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            default=None,
            help="Nivel de log (por defecto INFO).",
        )
        parser.add_argument(
            "--profile-dir",
            type=Path,
            default=None,
            help="Directorio del perfil de Chrome (por defecto ./chrome_profile).",
        )

        subparsers = parser.add_subparsers(dest="command", metavar="COMANDO")

        login = subparsers.add_parser(
            "login",
            help="Abre Chrome para iniciar sesión y guardar el perfil.",
        )
        login.add_argument(
            "--timeout",
            type=float,
            default=None,
            help="Segundos máximos para completar el login (por defecto 900).",
        )

        download = subparsers.add_parser(
            "download",
            help="Descarga un archivo usando la sesión guardada.",
        )
        download.add_argument("url", help="Enlace HTTPS de Google Drive.")
        download.add_argument(
            "-o",
            "--output-dir",
            type=Path,
            default=None,
            help="Carpeta de destino (por defecto ./downloads).",
        )
        download.add_argument(
            "--timeout",
            type=float,
            default=None,
            help="Segundos máximos para la descarga (por defecto 3600).",
        )
        download.add_argument(
            "--retries",
            type=int,
            default=None,
            help="Reintentos adicionales ante fallos temporales (0-5).",
        )
        download.add_argument(
            "--allow-any-host",
            action="store_true",
            default=None,
            help="Permite URLs de hosts distintos de Google Drive.",
        )

        status = subparsers.add_parser(
            "status",
            help="Muestra el estado de la sesión y de yt-dlp.",
        )
        status.add_argument(
            "--json",
            action="store_true",
            help="Salida en JSON.",
        )

        doctor = subparsers.add_parser(
            "doctor",
            help="Diagnostica dependencias, sesión y permisos.",
        )
        doctor.add_argument(
            "--json",
            action="store_true",
            help="Salida en JSON.",
        )

        api = subparsers.add_parser(
            "api",
            help="Levanta la API HTTP local.",
        )
        api.add_argument(
            "--host",
            default=None,
            help="Interfaz de escucha (por defecto 127.0.0.1).",
        )
        api.add_argument(
            "--port",
            type=int,
            default=None,
            help="Puerto de escucha (por defecto 8000).",
        )

        return parser


class CliOverridesFactory:
    def from_namespace(self, namespace: argparse.Namespace) -> ConfigOverrides:
        command = namespace.command
        return ConfigOverrides(
            profile_dir=getattr(namespace, "profile_dir", None),
            output_dir=(
                getattr(namespace, "output_dir", None)
                if command == "download"
                else None
            ),
            login_timeout_seconds=(
                getattr(namespace, "timeout", None)
                if command == "login"
                else None
            ),
            download_timeout_seconds=(
                getattr(namespace, "timeout", None)
                if command == "download"
                else None
            ),
            retries=(
                getattr(namespace, "retries", None)
                if command == "download"
                else None
            ),
            allow_any_host=(
                getattr(namespace, "allow_any_host", None)
                if command == "download"
                else None
            ),
            api_host=(
                getattr(namespace, "host", None) if command == "api" else None
            ),
            api_port=(
                getattr(namespace, "port", None) if command == "api" else None
            ),
            log_level=getattr(namespace, "log_level", None),
            verbose=bool(getattr(namespace, "verbose", False)),
        )


class CliCommand(ABC):
    @abstractmethod
    def execute(self) -> ExitCode:
        raise NotImplementedError


class LoginCommand(CliCommand):
    def __init__(
        self,
        service: LoginService,
        presenter: ConsolePresenter,
    ) -> None:
        self._service = service
        self._presenter = presenter

    def execute(self) -> ExitCode:
        self._presenter.info(
            "Se abrirá Chrome. Si ya está abierto con este perfil, ciérralo antes. "
            "Inicia sesión y cierra todas sus ventanas al terminar."
        )
        status = self._service.login()
        self._presenter.login_success(status)
        return ExitCode.OK


class DownloadCommand(CliCommand):
    def __init__(
        self,
        service: DownloadService,
        presenter: ConsolePresenter,
        url: str,
    ) -> None:
        self._service = service
        self._presenter = presenter
        self._url = url

    def execute(self) -> ExitCode:
        result = self._service.download(self._url)
        self._presenter.download_result(result)
        return ExitCode.OK


class StatusCommand(CliCommand):
    def __init__(
        self,
        service: StatusService,
        presenter: ConsolePresenter,
    ) -> None:
        self._service = service
        self._presenter = presenter

    def execute(self) -> ExitCode:
        snapshot = self._service.snapshot()
        self._presenter.system_status(snapshot)
        return ExitCode.OK


class DoctorCommand(CliCommand):
    def __init__(
        self,
        service: DoctorService,
        presenter: ConsolePresenter,
    ) -> None:
        self._service = service
        self._presenter = presenter

    def execute(self) -> ExitCode:
        report = self._service.run()
        self._presenter.doctor_report(report)
        return ExitCode.OK if report.healthy else ExitCode.FAILURE


class ApiCommand(CliCommand):
    def __init__(self, server: ApiServer, presenter: ConsolePresenter) -> None:
        self._server = server
        self._presenter = presenter

    def execute(self) -> ExitCode:
        self._presenter.info("Iniciando API...")
        self._server.run()
        return ExitCode.OK


class HelpCommand(CliCommand):
    def __init__(
        self,
        parser: argparse.ArgumentParser,
        presenter: ConsolePresenter,
    ) -> None:
        self._parser = parser
        self._presenter = presenter

    def execute(self) -> ExitCode:
        self._presenter.print_help(self._parser)
        return ExitCode.OK


class CommandFactory:
    def __init__(
        self,
        container: ServiceContainer,
        presenter: ConsolePresenter,
        config: AppConfig,
        container_factory: ContainerFactory,
        logger: logging.Logger,
        parser: argparse.ArgumentParser,
    ) -> None:
        self._container = container
        self._presenter = presenter
        self._config = config
        self._container_factory = container_factory
        self._logger = logger
        self._parser = parser

    def create(self, namespace: argparse.Namespace) -> CliCommand:
        command = namespace.command
        if command == "login":
            return LoginCommand(self._container.login_service, self._presenter)
        if command == "download":
            return DownloadCommand(
                self._container.download_service,
                self._presenter,
                namespace.url,
            )
        if command == "status":
            return StatusCommand(
                self._container.status_service,
                self._presenter,
            )
        if command == "doctor":
            return DoctorCommand(
                self._container.doctor_service,
                self._presenter,
            )
        if command == "api":
            return ApiCommand(
                ApiServer(self._config, self._container_factory, self._logger),
                self._presenter,
            )
        if command is None:
            return HelpCommand(self._parser, self._presenter)
        raise UsageError(f"Comando desconocido: {command}")


class ApplicationBootstrap:
    def __init__(
        self,
        base_dir: Path | None = None,
        environment: Mapping[str, str] | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self._base_dir = (
            base_dir if base_dir is not None else self._default_base_dir()
        )
        self._environment = environment
        self._stdout = stdout
        self._stderr = stderr

    @staticmethod
    def _default_base_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent

    def run(self, argv: Sequence[str] | None = None) -> ExitCode:
        parser = ArgumentParserFactory().create()
        presenter = ConsolePresenter(self._stdout, self._stderr)
        logger = logging.getLogger("gdrive_dl")
        configurator: LoggingConfigurator | None = None

        try:
            namespace = parser.parse_args(argv)
            presenter = ConsolePresenter(
                self._stdout,
                self._stderr,
                json_mode=bool(getattr(namespace, "json", False)),
            )
            if namespace.command is None:
                return HelpCommand(parser, presenter).execute()

            overrides = CliOverridesFactory().from_namespace(namespace)
            config = ConfigFactory(self._base_dir, self._environment).create(overrides)
            configurator = LoggingConfigurator(config)
            logger = configurator.configure()
            container_factory = ContainerFactory(config, logger, self._environment)
            container = container_factory.create(
                StreamProgressReporter(self._stderr if self._stderr is not None else sys.stderr)
            )
            command = CommandFactory(
                container,
                presenter,
                config,
                container_factory,
                logger,
                parser,
            ).create(namespace)
            return command.execute()
        except GdriveError as exc:
            presenter.error(exc)
            logger.debug("Error controlado", exc_info=True)
            return ExitCodeMapper.map(exc)
        except KeyboardInterrupt:
            presenter.warning("Interrumpido por el usuario.")
            return ExitCode.INTERRUPTED
        except SystemExit:
            raise
        except Exception:
            logger.exception("Error inesperado")
            presenter.unexpected_error()
            return ExitCode.FAILURE
        finally:
            if configurator is not None:
                configurator.close()


def main(argv: Sequence[str] | None = None) -> int:
    return int(ApplicationBootstrap().run(argv))
