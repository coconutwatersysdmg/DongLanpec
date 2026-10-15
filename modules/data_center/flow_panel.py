"""Activity-table flow map, interface checklist, and searchable SQL evidence."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QCheckBox, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from .flow_rules import INPUTS, FLOWS
from .graph_view import LineageView
from .provenance import catalog, table_graph, function_graph, statement_graph, field_usage


def grid(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setEditTriggers(QAbstractItemView.NoEditTriggers)
    result.setSelectionBehavior(QAbstractItemView.SelectRows)
    result.setSelectionMode(QAbstractItemView.SingleSelection)
    result.setAlternatingRowColors(True)
    result.verticalHeader().hide()
    result.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    result.horizontalHeader().setStretchLastSection(True)
    result.setWordWrap(False)
    return result


class FlowPanel(QWidget):
    open_table = pyqtSignal(str)
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.c = None
        self.ready = False
        self.pending_table = ''
        self.pending_column = ''
        layout = QVBoxLayout(self)
        self.summary = QLabel('活动库表关系、界面输入和读写位置；打开页面后加载。')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        bar = QHBoxLayout()
        self.tables = QComboBox()
        self.tables.setMinimumWidth(190)
        self.tables.setMaximumWidth(330)
        self.tables.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.columns = QComboBox()
        self.columns.setMinimumWidth(130)
        self.columns.setMaximumWidth(230)
        self.modules = QComboBox()
        self.modules.addItem('全部业务界面', '')
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索控件、参数、函数、SQL条件')
        for w in (self.tables, self.columns, self.modules, self.search):
            bar.addWidget(w)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.flows = QComboBox()
        self.flows.setMinimumWidth(310)
        bar.addWidget(self.flows, 1)
        for title, callback in (('查看当前表数据', self.locate), ('适合窗口', lambda: (self.statements if self.pages.currentIndex()==4 else self.canvas).fit_graph()), ('核对代码版本', self.verify_sources)):
            b = QPushButton(title)
            b.clicked.connect(callback)
            bar.addWidget(b)
        self.recheck_button = QPushButton('刷新并重新检查')
        self.recheck_button.clicked.connect(self.refresh_requested.emit)
        self.recheck_button.setToolTip('源码版重新扫描并替换索引；安装版校验并重载当前程序的随包索引，同时检查数据库结构。')
        bar.addWidget(self.recheck_button)
        layout.addLayout(bar)
        self.pages = QTabWidget()
        self.canvas = LineageView()
        self.pages.addTab(self.canvas, '流转图')
        self.inputs = grid(['界面 / 输入', '控件', '数据库落点', '字段', '触发 / 保存'])
        self.pages.addTab(self.inputs, '界面输入清单')
        self.sql = grid(['界面', '操作', '字段 / 精度', '函数', '代码位置'])
        self.pages.addTab(self.sql, '字段读写依据')
        self.coverage = grid(['活动库表', '字段数', '界面输入组', '读 / 写 / 删除', '梳理状态'])
        self.pages.addTab(self.coverage, '全部表覆盖')
        self.statements = LineageView()
        statement_page = QWidget()
        statement_layout = QVBoxLayout(statement_page)
        caller_bar = QHBoxLayout()
        caller_bar.addWidget(QLabel('调用来源'))
        self.callers = QComboBox()
        self.callers.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        caller_bar.addWidget(self.callers, 1)
        self.full_statements = QCheckBox('显示定位参数与连接上下文')
        self.full_statements.toggled.connect(self.select_caller)
        caller_bar.addWidget(self.full_statements)
        function_button = QPushButton('函数关联表')
        function_button.clicked.connect(lambda: self.show_function_graph(self.sql.currentRow()))
        caller_bar.addWidget(function_button)
        statement_layout.addLayout(caller_bar)
        statement_layout.addWidget(self.statements)
        self.pages.addTab(statement_page, '语句级来源')
        self.callers.currentIndexChanged.connect(self.select_caller)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText('点击节点、连线或清单行，查看字段映射、触发条件和代码位置。')
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.pages)
        splitter.addWidget(self.detail)
        splitter.setSizes([560, 145])
        layout.addWidget(splitter, 1)
        self.status = QLabel('青色点线：代码依据。输入控件为绿色；表结构为紫色；处理节点为青色。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tables.currentIndexChanged.connect(self.table_changed)
        self.columns.currentIndexChanged.connect(self.refresh)
        self.modules.currentIndexChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.refresh)
        # Text filtering is cheap because lists are capped and graphs are grouped.
        self.search.textChanged.connect(self.refresh)
        self.flows.currentIndexChanged.connect(self.draw)
        self.canvas.field_selected.connect(lambda n: self.detail.setPlainText(n.detail))
        self.canvas.edge_selected.connect(lambda e: self.detail.setPlainText(e.evidence))
        self.canvas.field_edit.connect(lambda n: self.detail.setPlainText(n.detail))
        self.inputs.itemSelectionChanged.connect(lambda: self.show_detail(self.inputs))
        self.sql.itemSelectionChanged.connect(lambda: self.show_detail(self.sql))
        self.sql.cellDoubleClicked.connect(self.show_statement_graph)
        self.statements.field_selected.connect(lambda n: self.detail.setPlainText(n.detail))
        self.statements.edge_selected.connect(lambda e: self.detail.setPlainText(e.evidence))
        self.statements.field_edit.connect(lambda n: self.detail.setPlainText(n.detail))
        self.coverage.itemSelectionChanged.connect(lambda: self.show_detail(self.coverage))
        self.coverage.cellDoubleClicked.connect(lambda r, _: self.focus_table(self.coverage.item(r, 0).data(Qt.UserRole + 1)))

    def ensure_loaded(self):
        if self.ready:
            return
        try:
            self.c = catalog()
        except (OSError, ValueError, KeyError) as exc:
            self.summary.setText('关系索引未加载：%s。请检查安装包的血缘资源。' % exc)
            return
        self.tables.blockSignals(True)
        self.tables.addItem('全部活动库表', '')
        for name in sorted(self.c.schema):
            self.tables.addItem(name.removeprefix('产品设计活动表_'), name)
        self.tables.blockSignals(False)
        self.modules.blockSignals(True)
        for name in sorted({r['module'] for r in self.c.data['records']} | {r.module for r in INPUTS}):
            self.modules.addItem(name, name)
        self.modules.blockSignals(False)
        self.ready = True
        self.fill_coverage()
        self.verify_sources()
        self.focus_table(self.pending_table or '产品设计活动表_设计数据表', self.pending_column)

    def verify_sources(self):
        if not self.c:
            return
        changed, unavailable = self.c.source_status()
        covered = sum(bool(self.c.by_table.get(t)) for t in self.c.schema)
        message = '活动库 %s/%s 张表有SQL依据 · %s 组界面输入 · %s 条业务流程 · 静态梳理，不是运行历史。' % (covered, len(self.c.schema), len(INPUTS), len(FLOWS))
        message += '\n程序 %s · 索引 %s · 生成于 %s' % (self.c.data.get('app_version', '未知'), self.c.data.get('source_id', '旧格式')[:12], self.c.data.get('generated_at', '未知'))
        if changed:
            message += '\n%s 个源码文件已变化，索引需要重建；下方位置以快照为准。' % len(changed)
        elif self.c.frozen:
            message += '\n安装版：已校验当前构建的随包索引；内部语句依据不依赖源码文件。'
        else:
            message += '\n索引与当前业务源码一致。'
        errors = self.c.data.get('errors', [])
        inactive = [r.title for r in INPUTS + FLOWS if self.c.rule_status(r) != '已核对']
        if inactive:
            message += '\n%s 组旧语义映射停用/待复核；具体语句按新代码重新解析。' % len(inactive)
        if errors:
            message += ' %s 个脚本解析失败，可在此提示中查看详情。' % len(errors)
        self.summary.setText(message)
        self.summary.setToolTip('\n'.join(changed + inactive + [e['path'] + ': ' + e['error'] for e in errors]))

    def focus_table(self, name, column=''):
        self.pending_table, self.pending_column = name, column
        if not self.ready:
            return
        self.search.clear()
        self.modules.setCurrentIndex(0)
        self.tables.setCurrentIndex(max(0, self.tables.findData(name)))
        self.table_changed()
        self.columns.setCurrentIndex(max(0, self.columns.findData(column)))
        self.pages.setCurrentIndex(0)

    def table_changed(self, *_):
        if not self.ready:
            return
        name = self.tables.currentData() or ''
        self.columns.blockSignals(True)
        self.columns.clear()
        self.columns.addItem('全部字段', '')
        for col in self.c.schema.get(name, []):
            self.columns.addItem(col, col)
        self.columns.blockSignals(False)
        self.flows.blockSignals(True)
        self.flows.clear()
        self.flows.addItem('表的界面输入与代码读写', None)
        for i, rule in enumerate(FLOWS):
            if not name or name in rule.sources + rule.targets:
                self.flows.addItem(rule.title, i)
        self.flows.blockSignals(False)
        self.refresh()

    def refresh(self, *_):
        if self.ready:
            self.refresh_lists()
            self.draw()

    def draw(self, *_):
        if not self.ready:
            return
        name = self.tables.currentData() or '产品设计活动表_设计数据表'
        self.canvas.show_graph(table_graph(name, self.flows.currentData(), self.columns.currentData() or '',
                                          self.modules.currentData() or '', self.search.text().strip()))
        if not self.tables.currentData() and self.flows.currentData() is None:
            self.detail.setPlainText('请选择一张表查看流转图。“全部活动库表”用于汇总检索清单；此图默认以设计数据表为中心。')

    @staticmethod
    def fill(widget, rows):
        widget.setUpdatesEnabled(False)
        widget.setRowCount(len(rows))
        for row, (values, detail, token) in enumerate(rows):
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, detail)
                    item.setData(Qt.UserRole + 1, token)
                widget.setItem(row, col, item)
        widget.setUpdatesEnabled(True)
        for col in range(widget.columnCount() - 1):
            widget.setColumnWidth(col, (200, 230, 250, 240)[col % 4])

    def refresh_lists(self, *_):
        if not self.ready:
            return
        table = self.tables.currentData() or ''
        column = self.columns.currentData() or ''
        module = self.modules.currentData() or ''
        query = self.search.text().strip().casefold()
        inputs = []
        for r in INPUTS:
            detail = self.c.input_detail(r)
            if (table and r.target != table) or (column and column not in r.fields and '*' not in r.fields) or (module and r.module != module) or (query and query not in detail.casefold()):
                continue
            state = self.c.rule_status(r)
            inputs.append(((r.module + ' / ' + r.title + (' [待复核/停用]' if state != '已核对' else ''), r.control, r.target, '、'.join(r.fields), r.trigger), detail, r.target))
        self.fill(self.inputs, inputs)
        records = self.c.records(table, column) if table else self.c.data['records']
        rows = []
        for r in records:
            if module and module != r['module']:
                continue
            location = '%s:%s' % (r['path'], r['line'])
            detail = '\n'.join((r['table'], r['module'] + ' · ' + r['operation'] + ' · ' + r['precision'] + ' · ' + r['mode'],
                                 location, r['function'], '字段：' + '、'.join(r['fields']), '定位条件：' + r['where'],
                                 '定位引用字段：' + '、'.join(r.get('predicate_fields', [])),
                                 'SQL：' + r['sql'], '参数表达式：' + r['arguments'],
                                 '字段赋值：\n' + '\n'.join(k + ' ← ' + v for k, v in r['bindings'].items()),
                                 '静态调用位置；动态列需结合运行参数核对。不同产品型式、旧入口须按实际入口判断。双击此行展开语句级来源图。'))
            if query and query not in detail.casefold():
                continue
            usage = ' / 仅定位引用' if field_usage(r, column) == '定位引用' else ''
            rows.append(((r['module'], r['operation'] + ' / ' + r['mode'] + usage, '、'.join(r['fields']) + ' [' + r['precision'] + ']', r['function'], location), detail, (r['path'], r['function'], r['line'])))
        self.fill(self.sql, rows[:500])
        self.pages.setTabText(1, '界面输入清单（%s）' % len(inputs))
        self.pages.setTabText(2, '字段读写依据（%s）' % len(rows))
        self.status.setText('当前筛选：%s 组界面输入，%s 处SQL依据%s。青色点线只展示代码关系；具体值与联动在“字段血缘”编辑。' %
                            (len(inputs), len(rows), '，显示前500处，请继续筛选' if len(rows) > 500 else ''))

    def fill_coverage(self):
        rows = []
        for t in sorted(self.c.schema):
            sites = self.c.by_table.get(t, [])
            counts = [sum(r['operation'] == 'SELECT' for r in sites), sum(r['operation'] in ('INSERT', 'UPDATE', 'REPLACE') for r in sites), sum(r['operation'] == 'DELETE' for r in sites)]
            inputs = [r for r in INPUTS if r.target == t]
            flows = [r for r in FLOWS if t in r.sources + r.targets]
            state = '已定位读写' if sites else '尚无代码依据'
            if not inputs:
                state += ' · 无独立输入映射（检查流程/SQL）'
            detail = t + '\n字段：' + '、'.join(self.c.schema[t]) + '\n界面输入：' + '、'.join(r.title for r in inputs) + '\n业务流程：' + '、'.join(r.title for r in flows) + '\n' + state + '\n双击此行查看这张表的流转。'
            rows.append(((t, len(self.c.schema[t]), len(inputs), ' / '.join(map(str, counts)), state), detail, t))
        self.fill(self.coverage, rows)
        self.coverage.setColumnWidth(0, 320)
        self.coverage.setColumnWidth(1, 75)
        self.coverage.setColumnWidth(2, 100)
        self.coverage.setColumnWidth(3, 150)

    def show_detail(self, widget):
        row = widget.currentRow()
        if row >= 0 and widget.item(row, 0):
            detail = widget.item(row, 0).data(Qt.UserRole) or ''
            if widget is self.sql:
                path, function, line = widget.item(row, 0).data(Qt.UserRole + 1)
                detail += '\n\n具体语句的来源追溯：\n' + self.c.trace.format(path, function, line, self.columns.currentData() or '')
            self.detail.setPlainText(detail)

    def locate(self):
        table = self.tables.currentData()
        if table:
            self.open_table.emit(table)

    def show_function_graph(self, row, _column=0):
        item = self.sql.item(row, 0)
        if item:
            path, function, _ = item.data(Qt.UserRole + 1)
            self.canvas.show_graph(function_graph(path, function))
            self.pages.setCurrentIndex(0)
            self.status.setText('当前为选中函数的全部表读写拓扑；条件分支以详情为准。选择流程或表可返回业务流转图。')

    def show_statement_graph(self, row, _column=0):
        item = self.sql.item(row, 0)
        if item:
            path, function, line = item.data(Qt.UserRole + 1)
            self.callers.blockSignals(True)
            self.callers.clear()
            self.callers.addItem('当前SQL语句 · ' + function, (path, function, line))
            seen = set()
            for key, step, _call in self.c.trace.callers.get((path, function), []):
                token = (key[0], key[1], step['line'])
                if token not in seen:
                    self.callers.addItem('%s:%s · %s' % (key[0], step['line'], key[1]), token)
                    seen.add(token)
            self.callers.blockSignals(False)
            self.select_caller()
            self.pages.setCurrentIndex(4)
            self.status.setText('语句级来源：读取 → 赋值/转换 → 调用 → 写入；节点含确切行号和分支条件。参数、动态调用与追溯上限会显示边界。')

    def select_caller(self, *_):
        token = self.callers.currentData()
        if token:
            path, function, line = token
            self.statements.show_graph(statement_graph(path, function, line, self.columns.currentData() or '', compact=not self.full_statements.isChecked()), column_spacing=330)
            self.detail.setPlainText(self.c.trace.format(path, function, line, self.columns.currentData() or ''))

    def reload_index(self, report):
        table, column = self.tables.currentData(), self.columns.currentData()
        self.callers.clear()
        self.statements.clear_graph()
        self.ready = False
        for combo in (self.tables, self.columns, self.modules, self.flows):
            combo.blockSignals(True)
            combo.clear()
            combo.blockSignals(False)
        self.modules.addItem('全部业务界面', '')
        self.pending_table, self.pending_column = table or '', column or ''
        self.ensure_loaded()
        self.status.setText('\n'.join(report['notes']) + '\n文件变化 %s 处；表结构差异 %s 处。' % (len(report['changed']), len(report['schema_changes'])))
        self.detail.setPlainText('\n'.join(report['notes'] + report['changed'] + report['schema_changes']))
