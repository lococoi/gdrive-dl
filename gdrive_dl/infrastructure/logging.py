from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from ..config import AppConfig


class LoggingConfigurator:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def configure(self) -> logging.Logger:
        logger = logging.getLogger("gdrive_dl")
        logger.setLevel(getattr(logging, self._config.log_level))
        logger.propagate = False

        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"
        )
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        logger.addHandler(console)

        log_dir = self._config.base_dir / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "gdrive-dl.log",
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("No se pudo crear el archivo de log en %s: %s", log_dir, exc)

        return logger

    @staticmethod
    def close() -> None:
        logger = logging.getLogger("gdrive_dl")
        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
