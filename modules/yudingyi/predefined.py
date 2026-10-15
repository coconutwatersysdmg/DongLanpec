import json
import ast
import os
import sys
import pymysql
import re
from datetime import datetime
from collections import defaultdict
from functools import partial

from PyQt5 import sip
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QScrollArea,
    QTableWidget, QTableWidgetItem, QPushButton, QCheckBox, QMessageBox,
    QLineEdit, QComboBox, QInputDialog, QHeaderView, QFrame, QSplitter,
    QTreeWidget, QTreeWidgetItem, QSizePolicy,
    QAbstractScrollArea, QAbstractItemView
)
from PyQt5.QtGui import QFont, QCursor
from PyQt5.QtCore import Qt, QTimer, QObject, QThread, pyqtSignal, pyqtSlot

from modules.chanpinguanli import bianl
from modules.yudingyi.sync_element_define_from_config import run_predefined_save_sync


class ResizableLineEdit(QLineEdit):
    """
    支持从右边缘拖动改变宽度的输入框。

    - 默认宽度保持调用处原有宽度；
    - 鼠标悬停时显示完整文本；
    - 将鼠标移动到输入框最右侧，光标变成左右箭头后即可拖动；
    - 双击右边缘可恢复默认宽度。
    """

    RESIZE_MARGIN = 7

    def __init__(
            self,
            text="",
            parent=None,
            default_width=120,
            min_width=40,
            max_width=900
    ):
        super().__init__(str(text), parent)

        self._default_width = int(default_width)
        self._minimum_drag_width = int(min_width)
        self._maximum_drag_width = int(max_width)
        self._is_drag_resizing = False
        self._resize_start_global_x = 0
        self._resize_start_width = self._default_width

        self.setMouseTracking(True)
        self.setMinimumWidth(self._minimum_drag_width)
        self.setMaximumWidth(self._maximum_drag_width)
        self.setFixedWidth(self._default_width)

        self.textChanged.connect(self._update_full_text_tooltip)
        self._update_full_text_tooltip(self.text())

    def _update_full_text_tooltip(self, text):
        """始终让悬停提示与输入框当前内容一致。"""
        self.setToolTip(str(text) if text is not None else "")

    def _is_on_resize_edge(self, pos):
        return pos.x() >= self.width() - self.RESIZE_MARGIN

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_on_resize_edge(event.pos()):
            self._is_drag_resizing = True
            self._resize_start_global_x = event.globalX()
            self._resize_start_width = self.width()
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_drag_resizing:
            delta = event.globalX() - self._resize_start_global_x
            new_width = self._resize_start_width + delta
            new_width = max(
                self._minimum_drag_width,
                min(self._maximum_drag_width, new_width)
            )
            self.setFixedWidth(new_width)
            event.accept()
            return

        if self._is_on_resize_edge(event.pos()):
            self.setCursor(QCursor(Qt.SizeHorCursor))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_drag_resizing and event.button() == Qt.LeftButton:
            self._is_drag_resizing = False
            self.releaseMouse()
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_on_resize_edge(event.pos()):
            self.setFixedWidth(self._default_width)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        if not self._is_drag_resizing:
            self.unsetCursor()
        super().leaveEvent(event)


class ResizableComboBox(QComboBox):
    """
    支持从右边缘拖动改变宽度的下拉框。

    当前选中的完整文本通过控件悬停提示显示；下拉列表中的每个模板名
    通过 Qt.ToolTipRole 显示完整名称。
    """

    RESIZE_MARGIN = 7

    def __init__(
            self,
            parent=None,
            default_width=210,
            min_width=90,
            max_width=700
    ):
        super().__init__(parent)

        self._default_width = int(default_width)
        self._minimum_drag_width = int(min_width)
        self._maximum_drag_width = int(max_width)
        self._is_drag_resizing = False
        self._resize_start_global_x = 0
        self._resize_start_width = self._default_width

        self.setMouseTracking(True)
        self.view().setMouseTracking(True)
        self.setMinimumWidth(self._minimum_drag_width)
        self.setMaximumWidth(self._maximum_drag_width)
        self.setFixedWidth(self._default_width)

        self.currentTextChanged.connect(self._update_full_text_tooltip)
        self._update_full_text_tooltip(self.currentText())

    def _update_full_text_tooltip(self, text=None):
        if text is None:
            text = self.currentText()
        self.setToolTip(str(text) if text is not None else "")

    def refresh_tooltip(self):
        """在 blockSignals 状态下切换选项后也能手动刷新提示。"""
        self._update_full_text_tooltip(self.currentText())

    def setCurrentIndex(self, index):
        super().setCurrentIndex(index)
        self.refresh_tooltip()

    def clear(self):
        super().clear()
        self.refresh_tooltip()

    def _is_on_resize_edge(self, pos):
        return pos.x() >= self.width() - self.RESIZE_MARGIN

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_on_resize_edge(event.pos()):
            self._is_drag_resizing = True
            self._resize_start_global_x = event.globalX()
            self._resize_start_width = self.width()
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_drag_resizing:
            delta = event.globalX() - self._resize_start_global_x
            new_width = self._resize_start_width + delta
            new_width = max(
                self._minimum_drag_width,
                min(self._maximum_drag_width, new_width)
            )
            self.setFixedWidth(new_width)
            event.accept()
            return

        if self._is_on_resize_edge(event.pos()):
            self.setCursor(QCursor(Qt.SizeHorCursor))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_drag_resizing and event.button() == Qt.LeftButton:
            self._is_drag_resizing = False
            self.releaseMouse()
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_on_resize_edge(event.pos()):
            self.setFixedWidth(self._default_width)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        if not self._is_drag_resizing:
            self.unsetCursor()
        super().leaveEvent(event)


class RemoteBackupSyncWorker(QObject):
    """在后台线程中同步远程 user_config_beifen，避免阻塞界面启动。"""

    finished = pyqtSignal(bool, str, int)

    def __init__(self, local_db_config, remote_db_config):
        super().__init__()
        self.local_db_config = dict(local_db_config)
        self.remote_db_config = dict(remote_db_config)

    @staticmethod
    def _signature_sql():
        # 先比较各版本的行数与内容校验和；版本未变化时不再下载整表。
        return """
            SELECT
                name,
                COUNT(*) AS row_count,
                COALESCE(
                    SUM(
                        CRC32(
                            CONCAT_WS(
                                CHAR(31),
                                COALESCE(CAST(id AS CHAR), ''),
                                COALESCE(CAST(user_id AS CHAR), ''),
                                COALESCE(config_type, ''),
                                COALESCE(`value`, ''),
                                COALESCE(title, ''),
                                COALESCE(object, ''),
                                COALESCE(subtitle, ''),
                                COALESCE(memo, ''),
                                COALESCE(content, ''),
                                COALESCE(name, '')
                            )
                        )
                    ),
                    0
                ) AS checksum_value
            FROM user_config_beifen
            GROUP BY name
        """

    @staticmethod
    def _to_signature_map(rows):
        result = {}
        for row in rows:
            name = row.get("name")
            result[name] = (
                int(row.get("row_count") or 0),
                str(row.get("checksum_value") or 0)
            )
        return result

    @staticmethod
    def _placeholders(count):
        return ",".join(["%s"] * count)

    @pyqtSlot()
    def run(self):
        remote = None
        local = None

        try:
            remote = pymysql.connect(
                host=self.remote_db_config["host"],
                port=self.remote_db_config.get("port", 3306),
                user=self.remote_db_config["user"],
                password=self.remote_db_config["password"],
                database=self.remote_db_config["database"],
                charset=self.remote_db_config.get("charset", "utf8mb4"),
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
                connect_timeout=self.remote_db_config.get("connect_timeout", 2),
                read_timeout=self.remote_db_config.get("read_timeout", 15),
                write_timeout=self.remote_db_config.get("write_timeout", 15)
            )

            local = pymysql.connect(
                host=self.local_db_config["host"],
                port=self.local_db_config.get("port", 3306),
                user=self.local_db_config["user"],
                password=self.local_db_config["password"],
                database=self.local_db_config["database"],
                charset=self.local_db_config.get("charset", "utf8mb4"),
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
                connect_timeout=2,
                read_timeout=15,
                write_timeout=15
            )

            signature_sql = self._signature_sql()

            with remote.cursor() as rcur:
                rcur.execute(signature_sql)
                remote_signatures = self._to_signature_map(rcur.fetchall())

            with local.cursor() as lcur:
                lcur.execute(signature_sql)
                local_signatures = self._to_signature_map(lcur.fetchall())

            changed_names = [
                name for name, signature in remote_signatures.items()
                if local_signatures.get(name) != signature
            ]
            removed_names = [
                name for name in local_signatures
                if name not in remote_signatures
            ]

            if not changed_names and not removed_names:
                self.finished.emit(True, "服务器版本与本地一致，无需更新", 0)
                return

            rows = []
            if changed_names:
                placeholders = self._placeholders(len(changed_names))
                select_sql = f"""
                    SELECT
                        id, user_id, config_type, `value`, title, object,
                        subtitle, memo, content, name
                    FROM user_config_beifen
                    WHERE name IN ({placeholders})
                    ORDER BY name, id
                """
                with remote.cursor() as rcur:
                    rcur.execute(select_sql, tuple(changed_names))
                    rows = rcur.fetchall()

            with local.cursor() as lcur:
                names_to_delete = removed_names + changed_names
                if names_to_delete:
                    placeholders = self._placeholders(len(names_to_delete))
                    lcur.execute(
                        f"DELETE FROM user_config_beifen WHERE name IN ({placeholders})",
                        tuple(names_to_delete)
                    )

                if rows:
                    insert_sql = """
                        INSERT INTO user_config_beifen
                        (id, user_id, config_type, value, title, object,
                         subtitle, memo, content, name)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """
                    lcur.executemany(insert_sql, [
                        (
                            row["id"], row["user_id"], row["config_type"],
                            row["value"], row["title"], row["object"],
                            row["subtitle"], row["memo"], row["content"],
                            row["name"]
                        )
                        for row in rows
                    ])

            local.commit()
            self.finished.emit(
                True,
                f"服务器同步完成：更新 {len(changed_names)} 个版本，删除 {len(removed_names)} 个旧版本",
                len(rows)
            )

        except Exception as exc:
            if local is not None:
                try:
                    local.rollback()
                except Exception:
                    pass
            self.finished.emit(False, f"服务器同步失败：{exc}", 0)

        finally:
            for conn in (remote, local):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass


