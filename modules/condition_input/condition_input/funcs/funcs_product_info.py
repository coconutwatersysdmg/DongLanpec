from modules.condition_input.funcs.db_cnt import get_connection
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsTextItem

# 直接定义数据库连接配置在模块里
db_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品需求库'
}


def widget_fold(widget, button):
    visible = widget.isVisible()
    widget.setVisible(not visible)
    button.setArrowType(Qt.RightArrow if visible else Qt.DownArrow)


def get_product_info(product_id):
    """ 从产品需求库获取产品信息 """
    connection = get_connection(
        db_config['host'],
        db_config['port'],
        db_config['user'],
        db_config['password'],
        db_config['database']
    )
    try:
        with connection.cursor() as cursor:
            sql = "SELECT 产品编号, 产品型号, 设备位号, 产品示意图 FROM 产品需求表 WHERE 产品ID= %s"
            cursor.execute(sql, (product_id,))
            result = cursor.fetchone()
            return result
    finally:
        connection.close()


def update_diagram(graph_view, pixmap):
    if not hasattr(graph_view, "_scene"):
        graph_view._scene = QGraphicsScene()
        graph_view.setScene(graph_view._scene)
        graph_view._pixmap_item = QGraphicsPixmapItem()
        graph_view._scene.addItem(graph_view._pixmap_item)

        graph_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        graph_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        graph_view.setTransformationAnchor(graph_view.AnchorUnderMouse)
        graph_view.setResizeAnchor(graph_view.AnchorViewCenter)

    if pixmap:
        view_size = graph_view.viewport().size()
        scaled = pixmap.scaled(view_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        graph_view._pixmap_item.setPixmap(scaled)

        # ✅ 修复类型错误，使用 QRectF
        graph_view._scene.setSceneRect(QRectF(scaled.rect()))
        graph_view.centerOn(graph_view._pixmap_item)
    else:
        graph_view._scene.clear()
        graph_view._scene.addItem(QGraphicsTextItem("当前产品示意图未完善"))

def check_pdt_define(product_id):
    connection = get_connection(
        db_config['host'],
        db_config['port'],
        db_config['user'],
        db_config['password'],
        db_config['database']
    )
    try:
        with connection.cursor() as cursor:
            sql = "SELECT 产品类型, 产品型式, 设计阶段 FROM 产品需求表 WHERE 产品ID= %s"
            cursor.execute(sql, (product_id,))
            result = cursor.fetchone()
            if result is None:
                return False
            return True
    finally:
        connection.close()

def check_has_any_product(project_id):
    """检查指定项目下是否存在至少一个产品"""
    connection = get_connection(
        db_config['host'],
        db_config['port'],
        db_config['user'],
        db_config['password'],
        db_config['database']
    )
    try:
        with connection.cursor() as cursor:
            # 关键修改：查询该项目下是否有任何产品记录
            sql = "SELECT 1 FROM 产品需求表 WHERE 项目ID= %s LIMIT 1"
            cursor.execute(sql, (project_id,))
            result = cursor.fetchone()
            # 如果有记录则返回True，否则返回False
            return result is not None
    finally:
        connection.close()