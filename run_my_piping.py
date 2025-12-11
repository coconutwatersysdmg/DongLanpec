#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复模块导入问题的启动脚本
"""
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 现在可以正常导入模块了
if __name__ == "__main__":
    # 导入并运行主程序
    from modules.buguan.buguan_ziyong.My_Piping import *
    
    # 如果My_Piping.py有main函数或需要执行的代码，在这里调用
    # 由于My_Piping.py看起来是一个GUI应用，直接导入应该会启动界面