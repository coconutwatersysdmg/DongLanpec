"""Independent desktop application; no host application imports or DB startup."""
import argparse
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description='工程数据空间：产品、参数、计算、资源与血缘')
    parser.add_argument('--config', help='独立 JSON 配置文件')
    parser.add_argument('--source-root', help='可选的业务源码目录，仅用于静态分析')
    parser.add_argument('--product-id', default='', help='初始产品范围')
    parser.add_argument('--actor', default='', help='数据中心修改记录的操作人')
    args = parser.parse_args(argv)
    if args.config:
        os.environ['DATA_CENTER_CONFIG'] = args.config
    if args.source_root:
        os.environ['DONGLANPEC_SOURCE_ROOT'] = args.source_root
    from PyQt5.QtWidgets import QApplication, QMainWindow
    from . import create_data_center
    app = QApplication.instance() or QApplication(sys.argv)
    from .fonts import pixel_font
    app.setFont(pixel_font())
    window = QMainWindow()
    window.setWindowTitle('工程数据空间 · 独立应用')
    window.resize(1480, 900)
    window.setCentralWidget(create_data_center(window, product_id=args.product_id, actor=args.actor))
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
