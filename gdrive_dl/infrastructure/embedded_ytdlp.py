from __future__ import annotations

import sys


class EmbeddedYtDlp:
    COMMAND = "__yt-dlp"

    @classmethod
    def is_invocation(cls, argv: list[str]) -> bool:
        return len(argv) > 1 and argv[1] == cls.COMMAND

    def run(self, argv: list[str]) -> int:
        try:
            from yt_dlp import main as yt_dlp_main
        except ImportError as exc:
            print(
                f"The embedded yt-dlp package is not available in this build: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            result = yt_dlp_main(argv)
            return int(result or 0)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            return int(code) if isinstance(code, int) else 1
