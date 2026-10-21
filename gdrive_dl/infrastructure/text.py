from __future__ import annotations

import re


class AnsiStripper:
    _PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    @classmethod
    def strip(cls, text: str) -> str:
        return cls._PATTERN.sub("", text)
