from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from gdrive_dl import __version__
from gdrive_dl.api import ApiApplicationFactory
from gdrive_dl.config import ConfigFactory
from gdrive_dl.container import ServiceContainer
from gdrive_dl.errors import InvalidUrlError
from gdrive_dl.models import (
    DownloadResult,
    DownloadStatus,
    SessionStatus,
    SystemStatus,
)

API_TESTABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)


@unittest.skipUnless(API_TESTABLE, "fastapi/httpx no están instalados")
class ApiTests(unittest.TestCase):
    def make_app(
        self,
        *,
        token: str | None = None,
        download_error: Exception | None = None,
    ):
        from fastapi.testclient import TestClient

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        environment = {"GDRIVE_API_TOKEN": token} if token else {}
        config = ConfigFactory(base, environment=environment).create()

        class FakeDownloadService:
            def download(self, url: str) -> DownloadResult:
                if download_error is not None:
                    raise download_error
                return DownloadResult(
                    status=DownloadStatus.DOWNLOADED,
                    url=url,
                    output_path=base / "video.mp4",
                    attempts=1,
                    duration_seconds=1.0,
                    message="ok",
                )

        class FakeStatusService:
            def snapshot(self) -> SystemStatus:
                return SystemStatus(
                    session=SessionStatus(
                        profile_dir=config.profile_dir,
                        cookie_db=None,
                        google_auth_cookie_count=0,
                        problem="sin sesión",
                    ),
                    yt_dlp_available=True,
                    yt_dlp_version="2026.08.19",
                    app_version=__version__,
                )

        container = ServiceContainer(
            config=config,
            login_service=None,
            download_service=FakeDownloadService(),
            status_service=FakeStatusService(),
            doctor_service=None,
        )
        app = ApiApplicationFactory().create(container, config)
        return TestClient(app)

    def test_health_endpoint(self) -> None:
        client = self.make_app()
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_status_endpoint(self) -> None:
        client = self.make_app()
        response = client.get("/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["yt_dlp_version"], "2026.08.19")
        self.assertFalse(payload["session"]["available"])

    def test_download_endpoint(self) -> None:
        client = self.make_app()
        response = client.post(
            "/download",
            json={"url": "https://drive.google.com/file/d/abc/view"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status"], "downloaded")

    def test_download_error_mapping(self) -> None:
        client = self.make_app(download_error=InvalidUrlError("URL inválida"))
        response = client.post(
            "/download",
            json={"url": "https://drive.google.com/file/d/abc/view"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_url")

    def test_bearer_token_is_required(self) -> None:
        client = self.make_app(token="x" * 32)
        unauthenticated = client.get("/status")
        self.assertEqual(unauthenticated.status_code, 401)
        authenticated = client.get(
            "/status",
            headers={"Authorization": f"Bearer {'x' * 32}"},
        )
        self.assertEqual(authenticated.status_code, 200)


if __name__ == "__main__":
    unittest.main()
