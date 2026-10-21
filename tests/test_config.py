from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gdrive_dl.config import ConfigFactory, ConfigOverrides
from gdrive_dl.errors import ConfigurationError


class ConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = ConfigFactory(base, environment={}).create()
            self.assertEqual(config.profile_dir, (base / "chrome_profile").resolve())
            self.assertEqual(config.output_dir, (base / "downloads").resolve())
            self.assertEqual(config.api_host, "127.0.0.1")
            self.assertEqual(config.api_port, 8000)
            self.assertEqual(config.retries, 2)
            self.assertIn("drive.google.com", config.allowed_hosts)

    def test_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = ConfigFactory(
                base,
                environment={
                    "GDRIVE_RETRIES": "4",
                    "GDRIVE_API_PORT": "9100",
                    "GDRIVE_DOWNLOAD_TIMEOUT": "120",
                    "GDRIVE_ALLOW_ANY_HOST": "true",
                    "GDRIVE_LOG_LEVEL": "warning",
                },
            ).create()
            self.assertEqual(config.retries, 4)
            self.assertEqual(config.api_port, 9100)
            self.assertEqual(config.download_timeout_seconds, 120.0)
            self.assertTrue(config.allow_any_host)
            self.assertEqual(config.log_level, "WARNING")

    def test_cli_overrides_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "custom"
            config = ConfigFactory(
                base,
                environment={"GDRIVE_RETRIES": "4"},
            ).create(ConfigOverrides(retries=1, output_dir=output, verbose=True))
            self.assertEqual(config.retries, 1)
            self.assertEqual(config.output_dir, output.resolve())
            self.assertEqual(config.log_level, "DEBUG")

    def test_invalid_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(
            ConfigurationError
        ):
            ConfigFactory(
                Path(temporary),
                environment={"GDRIVE_ALLOW_ANY_HOST": "maybe"},
            ).create()

    def test_non_loopback_api_requires_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(
            ConfigurationError
        ):
            ConfigFactory(
                Path(temporary),
                environment={"GDRIVE_API_HOST": "0.0.0.0"},
            ).create()

    def test_non_loopback_api_with_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = ConfigFactory(
                Path(temporary),
                environment={
                    "GDRIVE_API_HOST": "0.0.0.0",
                    "GDRIVE_API_TOKEN": "x" * 32,
                },
            ).create()
            self.assertEqual(config.api_host, "0.0.0.0")
            self.assertEqual(config.api_token, "x" * 32)

    def test_short_api_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(
            ConfigurationError
        ):
            ConfigFactory(
                Path(temporary),
                environment={"GDRIVE_API_TOKEN": "short"},
            ).create()

    def test_nested_directories_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaises(ConfigurationError):
                ConfigFactory(base, environment={}).create(
                    ConfigOverrides(
                        profile_dir=base / "downloads" / "profile",
                        output_dir=base / "downloads",
                    )
                )

    def test_invalid_timeout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(
            ConfigurationError
        ):
            ConfigFactory(Path(temporary), environment={}).create(
                ConfigOverrides(download_timeout_seconds=1)
            )


if __name__ == "__main__":
    unittest.main()
