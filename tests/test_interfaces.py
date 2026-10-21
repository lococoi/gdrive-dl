from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gdrive_dl import __version__
from gdrive_dl.api import ApiErrorMapper
from gdrive_dl.cli import (
    ApplicationBootstrap,
    ArgumentParserFactory,
    CliOverridesFactory,
    ExitCode,
)
from gdrive_dl.errors import (
    ConcurrencyLimitError,
    DownloadError,
    DownloadTimeoutError,
    InvalidUrlError,
    SessionNotFoundError,
    ToolNotFoundError,
)


class ApiErrorMapperTests(unittest.TestCase):
    def test_maps_errors_to_http_status(self) -> None:
        mapper = ApiErrorMapper()
        self.assertEqual(mapper.map(InvalidUrlError("x"))[0], 400)
        self.assertEqual(mapper.map(SessionNotFoundError("x"))[0], 409)
        self.assertEqual(mapper.map(ConcurrencyLimitError("x"))[0], 429)
        self.assertEqual(mapper.map(DownloadTimeoutError("x"))[0], 504)
        self.assertEqual(mapper.map(ToolNotFoundError("x"))[0], 503)
        self.assertEqual(mapper.map(DownloadError("x"))[0], 502)


class ArgumentParserTests(unittest.TestCase):
    def test_parses_download_options(self) -> None:
        parser = ArgumentParserFactory().create()
        namespace = parser.parse_args(
            [
                "--verbose",
                "download",
                "https://drive.google.com/file/d/abc/view",
                "--retries",
                "4",
                "--allow-any-host",
            ]
        )
        overrides = CliOverridesFactory().from_namespace(namespace)
        self.assertTrue(namespace.verbose)
        self.assertEqual(overrides.retries, 4)
        self.assertTrue(overrides.allow_any_host)

    def test_download_without_optional_flags(self) -> None:
        parser = ArgumentParserFactory().create()
        namespace = parser.parse_args(
            ["download", "https://drive.google.com/file/d/abc/view"]
        )
        overrides = CliOverridesFactory().from_namespace(namespace)
        self.assertIsNone(overrides.retries)
        self.assertIsNone(overrides.allow_any_host)


class ApplicationBootstrapTests(unittest.TestCase):
    def test_no_command_prints_help(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            stderr = io.StringIO()
            application = ApplicationBootstrap(
                base_dir=Path(temporary),
                environment={},
                stdout=stdout,
                stderr=stderr,
            )
            exit_code = application.run([])
            self.assertEqual(exit_code, ExitCode.OK)
            self.assertIn("usage:", stdout.getvalue())

    def test_status_with_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            stderr = io.StringIO()
            application = ApplicationBootstrap(
                base_dir=Path(temporary),
                environment={"GDRIVE_YTDLP": sys.executable},
                stdout=stdout,
                stderr=stderr,
            )
            exit_code = application.run(["status", "--json"])
            self.assertEqual(exit_code, ExitCode.OK)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["app_version"], __version__)
            self.assertFalse(payload["session"]["available"])

    def test_invalid_url_returns_usage_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            stderr = io.StringIO()
            application = ApplicationBootstrap(
                base_dir=Path(temporary),
                environment={"GDRIVE_YTDLP": sys.executable},
                stdout=stdout,
                stderr=stderr,
            )
            exit_code = application.run(["download", "not-a-url"])
            self.assertEqual(exit_code, ExitCode.USAGE)
            self.assertIn("ERROR", stderr.getvalue())

    def test_frozen_application_uses_executable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "gdrive-dl.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys,
                "executable",
                str(executable),
            ):
                self.assertEqual(
                    ApplicationBootstrap._default_base_dir(),
                    Path(temporary).resolve(),
                )


if __name__ == "__main__":
    unittest.main()
