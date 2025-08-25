# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[
    	('dependencies/bin/HE3DTB.dll', '.'),
    	('dependencies/bin/Newtonsoft.Json.dll', '.'),
    ],
    datas=[
    ('dependencies/1 输入参数表', 'dependencies/1 输入参数表'),
    ('dependencies/application', 'dependencies/application'),
    ('dependencies/中间数据', 'dependencies/中间数据'),
],

    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # 设置为 True 可开启终端调试
    icon=None
)
