替换说明（请整夹替换）
====================
1. 删除甲方旧的 D:\softwareYS\Python\DongLanpec\venv 后，解压本包中的 venv 到该路径。
2. 解释器：D:\softwareYS\Python\DongLanpec\venv\Scripts\python.exe
3. 若仍装过 python-qt5，先卸载：
   .\Scripts\python.exe -m pip uninstall -y python-qt5
4. 代码要的是 PyQt5，不要装 python-qt5 / 不要混用 PySide6。
5. 若仍报 Qt DLL 错，请安装 Microsoft Visual C++ Redistributable 2015-2022 x64。
