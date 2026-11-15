# -*- coding: utf-8 -*-
"""
统一的中文按钮弹窗

【为什么需要】
Qt 的标准按钮（OK / Cancel / Yes / No）文字来自 qtbase_*.qm 翻译文件。
本机只有 qtbase_zh_TW.qm（繁体），没有 qtbase_zh_CN.qm，
而 qt_zh_CN.qm 是空壳——实测加载成功后按钮依然是 '&Yes' / '&No' / 'OK'。
所以只能自己建按钮、自己写中文。

【用法】
    import ui_msg
    if ui_msg.ask(self, "确认删除", "确定删除吗？"):
        ...
    ui_msg.info(self, "提示", "至少要保留一个产品。")
    ui_msg.warn(self, "还不能确认", "还有 3 处不合法。")

按钮一律：确认 / 取消（询问类），知道了（提示类）。
"""
from PyQt5.QtWidgets import QMessageBox


def _show(parent, title, text, icon, buttons, default_index=0):
    """
    建一个自己控制按钮文字的弹窗。

    buttons: [(文字, QMessageBox.ButtonRole), ...]
    返回：被点击的按钮索引（Esc 关闭返回 -1）
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)

    added = []
    for label, role in buttons:
        added.append(box.addButton(label, role))

    if 0 <= default_index < len(added):
        box.setDefaultButton(added[default_index])

    box.exec_()
    clicked = box.clickedButton()
    for i, b in enumerate(added):
        if clicked is b:
            return i
    return -1


def ask(parent, title, text, ok_text="确认", cancel_text="取消", detail=None):
    """询问类。点确认返回 True，点取消或按 Esc 返回 False。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    if detail:
        box.setInformativeText(detail)

    b_ok = box.addButton(ok_text, QMessageBox.AcceptRole)
    b_no = box.addButton(cancel_text, QMessageBox.RejectRole)
    box.setDefaultButton(b_ok)
    box.setEscapeButton(b_no)

    box.exec_()
    return box.clickedButton() is b_ok


def info(parent, title, text, ok_text="知道了"):
    """提示类。只有一个按钮。"""
    _show(parent, title, text, QMessageBox.Information,
          [(ok_text, QMessageBox.AcceptRole)])


def warn(parent, title, text, ok_text="知道了"):
    """警告类。只有一个按钮。写法上比「OK」更像人话。"""
    _show(parent, title, text, QMessageBox.Warning,
          [(ok_text, QMessageBox.AcceptRole)])


def error(parent, title, text, ok_text="知道了"):
    """错误类。"""
    _show(parent, title, text, QMessageBox.Critical,
          [(ok_text, QMessageBox.AcceptRole)])
