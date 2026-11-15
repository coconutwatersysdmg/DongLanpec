"""Product-scoped recorded executions, historical values and design baselines."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .graph_view import LineageView
from .lifecycle_service import LifecycleService
from .models import ACTIVITY_DB, DataCenterError, display, dumps
from .quality import TYPES

STATUS = dict(running='运行中', completed='已完成', failed='失败', partial='部分完成 / 证据不全',
              cancelled='已取消', interrupted='进程中断')


def pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=display)


class RuleDialog(QDialog):
    def __init__(self, parent, product, entry=None):
        super().__init__(parent)
        self.setWindowTitle('配置质量规则')
        self.resize(620, 570)
        form = QFormLayout(self)
        spec = entry['specification'] if entry else {}
        self.name = QLineEdit(entry['name'] if entry else '')
        self.database = QLineEdit(spec.get('database', ACTIVITY_DB))
        self.table = QLineEdit(spec.get('table', ''))
        self.fields = QLineEdit('、'.join(spec.get('fields', [])))
        self.kind = QComboBox()
        for key, title in TYPES.items():
            self.kind.addItem(title, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get('type'))))
        self.minimum, self.maximum = QLineEdit(str(spec.get('min', ''))), QLineEdit(str(spec.get('max', '')))
        self.allowed = QLineEdit('、'.join(map(str, spec.get('values', []))))
        self.other = QLineEdit(spec.get('other', ''))
        self.operator = QComboBox()
        self.operator.addItems(['<=', '<', '>=', '>', '==', '!='])
        self.operator.setCurrentText(spec.get('operator', '<='))
        self.where = QLineEdit('；'.join('%s=%s' % (k, v) for k, v in spec.get('where', {}).items()))
        self.where.setPlaceholderText('例如 参数名称=设计压力；侧别=管程（按显示值匹配）')
        self.warning = QCheckBox('只提示，不阻止冻结')
        self.warning.setChecked(spec.get('severity') == 'warning')
        self.enabled = QCheckBox('启用规则')
        self.enabled.setChecked(bool(entry.get('enabled', True)) if entry else True)
        self.shared = QCheckBox('适用于所有产品')
        self.shared.setChecked(not entry['product_id'] if entry else not product)
        for title, control in [('名称', self.name), ('数据库', self.database), ('表', self.table),
            ('规则', self.kind), ('字段（组合字段用顿号分隔）', self.fields), ('数值下限（可空）', self.minimum),
            ('数值上限（可空）', self.maximum), ('允许值（顿号分隔）', self.allowed),
            ('比较运算符', self.operator), ('比较的另一字段', self.other), ('适用记录（可空）', self.where),
            ('级别', self.warning), ('状态', self.enabled), ('范围', self.shared)]:
            form.addRow(title, control)
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        form.addRow(controls)

    def specification(self):
        spec = dict(database=self.database.text().strip(), table=self.table.text().strip(),
                    type=self.kind.currentData(), fields=[v.strip() for v in self.fields.text().split('、') if v.strip()],
                    severity='warning' if self.warning.isChecked() else 'error')
        if spec['type'] == 'numeric':
            spec.update(min=self.minimum.text().strip(), max=self.maximum.text().strip())
        elif spec['type'] == 'enum':
            spec['values'] = [v.strip() for v in self.allowed.text().split('、') if v.strip()]
        elif spec['type'] == 'compare':
            spec.update(other=self.other.text().strip(), operator=self.operator.currentText())
        if self.where.text().strip():
            pairs = [v.partition('=') for v in self.where.text().split('；') if v.strip()]
            if any(not middle or not key.strip() for key, middle, value in pairs):
                raise DataCenterError('适用记录请使用 字段=值，多项以分号“；”分隔。')
            spec['where'] = {k.strip(): v.strip() for k, _, v in pairs}
            spec['where_display'] = True
        return spec


class LifecyclePanel(QWidget):
    def __init__(self, parent, backend, resources, runner, scope, actor):
        super().__init__(parent)
        from .widget import button, read_table
        self.service = LifecycleService(backend, resources)
        self.runner, self.scope, self.actor = runner, scope, actor
        self.loaded = False
        self.run_rows, self.baseline_rows, self.rule_rows = [], [], []
        self.selected_run = self.selected_baseline = self.snapshot = self.selected_entity = None
        outer = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.hint = QLabel('先选择产品范围，再查看运行或固定设计版本。')
        self.hint.setWordWrap(True)
        bar.addWidget(self.hint, 1)
        bar.addWidget(button('刷新运行与版本', self.reload))
        outer.addLayout(bar)
        storage = QLabel('运行证据与基线目录：' + str(self.service.store.home) + '（资源管理页的备份已包含这些历史内容）')
        storage.setWordWrap(True)
        outer.addWidget(storage)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)

        run_page = QWidget()
        layout = QVBoxLayout(run_page)
        layout.addWidget(QLabel('只展示已接入入口观察到的执行；历史证据只读，DLL 内部查询不在覆盖范围。'))
        self.runs = read_table(['开始时间', '产品ID', '操作', '状态', '操作人', '结束时间'])
        self.runs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runs.setSelectionMode(QAbstractItemView.SingleSelection)
        self.runs.itemSelectionChanged.connect(self.select_run)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.runs)
        self.canvas = LineageView()
        self.canvas.field_selected.connect(self.select_node)
        self.canvas.edge_selected.connect(lambda edge: self.detail.setPlainText(edge.evidence))
        splitter.addWidget(self.canvas)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        splitter.addWidget(self.detail)
        splitter.setSizes([190, 380, 140])
        layout.addWidget(splitter)
        buttons = QHBoxLayout()
        buttons.addWidget(button('适合窗口', self.canvas.fit_graph))
        buttons.addWidget(button('保存所选证据副本', self.export_entity))
        buttons.addStretch()
        layout.addLayout(buttons)
        self.tabs.addTab(run_page, '真实运行血缘')

        baseline_page = QWidget()
        layout = QVBoxLayout(baseline_page)
        buttons = QHBoxLayout()
        for title, action in [('保存产品数据版本', self.capture), ('冻结设计基线', self.freeze),
                              ('与当前值比较', self.compare_current), ('比较两条基线', self.compare_two),
                              ('导出基线', self.export_baseline)]:
            buttons.addWidget(button(title, action))
        layout.addLayout(buttons)
        scope_bar = QHBoxLayout()
        self.databases = QLineEdit(ACTIVITY_DB)
        self.databases.setPlaceholderText('多个数据库用顿号分隔；仅快照其中含产品ID的表')
        self.shared = QCheckBox('基线包含公共文件')
        scope_bar.addWidget(QLabel('产品数据库'))
        scope_bar.addWidget(self.databases, 1)
        scope_bar.addWidget(self.shared)
        layout.addLayout(scope_bar)
        self.baselines = read_table(['基线名称', '产品ID', '冻结时间', '操作人'])
        self.baselines.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.baselines.itemSelectionChanged.connect(self.select_baseline)
        layout.addWidget(self.baselines, 1)
        versions_bar = QHBoxLayout()
        versions_bar.addWidget(QLabel('已保存的数据库版本'))
        self.versions = QComboBox()
        self.versions.setMinimumContentsLength(24)
        self.versions.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.versions.activated.connect(self.show_version)
        versions_bar.addWidget(self.versions, 1)
        layout.addLayout(versions_bar)
        self.tables = QComboBox()
        self.tables.activated.connect(self.show_snapshot_table)
        layout.addWidget(self.tables)
        self.values = read_table([])
        layout.addWidget(self.values, 2)
        self.comparison = QPlainTextEdit()
        self.comparison.setReadOnly(True)
        self.comparison.setMaximumHeight(190)
        layout.addWidget(self.comparison)
        self.tabs.addTab(baseline_page, '版本与设计基线')

        quality_page = QWidget()
        layout = QVBoxLayout(quality_page)
        buttons = QHBoxLayout()
        buttons.addWidget(button('检查当前产品', self.check_quality))
        buttons.addWidget(button('添加质量规则', self.add_rule))
        buttons.addWidget(button('编辑所选规则', self.edit_rule))
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(QLabel('范围取“版本与设计基线”页的数据库。内置结构检查始终执行；工程阈值由规则明确配置。'))
        self.rules = read_table(['名称', '产品范围', '类型', '表 / 字段', '状态', '级别'])
        self.rules.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rules.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.rules)
        self.quality_summary = QLabel('尚未运行检查。')
        layout.addWidget(self.quality_summary)
        self.issues = read_table(['级别', '规则', '表', '记录定位', '问题'])
        layout.addWidget(self.issues, 2)
        self.tabs.addTab(quality_page, '质量检查')

    def ensure_loaded(self):
        if not self.loaded:
            self.reload()

    def reload(self):
        product = self.scope()
        def load():
            note = ''
            try:
                self.service.import_center_history()
            except Exception as exc:
                note = '数据库事务历史暂未同步：' + str(exc)
            self.service.store.recover_interrupted()
            return (self.service.store.runs(product), self.service.store.baselines(product),
                    self.service.store.rules(product),
                    self.service.store.entity_versions(product, 'product-database') if product else [], note)
        self.runner('读取实际运行与设计版本', load, self.show_lists)

    def show_lists(self, result):
        from .widget import fill_table
        self.run_rows, self.baseline_rows, self.rule_rows, versions, note = result
        self.loaded = True
        self.runs.blockSignals(True)
        self.baselines.blockSignals(True)
        fill_table(self.runs, [[r['started'], r['product_id'], r['title'], STATUS.get(r['status'], r['status']),
                               r['actor'], r['ended']] for r in self.run_rows])
        fill_table(self.baselines, [[r['name'], r['product_id'], r['created'], r['actor']] for r in self.baseline_rows])
        self.runs.clearSelection()
        self.baselines.clearSelection()
        self.runs.blockSignals(False)
        self.baselines.blockSignals(False)
        fill_table(self.rules, [[r['name'], r['product_id'] or '所有产品', TYPES[r['specification']['type']],
            r['specification']['table'] + ' / ' + '、'.join(r['specification']['fields']),
            '启用' if r['enabled'] else '停用', '提示' if r['specification'].get('severity') == 'warning' else '错误'] for r in self.rule_rows])
        self.versions.clear()
        for item in versions:
            self.versions.addItem('v%s · %s · %s' % (item['version'], item['created'], item['content_sha'][:12]), item['id'])
        self.selected_run = self.selected_baseline = self.snapshot = self.selected_entity = None
        self.canvas.scene().clear()
        self.detail.clear()
        self.tables.clear()
        self.values.setRowCount(0)
        self.comparison.clear()
        self.issues.setRowCount(0)
        self.quality_summary.setText('尚未运行检查。')
        self.hint.setText('产品：%s · %s 条运行 · %s 条基线%s' % (self.scope() or '全部（创建版本需指定产品）',
            len(self.run_rows), len(self.baseline_rows), '\n' + note if note else ''))

    def select_run(self):
        rows = self.runs.selectionModel().selectedRows()
        if not rows:
            return
        run_id = self.run_rows[rows[0].row()]['id']
        self.runner('展开运行证据', lambda: (self.service.store.run(run_id), self.service.run_graph(run_id)), self.show_run)

    def show_run(self, value):
        self.selected_run, graph = value
        self.selected_entity = None
        self.canvas.show_graph(graph)
        self.detail.setPlainText(pretty(self.selected_run))

    def select_node(self, node):
        if node.kind == 'operation':
            self.runner('读取运行详情', lambda: self.service.store.run(node.token),
                        lambda value: self.detail.setPlainText(pretty(value)))
            self.selected_entity = None
            return
        self.selected_entity = node.token
        def show(entity):
            content = entity.pop('content')
            self.detail.setPlainText(pretty(entity) + '\n\n' +
                (content[:131072].decode('utf-8', errors='replace') + ('\n（预览截断，可保存完整副本）' if len(content) > 131072 else '')
                 if isinstance(content, bytes) and entity['kind'] != 'file' else
                 '二进制文件，请保存证据副本查看。' if isinstance(content, bytes) else pretty(content)))
        self.runner('读取不可变证据', lambda: self.service.store.entity(node.token, content=True), show)

    def product(self):
        product = self.scope()
        if not product:
            raise DataCenterError('请先在顶部指定产品ID并应用范围。')
        return product

    def database_scope(self):
        return [v.strip() for v in self.databases.text().split('、') if v.strip()] or [ACTIVITY_DB]

    def capture(self):
        try:
            product, databases = self.product(), self.database_scope()
        except DataCenterError as exc:
            QMessageBox.information(self, '产品范围', str(exc))
            return
        def done(value):
            self.show_snapshot(self.service.store.entity(value[0], content=True)['content'])
            self.comparison.setPlainText('已保存数据库版本。刷新列表后可从版本选择框重新打开。')
        self.runner('保存一致的产品数据版本', lambda: self.service.capture(product, databases), done)

    def freeze(self):
        try:
            product, databases = self.product(), self.database_scope()
        except DataCenterError as exc:
            QMessageBox.information(self, '产品范围', str(exc))
            return
        name, accepted = QInputDialog.getText(self, '冻结设计基线', '基线名称（同一产品不可重复）')
        if not accepted or not name.strip():
            return
        shared = self.shared.isChecked()
        self.runner('检查质量并固定数据库及文件版本', lambda: self.service.freeze(product, name.strip(),
                    self.actor, databases=databases, include_shared=shared), self.baseline_created)

    def baseline_created(self, baseline):
        self.hint.setText('已冻结：' + baseline['name'])
        self.reload()

    def select_baseline(self):
        rows = self.baselines.selectionModel().selectedRows()
        if not rows:
            return
        baseline_id = self.baseline_rows[rows[0].row()]['id']
        def load():
            baseline = self.service.store.baseline(baseline_id)
            return baseline, self.service.store.entity(baseline['manifest']['snapshot'], content=True)['content']
        def show(value):
            self.selected_baseline, snapshot = value
            self.show_snapshot(snapshot)
            self.comparison.setPlainText(pretty(self.selected_baseline['manifest']))
        self.runner('读取基线历史数据', load, show)

    def show_version(self):
        entity_id = self.versions.currentData()
        if entity_id:
            self.runner('读取数据库历史版本', lambda: self.service.store.entity(entity_id, content=True),
                        lambda value: self.show_snapshot(value['content']))

    def show_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.tables.clear()
        for i, table in enumerate(snapshot['tables']):
            self.tables.addItem('%s.%s · %s 行' % (table['database'], table['table'], len(table['rows'])), i)
        self.show_snapshot_table()

    def show_snapshot_table(self):
        from .widget import fill_table
        if not self.snapshot or self.tables.currentData() is None:
            return
        table = self.snapshot['tables'][self.tables.currentData()]
        names = [column['name'] for column in table['columns']]
        self.values.setColumnCount(len(names))
        self.values.setHorizontalHeaderLabels(names)
        fill_table(self.values, [[row.get(name) for name in names] for row in table['rows'][:5000]])
        self.values.setToolTip('只读历史值。显示前 5000 行，完整数据在导出基线中。')

    def compare_current(self):
        if self.selected_baseline:
            baseline_id = self.selected_baseline['id']
            self.runner('比较基线与当前数据', lambda: self.service.compare_current(baseline_id), self.show_comparison)

    def compare_two(self):
        rows = sorted({index.row() for index in self.baselines.selectionModel().selectedRows()})
        if len(rows) != 2:
            QMessageBox.information(self, '比较基线', '请按住 Ctrl 选择两条同产品基线。')
            return
        newer, older = [self.baseline_rows[i] for i in rows]
        self.runner('比较两份不可变基线', lambda: self.service.compare(older['id'], newer['id']), self.show_comparison)

    def show_comparison(self, value):
        self.comparison.setPlainText('数据库差异 %s 项 · 文件差异 %s 项 · 绑定来源变化：%s%s\n%s' % (
            value['total'], len(value.get('files', [])), '是' if value.get('dependencies_changed') else '否',
            '（数据库差异仅预览前 2000 项）' if value['truncated'] else '', pretty(value)))

    def export_baseline(self):
        if not self.selected_baseline:
            return
        parent = QFileDialog.getExistingDirectory(self, '选择导出父目录')
        if not parent:
            return
        baseline_id = self.selected_baseline['id']
        destination = Path(parent) / ('baseline_' + baseline_id)
        self.runner('导出并校验基线证据', lambda: self.service.export_baseline(baseline_id, destination),
                    lambda path: self.comparison.setPlainText('基线已导出：' + str(path)))

    def export_entity(self):
        if not self.selected_entity:
            return
        entity_id = self.selected_entity
        entity = self.service.store.entity(entity_id)
        name = entity['metadata'].get('name') or ('evidence_' + entity_id + ('.bin' if entity['encoding'] == 'raw' else '.json'))
        path, _ = QFileDialog.getSaveFileName(self, '保存历史证据副本', Path(name).name)
        if not path:
            return
        def save():
            value = self.service.store.entity(entity_id, content=True)['content']
            Path(path).write_bytes(value if isinstance(value, bytes) else dumps(value).encode('utf-8'))
            return path
        self.runner('校验并保存证据副本', save, lambda path: self.detail.appendPlainText('\n已保存：' + path))

    def add_rule(self):
        self.edit_rule(new=True)

    def edit_rule(self, checked=False, new=False):
        entry = None
        if not new:
            rows = self.rules.selectionModel().selectedRows()
            if not rows:
                return
            entry = self.rule_rows[rows[0].row()]
        product = self.scope()
        dialog = RuleDialog(self, product, entry)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            spec = dialog.specification()
            from .quality import validate_rule
            validate_rule(spec)
        except DataCenterError as exc:
            QMessageBox.information(self, '规则未保存', str(exc))
            return
        rule_product = '' if dialog.shared.isChecked() else product
        name, enabled, rule_id = dialog.name.text(), dialog.enabled.isChecked(), entry['id'] if entry else None
        self.runner('保存显式质量规则', lambda: self.service.store.save_rule(name, spec, rule_product,
                    enabled, rule_id), lambda value: self.reload())

    def check_quality(self):
        try:
            product, databases = self.product(), self.database_scope()
        except DataCenterError as exc:
            QMessageBox.information(self, '产品范围', str(exc))
            return
        self.runner('对一致快照执行质量检查', lambda: self.service.check_quality(product, databases), self.show_quality)

    def show_quality(self, result):
        from .widget import fill_table
        report = result['report']
        self.quality_summary.setText('错误 %s 项 · 提示 %s 项 · 已固定被检查快照%s' % (
            report['errors'], report['warnings'], '（问题仅显示前 2000 项）' if report['truncated'] else ''))
        fill_table(self.issues, [['错误' if item['severity'] == 'error' else '提示', item['rule'], item['table'],
                               item['identity'], item['message']] for item in report['issues']])
