# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve()

all_yt_dlp = collect_submodules("yt_dlp")
kept_extractors = {
    "yt_dlp.extractor.abc",
    "yt_dlp.extractor.adobepass",
    "yt_dlp.extractor.afreecatv",
    "yt_dlp.extractor.common",
    "yt_dlp.extractor.commonprotocols",
    "yt_dlp.extractor.extractors",
    "yt_dlp.extractor.generic",
    "yt_dlp.extractor.googledrive",
    "yt_dlp.extractor.googlesearch",
    "yt_dlp.extractor.lazy_extractors",
    "yt_dlp.extractor.openload",
    "yt_dlp.extractor.youtube",
}

def is_kept_extractor(module: str) -> bool:
    return module in kept_extractors or module.startswith("yt_dlp.extractor.youtube.")


hiddenimports = sorted(
    set(
        module
        for module in all_yt_dlp
        if not module.startswith("yt_dlp.extractor.")
        or is_kept_extractor(module)
    )
    | {
        "fastapi",
        "fastapi.exceptions",
        "fastapi.responses",
        "starlette.exceptions",
        "uvicorn",
        "yt_dlp",
    }
)

excludes = sorted(
    set(
        module
        for module in all_yt_dlp
        if module.startswith("yt_dlp.extractor.")
        and not is_kept_extractor(module)
    )
    | {
        "ast_serialize",
        "distutils",
        "email_validator",
        "fastapi.testclient",
        "httptools",
        "httpx",
        "httpcore",
        "mypy",
        "mypy_extensions",
        "pkg_resources",
        "pydantic.mypy",
        "setuptools",
        "uvicorn.workers",
        "uvloop",
        "watchfiles",
        "websockets",
        "wheel",
        "wsproto",
    }
)

a = Analysis(
    [str(root / "gdrive-dl.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
