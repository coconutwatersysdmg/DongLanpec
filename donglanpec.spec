# -*- mode: python ; coding: utf-8 -*-

import os
import shutil
from pathlib import Path

block_cipher = None

# 收集 PyQt5 运行库
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

# ---------- 预处理：准备 qt.conf 与 PyQt5 插件目录 ----------
# 固定一个可写的临时目录，避免“Could not create temporary directory!”
RUNTIME_TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "DongLanpec_temp")
os.makedirs(RUNTIME_TMP, exist_ok=True)

# 生成 qt.conf（必须在 Analysis 之前生成，这样能作为 datas 2元组加入）
qtconf_src = os.path.abspath("qt.conf")
if not os.path.exists(qtconf_src):
    with open(qtconf_src, "w", encoding="utf-8") as f:
        f.write("[Paths]\nPlugins = internal/PyQt5/Qt/plugins\n")

# 解析 PyQt5 插件目录（不依赖 collect_qt_plugins，手动兜底更稳定）
try:
    import PyQt5
    _pyqt_dir = os.path.dirname(PyQt5.__file__)
    _qt_plugins_dir = os.path.join(_pyqt_dir, "Qt", "plugins")
except Exception:
    _qt_plugins_dir = None

qt_plugin_subdirs = [
    "platforms", "imageformats", "styles", "iconengines",
    "platforminputcontexts", "audio", "printsupport"
]

qt_plugin_datas = []
if _qt_plugins_dir and os.path.isdir(_qt_plugins_dir):
    for sub in qt_plugin_subdirs:
        src_dir = os.path.join(_qt_plugins_dir, sub)
        if os.path.isdir(src_dir):
            # datas 里用 2元组 (src, dest)，由 Analysis 规范化
            qt_plugin_datas.append((src_dir, os.path.join("PyQt5", "Qt", "plugins", sub)))

# ---------- Analysis ----------
# Build statement evidence before code compilation, without importing main.py or
# requiring a running database. Only compressed metadata enters the data files.
import sys
if str(Path(SPECPATH)) not in sys.path:
    sys.path.insert(0, str(Path(SPECPATH)))
from modules.data_center.index_store import prepare_bundle
prepare_bundle(Path(SPECPATH))
a = Analysis(
    ['main.py'],
    pathex=[],
    # 自动收集 PyQt5 的 DLL（Qt5Core/Gui/Widgets 等）
    binaries=collect_dynamic_libs('PyQt5'),
    datas=[
        ('modules/data_center/flow_catalog.json.gz', 'modules/data_center'),
        # 你的原始静态资源
        ('main_viewer.ui', '.'),
        ('main_viewer333.ui', '.'),
        ('main_viewer333_new.ui', '.'),
        ('login.ui','.'),
        ('register.ui','.'),

        ('help.html', '.'),
        ('icons', 'icons'),
        ('modules\\condition_input\\viewer.ui', 'modules/condition_input'),
        ('modules\\condition_input\\viewer_new.ui', 'modules/condition_input'),
        ('modules\\condition_input\\mutigongkuang_new.ui', 'modules/condition_input'),

        ('modules\\condition_input\\mutigongkuang.ui', 'modules/condition_input'),
        ('modules\\guankoudingyi\\ui', 'modules/guankoudingyi/ui'),
        ('modules\\guankoudingyi\\table_template\\管口导出模板.xlsx', 'modules/guankoudingyi/table_template'),
        ('modules\\guankoudingyi\\table_template\\导出模板.xlsx', 'modules/guankoudingyi/table_template'),

        ('modules\\cailiaodingyi\\ui', 'modules/cailiaodingyi/ui'),
        ('modules\\cailiaodingyi\\img', 'modules/cailiaodingyi/img'),
        ('modules\\chanpinguanli\\gpt.ui', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\guanli.ui', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\guanli1.ui', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\guanli_nextbtn.ui', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\guanli_new.ui', 'modules/chanpinguanli'),

        ('modules\\chanpinguanli\\icons', 'modules/chanpinguanli/icons'),
        ('modules\\chanpinguanli\\附件3_产品示意图', 'modules/chanpinguanli/附件3_产品示意图'),
        ('modules\\chanpinguanli\\条件输入数据表.xlsx', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\管口导入模板.xlsx', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\容器管口导入模板.xlsx', 'modules/chanpinguanli'),
        ('modules\\chanpinguanli\\容器条件输入数据表.xlsx', 'modules/chanpinguanli'),

        ('modules\\wenbenshengcheng\\jisuanbaogao.xlsx', 'modules/wenbenshengcheng'),
        ('modules\\wenbenshengcheng\\U型管计算2.xlsx', 'modules/wenbenshengcheng'),
        ('modules/yudingyi/templates/predefined.html', 'modules/yudingyi/templates'),
        ('modules\\buguan\\buguan_ziyong\\static', 'modules/buguan/buguan_ziyong/static'),
        ('modules\\yudingyi\\encrypted_images', 'modules/yudingyi/encrypted_images'),

        ('mysql', 'mysql'),

        # [NEW] qt.conf 放根目录
        (qtconf_src, '.'),

        # [NEW] PyQt5 插件目录（platforms 等）
        *qt_plugin_datas,
    ],
    hiddenimports=collect_submodules('PyQt5') + ['PyQt5.sip', 'PyQt5.QtPrintSupport'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib.backends.backend_tkagg'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DongLanpec',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='internal',
    runtime_tmpdir=RUNTIME_TMP,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='stage_out',
)

# ---------- 后处理：复制到项目根 ----------
_root = Path(os.getcwd())                 # 项目根
_stage = Path(DISTPATH) / 'stage_out'     # 构建中转输出
_exe_src = _stage / ('DongLanpec.exe' if os.name == 'nt' else 'DongLanpec')
_exe_dst = _root / _exe_src.name
_internal_src = _stage / 'internal'
_internal_dst = _root / 'internal'

if _exe_src.exists():
    try:
        if _exe_dst.exists():
            _exe_dst.unlink()
        shutil.copy2(_exe_src, _exe_dst)
    except Exception as e:
        print('[post-copy] copy exe failed:', e)

if _internal_src.exists():
    try:
        if _internal_dst.exists():
            shutil.rmtree(_internal_dst, ignore_errors=True)
        shutil.copytree(_internal_src, _internal_dst)
    except Exception as e:
        print('[post-copy] copy internal failed:', e)
