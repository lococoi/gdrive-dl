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
    def __init__(self, root: Path, url: str, *, use_local: bool = False) -> None:
        self._url = url
        self._target = root / "yt-dlp.exe"
        self._use_local = use_local

    def ensure(self) -> Path:
        if self._use_local:
            if not self._target.is_file():
                raise BuildError(
                    "--use-local was requested, but yt-dlp.exe does not exist."
                )
            self._validate(self._target)
            return self._target

        temporary = self._target.with_name("yt-dlp.exe.download")
        print(f"Downloading the latest yt-dlp Windows build from {self._url}")
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
        except BuildError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise BuildError(f"Could not download yt-dlp: {exc}") from exc

        return self._target

    @staticmethod
    def version(path: Path) -> str:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return lines[-1] if lines else "unknown"

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
    def __init__(
        self,
        root: Path,
        yt_dlp_url: str,
        *,
        use_local_yt_dlp: bool = False,
    ) -> None:
        self._root = root
        self._yt_dlp_url = yt_dlp_url
        self._use_local_yt_dlp = use_local_yt_dlp

    def run(self) -> Path:
        provider = YtDlpBinaryProvider(
            self._root,
            self._yt_dlp_url,
            use_local=self._use_local_yt_dlp,
        )
        yt_dlp = provider.ensure()
        print(
            f"Using yt-dlp {provider.version(yt_dlp)}: "
            f"{yt_dlp} ({self._size(yt_dlp)})"
        )
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
        help=(
            "URL used to download the Windows yt-dlp build. "
            "Defaults to the latest official release."
        ),
    )
    parser.add_argument(
        "--use-local",
        action="store_true",
        help=(
            "Use an existing yt-dlp.exe instead of downloading the latest "
            "Windows build. Intended for offline builds."
        ),
    )
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        BuildApplication(
            root,
            arguments.yt_dlp_url,
            use_local_yt_dlp=arguments.use_local,
        ).run()
    except (BuildError, subprocess.CalledProcessError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
