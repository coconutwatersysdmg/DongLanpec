# -*- coding: utf-8 -*-
"""用 ASCII 临时文件 + alias 重编 pic_rc.py，避开 pyrcc5 中文路径问题。"""
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
# 界面仍用 :/icons/<中文名>.png
ICON_FILES = [
    "保温支撑圈.png",
    "保温支撑条.png",
    "吊耳.png",
    "铭牌.png",
    "鞍式支座.png",
    "耳座.png",
    "加强圈.png",
    "轴式吊耳.png",
]
ASCII_MAP = {
    "保温支撑圈.png": "_tmp_bwzhichengquan.png",
    "保温支撑条.png": "_tmp_bwzhichengtiao.png",
    "吊耳.png": "_tmp_diaoer.png",
    "铭牌.png": "_tmp_mingpai.png",
    "鞍式支座.png": "_tmp_anshi.png",
    "耳座.png": "_tmp_erzuo.png",
    "加强圈.png": "_tmp_jiaqiangquan.png",
    "轴式吊耳.png": "_tmp_zhoushidiaoer.png",
}


def main():
    tmp_files = []
    try:
        for cn_name in ICON_FILES:
            src = os.path.join(BASE, cn_name)
            if not os.path.isfile(src):
                print("missing:", cn_name, file=sys.stderr)
                return 1
            ascii_name = ASCII_MAP[cn_name]
            dst = os.path.join(BASE, ascii_name)
            shutil.copy2(src, dst)
            tmp_files.append(dst)
            print("ok", cn_name, os.path.getsize(src), "->", ascii_name)

        qrc_path = os.path.join(BASE, "_tmp_pic.qrc")
        lines = ['<RCC>', '  <qresource prefix="/icons">']
        for cn_name in ICON_FILES:
            lines.append(
                f'    <file alias="{cn_name}">{ASCII_MAP[cn_name]}</file>'
            )
        lines.extend(["  </qresource>", "</RCC>", ""])
        with open(qrc_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        tmp_files.append(qrc_path)

        pyrcc = r"D:\Anaconda\Library\bin\pyrcc5.bat"
        out_py = os.path.join(BASE, "pic_rc.py")
        r = subprocess.run(
            [pyrcc, "-o", out_py, qrc_path],
            cwd=BASE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print(r.stdout)
        print(r.stderr)
        if r.returncode != 0:
            print("pyrcc failed", r.returncode, file=sys.stderr)
            return r.returncode

        # 校验
        sys.path.insert(0, os.path.abspath(os.path.join(BASE, "..", "..", "..")))
        import importlib
        import modules.guankoudingyi.resource.pic_rc as pic_rc
        importlib.reload(pic_rc)
        from PyQt5.QtCore import QFile

        for cn_name in ICON_FILES:
            f = QFile(":/icons/" + cn_name)
            print("res", cn_name, f.exists(), f.size() if f.exists() else 0)
            if not f.exists():
                return 2
        print("rebuild ok")
        return 0
    finally:
        for p in tmp_files:
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
