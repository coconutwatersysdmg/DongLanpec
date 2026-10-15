"""DongLanpec 数据中心：DogiCat 数据核心与 Qt 字段血缘工作台。"""


def create_data_center(parent=None, product_id=None, actor=""):
    from .widget import DataCenterWidget
    return DataCenterWidget(parent, product_id=product_id, actor=actor)
