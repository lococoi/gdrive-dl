from __future__ import annotations

import sys

from gdrive_dl.infrastructure.embedded_ytdlp import EmbeddedYtDlp

if __name__ == "__main__":
    if EmbeddedYtDlp.is_invocation(sys.argv):
        raise SystemExit(EmbeddedYtDlp().run(sys.argv[2:]))

    from gdrive_dl.cli import main

    raise SystemExit(main())