class ConfigLibraryWidget(QWidget):
    """集成到 ConfigManager 的右侧子界面，支持多行同级占位符渲染与表格 + 多版本管理"""

    def __init__(self, db_config=None, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1200, 700)
        self.db_config = db_config or {
            'host': 'localhost',
            'port': 3306,
            'user': 'root',
            'password': '123456',
            'database': '配置库',
            'charset': 'utf8'
        }

        self.conn = None
        self._ensure_conn()

        # 远程同步改为后台执行，启动时先立即显示本地数据。
        self.remote_db_config = {
            "host": "10.32.22.189",
            "port": 3306,
            "user": "DongLanpec",
            "password": "DongLanpec704704",
            "database": "配置库",
            "charset": "utf8mb4",
            "connect_timeout": 2,
            "read_timeout": 15,
            "write_timeout": 15
        }
        self._remote_sync_thread = None
        self._remote_sync_worker = None

        # ==========================
        # 用户权限
        # ==========================
        self.is_admin = self._check_user_is_admin(bianl.current_username)
        print("当前用户管理员:", self.is_admin)

        # ==========================
        # 数据缓存
        # ==========================
        self.rows_cache = {}  # {(id, type): {...}}
        self.dirty_ids = set()  # 修改过的普通配置
        self.table_widgets = {}  # {id: table}
        self.dirty_table_ids = set()  # 修改过的表格配置

        self.all_rows = []
        self.grouped_rows = defaultdict(list)
        self.current_object_key = None

        # ==========================
        # 主布局
        # ==========================
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(6)

        # ==========================
        # 总体样式
        # ==========================
        self.setStyleSheet("""
            QWidget {
                font-family: "Microsoft YaHei";
                font-size: 14px;
                color: #111;
            }

            QPushButton {
                background-color: #eef5ff;
                border: 1px solid #b8cbe6;
                padding: 4px 10px;
                min-height: 28px;
            }

            QPushButton:hover {
                background-color: #e1efff;
                border: 1px solid #7da9df;
            }

            QPushButton:pressed {
                background-color: #d2e7ff;
            }

            QComboBox, QLineEdit {
                background-color: white;
                border: 1px solid #c8c8c8;
                min-height: 28px;
                padding-left: 4px;
            }

            QTreeWidget {
                background: white;
                border: 1px solid #cfd8e6;
                outline: none;
            }

            QTreeWidget::item {
                height: 28px;
            }

            QTreeWidget::item:selected {
                background: #eaf2ff;
                color: black;
                border: 1px dotted #333;
            }

            QScrollArea {
                border: none;
                background: white;
            }

            QTableWidget {
                background: white;
                alternate-background-color: #f3f3f3;
                gridline-color: #e5e5e5;
                border: 1px solid #dedede;
            }
        """)

        # =====================================================
        # 顶部工具栏
        # =====================================================
        toolbar_frame = QFrame(self)
        toolbar_frame.setFixedHeight(52)
        toolbar_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        toolbar_frame.setStyleSheet("""
            QFrame {
                background: #f7f9fc;
                border: 1px solid #d7e1ef;
            }
        """)

        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(6, 6, 6, 6)
        toolbar_layout.setSpacing(8)

        self.btn_sync_remote = QPushButton("同步服务器")
        self.sync_status_label = QLabel("")
        self.sync_status_label.setStyleSheet("color:#5b677a;")

        # 默认仍为原来的 210 像素；可拖动右边缘调整宽度。
        self.version_selector = ResizableComboBox(default_width=210)

        # 删除前自动保存 user_config_beifen 文件快照，再同时删除本地与服务器版本。
        self.btn_delete_version = QPushButton("删除模板")
        self.btn_delete_version.setStyleSheet("""
            QPushButton {
                background-color: #fff3f3;
                border: 1px solid #e0aaaa;
            }
            QPushButton:hover {
                background-color: #ffe5e5;
                border: 1px solid #cf7777;
            }
            QPushButton:pressed {
                background-color: #ffd7d7;
            }
        """)

        self.btn_restore_backup = QPushButton("恢复备份")
        self.btn_restore_backup.setToolTip(
            "从当前产品文件夹中的最近备份增量恢复缺失记录，不覆盖现有模板数据"
        )

        # 默认仍为原来的 130 像素；输入内容悬停可完整显示，也可拖动缩放。
        self.new_version_edit = ResizableLineEdit(
            default_width=130,
            min_width=60,
            max_width=500
        )

        self.btn_save_as_version = QPushButton("确定")

        toolbar_layout.addWidget(self.btn_sync_remote)
        toolbar_layout.addWidget(self.sync_status_label)

        lbl_template = QLabel("模板切换")
        toolbar_layout.addWidget(lbl_template)
        toolbar_layout.addWidget(self.version_selector)
        toolbar_layout.addWidget(self.btn_delete_version)
        toolbar_layout.addWidget(self.btn_restore_backup)

        lbl_save_as = QLabel("另存模板")
        toolbar_layout.addWidget(lbl_save_as)
        toolbar_layout.addWidget(self.new_version_edit)
        toolbar_layout.addWidget(self.btn_save_as_version)

        toolbar_layout.addStretch(1)

        self.main_layout.addWidget(toolbar_frame, 0)
        # =====================================================
        # 中间区域：左侧目录树 + 右侧内容区
        # =====================================================
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)

        # --------------------------
        # 左侧树形目录
        # --------------------------
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(260)
        self.tree.setMaximumWidth(360)

        self.splitter.addWidget(self.tree)

        # --------------------------
        # 右侧内容区
        # --------------------------
        right_frame = QFrame()
        right_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        right_frame.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #cfd8e6;
            }
        """)

        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.container = QWidget()
        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(8, 8, 8, 8)
        self.container_layout.setSpacing(8)

        # 关键：所有内容固定从左上角开始排
        self.container_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll.setWidget(self.container)

        # 关键：scroll 占满右侧区域
        right_layout.addWidget(self.scroll, 1)

        # 右下角确定按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addStretch(1)

        self.save_button = QPushButton("确定")
        self.save_button.setFixedSize(90, 36)
        self.save_button.clicked.connect(
            lambda: self.save_all_tables(
                silent=False,
                sync_local_beifen=True,
                sync_remote=True
            )
        )

        bottom_layout.addWidget(self.save_button)

        # 底部按钮栏固定高度，不参与拉伸
        right_layout.addLayout(bottom_layout, 0)

        self.splitter.addWidget(right_frame)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        self.splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_layout.addWidget(self.splitter, 1)
        # =====================================================
        # 管理员按钮逻辑
        # =====================================================
        if not self.is_admin:
            self.btn_delete_version.setEnabled(False)
            self.btn_restore_backup.setEnabled(False)
            self.btn_save_as_version.setEnabled(False)
            self.new_version_edit.setEnabled(False)

        # =====================================================
        # 版本选择器初始化
        # =====================================================
        self.load_versions()

        self.version_selector.blockSignals(True)
        if self.version_selector.count() > 0:
            self.version_selector.setCurrentIndex(0)
        self.version_selector.blockSignals(False)
        self.version_selector.refresh_tooltip()

        self.version_selector.currentIndexChanged.connect(self.apply_version)

        # =====================================================
        # 信号绑定
        # =====================================================
        # 只保留 currentItemChanged，避免鼠标点击时 itemClicked 与
        # currentItemChanged 连续触发，造成右侧内容重复渲染。
        self.tree.currentItemChanged.connect(
            lambda current, previous: self._on_config_tree_item_clicked(current, 0)
        )
        self.btn_delete_version.clicked.connect(self.delete_version)
        self.btn_restore_backup.clicked.connect(self.restore_backup_incrementally)
        self.btn_save_as_version.clicked.connect(self.save_to_beifen_from_toolbar)
        self.btn_sync_remote.clicked.connect(self.sync_remote_to_local)

        # =====================================================
        # 初次加载数据：只渲染一次，先显示本地内容
        # =====================================================
        self.ensure_initial_version_applied()
        self.reload_and_render()

        # 界面完成创建后再后台同步服务器，不阻塞窗口打开。
        QTimer.singleShot(150, self.sync_remote_to_local)

    def refresh_ui_after_db_changed(self, select_name=None, keep_current=True):
        """
        数据库更新后，强制刷新下拉框、左侧树、右侧内容。
        keep_current=True 时，尽量保持当前正在看的配置项不跳走。
        """
        old_key = self.current_object_key

        if select_name:
            self.refresh_version_selector(select_name=select_name)

        self.reload_and_render()

        if keep_current and old_key:
            item = self._find_tree_item_by_key(old_key)
            if item:
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(item)
                self.tree.blockSignals(False)
                self.current_object_key = old_key
                self.render_selected_config_object(old_key)

    def _find_tree_item_by_key(self, key):
        """
        根据 key 找左侧树节点。
        支持 title / subtitle / object 三种节点。
        """
        if not key or not hasattr(self, "tree"):
            return None

        def walk(item):
            if item.data(0, Qt.UserRole) == key:
                return item

            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found

            return None

        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found:
                return found

        return None
    def save_to_beifen_from_toolbar(self):
        """
        工具栏“另存模板”按钮：
        1. 保存当前界面修改到 user_config
        2. 保存到本地 user_config_beifen
        3. 同步保存到远程 user_config_beifen
        4. 切换当前 user_config 的 name
        5. 刷新界面
        """
        name = self.new_version_edit.text().strip()

        # 如果输入框为空，仍然走原来的弹窗保存逻辑
        if not name:
            self.save_to_beifen()
            return

        if self.version_exists(name):
            QMessageBox.warning(self, "名称冲突", f"版本《{name}》已存在，请更换其他名称。")
            return

        # 先保存当前页面所有修改到 user_config
        ok = self.save_all_tables(
            silent=True,
            sync_local_beifen=False,
            sync_remote=False
        )
        if not ok:
            return

        local_rows = []

        try:
            self._ensure_conn()

            # ==========================
            # 1. 读取本地 user_config 作为事实源
            # ==========================
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        id, user_id, config_type, value,
                        title, object, subtitle, memo, content
                    FROM user_config
                    ORDER BY id
                """)
                local_rows = cur.fetchall()

            if not local_rows:
                QMessageBox.warning(self, "提示", "user_config 为空，无法另存模板。")
                return

            # ==========================
            # 2. 写入本地 user_config_beifen
            # ==========================
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM user_config_beifen WHERE name=%s", (name,))

                insert_sql = """
                    INSERT INTO user_config_beifen
                    (id, user_id, config_type, value,
                     title, object, subtitle, memo, content, name)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """

                cur.executemany(insert_sql, [
                    (
                        r["id"],
                        r["user_id"],
                        r["config_type"],
                        r["value"],
                        r["title"],
                        r["object"],
                        r["subtitle"],
                        r["memo"],
                        r["content"],
                        name
                    )
                    for r in local_rows
                ])

                # 当前主表也切换到新模板名
                cur.execute("UPDATE user_config SET name=%s", (name,))

            print(f"💾 已保存版本《{name}》到本地数据库（{len(local_rows)} 行）")

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"本地保存模板失败：{e}")
            return

        self._update_selected_product_config()

        # ==========================
        # 3. 写入远程 user_config_beifen
        # ==========================
        remote_ok = False
        remote_error = ""

        remote = self.get_remote_conn()

        if remote:
            try:
                # 这里直接复用你已有的远程写入方法
                self._write_rows_to_remote_beifen(
                    remote_conn=remote,
                    version_name=name,
                    rows=local_rows
                )

                remote.commit()
                remote_ok = True

                print(f"☁️ 已同步版本《{name}》到远程服务器（{len(local_rows)} 行）")

            except Exception as e:
                remote_error = str(e)
                print("⚠️ 远程写入失败：", e)

            finally:
                try:
                    remote.close()
                except:
                    pass
        else:
            remote_error = "无法连接远程服务器"

        # ==========================
        # 4. 刷新界面
        # ==========================
        self.refresh_ui_after_db_changed(select_name=name, keep_current=True)
        self.new_version_edit.clear()

        # ==========================
        # 5. 提示结果
        # ==========================
        if remote_ok:
            QMessageBox.information(
                self,
                "成功",
                f"已另存为模板并同步到远程服务器：{name}"
            )
        else:
            QMessageBox.warning(
                self,
                "部分成功",
                f"模板《{name}》已保存到本地，但远程同步失败：\n{remote_error}"
            )
        run_predefined_save_sync()

    def _fit_table_size(
            self,
            table: QTableWidget,
            min_row_h=28,
            min_h=120,
            max_h=420,
            min_col_w=80
    ):
        """按内容设置表格尺寸，但只执行一次列宽测量。"""
        if table is None or sip.isdeleted(table):
            return

        table.setUpdatesEnabled(False)
        try:
            table.setWordWrap(False)

            # 单行文本无需 resizeRowsToContents；固定行高明显更快。
            for row_index in range(table.rowCount()):
                table.setRowHeight(row_index, min_row_h)

            header = table.horizontalHeader()
            header.setMinimumSectionSize(min_col_w)
            header.setSectionResizeMode(QHeaderView.Interactive)

            # 只测量一次，避免 ResizeToContents 持续反复计算。
            table.resizeColumnsToContents()

            total_w = table.frameWidth() * 2
            if table.verticalHeader().isVisible():
                total_w += table.verticalHeader().width()

            for column_index in range(table.columnCount()):
                width = max(table.columnWidth(column_index), min_col_w)
                table.setColumnWidth(column_index, width)
                total_w += width

            table.setMinimumWidth(total_w + 2)

            total_h = table.horizontalHeader().height()
            total_h += table.rowCount() * min_row_h
            total_h = max(min_h, total_h)

            if total_h > max_h:
                table.setFixedHeight(max_h)
                table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            else:
                table.setFixedHeight(total_h)
                table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            table.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        finally:
            table.setUpdatesEnabled(True)

    def _wrap_table_widget(self, table: QTableWidget) -> QWidget:
        """
        防止 QVBoxLayout 拉伸 table，
        让 table 真正按内容大小显示
        """
        wrapper = QWidget()
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ❗关键：左对齐 + 右侧 stretch
        h.setAlignment(Qt.AlignLeft)
        h.addWidget(table)
        h.addStretch(1)

        return wrapper

    # ==========================
    # 判断管理员
    # ==========================
    def _check_user_is_admin(self, username):
        conn = None
        try:
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="用户库",
                port=3306,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=2
            )
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 用户类型 FROM 用户表 WHERE username=%s LIMIT 1",
                    (username,)
                )
                row = cursor.fetchone()

            if not row:
                return False

            role = str(row.get("用户类型", "")).lower()
            return role in ("admin", "administrator", "管理员")

        except Exception as e:
            print("检查管理员失败：", e)
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    # ==========================
    # DB 连接
    # ==========================
    def _ensure_conn(self):
        if self.conn:
            try:
                self.conn.ping(reconnect=True)
                return
            except Exception:
                pass

        self.conn = pymysql.connect(
            host=self.db_config['host'],
            port=self.db_config['port'],
            user=self.db_config['user'],
            password=self.db_config['password'],
            database=self.db_config['database'],
            charset=self.db_config['charset'],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )

    # ==========================
    # 加载 user_config 主数据
    # ==========================
    def load_user_config_rows(self):
        """
        读取 user_config 后，在 Python 中进行自然排序。
        不再完全依赖 SQL 的字符串 ORDER BY。
        """
        self._ensure_conn()

        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM user_config")
            rows = cur.fetchall()

        rows.sort(key=self._row_tree_sort_key)
        return rows

    def get_remote_conn(self):
        """连接远程服务器，如果失败则返回 None（不会抛异常）"""
        try:
            conn = pymysql.connect(
                host="10.32.22.189",
                user="DongLanpec",
                password="DongLanpec704704",
                database="配置库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
                connect_timeout=2,
                read_timeout=15,
                write_timeout=15
            )
            return conn
        except Exception as e:
            print("⚠️ 无法连接远程服务器，已跳过远程同步：", e)
            return None

    def version_exists(self, name):
        """检查 name 是否已存在于 user_config_beifen"""
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM user_config_beifen WHERE name=%s", (name,))
            return cur.fetchone()["c"] > 0

    # ==========================
    # 加载备份版本名
    # ==========================
    def refresh_version_selector(self, select_name=None):
        """
        刷新版本下拉框：
        - 下拉框仅显示 user_config_beifen 中的版本
        - 默认版本总是存在
        """
        self.version_selector.blockSignals(True)

        # 当前文本
        current = select_name or self.version_selector.currentText() or "默认"

        self.version_selector.clear()

        # 读取本地所有版本
        self.load_versions()

        # 尝试选中目标版本
        idx = self.version_selector.findText(current)
        if idx == -1:
            idx = self.version_selector.findText("默认")

        if idx != -1:
            self.version_selector.setCurrentIndex(idx)

        self.version_selector.blockSignals(False)
        self.version_selector.refresh_tooltip()

    def load_versions(self):
        """从 user_config_beifen 读取所有版本名，并为每项设置完整名称悬停提示。"""
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM user_config_beifen ORDER BY name")
            rows = cur.fetchall()
            for r in rows:
                version_name = str(r.get("name") or "")
                self.version_selector.addItem(version_name)
                item_index = self.version_selector.count() - 1
                self.version_selector.setItemData(
                    item_index,
                    version_name,
                    Qt.ToolTipRole
                )

    @staticmethod
    def _get_program_root_dir():
        """
        获取程序根目录：
        1. 打包后的程序使用可执行文件所在目录；
        2. 源码运行时使用主程序文件所在目录；
        3. 无法获取主程序文件时退回当前工作目录。
        """
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))

        main_module = sys.modules.get("__main__")
        main_file = getattr(main_module, "__file__", None)
        if main_file:
            return os.path.dirname(os.path.abspath(main_file))

        return os.path.abspath(os.getcwd())

    def _get_predefined_config_backup_dir(self):
        """
        在程序根目录下创建并返回“预定义配置备份”文件夹。

        例如：
            程序根目录/预定义配置备份
        """
        root_dir = self._get_program_root_dir()
        if not os.path.isdir(root_dir):
            raise FileNotFoundError(f"程序根目录不存在：{root_dir}")

        backup_dir = os.path.join(root_dir, "预定义配置备份")
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    @staticmethod
    def _backup_file_pattern():
        return "user_config_beifen_before_delete_*.json"

    def _list_user_config_backup_files(self, backup_dir):
        files = []
        for filename in os.listdir(backup_dir):
            if (
                filename.startswith("user_config_beifen_before_delete_")
                and filename.lower().endswith(".json")
            ):
                path = os.path.join(backup_dir, filename)
                if os.path.isfile(path):
                    files.append(path)
        files.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
        return files

    def _prune_user_config_backups(self, backup_dir, keep_count=3):
        """程序根目录下最多保留最近 keep_count 份删除前快照。"""
        backup_files = self._list_user_config_backup_files(backup_dir)
        for old_path in backup_files[keep_count:]:
            try:
                os.remove(old_path)
                print(f"🧹 已删除过期配置备份：{old_path}")
            except Exception as exc:
                print(f"⚠️ 删除过期配置备份失败：{old_path}，{exc}")

    def _read_all_local_beifen_rows(self):
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id, user_id, config_type, `value`, title, object,
                    subtitle, memo, content, name
                FROM user_config_beifen
                ORDER BY name, id
            """)
            return cur.fetchall() or []

    def _create_user_config_beifen_backup(self, deleting_version):
        """
        在程序根目录的“预定义配置备份”文件夹中保存删除前的
        完整 user_config_beifen 快照。
        使用临时文件 + os.replace，避免写到一半留下损坏备份。
        """
        backup_dir = self._get_predefined_config_backup_dir()
        rows = self._read_all_local_beifen_rows()
        if not rows:
            raise RuntimeError("本地 user_config_beifen 为空，无法创建删除前备份。")

        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"user_config_beifen_before_delete_{timestamp}.json"
        backup_path = os.path.join(backup_dir, filename)
        temp_path = backup_path + ".tmp"

        payload = {
            "backup_type": "user_config_beifen_before_delete",
            "format_version": 1,
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "backup_directory": backup_dir,
            "deleted_version": deleting_version,
            "row_count": len(rows),
            "rows": rows
        }

        try:
            with open(temp_path, "w", encoding="utf-8") as file_obj:
                json.dump(
                    payload,
                    file_obj,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                )
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temp_path, backup_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

        self._prune_user_config_backups(backup_dir, keep_count=3)
        print(f"📦 删除前配置备份已保存：{backup_path}")
        return backup_path, rows

    @staticmethod
    def _normalize_backup_rows(payload):
        if not isinstance(payload, dict):
            raise ValueError("备份文件根节点格式不正确。")
        if payload.get("backup_type") != "user_config_beifen_before_delete":
            raise ValueError("所选文件不是 user_config_beifen 删除前备份。")

        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("备份文件缺少 rows 列表。")

        required_fields = (
            "id", "user_id", "config_type", "value", "title",
            "object", "subtitle", "memo", "content", "name"
        )
        normalized = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"备份第 {index} 行不是对象。")
            missing = [field for field in required_fields if field not in row]
            if missing:
                raise ValueError(
                    f"备份第 {index} 行缺少字段：{', '.join(missing)}"
                )
            normalized.append({field: row.get(field) for field in required_fields})
        return normalized

    @staticmethod
    def _backup_row_key(row):
        return str(row.get("name") or ""), str(row.get("id") or "")

    @staticmethod
    def _insert_beifen_rows(conn, rows):
        if not rows:
            return 0
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO user_config_beifen
                (id, user_id, config_type, value, title, object,
                 subtitle, memo, content, name)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    (
                        row.get("id"), row.get("user_id"),
                        row.get("config_type"), row.get("value"),
                        row.get("title"), row.get("object"),
                        row.get("subtitle"), row.get("memo"),
                        row.get("content"), row.get("name")
                    )
                    for row in rows
                ]
            )
        return len(rows)

    @staticmethod
    def _read_existing_beifen_keys(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM user_config_beifen")
            rows = cur.fetchall() or []
        return {
            (str(row.get("name") or ""), str(row.get("id") or ""))
            for row in rows
        }

    @staticmethod
    def _delete_specific_beifen_rows(conn, rows):
        if not rows:
            return
        with conn.cursor() as cur:
            cur.executemany(
                "DELETE FROM user_config_beifen WHERE name=%s AND id=%s",
                [
                    (row.get("name"), row.get("id"))
                    for row in rows
                ]
            )

    def restore_backup_incrementally(self):
        """
        从文件快照增量恢复：
        - 本地缺什么补什么；
        - 服务器缺什么补什么；
        - 已存在的 (name, id) 记录不覆盖。
        """
        if not self.is_admin:
            QMessageBox.warning(self, "权限不足", "只有管理员可以恢复模板备份。")
            return

        if self._remote_sync_thread is not None and self._remote_sync_thread.isRunning():
            QMessageBox.information(self, "正在同步", "服务器同步尚未结束，请稍后再恢复。")
            return

        try:
            backup_dir = self._get_predefined_config_backup_dir()
            backup_files = self._list_user_config_backup_files(backup_dir)
        except Exception as exc:
            QMessageBox.critical(self, "无法读取备份", str(exc))
            return

        if not backup_files:
            QMessageBox.information(
                self,
                "没有备份",
                f"预定义配置备份文件夹中没有可恢复的配置备份：\n{backup_dir}"
            )
            return

        display_to_path = {}
        display_items = []
        for path in backup_files[:3]:
            try:
                with open(path, "r", encoding="utf-8") as file_obj:
                    meta = json.load(file_obj)
                created_at = str(meta.get("created_at") or "未知时间")
                deleted_version = str(meta.get("deleted_version") or "未知模板")
                row_count = int(meta.get("row_count") or 0)
                label = (
                    f"{created_at}｜删除《{deleted_version}》前｜{row_count} 行"
                )
            except Exception:
                label = os.path.basename(path)

            # 防止极端情况下显示文本重复。
            unique_label = label
            suffix = 2
            while unique_label in display_to_path:
                unique_label = f"{label} ({suffix})"
                suffix += 1
            display_to_path[unique_label] = path
            display_items.append(unique_label)

        selected, ok = QInputDialog.getItem(
            self,
            "选择配置备份",
            "请选择要增量恢复的删除前备份：",
            display_items,
            0,
            False
        )
        if not ok or not selected:
            return

        backup_path = display_to_path[selected]
        try:
            with open(backup_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            backup_rows = self._normalize_backup_rows(payload)
        except Exception as exc:
            QMessageBox.critical(self, "备份损坏", f"无法读取所选备份：\n{exc}")
            return

        reply = QMessageBox.question(
            self,
            "确认增量恢复",
            "将从所选备份向本地和服务器补充缺失记录。\n\n"
            "已存在的模板记录不会被覆盖，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        remote = self.get_remote_conn()
        if remote is None:
            QMessageBox.critical(
                self,
                "恢复中止",
                "无法连接服务器。为避免本地与服务器不一致，本次未恢复任何数据。"
            )
            return

        self._ensure_conn()
        old_local_autocommit = self.conn.get_autocommit()
        old_remote_autocommit = remote.get_autocommit()
        remote_committed = False
        local_missing = []
        remote_missing = []

        try:
            self.conn.autocommit(False)
            remote.autocommit(False)

            local_keys = self._read_existing_beifen_keys(self.conn)
            remote_keys = self._read_existing_beifen_keys(remote)

            local_missing = [
                row for row in backup_rows
                if self._backup_row_key(row) not in local_keys
            ]
            remote_missing = [
                row for row in backup_rows
                if self._backup_row_key(row) not in remote_keys
            ]

            if not local_missing and not remote_missing:
                self.conn.rollback()
                remote.rollback()
                QMessageBox.information(
                    self,
                    "无需恢复",
                    "本地和服务器已经包含该备份中的全部记录。"
                )
                return

            self._insert_beifen_rows(self.conn, local_missing)
            self._insert_beifen_rows(remote, remote_missing)

            # 先提交服务器；若随后本地提交失败，会撤销本次服务器新增。
            remote.commit()
            remote_committed = True
            self.conn.commit()

        except Exception as exc:
            try:
                self.conn.rollback()
            except Exception:
                pass
            if not remote_committed:
                try:
                    remote.rollback()
                except Exception:
                    pass
            else:
                # 补偿：只移除本次向服务器新增的记录，不影响原有数据。
                try:
                    remote.autocommit(False)
                    self._delete_specific_beifen_rows(remote, remote_missing)
                    remote.commit()
                except Exception as compensate_exc:
                    print(f"❌ 服务器恢复补偿失败：{compensate_exc}")

            QMessageBox.critical(self, "恢复失败", f"增量恢复失败：\n{exc}")
            return

        finally:
            try:
                self.conn.autocommit(old_local_autocommit)
            except Exception:
                pass
            try:
                remote.autocommit(old_remote_autocommit)
            except Exception:
                pass
            try:
                remote.close()
            except Exception:
                pass

        current_name = self.version_selector.currentText().strip() or "默认"
        self.refresh_version_selector(select_name=current_name)

        restored_names = sorted({
            str(row.get("name") or "")
            for row in local_missing + remote_missing
            if str(row.get("name") or "").strip()
        })
        name_text = "、".join(f"《{name}》" for name in restored_names) or "无"

        QMessageBox.information(
            self,
            "恢复成功",
            f"增量恢复完成。\n\n"
            f"本地补回：{len(local_missing)} 行\n"
            f"服务器补回：{len(remote_missing)} 行\n"
            f"涉及模板：{name_text}\n\n"
            "已有记录未被覆盖。恢复后的模板可在下拉框中重新选择。"
        )

    def _restore_remote_version_for_compensation(self, remote_conn, version_name, rows):
        """本地提交失败时，补偿恢复已经在服务器提交删除的模板。"""
        version_rows = [
            row for row in rows
            if str(row.get("name") or "") == str(version_name)
        ]
        remote_conn.autocommit(False)
        with remote_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_config_beifen WHERE name=%s",
                (version_name,)
            )
        self._insert_beifen_rows(remote_conn, version_rows)
        remote_conn.commit()

    def delete_version(self):
        """
        安全删除当前模板：
        1. 在程序根目录的“预定义配置备份”文件夹中创建完整删除前快照；
        2. 快照最多保留最近三份；
        3. 同时删除本地与服务器中的模板；
        4. 任一必要步骤失败则中止，并尽量补偿回滚。
        """
        if not self.is_admin:
            QMessageBox.warning(self, "权限不足", "只有管理员可以删除模板。")
            return

        if self._remote_sync_thread is not None and self._remote_sync_thread.isRunning():
            QMessageBox.information(
                self,
                "正在同步",
                "服务器同步尚未结束，请在同步完成后再删除模板。"
            )
            return

        version_name = self.version_selector.currentText().strip()
        if not version_name:
            QMessageBox.warning(self, "提示", "当前没有可删除的模板。")
            return
        if version_name == "默认":
            QMessageBox.warning(self, "禁止删除", "默认模板不能删除。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除模板",
            f"确定删除本地和服务器中的模板《{version_name}》吗？\n\n"
            "删除前会在程序根目录的“预定义配置备份”文件夹中保存完整配置快照，"
            "并只保留最近三份备份。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 必须先连上服务器，否则不开始删除，避免双端状态不一致。
        remote = self.get_remote_conn()
        if remote is None:
            QMessageBox.critical(
                self,
                "删除中止",
                "无法连接服务器。为避免只删除本地或只删除服务器，本次未执行删除。"
            )
            return

        try:
            backup_path, backup_rows = self._create_user_config_beifen_backup(
                deleting_version=version_name
            )
        except Exception as exc:
            try:
                remote.close()
            except Exception:
                pass
            QMessageBox.critical(
                self,
                "删除中止",
                f"删除前备份失败，因此没有删除任何模板：\n{exc}"
            )
            return

        self._ensure_conn()
        old_local_autocommit = self.conn.get_autocommit()
        old_remote_autocommit = remote.get_autocommit()
        fallback_name = ""
        remote_committed = False
        local_deleted_rows = 0
        remote_deleted_rows = 0

        try:
            self.conn.autocommit(False)
            remote.autocommit(False)

            # 服务器先进入事务但暂不提交。
            with remote.cursor() as rcur:
                rcur.execute(
                    "DELETE FROM user_config_beifen WHERE name=%s",
                    (version_name,)
                )
                remote_deleted_rows = rcur.rowcount

            with self.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_config_beifen WHERE name=%s",
                    (version_name,)
                )
                local_deleted_rows = cur.rowcount

                if local_deleted_rows <= 0:
                    raise RuntimeError(
                        f"本地没有找到模板《{version_name}》，可能已经被删除。"
                    )

                cur.execute(
                    "SELECT 1 FROM user_config_beifen WHERE name=%s LIMIT 1",
                    ("默认",)
                )
                if cur.fetchone():
                    fallback_name = "默认"
                else:
                    cur.execute("""
                        SELECT name
                        FROM user_config_beifen
                        WHERE name IS NOT NULL AND name <> ''
                        ORDER BY name
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    fallback_name = str((row or {}).get("name") or "").strip()

                # 删除后统一切换到安全模板，确保 user_config 与下拉框保持一致。
                cur.execute("DELETE FROM user_config")
                if fallback_name:
                    cur.execute("""
                        INSERT INTO user_config
                        (id, user_id, config_type, value,
                         title, object, subtitle, memo, content, name)
                        SELECT
                            id, user_id, config_type, `value`,
                            title, object, subtitle, memo, content, name
                        FROM user_config_beifen
                        WHERE name=%s
                        ORDER BY id
                    """, (fallback_name,))

            # 先提交服务器。若本地提交异常，下面会用文件快照补偿服务器。
            remote.commit()
            remote_committed = True
            self.conn.commit()

        except Exception as exc:
            try:
                self.conn.rollback()
            except Exception:
                pass

            if not remote_committed:
                try:
                    remote.rollback()
                except Exception:
                    pass
            else:
                try:
                    self._restore_remote_version_for_compensation(
                        remote_conn=remote,
                        version_name=version_name,
                        rows=backup_rows
                    )
                except Exception as compensate_exc:
                    print(f"❌ 服务器删除补偿失败：{compensate_exc}")

            QMessageBox.critical(
                self,
                "删除失败",
                f"模板删除失败：\n{exc}\n\n"
                f"删除前备份仍保留在：\n{backup_path}"
            )
            return

        finally:
            try:
                self.conn.autocommit(old_local_autocommit)
            except Exception:
                pass
            try:
                remote.autocommit(old_remote_autocommit)
            except Exception:
                pass
            try:
                remote.close()
            except Exception:
                pass

        if fallback_name:
            self._update_selected_product_config()
        self.refresh_version_selector(select_name=fallback_name or None)
        self.reload_and_render()

        switch_text = (
            f"当前已切换到《{fallback_name}》"
            if fallback_name else
            "当前已无可用模板"
        )
        QMessageBox.information(
            self,
            "删除成功",
            f"模板《{version_name}》已从本地和服务器删除。\n\n"
            f"本地删除：{local_deleted_rows} 行\n"
            f"服务器删除：{remote_deleted_rows} 行\n"
            f"{switch_text}\n\n"
            f"删除前备份：\n{backup_path}\n\n"
            "可使用“恢复备份”进行不覆盖现有数据的增量恢复。"
        )

    def _update_selected_product_config(self):
        """仅在用户成功改动活动配置后更新当前产品；页面初始化不调用。"""
        product_id = bianl.product_id
        if not product_id:
            return
        try:
            from modules.yudingyi.product_config import bind_product_to_current_config
            from modules.chanpinguanli.predefined_column import refresh_predefined_row

            bind_product_to_current_config(product_id)
            table = bianl.product_table
            if table is not None:
                for row, status in bianl.product_table_row_status.items():
                    if isinstance(status, dict) and status.get("product_id") == product_id:
                        refresh_predefined_row(table, row, product_id)
                        break
        except Exception as exc:
            QMessageBox.warning(
                self, "产品预定义关联更新失败",
                f"预定义已更新，但产品 {product_id} 的预定义配置关联未能更新：\n{exc}",
            )

    def ensure_initial_version_applied(self):
        """让下拉框指向 user_config 当前版本，正常情况下不复制数据。"""
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("SELECT name FROM user_config LIMIT 1")
            row = cur.fetchone()

        db_version = str(row.get("name") if row else "默认").strip() or "默认"

        idx = self.version_selector.findText(db_version)
        if idx != -1:
            self.version_selector.blockSignals(True)
            self.version_selector.setCurrentIndex(idx)
            self.version_selector.blockSignals(False)
            return

        # 当前主表版本已不存在时，才真正恢复默认版本。
        default_idx = self.version_selector.findText("默认")
        if default_idx != -1:
            self.version_selector.blockSignals(True)
            self.version_selector.setCurrentIndex(default_idx)
            self.version_selector.blockSignals(False)
            self.apply_version_silent("默认", refresh=False)

    # ==========================
    # 切换版本（覆盖 user_config）
    # ==========================
    def apply_version_silent(self, version_name, refresh=True):
        """静默切换版本；refresh=False 用于启动阶段，避免重复渲染。"""
        if not version_name:
            return

        self._ensure_conn()
        with self.conn.cursor() as cur:
            # 清空 user_config
            cur.execute("DELETE FROM user_config")

            # 覆盖写入
            cur.execute("""
                INSERT INTO user_config
                (id, user_id, config_type, value, title, object, subtitle, memo, content, name)
                SELECT 
                    id, user_id, config_type, `value`,
                    title, object, subtitle, memo, content, name
                FROM user_config_beifen
                WHERE name=%s
                ORDER BY id
            """, (version_name,))

        if refresh:
            self.reload_and_render()

    def apply_version(self):
        version_name = self.version_selector.currentText()
        if not version_name:
            return

        reply = QMessageBox.question(
            self, "确认切换版本",
            f"是否切换到版本：{version_name}？\n",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._ensure_conn()
        with self.conn.cursor() as cur:
            # 1. 清空 user_config
            cur.execute("DELETE FROM user_config")

            # 2. 从备份表中按 name 完整复制（包括 id / user_id / config_type 等）
            cur.execute("""
                INSERT INTO user_config
                (id, user_id, config_type, value, title, object, subtitle, memo, content, name)
                SELECT 
                    id, 
                    user_id, 
                    config_type, 
                    `value`, 
                    title, 
                    object, 
                    subtitle, 
                    memo, 
                    content, 
                    name
                FROM user_config_beifen
                WHERE name=%s
                ORDER BY id
            """, (version_name,))

        self._update_selected_product_config()
        QMessageBox.information(self, "成功", f"已切换到版本：{version_name}。后续强度计算将使用此配置。")
        self.reload_and_render()
        run_predefined_save_sync()

    # ==========================
    # 保存为新版本（管理员）
    # ==========================
    def _write_rows_to_remote_beifen(self, remote_conn, version_name, rows):
        """
        用【本地 user_config 的行数据】
        生成【远程 user_config_beifen 的某个版本】
        """
        with remote_conn.cursor() as cur:
            # 1. 只删除该版本
            cur.execute(
                "DELETE FROM user_config_beifen WHERE name=%s",
                (version_name,)
            )

            # 2. 批量写入；避免每一行都产生一次网络往返。
            insert_sql = """
                INSERT INTO user_config_beifen
                (id, user_id, config_type, value,
                 title, object, subtitle, memo, content, name)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """

            cur.executemany(insert_sql, [
                (
                    r["id"],
                    r["user_id"],
                    r["config_type"],
                    r["value"],
                    r["title"],
                    r["object"],
                    r["subtitle"],
                    r["memo"],
                    r["content"],
                    version_name
                )
                for r in rows
            ])

            print(f"☁️ 远程版本《{version_name}》批量写入 {len(rows)} 行")

    def save_to_beifen(self):
        """保存为新版本：先输入版本名 → 保存当前编辑态 → 本地+远程写入 beifen"""

        # 1) 先输入版本名（顺序修正）
        name, ok = QInputDialog.getText(self, "保存为新版本", "请输入版本名称：")
        if not ok or not name.strip():
            return
        name = name.strip()

        # 2) 检查名称是否已存在（本地为准，不允许重复）
        if self.version_exists(name):
            QMessageBox.warning(self, "名称冲突", f"版本《{name}》已存在，请更换其他名称。")
            return

        ok = self.save_all_tables(
            silent=True,
            sync_local_beifen=False,
            sync_remote=False
        )
        if not ok:
            return
        # 4) 读取【本地 user_config】作为事实源（后续本地/远程都用它）
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id, user_id, config_type, value,
                    title, object, subtitle, memo, content
                FROM user_config
                ORDER BY id
            """)
            local_rows = cur.fetchall()

        if not local_rows:
            QMessageBox.warning(self, "提示", "user_config 为空，无法保存新版本。")
            return

        # 5) 本地写入 user_config_beifen：只写这个新版本 name
        try:
            with self.conn.cursor() as lcur:
                # 保守起见：如果异常情况下已经存在同名记录，先删（你已做过 exists 校验，这里是兜底）
                lcur.execute("DELETE FROM user_config_beifen WHERE name=%s", (name,))

                insert_sql = """
                    INSERT INTO user_config_beifen
                    (id, user_id, config_type, value,
                     title, object, subtitle, memo, content, name)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """
                lcur.executemany(insert_sql, [
                    (
                        r["id"], r["user_id"], r["config_type"], r["value"],
                        r["title"], r["object"], r["subtitle"], r["memo"],
                        r["content"], name
                    )
                    for r in local_rows
                ])
                lcur.execute("UPDATE user_config SET name=%s", (name,))
            print(f"💾 已保存版本《{name}》到本地数据库（{len(local_rows)} 行）")

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"本地保存版本失败：{e}")
            return

        self._update_selected_product_config()

        # 6) 远程写入：用【本地 local_rows】生成远程 user_config_beifen（关键修正点）
        remote = self.get_remote_conn()
        if remote:
            try:
                with remote.cursor() as rcur:
                    rcur.execute("DELETE FROM user_config_beifen WHERE name=%s", (name,))

                    insert_sql = """
                        INSERT INTO user_config_beifen
                        (id, user_id, config_type, value,
                         title, object, subtitle, memo, content, name)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """
                    rcur.executemany(insert_sql, [
                        (
                            r["id"], r["user_id"], r["config_type"], r["value"],
                            r["title"], r["object"], r["subtitle"], r["memo"],
                            r["content"], name
                        )
                        for r in local_rows
                    ])

                remote.commit()
                print(f"☁️ 已同步版本《{name}》到远程服务器（{len(local_rows)} 行）")

            except Exception as e:
                print("⚠️ 远程写入失败：", e)

            finally:
                try:
                    remote.close()
                except:
                    pass
        else:
            print("⚠️ 未连接远程服务器，本次版本仅保存到本地")

        # 7) 刷新下拉并选中新版本
        self.refresh_ui_after_db_changed(select_name=name, keep_current=True)

        QMessageBox.information(self, "成功", f"已成功保存模板并切换到：{name}")
        run_predefined_save_sync()

    def _table_to_data(self, tbl: QTableWidget):
        """把 QTableWidget 当前内容转成二维数组"""
        table_data = []
        for r in range(tbl.rowCount()):
            row_data = []
            for c in range(tbl.columnCount()):
                item = tbl.item(r, c)
                row_data.append(item.text() if item else "")
            table_data.append(row_data)
        return table_data

    def _set_current_user_config_version_name(self, version_name):
        """
        另存模板后，把当前 user_config 的 name 改成新模板名。
        这样数据库主表也会显示当前已切换到新模板。
        """
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE user_config SET name=%s",
                (version_name,)
            )
    def sync_remote_to_local(self):
        """后台同步远程备份表；该方法立即返回，不阻塞主界面。"""
        if self._remote_sync_thread is not None and self._remote_sync_thread.isRunning():
            return

        self.btn_sync_remote.setEnabled(False)
        self.btn_sync_remote.setText("同步中…")
        if self.is_admin:
            self.btn_delete_version.setEnabled(False)
            self.btn_restore_backup.setEnabled(False)
        self.sync_status_label.setText("正在检查服务器版本")

        self._remote_sync_thread = QThread(self)
        self._remote_sync_worker = RemoteBackupSyncWorker(
            local_db_config=self.db_config,
            remote_db_config=self.remote_db_config
        )
        self._remote_sync_worker.moveToThread(self._remote_sync_thread)

        self._remote_sync_thread.started.connect(self._remote_sync_worker.run)
        self._remote_sync_worker.finished.connect(self._on_remote_sync_finished)
        self._remote_sync_worker.finished.connect(self._remote_sync_thread.quit)
        self._remote_sync_worker.finished.connect(self._remote_sync_worker.deleteLater)
        self._remote_sync_thread.finished.connect(self._remote_sync_thread.deleteLater)
        self._remote_sync_thread.finished.connect(self._clear_remote_sync_refs)

        self._remote_sync_thread.start()

    def _on_remote_sync_finished(self, success, message, changed_row_count):
        self.btn_sync_remote.setEnabled(True)
        self.btn_sync_remote.setText("同步服务器")
        self.btn_delete_version.setEnabled(self.is_admin)
        self.btn_restore_backup.setEnabled(self.is_admin)
        self.sync_status_label.setText(message)

        if success:
            # 后台同步只修改备份表，因此只刷新版本下拉框，不重建右侧大量控件。
            current_name = self.version_selector.currentText().strip() or "默认"
            self.refresh_version_selector(select_name=current_name)
            print(f"✅ {message}，涉及 {changed_row_count} 行")
        else:
            print(f"⚠️ {message}")

    def _clear_remote_sync_refs(self):
        self._remote_sync_worker = None
        self._remote_sync_thread = None

    # ==========================
    # 以下为你的原逻辑（未改动）
    # ==========================

    def _normalize_content(self, s):
        if s is None:
            return ""
        s = str(s).replace("\r", " ").replace("\n", " ").replace("\t", " ")
        return re.sub(r'\s+', ' ', s).strip()

    def _clean_placeholders(self, s):
        if not s:
            return s
        s = re.sub(r'"\s*(\{\d+\}|\[\d+\])\s*"', r'\1', s)
        s = re.sub(r"'\s*(\{\d+\}|\[\d+\])\s*'", r'\1', s)
        return s

    def _parse_value_field(self, raw):
        if raw is None:
            return ''
        if isinstance(raw, (list, dict, bool)):
            return raw
        s = str(raw).strip()
        if not s:
            return ''
        try:
            return json.loads(s)
        except:
            pass
        try:
            return ast.literal_eval(s)
        except:
            pass
        if s.lower() in ('true', 'false'):
            return s.lower() == 'true'
        try:
            if '.' in s:
                return float(s)
            return int(s)
        except:
            pass
        return s

    # ==========================
    # 页面渲染（保持不变）
    # ==========================
    # ==========================
    # 页面清理
    # ==========================
    def clear_render(self, reset_cache=True):
        """
        清空右侧内容区。

        reset_cache=True:
            用于重新加载数据库，此时清空所有未保存缓存。

        reset_cache=False:
            用于切换左侧分支，此时保留 rows_cache / dirty_ids / dirty_table_ids，
            只清空当前右侧控件。
        """
        if not hasattr(self, "container_layout"):
            return

        # 切换分支前，先把当前页表格内容存入缓存
        if not reset_cache:
            self._cache_current_page_tables()

        while self.container_layout.count():
            item = self.container_layout.takeAt(0)

            w = item.widget()
            child_layout = item.layout()

            if w is not None:
                w.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

        # 当前页面控件已经清掉，table_widgets 不能继续保留旧控件引用
        self.table_widgets.clear()

        if reset_cache:
            self.rows_cache.clear()
            self.dirty_ids.clear()
            self.dirty_table_ids.clear()

    def _get_display_value(self, row, db_value):
        """
        渲染界面时使用：
        1. 如果该 id 有未保存缓存，优先显示缓存值；
        2. 否则显示数据库值。
        """
        row_id = row.get("id")

        table_entry = self.rows_cache.get((row_id, "table"))
        if table_entry and "value" in table_entry:
            return table_entry["value"]

        normal_entry = self.rows_cache.get((row_id, "content_placeholders"))
        if normal_entry and "value" in normal_entry:
            return normal_entry["value"]

        return db_value
    def _cache_current_page_tables(self):
        """
        切换左侧分支前，把当前页面上的表格内容缓存起来。
        这样表格修改后切换分支，再切回来不会丢。
        """
        for row_id, tbl in list(self.table_widgets.items()):
            if tbl is None or sip.isdeleted(tbl):
                continue

            self.rows_cache[(row_id, "table")] = {
                "id": row_id,
                "type": "table",
                "value": self._table_to_data(tbl)
            }
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)

            w = item.widget()
            child_layout = item.layout()

            if w is not None:
                w.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)


    # ==========================
    # 重新加载：构建左侧树 + 默认显示第一个配置
    # ==========================
    def reload_and_render(self):
        """
        新版渲染逻辑：
        1. 从 user_config 读取所有行；
        2. 按 title / subtitle / object / content 分组；
        3. 左侧树只显示 title -> subtitle -> object；
        4. 右侧只显示当前选中的 object。
        """
        self.clear_render(reset_cache=True)

        if hasattr(self, "tree"):
            self.tree.clear()

        # load_user_config_rows 已完成自然排序，不再重复排序。
        self.all_rows = self.load_user_config_rows()

        self.grouped_rows = defaultdict(list)

        for row in self.all_rows:
            key = (
                row.get("title") or "",
                row.get("subtitle") or "",
                row.get("object") or "",
                row.get("content") or ""
            )
            self.grouped_rows[key].append(row)

        self._build_config_tree()

        first_leaf = self._get_first_leaf_item()
        if first_leaf:
            # setCurrentItem 会触发 currentItemChanged；这里先阻断信号，随后只渲染一次。
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(first_leaf)
            self.tree.blockSignals(False)

            key = first_leaf.data(0, Qt.UserRole)
            if key:
                self.current_object_key = key
                self.render_selected_config_object(key)
        else:
            lbl = QLabel("暂无配置数据。")
            lbl.setFont(QFont("Microsoft YaHei", 11))
            self.container_layout.addWidget(lbl)
    # ==========================
    # 构建左侧树
    # ==========================
    def _build_config_tree(self):
        """
        左侧目录结构：
        title
          └ subtitle
               └ object

        现在三层节点都可以点击：
        - 点击 title：显示该 title 下所有配置
        - 点击 subtitle：显示该 subtitle 下所有配置
        - 点击 object：显示该 object 下所有配置
        """
        if not hasattr(self, "tree"):
            return

        self.tree.blockSignals(True)
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()

        self.tree.setSortingEnabled(False)

        title_items = {}
        subtitle_items = {}
        object_items = {}

        for row in self.all_rows:
            title = row.get("title") or ""
            subtitle = row.get("subtitle") or ""
            obj = row.get("object") or ""

            if not title and not subtitle and not obj:
                continue

            # ==========================
            # 一级：title
            # ==========================
            title_key = ("title", title, "", "")

            if title not in title_items:
                title_item = QTreeWidgetItem([str(title)])
                title_item.setExpanded(True)

                # 关键：title 节点也存 key
                title_item.setData(0, Qt.UserRole, title_key)

                self.tree.addTopLevelItem(title_item)
                title_items[title] = title_item

            # ==========================
            # 二级：subtitle
            # ==========================
            subtitle_key = (title, subtitle)

            if subtitle_key not in subtitle_items:
                subtitle_item = QTreeWidgetItem([str(subtitle)])
                subtitle_item.setExpanded(True)

                # 关键：subtitle 节点也存 key
                subtitle_item.setData(0, Qt.UserRole, ("subtitle", title, subtitle, ""))

                title_items[title].addChild(subtitle_item)
                subtitle_items[subtitle_key] = subtitle_item

            # ==========================
            # 三级：object
            # ==========================
            object_key = (title, subtitle, obj)

            if object_key not in object_items:
                obj_item = QTreeWidgetItem([str(obj)])

                # object 节点存完整 key
                obj_item.setData(0, Qt.UserRole, ("object", title, subtitle, obj))

                subtitle_items[subtitle_key].addChild(obj_item)
                object_items[object_key] = obj_item

        # title/subtitle 创建时已经 setExpanded(True)，无需再遍历 expandAll。
        self.tree.setUpdatesEnabled(True)
        self.tree.blockSignals(False)
        self.tree.viewport().update()
    def _get_first_leaf_item(self):
        """
        获取左侧树第一个 object 节点。
        """
        if not hasattr(self, "tree"):
            return None

        for i in range(self.tree.topLevelItemCount()):
            title_item = self.tree.topLevelItem(i)

            for j in range(title_item.childCount()):
                subtitle_item = title_item.child(j)

                for k in range(subtitle_item.childCount()):
                    return subtitle_item.child(k)

        return None

    # ==========================
    # 左侧树点击事件
    # ==========================
    def _on_config_tree_item_clicked(self, item, column):
        """
        点击左侧任意层级节点后，右侧显示对应范围配置：
        - title：显示该 title 下所有配置
        - subtitle：显示该 subtitle 下所有配置
        - object：显示该 object 下所有配置
        """
        if item is None:
            return

        key = item.data(0, Qt.UserRole)

        if not key:
            return

        self.current_object_key = key
        self.render_selected_config_object(key)

    # ==========================
    # 右侧渲染指定配置项
    # ==========================
    def render_selected_config_object(self, object_key):
        """
        根据左侧选中的节点渲染右侧内容。

        object_key 支持：
        - ("title", title, "", "")
        - ("subtitle", title, subtitle, "")
        - ("object", title, subtitle, object)

        兼容旧格式：
        - (title, subtitle, object)
        """
        self.clear_render(reset_cache=False)

        # ==========================
        # 兼容旧 key
        # ==========================
        if not object_key:
            return

        if len(object_key) == 3:
            scope = "object"
            title, subtitle, obj = object_key
        else:
            scope, title, subtitle, obj = object_key

        matched_groups = []

        for (t, s, o, content_raw), row_group in self.grouped_rows.items():

            if scope == "title":
                matched = (t == title)

            elif scope == "subtitle":
                matched = (t == title and s == subtitle)

            else:
                matched = (t == title and s == subtitle and o == obj)

            if matched:
                matched_groups.append((t, s, o, content_raw, row_group))

        # 右侧配置块必须优先按照数据库 id 排列。
        # 不能先按 content 排序，因为每一条不同的 content 会形成独立分组，
        # 这会导致 1.2.3.7.1 显示在 1.2.3.4.1 前面。
        matched_groups.sort(
            key=lambda x: (
                self._natural_text_sort_key(x[0]),
                self._natural_text_sort_key(x[1]),
                self._natural_text_sort_key(x[2]),
                self._group_id_sort_key(x[4]),
                self._natural_text_sort_key(x[3]),
            )
        )

        if not matched_groups:
            lbl = QLabel("当前配置项无数据。")
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.container_layout.addWidget(lbl, 0, Qt.AlignLeft | Qt.AlignTop)
            return

        last_section_key = None

        for t, s, o, content_raw, row_group in matched_groups:

            # ==========================
            # 点击 title/subtitle 时，右侧加一个分组标题
            # 避免所有配置直接堆在一起看不清
            # ==========================
            section_key = (t, s, o)

            if scope != "object" and section_key != last_section_key:
                if scope == "title":
                    section_text = f"{s} / {o}" if s else str(o)
                elif scope == "subtitle":
                    section_text = str(o)
                else:
                    section_text = ""

                if section_text:
                    section_label = QLabel(section_text)
                    section_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
                    section_label.setStyleSheet("""
                        QLabel {
                            color: #1f3b57;
                            background: #f2f6fb;
                            border: 1px solid #d7e1ef;
                            padding: 6px 8px;
                            margin-top: 8px;
                        }
                    """)
                    section_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    self.container_layout.addWidget(section_label, 0, Qt.AlignLeft | Qt.AlignTop)

                last_section_key = section_key

            content = self._normalize_content(content_raw)
            content = self._clean_placeholders(content)

            row_group = sorted(row_group, key=self._id_sort_key)

            parsed_values_group = []
            for r in row_group:
                db_value = self._parse_value_field(r.get("value"))
                display_value = self._get_display_value(r, db_value)
                parsed_values_group.append(display_value)

            is_table = any(
                isinstance(v, list)
                and v
                and all(isinstance(row_i, list) for row_i in v)
                for v in parsed_values_group
            )

            is_checkbox_grid = (
                    not content
                    and row_group
                    and all(
                self._is_checkbox_row(r, v)
                for r, v in zip(row_group, parsed_values_group)
            )
            )

            if is_table:
                self._render_table_config_block(content, row_group, parsed_values_group)
                continue

            if is_checkbox_grid:
                self._render_checkbox_grid(row_group, parsed_values_group)
                continue

            if content:
                self._render_content_with_placeholders(
                    self.container_layout,
                    row_group,
                    content,
                    parsed_values_group
                )
            else:
                self._render_plain_rows(row_group, parsed_values_group)

        # 布局会自动更新尺寸，避免对包含大量控件的容器执行一次昂贵的 adjustSize。

    # ==========================
    # 表格类配置渲染
    # ==========================
    def _render_table_config_block(self, content, row_group, parsed_values_group):
        """
        渲染 value 为二维数组的配置。
        """
        if content:
            lbl = QLabel(content)
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#111; margin-bottom:8px;")
            self.container_layout.addWidget(lbl)

        for row, parsed_value in zip(row_group, parsed_values_group):
            if not (
                    isinstance(parsed_value, list)
                    and parsed_value
                    and all(isinstance(r_i, list) for r_i in parsed_value)
            ):
                continue

            row_count = len(parsed_value)
            col_count = max(len(r) for r in parsed_value)

            table = QTableWidget(row_count, col_count)
            table.setUpdatesEnabled(False)
            table.setFont(QFont("Microsoft YaHei", 10))
            table.setAlternatingRowColors(True)
            table.setShowGrid(True)
            table.setSelectionMode(QAbstractItemView.NoSelection)

            # 不显示默认行号列
            table.verticalHeader().setVisible(False)

            # 这里保留横向表头隐藏，和你截图中更接近
            table.horizontalHeader().setVisible(False)

            for r_idx, row_data in enumerate(parsed_value):
                for c_idx in range(col_count):
                    val = row_data[c_idx] if c_idx < len(row_data) else ""
                    item = QTableWidgetItem(str(val))
                    # 表格 value 过长时，悬停显示完整内容。
                    item.setToolTip(str(val))
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setFont(QFont("Microsoft YaHei", 10))

                    if not self.is_admin:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                    table.setItem(r_idx, c_idx, item)

            table.setUpdatesEnabled(True)

            if self.is_admin:
                table.setEditTriggers(QTableWidget.AllEditTriggers)
                table.itemChanged.connect(partial(self._mark_table_dirty, row.get("id")))
            else:
                table.setEditTriggers(QTableWidget.NoEditTriggers)

            row_id = row.get("id")
            self.table_widgets[row_id] = table

            # 保留已有缓存值，不能只存 widget，否则切换回来会把修改值覆盖掉
            old_entry = self.rows_cache.get((row_id, "table"), {})
            cached_value = old_entry.get("value", parsed_value)

            self.rows_cache[(row_id, "table")] = {
                "id": row_id,
                "type": "table",
                "widget": table,
                "value": cached_value
            }

            table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.container_layout.addWidget(table, 0, Qt.AlignTop)
            QTimer.singleShot(0, lambda t=table: self._fit_table_size(t))

            # 表格右侧/下方显示红色 id
            id_label = QLabel(f"{{{row_id}}}")
            id_label.setFont(QFont("Microsoft YaHei", 9))
            id_label.setStyleSheet("color:red;")
            id_label.setAlignment(Qt.AlignRight)
            self.container_layout.addWidget(id_label)

    # ==========================
    # 纯复选框网格渲染
    # ==========================
    def _render_checkbox_grid(self, row_group, parsed_values_group):
        """
        渲染类似截图 3 的复选框矩阵。
        """
        paired_rows = sorted(
            zip(row_group, parsed_values_group),
            key=lambda pair: self._id_sort_key(pair[0])
        )
        row_group = [pair[0] for pair in paired_rows]
        parsed_values_group = [pair[1] for pair in paired_rows]

        if not row_group:
            return

        items_per_col = 25
        col_count = max(1, (len(row_group) + items_per_col - 1) // items_per_col)
        row_count = min(items_per_col, len(row_group))

        table = QTableWidget(row_count, col_count)
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setShowGrid(True)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        for idx, row in enumerate(row_group):
            col = idx // items_per_col
            r = idx % items_per_col

            row_id = row.get("id")
            val = parsed_values_group[idx]

            cb = QCheckBox(str(row_id))
            cb.setFont(QFont("Microsoft YaHei", 10))

            if isinstance(val, bool):
                checked = val
            else:
                checked = str(val).strip().lower() in ("1", "true", "yes", "y", "√")

            cb.setChecked(checked)

            if self.is_admin:
                cb.stateChanged.connect(partial(self._on_checkbox_changed, row_id))
            else:
                cb.setEnabled(False)

            self._cache_or_update_row(row_id, checked, "content_placeholders")

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(36, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            cell_layout.addWidget(cb)

            table.setCellWidget(r, col, cell)

        for c in range(col_count):
            table.setColumnWidth(c, 130)

        for r in range(row_count):
            table.setRowHeight(r, 34)

        table.setFixedHeight(min(700, row_count * 34 + 4))
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.container_layout.addWidget(table, 0, Qt.AlignTop)

        id_label = QLabel(f"{{{row_group[0].get('id')}}}")
        id_label.setFont(QFont("Microsoft YaHei", 9))
        id_label.setStyleSheet("color:red;")
        id_label.setAlignment(Qt.AlignRight)
        self.container_layout.addWidget(id_label)

    # ==========================
    # 无 content 的普通行渲染
    # ==========================
    def _render_plain_rows(self, row_group, parsed_values_group):
        """
        用于 content 为空，但 value 不是表格、也不是复选框网格的情况。
        """
        for row, val in zip(row_group, parsed_values_group):
            h = QHBoxLayout()
            h.setContentsMargins(0, 6, 0, 6)
            h.setSpacing(8)

            name = (
                    row.get("memo")
                    or row.get("content")
                    or row.get("object")
                    or "配置值"
            )

            lbl = QLabel(str(name))
            lbl.setFont(QFont("Microsoft YaHei", 11))
            h.addWidget(lbl)

            le = ResizableLineEdit(
                str(val),
                default_width=120,
                min_width=40,
                max_width=900
            )
            le.setFixedHeight(26)
            le.setFont(QFont("Microsoft YaHei", 10))

            row_id = row.get("id")

            if self.is_admin:
                le.textChanged.connect(partial(self._update_single_value, row_id))
            else:
                le.setReadOnly(True)
                le.setStyleSheet("color:gray;")

            h.addWidget(le)

            id_label = QLabel(f"{{{row_id}}}")
            id_label.setFont(QFont("Microsoft YaHei", 9))
            id_label.setStyleSheet("color:red;")
            h.addWidget(id_label)

            h.addStretch(1)

            wrap = QWidget()
            wrap.setLayout(h)
            self.container_layout.addWidget(wrap)

    def _mark_table_dirty(self, row_id, item=None):
        """
        表格一改动，立即把表格内容缓存起来，并同步完整内容悬停提示。
        """
        self.dirty_table_ids.add(row_id)

        # setToolTip 也可能触发 itemChanged，因此临时阻断表格信号，避免递归。
        if item is not None:
            item_table = item.tableWidget()
            if item_table is not None:
                old_blocked = item_table.blockSignals(True)
                try:
                    item.setToolTip(item.text())
                finally:
                    item_table.blockSignals(old_blocked)

        tbl = self.table_widgets.get(row_id)
        if tbl is None or sip.isdeleted(tbl):
            return

        self.rows_cache[(row_id, "table")] = {
            "id": row_id,
            "type": "table",
            "widget": tbl,
            "value": self._table_to_data(tbl)
        }
    # ==========================
    # 占位符渲染（保持不变）
    # ==========================
    def _is_bool_like(self, v):
        if isinstance(v, bool):
            return True

        s = str(v).strip().lower()

        # 不再把 "1" / "0" 当成复选框，
        # 因为配置数值里经常会出现 1、0。
        return s in ("true", "false", "yes", "no", "y", "n", "√")

    @staticmethod
    def _chinese_number_to_int(text):
        """
        将中文序号转换为整数。

        支持：一、二、十、十一、二十、二十一、一百零二等；
        同时兼容“〇”和“两”。
        """
        if text is None:
            return None

        s = str(text).strip()
        if not s:
            return None

        # 少量常见简写先展开，便于统一计算。
        s = s.replace("廿", "二十").replace("卅", "三十").replace("卌", "四十")

        digit_map = {
            "零": 0, "〇": 0,
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }
        unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

        if not all(ch in digit_map or ch in unit_map for ch in s):
            return None

        # “二〇二六”这类不带单位的写法按逐位数字处理。
        if not any(ch in unit_map for ch in s):
            try:
                return int("".join(str(digit_map[ch]) for ch in s))
            except (KeyError, ValueError):
                return None

        total = 0
        section = 0
        number = 0

        for ch in s:
            if ch in digit_map:
                number = digit_map[ch]
                continue

            unit = unit_map[ch]
            if unit == 10000:
                section += number
                total += section * unit
                section = 0
                number = 0
            else:
                # “十”“十二”开头时，十位默认按一计算。
                if number == 0:
                    number = 1
                section += number * unit
                number = 0

        return total + section + number

    def _natural_text_sort_key(self, text):
        """
        自然排序，同时支持阿拉伯数字序号和中文序号。

        示例：
        一、总则
        二、管壳式热交换器
        三、容器
        十、其他

        以及：
        1.材料负偏差
        2.圆筒
        11.拉杆
        1.3.2.10
        """
        if text is None:
            return []

        s = str(text).strip()
        key = []

        chinese_chars = "零〇一二两三四五六七八九十百千万廿卅卌"

        # 识别常见中文章节序号：
        # 二、标题 / 二.标题 / （二）标题 / 第二章 标题
        chinese_prefix_patterns = (
            rf'^\s*第([{chinese_chars}]+)(?:章|节|篇|卷|部分|项|条|类)\s*',
            rf'^\s*[（(]([{chinese_chars}]+)[）)]\s*[、.．:：-]?\s*',
            rf'^\s*([{chinese_chars}]+)\s*[、.．:：]\s*',
        )

        for pattern in chinese_prefix_patterns:
            match = re.match(pattern, s)
            if not match:
                continue

            number = self._chinese_number_to_int(match.group(1))
            if number is not None:
                # 与阿拉伯数字使用相同的数值类型，确保二排在三前面。
                key.append((0, (number,)))
                s = s[match.end():].strip()
            break

        # 拆出阿拉伯数字段：
        # "12.旁路挡板" -> ["", "12", ".旁路挡板"]
        # "1.3.2.10" -> ["", "1.3.2.10", ""]
        parts = re.split(r'(\d+(?:\.\d+)*)', s)

        for part in parts:
            if part == "":
                continue

            if re.fullmatch(r'\d+(?:\.\d+)*', part):
                nums = tuple(int(x) for x in part.split(".") if x != "")
                key.append((0, nums))
            else:
                key.append((1, part))

        return key

    def _row_tree_sort_key(self, row):
        """
        全局数据排序专用：
        title -> subtitle -> object -> id -> content。

        同一个 object 内必须把 id 放在 content 前面，确保右侧内容严格按照
        1.2.3.1、1.2.3.2、1.2.3.4.1、1.2.3.7.1 的顺序显示。
        """
        return (
            self._natural_text_sort_key(row.get("title")),
            self._natural_text_sort_key(row.get("subtitle")),
            self._natural_text_sort_key(row.get("object")),
            self._id_sort_key(row),
            self._natural_text_sort_key(row.get("content")),
        )

    def _id_sort_key(self, row):
        """
        按 id 进行统一的层级自然排序。

        示例：
        1.2.3.4.1 < 1.2.3.7.1 < 1.2.3.10.1

        返回值始终使用 _natural_text_sort_key 的统一结构，避免原先由 int 和
        str 混合组成的列表在部分 id 格式下出现比较异常。
        """
        return self._natural_text_sort_key(row.get("id"))

    def _group_id_sort_key(self, row_group):
        """
        获取一个 content 分组的最小 id，供右侧配置块排序使用。

        grouped_rows 的键中包含 content，因此不同内容会成为不同配置块。
        若配置块先按 content 排序，即使块内行已经按 id 排序，块与块之间仍会乱序。
        """
        if not row_group:
            return self._natural_text_sort_key("")

        first_row = min(row_group, key=self._id_sort_key)
        return self._id_sort_key(first_row)

    def _is_checkbox_row(self, row, value):
        """
        判断该行是否应该作为 {n} 复选框行。

        优先使用 config_type / memo 等字段判断；
        如果你的数据库里有明确字段，比如 config_type='checkbox'，
        可以在这里继续加。
        """
        config_type = str(row.get("config_type", "") or "").lower()
        memo = str(row.get("memo", "") or "").lower()

        if config_type in ("checkbox", "bool", "boolean", "check"):
            return True

        if "checkbox" in memo or "复选" in memo or "勾选" in memo:
            return True

        # 兜底：true / false / √ 这类值认为是复选框
        if isinstance(value, bool):
            return True

        sval = str(value).strip().lower()
        return sval in ("true", "false", "yes", "no", "y", "n", "√")

    def _map_placeholders_to_rows(self, row_group, parsed_values, placeholders):
        """
        稳定匹配规则：
        - {1} -> 第 1 个复选框行
        - {2} -> 第 2 个复选框行
        - [1] -> 第 1 个输入框行
        - [2] -> 第 2 个输入框行

        这样不会因为 content 中 {1}、[1] 混排，或者 value=1/0 被误判而乱序。
        """
        # 先按 id 自然排序，保证同一组内部顺序稳定
        indexed_rows = list(enumerate(row_group))
        indexed_rows.sort(key=lambda x: self._id_sort_key(x[1]))

        checkbox_indices = []
        input_indices = []

        for original_idx, row in indexed_rows:
            value = parsed_values[original_idx]

            if self._is_checkbox_row(row, value):
                checkbox_indices.append(original_idx)
            else:
                input_indices.append(original_idx)

        mapping = []

        for ph in placeholders:
            m = re.search(r'\d+', ph)
            num = int(m.group()) if m else 1

            if ph.startswith("{"):
                # {1}, {2}, ...
                if 1 <= num <= len(checkbox_indices):
                    mapping.append(checkbox_indices[num - 1])
                elif checkbox_indices:
                    mapping.append(checkbox_indices[-1])
                else:
                    mapping.append(0)

            else:
                # [1], [2], ...
                if 1 <= num <= len(input_indices):
                    mapping.append(input_indices[num - 1])
                elif input_indices:
                    mapping.append(input_indices[-1])
                else:
                    mapping.append(0)

        return mapping

    def _make_red_id_label(self, row_id):
        """
        生成红色配置 id 标签，例如 {1.3.2.1}
        """
        id_label = QLabel(f"{{{row_id}}}")
        id_label.setFont(QFont("Microsoft YaHei", 9))
        id_label.setStyleSheet("color:red;")
        id_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        return id_label

    def _render_content_with_placeholders(self, vobj_layout, row_group, content, parsed_values):
        """
        渲染普通自然语句配置：
        - {1} 渲染为 QCheckBox
        - [1] 渲染为 QLineEdit
        - 每个控件后面显示对应 row_id，例如 {1.3.2.1}
        """

        if not content:
            return

        content = re.sub(r'\s+', ' ', str(content)).strip()
        token_pattern = re.compile(r"(\{\d+\}|\[\d+\])")
        tokens = token_pattern.split(content)
        placeholders = [tok for tok in tokens if token_pattern.fullmatch(tok)]

        ph_to_rowidx = self._map_placeholders_to_rows(row_group, parsed_values, placeholders)

        h = QHBoxLayout()
        h.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        h.setSpacing(4)
        h.setContentsMargins(0, 0, 0, 0)

        text_font = QFont("Microsoft YaHei", 9)
        ph_idx = 0

        # 防止同一行里多个占位符映射到同一个 row_id 时，重复显示太多次
        shown_id_set = set()

        for tok in tokens:
            if token_pattern.fullmatch(tok):
                rindex = ph_to_rowidx[ph_idx]
                ph_idx += 1

                row = row_group[rindex]
                parsed_val = parsed_values[rindex]
                row_id = row["id"]

                if tok.startswith("{"):
                    cb = QCheckBox()
                    cb.setFont(text_font)

                    checked = False
                    if isinstance(parsed_val, bool):
                        checked = parsed_val
                    else:
                        sval = str(parsed_val).lower().strip()
                        checked = sval in ("1", "true", "yes", "y", "√")

                    cb.setChecked(checked)

                    if self.is_admin:
                        cb.stateChanged.connect(partial(self._on_checkbox_changed, row_id))
                    else:
                        cb.setEnabled(False)

                    h.addWidget(cb)
                    self._cache_or_update_row(row_id, checked, "content_placeholders")

                else:
                    le = ResizableLineEdit(
                        str(parsed_val),
                        default_width=70,
                        min_width=35,
                        max_width=900
                    )
                    le.setFont(text_font)
                    le.setFixedHeight(22)
                    le.setAlignment(Qt.AlignCenter)

                    if self.is_admin:
                        le.textChanged.connect(partial(self._update_single_value, row_id))
                    else:
                        le.setReadOnly(True)
                        le.setStyleSheet("color:gray;")

                    h.addWidget(le)
                    self._cache_or_update_row(row_id, parsed_val, "content_placeholders")

                # 关键：普通配置也显示红色 id
                if row_id not in shown_id_set:
                    h.addWidget(self._make_red_id_label(row_id))
                    shown_id_set.add(row_id)

            else:
                if tok:
                    lbl = QLabel(tok)
                    lbl.setFont(text_font)
                    lbl.setStyleSheet("color:#111;")
                    lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                    h.addWidget(lbl)

        h.addStretch(1)

        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setLayout(h)

        vobj_layout.addWidget(wrap, 0, Qt.AlignTop)
    # ==========================
    # 用户修改缓存
    # ==========================
    def _on_checkbox_changed(self, row_id, state):
        checked = (state == Qt.Checked)
        self._cache_or_update_row(row_id, checked, 'content_placeholders')

    def _cache_or_update_row(self, row_id, value, typ):
        self.rows_cache[(row_id, typ)] = {
            'id': row_id,
            'type': typ,
            'value': value
        }

    def _update_single_value(self, row_id, value):
        self.rows_cache[(row_id, 'content_placeholders')] = {
            'id': row_id,
            'type': 'content_placeholders',
            'value': value
        }
        self.dirty_ids.add(row_id)

    def _on_checkbox_changed(self, row_id, state):
        checked = (state == Qt.Checked)
        self.rows_cache[(row_id, 'content_placeholders')] = {
            'id': row_id,
            'type': 'content_placeholders',
            'value': checked
        }
        self.dirty_ids.add(row_id)

    # ==========================
    # 保存（你的原逻辑无改动）
    # ==========================
    def _sync_current_version_to_beifen(self, conn, version_name):
        """
        将当前 user_config 内容，保存为指定 version_name 的快照
        id 为人工编号，必须显式插入
        """
        with conn.cursor() as cur:
            # 1. 删除该版本旧快照
            cur.execute(
                "DELETE FROM user_config_beifen WHERE name=%s",
                (version_name,)
            )

            # 2. 从 user_config 插入为该版本
            cur.execute("""
                INSERT INTO user_config_beifen
                (id, user_id, config_type, value,
                 title, object, subtitle, memo, content, name)
                SELECT
                    id, user_id, config_type, `value`,
                    title, object, subtitle, memo, content, %s
                FROM user_config
            """, (version_name,))

            print(
                f"🧩 保存版本《{version_name}》："
                f"插入 {cur.rowcount} 行"
            )

    def save_all_tables(self, silent=False, sync_local_beifen=True, sync_remote=False):
        self._ensure_conn()

        updates = []

        # 1. 仅保存被修改的 placeholders
        for row_id in self.dirty_ids:
            entry = self.rows_cache.get((row_id, 'content_placeholders'))
            if not entry:
                continue

            val = entry['value']
            val_db = 'true' if val is True else 'false' if val is False else str(val)
            updates.append((val_db, row_id))

        # 2. 仅保存被修改的表格
        # 2. 仅保存被修改的表格
        for row_id in self.dirty_table_ids:
            table_data = None

            tbl = self.table_widgets.get(row_id)

            # 情况1：表格控件还在，直接读控件
            if tbl is not None and not sip.isdeleted(tbl):
                table_data = self._table_to_data(tbl)

            # 情况2：表格控件已经被切换页面删掉，从缓存读
            if table_data is None:
                entry = self.rows_cache.get((row_id, "table"))
                if entry:
                    table_data = entry.get("value")

            if table_data is None:
                continue

            updates.append((json.dumps(table_data, ensure_ascii=False), row_id))

        # 没有变更，直接返回
        if not updates:
            if not silent:
                QMessageBox.information(self, "提示", "没有需要保存的修改。")
            return True

        # 3. 批量更新 user_config
        self.conn.autocommit(False)
        try:
            with self.conn.cursor() as cur:
                cur.executemany(
                    "UPDATE user_config SET `value`=%s WHERE id=%s",
                    updates
                )

                # 4. 同步当前版本到本地 beifen：直接数据库内复制，不再先 SELECT 全表回 Python
                version_name = self.version_selector.currentText().strip()
                if sync_local_beifen and version_name:
                    cur.execute("DELETE FROM user_config_beifen WHERE name=%s", (version_name,))
                    cur.execute("""
                        INSERT INTO user_config_beifen
                        (id, user_id, config_type, value, title, object, subtitle, memo, content, name)
                        SELECT
                            id, user_id, config_type, value, title, object, subtitle, memo, content, %s
                        FROM user_config
                    """, (version_name,))

            self.conn.commit()

        except Exception as e:
            self.conn.rollback()
            if not silent:
                QMessageBox.critical(self, "保存失败", str(e))
            else:
                 print("保存失败：", e)

            return False
        finally:
            self.conn.autocommit(True)

        # 另存模板中的静默保存只是中间步骤，由外层切换到新名称后再更新产品。
        if not silent:
            self._update_selected_product_config()

        # 5. 普通保存默认不做远程同步；只有明确需要时才做
        if sync_remote:
            version_name = self.version_selector.currentText().strip()
            if version_name:
                try:
                    # 这里才读取一次本地数据，供远程使用
                    with self.conn.cursor() as cur:
                        cur.execute("""
                            SELECT
                                id, user_id, config_type, value,
                                title, object, subtitle, memo, content
                            FROM user_config
                            ORDER BY id
                        """)
                        local_rows = cur.fetchall()

                    remote = self.get_remote_conn()
                    if remote:
                        try:
                            with remote.cursor() as rcur:
                                rcur.execute("DELETE FROM user_config_beifen WHERE name=%s", (version_name,))

                                insert_sql = """
                                    INSERT INTO user_config_beifen
                                    (id, user_id, config_type, value,
                                     title, object, subtitle, memo, content, name)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """
                                rcur.executemany(insert_sql, [
                                    (
                                        r["id"], r["user_id"], r["config_type"], r["value"],
                                        r["title"], r["object"], r["subtitle"], r["memo"],
                                        r["content"], version_name
                                    )
                                    for r in local_rows
                                ])
                            remote.commit()
                        finally:
                            try:
                                remote.close()
                            except:
                                pass
                except Exception as e:
                    print("⚠️ 远程版本同步失败，已跳过：", e)

        # 6. 清空脏标记
        self.dirty_ids.clear()
        self.dirty_table_ids.clear()


        # 保存后重新从数据库刷新界面
        if not silent:
            old_key = self.current_object_key
            self.reload_and_render()

            if old_key:
                item = self._find_tree_item_by_key(old_key)
                if item:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    self.tree.blockSignals(False)
                    self.current_object_key = old_key
                    self.render_selected_config_object(old_key)

            QMessageBox.information(self, "保存成功", "所有修改已保存。")

        if not silent:
            run_predefined_save_sync()

        return True
