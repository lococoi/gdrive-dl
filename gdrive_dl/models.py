from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Self
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .errors import InvalidUrlError, UnsupportedUrlError

_FOLDER_PATH = re.compile(r"^/drive/(?:u/\d+/)?folders/")
_FILE_PATH = re.compile(r"^/file/d/([^/]+)")


@dataclass(frozen=True, slots=True)
class DownloadUrl:
    value: str
    host: str

    MAX_LENGTH: ClassVar[int] = 4096

    @classmethod
    def parse(
        cls,
        raw: str,
        *,
        allowed_hosts: frozenset[str],
        allow_any_host: bool,
    ) -> Self:
        if not isinstance(raw, str):
            raise InvalidUrlError("La URL debe ser texto.")
        value = raw.strip()
        if not value:
            raise InvalidUrlError("La URL está vacía.")
        if len(value) > cls.MAX_LENGTH:
            raise InvalidUrlError(
                f"La URL supera el máximo de {cls.MAX_LENGTH} caracteres."
            )
        if value.startswith("-"):
            raise InvalidUrlError("La URL no puede comenzar con '-'.")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise InvalidUrlError("La URL contiene caracteres de control.")

        try:
            parts = urlsplit(value)
            port = parts.port
            host = parts.hostname
        except ValueError as exc:
            raise InvalidUrlError("La URL no tiene un formato válido.") from exc

        if parts.scheme.lower() != "https":
            raise InvalidUrlError(
                "Solo se permiten URLs HTTPS.",
                hint="Cambia http:// por https://.",
            )
        if parts.username is not None or parts.password is not None:
            raise InvalidUrlError("La URL no puede incluir credenciales.")
        if port not in (None, 443):
            raise InvalidUrlError("La URL no puede usar un puerto distinto de 443.")
        if not host:
            raise InvalidUrlError("La URL no incluye un host válido.")

        normalized_host = host.rstrip(".").lower()
        if not normalized_host:
            raise InvalidUrlError("La URL no incluye un host válido.")
        if normalized_host == "localhost" or normalized_host.endswith(
            (".localhost", ".local", ".internal", ".lan", ".home")
        ):
            raise InvalidUrlError("No se permiten hosts locales o privados.")

        try:
            address = ipaddress.ip_address(normalized_host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise InvalidUrlError("No se permiten direcciones IP privadas, locales o reservadas.")

        if not allow_any_host and normalized_host not in allowed_hosts:
            allowed = ", ".join(sorted(allowed_hosts))
            raise UnsupportedUrlError(
                f"El host '{normalized_host}' no está permitido.",
                hint=f"Hosts permitidos: {allowed}. Usa --allow-any-host para otros sitios.",
            )

        if normalized_host == "drive.google.com" and _FOLDER_PATH.match(parts.path):
            raise UnsupportedUrlError(
                "Las carpetas de Google Drive no se pueden descargar con yt-dlp.",
                hint="Abre el archivo y usa su enlace directo /file/d/<id>/view.",
            )

        return cls(value=value, host=normalized_host)

    @property
    def redacted(self) -> str:
        parts = urlsplit(self.value)
        query = "<redacted>" if parts.query else ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))

    @property
    def google_file_id(self) -> str | None:
        parts = urlsplit(self.value)
        match = _FILE_PATH.match(parts.path)
        if match:
            return match.group(1)
        identifiers = parse_qs(parts.query).get("id")
        if identifiers:
            return identifiers[0]
        return None

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SessionStatus:
    profile_dir: Path
    cookie_db: Path | None
    google_auth_cookie_count: int
    problem: str | None = None

    @property
    def available(self) -> bool:
        return (
            self.cookie_db is not None
            and self.google_auth_cookie_count > 0
            and self.problem is None
        )

    @property
    def reason(self) -> str | None:
        return self.problem


class DownloadStatus(str, Enum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class DownloadResult:
    status: DownloadStatus
    url: str
    output_path: Path | None
    attempts: int
    duration_seconds: float
    message: str


@dataclass(frozen=True, slots=True)
class SystemStatus:
    session: SessionStatus
    yt_dlp_available: bool
    yt_dlp_version: str | None
    app_version: str


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    healthy: bool
    detail: str
    critical: bool = True


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(check.healthy for check in self.checks if check.critical)

    @property
    def failed(self) -> tuple[DoctorCheck, ...]:
        return tuple(check for check in self.checks if not check.healthy)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
