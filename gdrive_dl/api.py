import hmac
import logging
from typing import Any

from . import __version__
from .config import AppConfig
from .container import ContainerFactory, ServiceContainer
from .errors import (
    BrowserError,
    ConcurrencyLimitError,
    ConfigurationError,
    CookieDatabaseError,
    DependencyUnavailableError,
    DownloadError,
    DownloadTimeoutError,
    GdriveError,
    InvalidUrlError,
    LoginTimeoutError,
    LoginVerificationError,
    OutputDirectoryError,
    SessionExpiredError,
    SessionNotFoundError,
    ToolNotFoundError,
    UnsupportedUrlError,
)
from .infrastructure.progress import NullProgressReporter


class ApiErrorMapper:
    def map(self, exc: GdriveError) -> tuple[int, dict[str, Any]]:
        if isinstance(exc, (InvalidUrlError, UnsupportedUrlError)):
            status_code = 400
        elif isinstance(
            exc,
            (
                SessionNotFoundError,
                SessionExpiredError,
                LoginTimeoutError,
                LoginVerificationError,
                CookieDatabaseError,
                BrowserError,
            ),
        ):
            status_code = 409
        elif isinstance(exc, ConcurrencyLimitError):
            status_code = 429
        elif isinstance(exc, DownloadTimeoutError):
            status_code = 504
        elif isinstance(exc, (ToolNotFoundError, DependencyUnavailableError)):
            status_code = 503
        elif isinstance(exc, (DownloadError, OutputDirectoryError)):
            status_code = 502
        elif isinstance(exc, ConfigurationError):
            status_code = 500
        else:
            status_code = 500
        return status_code, {
            "error": str(exc),
            "code": exc.code,
            "hint": exc.hint,
            "retryable": exc.retryable,
        }


class ApiApplicationFactory:
    def create(self, container: ServiceContainer, config: AppConfig) -> Any:
        try:
            from fastapi import Depends, FastAPI, Header, HTTPException, Request
            from fastapi.exceptions import RequestValidationError
            from fastapi.responses import JSONResponse
            from pydantic import BaseModel, Field
            from starlette.exceptions import HTTPException as StarletteHTTPException
        except ImportError as exc:
            raise DependencyUnavailableError(
                "Faltan dependencias para la API.",
                hint="Instala FastAPI, Uvicorn y Pydantic con: pip install -r requirements.txt",
            ) from exc

        class DownloadRequest(BaseModel):
            url: str = Field(
                ...,
                min_length=1,
                max_length=4096,
                description="Enlace HTTPS de Google Drive.",
            )

        class DownloadResponse(BaseModel):
            success: bool
            status: str
            output_path: str | None
            attempts: int
            duration_seconds: float
            message: str

        class SessionResponse(BaseModel):
            available: bool
            profile_dir: str
            cookie_db: str | None
            google_auth_cookie_count: int
            reason: str | None

        class StatusResponse(BaseModel):
            app_version: str
            session: SessionResponse
            yt_dlp_available: bool
            yt_dlp_version: str | None

        error_mapper = ApiErrorMapper()

        def require_token(
            authorization: str | None = Header(default=None),
        ) -> None:
            if config.api_token is None:
                return
            expected = f"Bearer {config.api_token}"
            provided = authorization or ""
            if not hmac.compare_digest(
                provided.encode("utf-8"),
                expected.encode("utf-8"),
            ):
                raise HTTPException(
                    status_code=401,
                    detail="Token de API inválido o ausente.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        app = FastAPI(
            title="gdrive-dl API",
            version=__version__,
            description="Descarga archivos de Google Drive usando una sesión de Chrome.",
        )
        app.state.container = container

        @app.exception_handler(GdriveError)
        async def handle_gdrive_error(request: Request, exc: GdriveError) -> JSONResponse:
            status_code, payload = error_mapper.map(exc)
            return JSONResponse(status_code=status_code, content=payload)

        @app.exception_handler(StarletteHTTPException)
        async def handle_http_error(
            request: Request,
            exc: StarletteHTTPException,
        ) -> JSONResponse:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": str(exc.detail),
                    "code": "http_error",
                    "hint": None,
                    "retryable": False,
                },
            )

        @app.exception_handler(RequestValidationError)
        async def handle_validation_error(
            request: Request,
            exc: RequestValidationError,
        ) -> JSONResponse:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "La petición no es válida.",
                    "code": "validation_error",
                    "hint": "Revisa el campo 'url' y su longitud.",
                    "retryable": False,
                },
            )

        @app.exception_handler(Exception)
        async def handle_unexpected_error(
            request: Request,
            exc: Exception,
        ) -> JSONResponse:
            logging.getLogger("gdrive_dl").exception("Error inesperado en la API")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Error interno del servidor.",
                    "code": "internal_error",
                    "hint": None,
                    "retryable": False,
                },
            )

        @app.get("/healthz")
        def healthz() -> dict[str, str]:
            return {"status": "ok"}

        @app.get(
            "/status",
            response_model=StatusResponse,
            dependencies=[Depends(require_token)],
        )
        def status() -> StatusResponse:
            snapshot = container.status_service.snapshot()
            session = snapshot.session
            return StatusResponse(
                app_version=snapshot.app_version,
                session=SessionResponse(
                    available=session.available,
                    profile_dir=str(session.profile_dir),
                    cookie_db=str(session.cookie_db) if session.cookie_db else None,
                    google_auth_cookie_count=session.google_auth_cookie_count,
                    reason=session.reason,
                ),
                yt_dlp_available=snapshot.yt_dlp_available,
                yt_dlp_version=snapshot.yt_dlp_version,
            )

        @app.post(
            "/download",
            response_model=DownloadResponse,
            dependencies=[Depends(require_token)],
        )
        def download(payload: DownloadRequest) -> DownloadResponse:
            result = container.download_service.download(payload.url)
            return DownloadResponse(
                success=True,
                status=result.status.value,
                output_path=str(result.output_path) if result.output_path else None,
                attempts=result.attempts,
                duration_seconds=result.duration_seconds,
                message=result.message,
            )

        return app


class ApiServer:
    def __init__(
        self,
        config: AppConfig,
        container_factory: ContainerFactory,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._container_factory = container_factory
        self._logger = logger

    def run(self) -> None:
        try:
            import uvicorn
        except ImportError as exc:
            raise DependencyUnavailableError(
                "Faltan dependencias para la API.",
                hint="Instala FastAPI, Uvicorn y Pydantic con: pip install -r requirements.txt",
            ) from exc

        container = self._container_factory.create(NullProgressReporter())
        app = ApiApplicationFactory().create(container, self._config)

        if not AppConfig.is_loopback_host(self._config.api_host):
            self._logger.warning(
                "La API está expuesta en una interfaz no local: %s",
                self._config.api_host,
            )
        self._logger.info(
            "API escuchando en http://%s:%s%s",
            self._config.api_host,
            self._config.api_port,
            " (token requerido)" if self._config.api_token else "",
        )
        uvicorn.run(
            app,
            host=self._config.api_host,
            port=self._config.api_port,
            log_level=self._config.log_level.lower(),
            access_log=True,
        )
