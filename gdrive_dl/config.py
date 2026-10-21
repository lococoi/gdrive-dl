from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from .errors import ConfigurationError

_DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "drive.google.com",
        "docs.google.com",
        "drive.usercontent.google.com",
    }
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    base_dir: Path
    profile_dir: Path
    output_dir: Path
    yt_dlp_command: tuple[str, ...] | None = None
    chrome_path: Path | None = None
    login_timeout_seconds: float = 900.0
    download_timeout_seconds: float = 3600.0
    max_concurrent_downloads: int = 2
    retries: int = 2
    retry_backoff_seconds: float = 2.0
    allowed_hosts: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_ALLOWED_HOSTS
    )
    allow_any_host: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_token: str | None = field(default=None, repr=False)
    log_level: str = "INFO"

    VALID_LOG_LEVELS: ClassVar[frozenset[str]] = frozenset(
        {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    )

    def __post_init__(self) -> None:
        base_dir = self.base_dir.expanduser().resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            raise ConfigurationError(f"El directorio base no existe: {base_dir}")

        profile_dir = self._resolve_path(self.profile_dir, base_dir)
        output_dir = self._resolve_path(self.output_dir, base_dir)

        if profile_dir.exists() and not profile_dir.is_dir():
            raise ConfigurationError(f"El perfil de Chrome no es un directorio: {profile_dir}")
        if output_dir.exists() and not output_dir.is_dir():
            raise ConfigurationError(f"La carpeta de descargas no es un directorio: {output_dir}")
        if (
            profile_dir == output_dir
            or profile_dir.is_relative_to(output_dir)
            or output_dir.is_relative_to(profile_dir)
        ):
            raise ConfigurationError(
                "El perfil de Chrome y la carpeta de descargas no pueden estar anidados."
            )

        if not 10.0 <= self.login_timeout_seconds <= 7200.0:
            raise ConfigurationError("login_timeout_seconds debe estar entre 10 y 7200.")
        if not 10.0 <= self.download_timeout_seconds <= 86400.0:
            raise ConfigurationError("download_timeout_seconds debe estar entre 10 y 86400.")
        if not 1 <= self.max_concurrent_downloads <= 8:
            raise ConfigurationError("max_concurrent_downloads debe estar entre 1 y 8.")
        if not 0 <= self.retries <= 5:
            raise ConfigurationError("retries debe estar entre 0 y 5.")
        if not 0.1 <= self.retry_backoff_seconds <= 60.0:
            raise ConfigurationError("retry_backoff_seconds debe estar entre 0.1 y 60.")

        api_host = self.api_host.strip()
        if not api_host or any(character.isspace() for character in api_host):
            raise ConfigurationError("api_host no es válido.")
        if not 1 <= self.api_port <= 65535:
            raise ConfigurationError("api_port debe estar entre 1 y 65535.")

        token = self.api_token.strip() if self.api_token is not None else None
        if token == "":
            token = None
        if token is not None and len(token) < 16:
            raise ConfigurationError(
                "GDRIVE_API_TOKEN debe tener al menos 16 caracteres.",
                hint="Genera uno con: python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
            )
        if token is None and not self.is_loopback_host(api_host):
            raise ConfigurationError(
                "La API no puede escuchar en una interfaz no local sin GDRIVE_API_TOKEN.",
                hint="Usa 127.0.0.1 o define un token de al menos 16 caracteres.",
            )

        allowed_hosts = frozenset(
            host.strip().lower()
            for host in self.allowed_hosts
            if host and host.strip()
        )
        if not self.allow_any_host and not allowed_hosts:
            raise ConfigurationError("Debes permitir al menos un host o activar allow_any_host.")

        log_level = self.log_level.strip().upper()
        if log_level not in self.VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"Nivel de log inválido: {self.log_level}",
                hint=f"Valores válidos: {', '.join(sorted(self.VALID_LOG_LEVELS))}",
            )

        command = self.yt_dlp_command
        if command is not None:
            command = tuple(str(part) for part in command)
            if not command or any(not part for part in command):
                raise ConfigurationError("yt_dlp_command no puede estar vacío.")

        chrome_path = self.chrome_path
        if chrome_path is not None:
            chrome_path = self._resolve_path(chrome_path, base_dir)
            if not chrome_path.is_file():
                raise ConfigurationError(f"No se encontró Chrome en: {chrome_path}")

        object.__setattr__(self, "base_dir", base_dir)
        object.__setattr__(self, "profile_dir", profile_dir)
        object.__setattr__(self, "output_dir", output_dir)
        object.__setattr__(self, "api_host", api_host)
        object.__setattr__(self, "api_token", token)
        object.__setattr__(self, "allowed_hosts", allowed_hosts)
        object.__setattr__(self, "log_level", log_level)
        object.__setattr__(self, "yt_dlp_command", command)
        object.__setattr__(self, "chrome_path", chrome_path)

    @staticmethod
    def is_loopback_host(host: str) -> bool:
        normalized = host.strip().lower()
        if normalized in {"localhost", "localhost.localdomain"}:
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _resolve_path(path: Path, base_dir: Path) -> Path:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = base_dir / expanded
        return expanded.resolve()


