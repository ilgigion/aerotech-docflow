# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).resolve().parent
updater_exe = project_root / "build" / "updater-dist" / "AerotechUpdater.exe"
if not updater_exe.is_file():
    raise SystemExit(f"Build AerotechUpdater.exe first: {updater_exe}")

a = Analysis(
    [str(project_root / "updater" / "setup.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(updater_exe), ".")],
    hiddenimports=collect_submodules("updater"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["app", "tests"],
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
    name="AerotechUpdaterSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    uac_admin=True,
)
