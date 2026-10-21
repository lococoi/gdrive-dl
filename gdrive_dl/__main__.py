from __future__ import annotations

import sys

from .infrastructure.embedded_ytdlp import EmbeddedYtDlp

if __name__ == "__main__":
    if EmbeddedYtDlp.is_invocation(sys.argv):
        raise SystemExit(EmbeddedYtDlp().run(sys.argv[2:]))

    from .cli import main

    raise SystemExit(main())