@dataclass(frozen=True, slots=True)
class ConfigOverrides:
    profile_dir: Path | None = None
    output_dir: Path | None = None
    yt_dlp_command: tuple[str, ...] | None = None
    chrome_path: Path | None = None
    login_timeout_seconds: float | None = None
    download_timeout_seconds: float | None = None
    max_concurrent_downloads: int | None = None
    retries: int | None = None
    allow_any_host: bool | None = None
    api_host: str | None = None
    api_port: int | None = None
    log_level: str | None = None
    verbose: bool = False


class EnvironmentReader:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def optional(self, name: str) -> str | None:
        value = self._values.get(name)
        if value is None:
            return None
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()
        return value or None

    def boolean(self, name: str, default: bool) -> bool:
        value = self.optional(name)
        if value is None:
            return default
        normalized = value.lower()
        if normalized in {"1", "true", "yes", "on", "si", "sí", "verdadero"}:
            return True
        if normalized in {"0", "false", "no", "off", "falso"}:
            return False
        raise ConfigurationError(
            f"{name} debe ser un booleano (true/false, 1/0, si/no)."
        )

    def integer(self, name: str, default: int) -> int:
        value = self.optional(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError as exc:
            raise ConfigurationError(f"{name} debe ser un entero.") from exc

    def decimal(self, name: str, default: float) -> float:
        value = self.optional(name)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError as exc:
            raise ConfigurationError(f"{name} debe ser un número.") from exc

    def path(self, name: str, base_dir: Path) -> Path | None:
        value = self.optional(name)
        if value is None:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()


class ConfigFactory:
    def __init__(
        self,
        base_dir: Path,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._base_dir = base_dir.expanduser().resolve()
        self._environment = EnvironmentReader(
            environment if environment is not None else os.environ
        )

    def create(self, overrides: ConfigOverrides | None = None) -> AppConfig:
        overrides = overrides or ConfigOverrides()
        reader = self._environment
        base_dir = self._base_dir

        profile_dir = (
            overrides.profile_dir
            or reader.path("GDRIVE_PROFILE_DIR", base_dir)
            or base_dir / "chrome_profile"
        )
        output_dir = (
            overrides.output_dir
            or reader.path("GDRIVE_OUTPUT_DIR", base_dir)
            or base_dir / "downloads"
        )

        yt_dlp_command = overrides.yt_dlp_command
        if yt_dlp_command is None:
            configured_yt_dlp = reader.optional("GDRIVE_YTDLP")
            if configured_yt_dlp is not None:
                candidate = Path(configured_yt_dlp).expanduser()
                looks_like_path = (
                    candidate.is_absolute()
                    or "/" in configured_yt_dlp
                    or "\\" in configured_yt_dlp
                    or candidate.suffix.lower() == ".exe"
                )
                if looks_like_path:
                    if not candidate.is_absolute():
                        candidate = base_dir / candidate
                    yt_dlp_command = (str(candidate.resolve()),)
                else:
                    yt_dlp_command = (configured_yt_dlp,)

        chrome_path = overrides.chrome_path or reader.path("GDRIVE_CHROME", base_dir)

        allowed_hosts_env = reader.optional("GDRIVE_ALLOWED_HOSTS")
        if allowed_hosts_env is None:
            allowed_hosts = _DEFAULT_ALLOWED_HOSTS
        else:
            allowed_hosts = frozenset(
                host.strip().lower()
                for host in allowed_hosts_env.split(",")
                if host.strip()
            )

        log_level = overrides.log_level or reader.optional("GDRIVE_LOG_LEVEL") or "INFO"
        if overrides.verbose:
            log_level = "DEBUG"

        return AppConfig(
            base_dir=base_dir,
            profile_dir=profile_dir,
            output_dir=output_dir,
            yt_dlp_command=yt_dlp_command,
            chrome_path=chrome_path,
            login_timeout_seconds=(
                overrides.login_timeout_seconds
                if overrides.login_timeout_seconds is not None
                else reader.decimal("GDRIVE_LOGIN_TIMEOUT", 900.0)
            ),
            download_timeout_seconds=(
                overrides.download_timeout_seconds
                if overrides.download_timeout_seconds is not None
                else reader.decimal("GDRIVE_DOWNLOAD_TIMEOUT", 3600.0)
            ),
            max_concurrent_downloads=(
                overrides.max_concurrent_downloads
                if overrides.max_concurrent_downloads is not None
                else reader.integer("GDRIVE_MAX_CONCURRENT", 2)
            ),
            retries=(
                overrides.retries
                if overrides.retries is not None
                else reader.integer("GDRIVE_RETRIES", 2)
            ),
            retry_backoff_seconds=reader.decimal("GDRIVE_RETRY_BACKOFF", 2.0),
            allowed_hosts=allowed_hosts,
            allow_any_host=(
                overrides.allow_any_host
                if overrides.allow_any_host is not None
                else reader.boolean("GDRIVE_ALLOW_ANY_HOST", False)
            ),
            api_host=overrides.api_host or reader.optional("GDRIVE_API_HOST") or "127.0.0.1",
            api_port=(
                overrides.api_port
                if overrides.api_port is not None
                else reader.integer("GDRIVE_API_PORT", 8000)
            ),
            api_token=reader.optional("GDRIVE_API_TOKEN"),
            log_level=log_level,
        )
