# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve()
yt_dlp_binary = root / "yt-dlp.exe"

if not yt_dlp_binary.is_file():
    raise SystemExit(
        "yt-dlp.exe is missing. Run python scripts/build_exe.py instead of PyInstaller directly."
    )

hiddenimports = sorted(
    set(
        collect_submodules("fastapi")
        + collect_submodules("starlette")
        + collect_submodules("uvicorn")
    )
)

a = Analysis(
    [str(root / "gdrive-dl.py")],
    pathex=[str(root)],
    binaries=[(str(yt_dlp_binary), ".")],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="gdrive-dl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
