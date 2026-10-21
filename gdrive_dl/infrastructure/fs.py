from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..errors import OutputDirectoryError
from ..ports import DirectoryPreparer


class OutputDirectory(DirectoryPreparer):
    def prepare(self, path: Path) -> Path:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OutputDirectoryError(
                f"No se pudo crear la carpeta de descargas: {path}",
                hint=str(exc),
            ) from exc

        if not path.is_dir():
            raise OutputDirectoryError(f"La ruta de descargas no es un directorio: {path}")

        descriptor: int | None = None
        temporary_name: str | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".gdrive-write-test-",
                dir=path,
            )
            os.close(descriptor)
            descriptor = None
            os.unlink(temporary_name)
            temporary_name = None
        except OSError as exc:
            raise OutputDirectoryError(
                f"La carpeta de descargas no es escribible: {path}",
                hint=str(exc),
            ) from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

        return path
