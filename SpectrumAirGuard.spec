# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_dir = Path(SPECPATH).resolve()
app_name = "SpectrumAirGuard"
block_cipher = None


datas = []
for folder_name in ("img", "audio"):
    folder_path = project_dir / folder_name
    if folder_path.exists():
        datas.append((str(folder_path), folder_name))

datas += collect_data_files("matplotlib")

hiddenimports = [
    "config",
    "core",
    "services",
    "widgets",
    "main_window",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.qt_compat",
    "matplotlib.backends.backend_agg",
    "PySide6.QtNetwork",
    "PySide6.QtPositioning",
]
hiddenimports += collect_submodules("matplotlib.backends")

icon_path = project_dir / "img" / "droneP.ico"
icon_arg = str(icon_path) if icon_path.exists() else None
version_file = project_dir / "installer" / "version_info.txt"
version_arg = str(version_file) if version_file.exists() else None


a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "qtpy", "kivy", "kivymd", "pygame"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
    version=version_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)


