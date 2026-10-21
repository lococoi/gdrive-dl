from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


class IconGenerator:
    SIZES = (
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    )

    def __init__(self, source: Path, target: Path) -> None:
        self._source = source
        self._target = target

    def generate(self) -> Path:
        if not self._source.is_file():
            raise FileNotFoundError(f"Logo not found: {self._source}")
        image = Image.open(self._source).convert("RGBA")
        self._target.parent.mkdir(parents=True, exist_ok=True)
        image.save(self._target, format="ICO", sizes=self.SIZES)
        return self._target


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    source = root / "assets" / "logo.png"
    target = root / "assets" / "logo.ico"
    try:
        generated = IconGenerator(source, target).generate()
    except (OSError, ValueError) as exc:
        print(f"Could not generate icon: {exc}", file=sys.stderr)
        return 1
    print(f"Generated: {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
