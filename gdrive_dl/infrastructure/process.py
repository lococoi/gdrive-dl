from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO

from ..errors import ProcessError, ProcessTimeoutError, ToolNotFoundError
from ..models import ProcessResult
from ..ports import ProcessRunner, Sleeper


class TailBuffer:
    def __init__(self, max_chars: int = 200_000) -> None:
        self._max_chars = max_chars
        self._chunks: deque[str] = deque()
        self._size = 0

    def append(self, text: str) -> None:
        if not text:
            return
        if len(text) > self._max_chars:
            text = text[-self._max_chars :]
        self._chunks.append(text)
        self._size += len(text)
        while self._size > self._max_chars and len(self._chunks) > 1:
            removed = self._chunks.popleft()
            self._size -= len(removed)

    def getvalue(self) -> str:
        return "".join(self._chunks)


class SystemSleeper(Sleeper):
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class SubprocessRunner(ProcessRunner):
    def __init__(
        self,
        logger: logging.Logger,
        *,
        max_capture_chars: int = 200_000,
        encoding: str = "utf-8",
    ) -> None:
        self._logger = logger
        self._max_capture_chars = max_capture_chars
        self._encoding = encoding

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None,
        capture: bool = True,
        stdout_handler: Callable[[str], None] | None = None,
        stderr_handler: Callable[[str], None] | None = None,
        cwd: Path | None = None,
    ) -> ProcessResult:
        command = tuple(str(part) for part in argv)
        if not command:
            raise ProcessError("No se puede ejecutar un comando vacío.")

        capture_output = capture or stdout_handler is not None or stderr_handler is not None
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
                stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
                text=True,
                encoding=self._encoding,
                errors="replace",
                bufsize=1,
                cwd=str(cwd) if cwd is not None else None,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except FileNotFoundError as exc:
            raise ToolNotFoundError(
                f"No se encontró el ejecutable: {command[0]}",
                hint="Verifica la ruta de yt-dlp o coloca yt-dlp.exe junto al script.",
            ) from exc
        except OSError as exc:
            raise ProcessError(
                f"No se pudo iniciar el proceso: {command[0]}",
                hint=str(exc),
            ) from exc

        stdout_buffer = TailBuffer(self._max_capture_chars)
        stderr_buffer = TailBuffer(self._max_capture_chars)
        threads: list[threading.Thread] = []
        if process.stdout is not None:
            threads.append(
                self._start_reader(process.stdout, stdout_buffer, stdout_handler, "stdout")
            )
        if process.stderr is not None:
            threads.append(
                self._start_reader(process.stderr, stderr_buffer, stderr_handler, "stderr")
            )

        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._terminate_tree(process)
            self._join_threads(threads)
            raise ProcessTimeoutError(
                f"El proceso excedió el tiempo límite de {(timeout or 0.0):.0f}s.",
                timeout_seconds=float(timeout or 0.0),
                stdout=stdout_buffer.getvalue(),
                stderr=stderr_buffer.getvalue(),
            ) from exc
        except KeyboardInterrupt:
            self._terminate_tree(process)
            self._join_threads(threads)
            raise

        self._join_threads(threads)
        return ProcessResult(
            returncode=returncode,
            stdout=stdout_buffer.getvalue(),
            stderr=stderr_buffer.getvalue(),
            duration_seconds=time.monotonic() - started,
        )

    def _start_reader(
        self,
        stream: IO[str],
        buffer: TailBuffer,
        handler: Callable[[str], None] | None,
        name: str,
    ) -> threading.Thread:
        def read_stream() -> None:
            try:
                for line in iter(stream.readline, ""):
                    buffer.append(line)
                    if handler is not None:
                        try:
                            handler(line)
                        except Exception:
                            self._logger.exception("Falló el manejador de salida de %s", name)
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        thread = threading.Thread(
            target=read_stream,
            name=f"gdrive-dl-{name}",
            daemon=True,
        )
        thread.start()
        return thread

    def _join_threads(self, threads: Sequence[threading.Thread]) -> None:
        for thread in threads:
            thread.join(timeout=5.0)
            if thread.is_alive():
                self._logger.warning("El hilo %s no terminó a tiempo", thread.name)

    def _terminate_tree(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.SubprocessError):
                pass
        else:
            getpgid = getattr(os, "getpgid", None)
            killpg = getattr(os, "killpg", None)
            if getpgid is not None and killpg is not None:
                try:
                    killpg(
                        getpgid(process.pid),
                        getattr(signal, "SIGKILL", signal.SIGTERM),
                    )
                except (OSError, ProcessLookupError):
                    pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
