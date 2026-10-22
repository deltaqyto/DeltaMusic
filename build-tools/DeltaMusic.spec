# PyInstaller spec for the player and the acquisition tool. Run build.bat, or `pyinstaller build-tools/DeltaMusic.spec`.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ONEFILE = os.environ.get("DELTAMUSIC_ONEFILE") == "1"

ICON_FILE = Path(SPECPATH) / "icon.ico"
ICON = str(ICON_FILE) if ICON_FILE.is_file() else None


def tree(source, destination):
    """Every file under source, mapped into destination, leaving out the bytecode caches a checkout accumulates."""
    return [(str(path), os.path.normpath(os.path.join(destination, path.relative_to(source).parent))) for path in source.rglob("*") if path.is_file() and "__pycache__" not in path.parts]


# Alembic compiles its environment and revisions from source at startup, so they ship as files rather than as modules.
DATAS = [(str(ROOT / "core" / "alembic.ini"), "core")]
DATAS += tree(ROOT / "core" / "library" / "migrations", "core/library/migrations")
DATAS += tree(ROOT / "frontends" / "qt" / "assets", "frontends/qt/assets")

HIDDEN = [
    # The acquisition backend is reached through import_module, so nothing points at it statically.
    "acquisition.backends.windows",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "alembic.ddl.sqlite",
    # qframelesswindow's native snap and resize go through pywin32.
    "win32api",
    "win32con",
    "win32gui",
    # The media session backend reaches WinRT through namespace packages and their extension modules.
    "winrt.runtime",
    "winrt.system",
    "winrt.windows.media.control",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt._winrt",
    "winrt._winrt_windows_media_control",
    "winrt._winrt_windows_foundation",
    "winrt._winrt_windows_foundation_collections",
]
# Reachable but never used, and they import packages that are not installed here.
UNUSED = ("ifaddr.test_ifaddr", "mutagen._tools")


def wanted(name):
    return not name.startswith(UNUSED)


# zeroconf and ifaddr pick platform modules at import time, and mutagen picks a format module per file.
HIDDEN += collect_submodules("zeroconf", filter=wanted)
HIDDEN += collect_submodules("ifaddr", filter=wanted)
HIDDEN += collect_submodules("mutagen", filter=wanted)

# Media.Control names Storage for session thumbnails, which nothing here reads, and installing it pulls in 79 projection packages.
EXCLUDES = ["winrt.windows.storage", "winrt.windows.storage.streams", "tkinter", "matplotlib", "pandas", "scipy", "pytest", "mypy", "numba", "Cython", "IPython", "sphinx", "PyInstaller"]


def analyse(script):
    return Analysis(
        [str(ROOT / "entry" / script)],
        pathex=[str(ROOT)],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
    )


player = analyse("main.py")
acquire = analyse("acquire.py")
player_pyz = PYZ(player.pure)
acquire_pyz = PYZ(acquire.pure)

if ONEFILE:
    player_exe = EXE(
        player_pyz,
        player.scripts,
        player.binaries,
        player.datas,
        [],
        name="DeltaMusic",
        console=False,
        icon=ICON,
        strip=False,
        upx=False,
    )
    acquire_exe = EXE(
        acquire_pyz,
        acquire.scripts,
        acquire.binaries,
        acquire.datas,
        [],
        name="DeltaMusicAcquire",
        console=True,
        icon=ICON,
        strip=False,
        upx=False,
    )
else:
    player_exe = EXE(
        player_pyz,
        player.scripts,
        [],
        exclude_binaries=True,
        name="DeltaMusic",
        console=False,
        icon=ICON,
        strip=False,
        upx=False,
    )
    acquire_exe = EXE(
        acquire_pyz,
        acquire.scripts,
        [],
        exclude_binaries=True,
        name="DeltaMusicAcquire",
        console=True,
        icon=ICON,
        strip=False,
        upx=False,
    )
    # Both executables share one folder, so Qt and the rest of the dependencies are collected once.
    COLLECT(
        player_exe,
        player.binaries,
        player.datas,
        acquire_exe,
        acquire.binaries,
        acquire.datas,
        strip=False,
        upx=False,
        name="DeltaMusic",
    )
