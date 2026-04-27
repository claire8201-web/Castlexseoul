# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['castlexseoul_v8.1.0.py'],
    pathex=[],
    binaries=[],
    datas=[('castlexseoul_v8.png', '.'), ('castlexseoul_v8.ico', '.')],
    hiddenimports=[],
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
    name='CastlexSeoul',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['castlexseoul_v8.ico'],
)
