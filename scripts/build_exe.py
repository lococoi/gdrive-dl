from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_YT_DLP_URL = (
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
)


class BuildError(RuntimeError):
    pass


class YtDlpBinaryProvider:
    def __init__(self, root: Path, url: str) -> None:
        self._root = root
        self._url = url
        self._target = root / "yt-dlp.exe"

    def ensure(self) -> Path:
        if self._target.is_file():
            self._validate(self._target)
            return self._target

        temporary = self._target.with_name("yt-dlp.exe.download")
        print(f"Downloading yt-dlp from {self._url}")
        try:
            request = urllib.request.Request(
                self._url,
                headers={"User-Agent": "gdrive-dl-build"},
            )
            with urllib.request.urlopen(
                request,
                timeout=120,
            ) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            self._validate(temporary)
            temporary.replace(self._target)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise BuildError(f"Could not download yt-dlp: {exc}") from exc

        return self._target

    @staticmethod
    def _validate(path: Path) -> None:
        if path.stat().st_size < 1_000_000:
            raise BuildError(f"yt-dlp binary looks incomplete: {path}")
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise BuildError(f"yt-dlp is not a Windows executable: {path}")


class PyInstallerBuilder:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._spec = root / "gdrive-dl.spec"

    def build(self) -> Path:
        if not self._spec.is_file():
            raise BuildError(f"Missing PyInstaller spec: {self._spec}")

        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                str(self._spec),
            ],
            cwd=self._root,
            check=True,
        )

        executable = self._root / "dist" / (
            "gdrive-dl.exe" if os.name == "nt" else "gdrive-dl"
        )
        if not executable.is_file():
            raise BuildError(f"PyInstaller did not produce {executable}")
        return executable


class BuildApplication:
    def __init__(self, root: Path, yt_dlp_url: str) -> None:
        self._root = root
        self._yt_dlp_url = yt_dlp_url

    def run(self) -> Path:
        yt_dlp = YtDlpBinaryProvider(self._root, self._yt_dlp_url).ensure()
        print(f"Using yt-dlp: {yt_dlp} ({self._size(yt_dlp)})")
        executable = PyInstallerBuilder(self._root).build()
        print(f"Built: {executable} ({self._size(executable)})")
        return executable

    @staticmethod
    def _size(path: Path) -> str:
        return f"{path.stat().st_size / (1024 * 1024):.1f} MiB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a self-contained gdrive-dl executable for Windows."
    )
    parser.add_argument(
        "--yt-dlp-url",
        default=DEFAULT_YT_DLP_URL,
        help="URL used to download yt-dlp.exe when it is missing.",
    )
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        BuildApplication(root, arguments.yt_dlp_url).run()
    except (BuildError, subprocess.CalledProcessError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
