# valg.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['valg/server.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'valg.plugins.geografi',
        'valg.plugins.kandidatdata_fv',
        'valg.plugins.partistemmer',
        'valg.plugins.valgdeltagelse',
        'valg.plugins.valgresultater_fv',
        'valg.queries',
        'valg.http_fetcher',
        'valg.differ',
        'valg.ai',
        'valg.calculator',
        'valg.processor',
        'valg.models',
        'valg.cli',
        'valg.fetcher',
        'flask',
        'werkzeug',
        'rich',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['paramiko', 'git'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='valg',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
