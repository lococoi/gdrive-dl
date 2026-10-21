from __future__ import annotations

import sys
from typing import TextIO

from ..ports import ProgressReporter
from .text import AnsiStripper


class NullProgressReporter(ProgressReporter):
    @property
    def enabled(self) -> bool:
        return False

    def report(self, line: str) -> None:
        return None


class StreamProgressReporter(ProgressReporter):
    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    @property
    def enabled(self) -> bool:
        return True

    def report(self, line: str) -> None:
        cleaned = AnsiStripper.strip(line).rstrip("\r\n").strip()
        if not cleaned:
            return
        self._stream.write(f"{cleaned}\n")
        self._stream.flush()
