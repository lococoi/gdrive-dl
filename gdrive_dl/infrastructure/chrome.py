from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from ..errors import (
    BrowserError,
    CookieDatabaseError,
    LoginTimeoutError,
    ProcessTimeoutError,
    ToolNotFoundError,
)
from ..models import SessionStatus
from ..ports import Authenticator, CookieInspector, ProcessRunner, SessionRepository


class ChromeLocator:
    def __init__(
        self,
        configured: Path | None,
        base_dir: Path,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._configured = configured
        self._base_dir = base_dir
        self._environment = dict(environment if environment is not None else os.environ)

    def resolve(self) -> Path:
        candidates: list[Path] = []
        if self._configured is not None:
            configured = self._configured.expanduser()
            if not configured.is_absolute():
                configured = self._base_dir / configured
            candidates.append(configured)

        for variable in ("CHROME_PATH", "GOOGLE_CHROME_PATH"):
            configured_path = self._environment.get(variable)
            if configured_path:
                candidates.append(Path(configured_path).expanduser())

        for executable in (
            "chrome.exe",
            "chrome",
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ):
            found = shutil.which(executable)
            if found:
                candidates.append(Path(found))

        if os.name == "nt":
            for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                root = self._environment.get(variable)
                if root:
                    candidates.append(
                        Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
                    )
        elif sys.platform == "darwin":
            candidates.append(
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            )
        else:
            candidates.extend(
                Path(path)
                for path in (
                    "/usr/bin/google-chrome",
                    "/usr/bin/google-chrome-stable",
                    "/usr/bin/chromium",
                    "/usr/bin/chromium-browser",
                )
            )

        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue

        raise ToolNotFoundError(
            "No se encontró Google Chrome.",
            hint="Instala Chrome o define GDRIVE_CHROME con la ruta al ejecutable.",
        )

    def is_available(self) -> bool:
        try:
            self.resolve()
        except ToolNotFoundError:
            return False
        return True


class SqliteCookieInspector(CookieInspector):
    GOOGLE_AUTH_COOKIE_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "SID",
            "HSID",
            "SSID",
            "APISID",
            "SAPISID",
            "__Secure-1PSID",
            "__Secure-3PSID",
            "__Secure-1PAPISID",
            "__Secure-3PAPISID",
        }
    )

    def count_google_auth_cookies(self, db_path: Path) -> int:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"file:{db_path.as_posix()}?mode=ro",
                uri=True,
                timeout=2.0,
            )
            names = tuple(sorted(self.GOOGLE_AUTH_COOKIE_NAMES))
            placeholders = ",".join("?" for _ in names)
            row = connection.execute(
                f"SELECT COUNT(*) FROM cookies "
                f"WHERE name IN ({placeholders}) AND host_key LIKE ?",
                (*names, "%google.com"),
            ).fetchone()
            return int(row[0]) if row is not None else 0
        except sqlite3.Error as exc:
            raise CookieDatabaseError(
                "No se pudo leer la base de cookies de Chrome.",
                hint="Cierra Chrome y vuelve a ejecutar el login.",
            ) from exc
        finally:
            if connection is not None:
                connection.close()


class ChromeProfileRepository(SessionRepository):
    def __init__(
        self,
        profile_dir: Path,
        inspector: CookieInspector,
        logger: logging.Logger,
    ) -> None:
        self._profile_dir = profile_dir
        self._inspector = inspector
        self._logger = logger

    @property
    def profile_dir(self) -> Path:
        return self._profile_dir

    def inspect(self) -> SessionStatus:
        try:
            if not self._profile_dir.exists():
                return SessionStatus(
                    profile_dir=self._profile_dir,
                    cookie_db=None,
                    google_auth_cookie_count=0,
                    problem="No existe el perfil de Chrome. Ejecuta 'login' primero.",
                )
            if not self._profile_dir.is_dir():
                return SessionStatus(
                    profile_dir=self._profile_dir,
                    cookie_db=None,
                    google_auth_cookie_count=0,
                    problem=f"El perfil de Chrome no es un directorio: {self._profile_dir}",
                )
        except OSError as exc:
            return SessionStatus(
                profile_dir=self._profile_dir,
                cookie_db=None,
                google_auth_cookie_count=0,
                problem=f"No se pudo acceder al perfil de Chrome: {exc}",
            )

        cookie_db = self._find_cookie_db()
        if cookie_db is None:
            return SessionStatus(
                profile_dir=self._profile_dir,
                cookie_db=None,
                google_auth_cookie_count=0,
                problem="No se encontró la base de cookies de Chrome. Ejecuta 'login'.",
            )

        try:
            count = self._inspector.count_google_auth_cookies(cookie_db)
        except CookieDatabaseError as exc:
            self._logger.warning("No se pudo inspeccionar la base de cookies: %s", exc)
            return SessionStatus(
                profile_dir=self._profile_dir,
                cookie_db=cookie_db,
                google_auth_cookie_count=0,
                problem=str(exc),
            )

        problem = None
        if count == 0:
            problem = (
                "No hay cookies de autenticación de Google en el perfil. "
                "Ejecuta 'login' y asegúrate de completar el inicio de sesión."
            )

        return SessionStatus(
            profile_dir=self._profile_dir,
            cookie_db=cookie_db,
            google_auth_cookie_count=count,
            problem=problem,
        )

    def _find_cookie_db(self) -> Path | None:
        candidates = (
            self._profile_dir / "Default" / "Network" / "Cookies",
            self._profile_dir / "Default" / "Cookies",
            self._profile_dir / "Network" / "Cookies",
            self._profile_dir / "Cookies",
        )
        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
            except OSError:
                continue
        return None


class ChromeProcessAuthenticator(Authenticator):
    def __init__(
        self,
        locator: ChromeLocator,
        runner: ProcessRunner,
        logger: logging.Logger,
    ) -> None:
        self._locator = locator
        self._runner = runner
        self._logger = logger

    def authenticate(self, profile_dir: Path, timeout_seconds: float) -> None:
        chrome = self._locator.resolve()
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BrowserError(
                f"No se pudo crear el perfil de Chrome: {profile_dir}",
                hint=str(exc),
            ) from exc
        if not profile_dir.is_dir():
            raise BrowserError(f"El perfil de Chrome no es un directorio: {profile_dir}")

        self._logger.info("Abriendo Chrome con el perfil aislado: %s", profile_dir)
        argv = (
            str(chrome),
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://accounts.google.com/",
        )
        try:
            result = self._runner.run(
                argv,
                timeout=timeout_seconds,
                capture=False,
            )
        except ProcessTimeoutError as exc:
            raise LoginTimeoutError(
                f"Chrome sigue abierto después de {timeout_seconds:.0f} segundos.",
                hint="Cierra la ventana de Chrome e inténtalo de nuevo.",
            ) from exc

        if result.returncode != 0:
            self._logger.warning(
                "Chrome terminó con código %s; se verificará la sesión de todos modos.",
                result.returncode,
            )
