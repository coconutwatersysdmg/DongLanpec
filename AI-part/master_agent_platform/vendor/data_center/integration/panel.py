"""Engineering UI for acquisition jobs, canonical objects and federated SELECT."""
from __future__ import annotations

import json
import uuid
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QComboBox, QDialog, QDialogButtonBox, QInputDialog,
    QMessageBox, QTabWidget, QCheckBox, QSplitter)

from ..models import DataCenterError, dumps, loads
from ..widget import button, read_table, fill_table
from .store import IntegrationStore
from .ingestion import Ingestion
from .federation import Federation
from .sources import TableSource


def pretty(value):
    return json.dumps(json.loads(dumps(value)), ensure_ascii=False, indent=2)


class ConfigurationDialog(QDialog):
    def __init__(self, store, kind, runner, parent=None):
        super().__init__(parent)
        self.store, self.kind, self.runner = store, kind, runner
        self.setWindowTitle('配置查询对象' if kind == 'view' else '新建采集任务')
        self.resize(820, 760)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.resource = QComboBox()
        for item in store.resources.list():
            if item['kind'] in ('sqlite', 'mysql', 'postgresql'):
                self.resource.addItem(item['title'] + ' · ' + item['kind'], item['id'])
        self.table, self.schema = QLineEdit(), QLineEdit()
        form.addRow('对象名（英文）' if kind == 'view' else '任务名称', self.name)
        if kind in ('view', 'incremental'):
            form.addRow('已接入数据库', self.resource)
            form.addRow('源表名称', self.table)
            form.addRow('模式（可留空）', self.schema)
            form.addRow(button('读取字段，生成初始映射', self.discover))
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        if kind in ('kafka', 'rabbitmq'):
            form.addRow('临时认证口令', self.secret)
        layout.addLayout(form)
        layout.addWidget(QLabel('字段映射：source / target / type；单位用 source_unit / unit，标识对应用 id_map。'))
        self.fields = QPlainTextEdit(pretty([
            dict(source='id', target='id', type='id'),
            dict(source='产品ID', target='product_id', type='id'),
            dict(source='压力', target='pressure', type='decimal', source_unit='kPa', unit='MPa', nullable=True)]))
        layout.addWidget(self.fields, 2)
        examples = {
            'view': dict(product_field='product_id'),
            'incremental': dict(mode='snapshot_diff', keys=['id'], product_field='product_id', interval=5),
            'kafka': dict(bootstrap_servers=['localhost:9092'], topic='', group_id='donglanpec-' + uuid.uuid4().hex[:12],
                          keys=['id'], product_field='product_id', interval=2, envelope='plain'),
            'rabbitmq': dict(host='localhost', port=5672, queue='', user='', virtual_host='/',
                            keys=['id'], product_field='product_id', interval=2, envelope='plain', tls=False),
        }
        layout.addWidget(QLabel('接入选项（JSON；不包含口令）：'))
        self.options = QPlainTextEdit(pretty(examples[kind]))
        self.options.setMaximumHeight(180)
        layout.addWidget(self.options)
        hint = QLabel('任务创建后默认暂停。数据库源只读；采集副本与检查点保存到本地目录，不自动改写业务值。'
                      '水位模式需配置 watermark 和完整主键 source_keys，不能检测硬删除。'
                      'Kafka 请使用专用消费组；RabbitMQ 消费的是已有队列，成功落盘或隔离后才确认。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def source(self):
        if not self.resource.currentData() or not self.table.text().strip():
            raise DataCenterError('请先接入数据库并填写源表名称。')
        return dict(resource_id=self.resource.currentData(), table=self.table.text().strip(), schema=self.schema.text().strip())

    def discover(self):
        try:
            config = self.source()
        except Exception as exc:
            QMessageBox.warning(self, '读取字段', str(exc))
            return
        def read():
            source = TableSource(self.store.resources, config)
            with source.open() as (conn, adapter):
                return source.columns(conn, adapter)
        def show(columns):
            if not self.isVisible():
                return
            if not columns or len(columns) > 80:
                QMessageBox.warning(self, '读取字段', '源表为空或超过80列，请手工选择需要的字段。')
                return
            fields = []
            for name, column in columns.items():
                dtype = column['type'].lower()
                target = 'product_id' if name == '产品ID' else name
                typ = 'id' if column['primary'] or name.lower().endswith('id') else 'integer' if 'int' in dtype else 'decimal' if any(t in dtype for t in ('decimal', 'numeric', 'real', 'float', 'double')) else 'text'
                fields.append(dict(source=name, target=target, type=typ, nullable=not column['primary']))
            self.fields.setPlainText(pretty(fields))
            if self.kind == 'incremental':
                options = json.loads(self.options.toPlainText())
                options['keys'] = [f['target'] for f in fields if columns[f['source']]['primary']]
                options['source_keys'] = [f['source'] for f in fields if columns[f['source']]['primary']]
                self.options.setPlainText(pretty(options))
        self.runner('读取源表结构', read, show)

    def values(self):
        try:
            config = json.loads(self.options.toPlainText())
            fields = json.loads(self.fields.toPlainText())
            if not isinstance(config, dict):
                raise ValueError()
        except ValueError:
            raise DataCenterError('字段映射或接入选项不是有效 JSON。') from None
        if self.kind in ('view', 'incremental'):
            config.update(self.source())
        config['fields'] = fields
        return self.name.text().strip(), config


class IntegrationPanel(QWidget):
    def __init__(self, resources, runner, scope, parent=None, autostart=True):
        super().__init__(parent)
        self.store = IntegrationStore(resources)
        self.engine = Ingestion(self.store)
        self.federation = Federation(self.store)
        self.runner, self.scope = runner, scope
        self.host = parent
        self.last_result = None
        self._build()
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        if autostart:
            self.engine.start()

    def _build(self):
        outer = QVBoxLayout(self)
        self.heading = QLabel('接入与联合查询 · 数据源只读，采集副本单独存放')
        outer.addWidget(self.heading)
        pages = QTabWidget()
        outer.addWidget(pages)
        acquire = QWidget()
        layout = QVBoxLayout(acquire)
        toolbar = QHBoxLayout()
        for title, kind in [('数据库增量任务', 'incremental'), ('Kafka 任务', 'kafka'), ('RabbitMQ 任务', 'rabbitmq')]:
            toolbar.addWidget(button(title, lambda checked=False, k=kind: self.add(k)))
        toolbar.addWidget(button('刷新任务', self.reload))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.jobs = read_table(['任务名称', '类型', '运行状态', '最近采集', '说明 / 错误'])
        self.jobs.setSelectionBehavior(self.jobs.SelectRows)
        self.jobs.setSelectionMode(self.jobs.SingleSelection)
        self.jobs.itemSelectionChanged.connect(self.select_job)
        for column, width in enumerate((260, 120, 290, 200)):
            self.jobs.setColumnWidth(column, width)
        layout.addWidget(self.jobs, 2)
        controls = QHBoxLayout()
        for title, callback in [('启动', lambda: self.enable(True)), ('暂停', lambda: self.enable(False)),
                                ('采集一次', self.once), ('临时认证', self.authenticate),
                                ('查看配置与检查点', self.inspect), ('处理失败消息', self.dead_letters),
                                ('采集结果加入查询', self.collected_view)]:
            controls.addWidget(button(title, callback))
        controls.addStretch()
        layout.addLayout(controls)
        self.records = read_table(['记录标识', '产品ID', '规范化数据', '来源位置', '采集时间'])
        for column, width in enumerate((180, 170, 310, 280)):
            self.records.setColumnWidth(column, width)
        layout.addWidget(self.records, 2)
        self.job_detail = QLabel('选择任务查看当前产品的采集记录。任务可接收多个产品；这些记录不会替代原业务数据。')
        self.job_detail.setWordWrap(True)
        layout.addWidget(self.job_detail)
        pages.addTab(acquire, '流式与增量采集')
        query = QWidget()
        layout = QVBoxLayout(query)
        controls = QHBoxLayout()
        controls.addWidget(button('配置查询对象', lambda: self.add('view')))
        controls.addWidget(button('查看对象与映射', self.show_views))
        controls.addWidget(button('查看计划', self.explain))
        controls.addWidget(button('执行联合查询', self.execute, True))
        self.current_product = QCheckBox('限定当前产品')
        self.current_product.setChecked(True)
        self.current_product.toggled.connect(self.clear_result)
        controls.addWidget(self.current_product)
        controls.addStretch()
        layout.addLayout(controls)
        self.sql = QPlainTextEdit('SELECT a.product_id, a.pressure\nFROM design AS a\nWHERE a.pressure > 0\nLIMIT 100')
        self.sql.setMaximumHeight(150)
        layout.addWidget(self.sql)
        split = QSplitter(Qt.Vertical)
        self.results = read_table([])
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.physical_plan = QPlainTextEdit()
        self.physical_plan.setReadOnly(True)
        details = QTabWidget()
        details.addTab(self.details, '读取计划与统计')
        details.addTab(self.physical_plan, '本地执行计划')
        split.addWidget(self.results)
        split.addWidget(details)
        split.setSizes([320, 220])
        layout.addWidget(split)
        pages.addTab(query, '跨源联合查询')

    def alert(self, function):
        try:
            return function()
        except Exception as exc:
            QMessageBox.warning(self, '接入与联合查询', str(exc))

    def add(self, kind):
        def perform():
            dialog = ConfigurationDialog(self.store, kind, self.runner, self)
            while dialog.exec_() == QDialog.Accepted:
                try:
                    name, config = dialog.values()
                    if kind == 'view':
                        self.store.save_view(name, config)
                    else:
                        key = self.store.add_job(name, kind, config)
                        self.engine.credentials[key] = dialog.secret.text()
                    self.reload()
                    return
                except Exception as exc:
                    QMessageBox.warning(self, '配置未保存', str(exc))
        self.alert(perform)

    def reload(self):
        selected = self.selected_key()
        jobs = self.store.jobs()
        self.jobs.blockSignals(True)
        fill_table(self.jobs, [[j['name'], j['kind'], ('运行 · ' if j['enabled'] else '暂停 · ') + j['status'], j['updated'], j['error']] for j in jobs])
        for i, job in enumerate(jobs):
            self.jobs.item(i, 0).setData(Qt.UserRole, job['id'])
        self.jobs.blockSignals(False)
        for i, job in enumerate(jobs):
            if job['id'] == selected:
                self.jobs.selectRow(i)
                break
        self.select_job()

    def selected_key(self):
        row = self.jobs.currentRow()
        item = self.jobs.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def require_key(self):
        key = self.selected_key()
        if not key:
            raise DataCenterError('请先选择采集任务。')
        return key

    def select_job(self):
        key = self.selected_key()
        records = self.store.records(key, self.scope(), limit=200) if key else []
        fill_table(self.records, [[r['record_key'], r['product_id'], dumps(r['data']), dumps(r['position']), r['updated']] for r in records[:200]])
        self.job_detail.setText('当前范围 %s · 显示%s条记录（最多200条） · 本地采集副本，与原业务值区分存放' % (self.scope() or '全部产品', len(records)))

    def tick(self):
        if self.isVisible():
            self.alert(self.reload)
            if self.last_result and self.last_result['plan']['product_id'] != (self.scope() if self.current_product.isChecked() else ''):
                self.clear_result()

    def enable(self, enabled):
        def perform():
            self.store.enable(self.require_key(), enabled)
            if enabled:
                self.engine.start()
            self.reload()
        self.alert(perform)

    def once(self):
        def perform():
            key = self.require_key()
            self.engine.stop_event.clear()
            def done(result):
                self.reload()
                self.completed('单次采集已完成；可查看采集记录与检查点。')
            self.runner('采集一次', lambda: self.engine.run_job(key), done)
        self.alert(perform)

    def authenticate(self):
        def perform():
            key = self.require_key()
            job = self.store.job(key)
            secret, ok = QInputDialog.getText(self, '临时认证', '仅在本次进程中使用的口令', QLineEdit.Password)
            if ok:
                if job['kind'] == 'incremental':
                    self.store.resources.credentials[job['config']['resource_id']] = secret
                else:
                    self.engine.credentials[key] = secret
        self.alert(perform)

    def text_dialog(self, title, text, editable=False):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(850, 620)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(text)
        editor.setReadOnly(not editable)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel if editable else QDialogButtonBox.Close)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return editor.toPlainText() if dialog.exec_() == QDialog.Accepted else None

    def inspect(self):
        self.alert(lambda: self.text_dialog('任务配置与检查点', pretty(self.store.job(self.require_key()))))

    def dead_letters(self):
        def perform():
            key = self.require_key()
            letters = self.store.dead_letters(key)
            if not letters:
                QMessageBox.information(self, '失败消息', '没有尚未处理的失败消息。')
                return
            labels = ['%s · %s' % (r['id'], r['error']) for r in letters]
            selected, ok = QInputDialog.getItem(self, '失败消息', '选择需要修正并重试的消息', labels, 0, False)
            if not ok:
                return
            row = self.store.dead_letter(key, letters[labels.index(selected)]['id'])
            raw = loads(row['payload'])
            edited = self.text_dialog('修正消息并重试；原始失败凭据保留', raw.decode('utf-8', errors='replace'), True)
            if edited is not None:
                self.engine.replay(key, row['id'], edited.encode('utf-8'))
                self.reload()
        self.alert(perform)

    def show_views(self):
        self.alert(lambda: self.text_dialog('已配置逻辑对象与字段映射', pretty(self.store.views())))

    def collected_view(self):
        def perform():
            job = self.store.job(self.require_key())
            name, ok = QInputDialog.getText(self, '采集结果加入查询', '英文逻辑对象名；可与原数据库对象 JOIN')
            if not ok:
                return
            fields = [dict(source=f['target'], target=f['target'], type=f.get('type', 'text'),
                           source_unit=f.get('unit', ''), unit=f.get('unit', ''), nullable=f.get('nullable', False))
                      for f in job['config']['fields']]
            self.store.save_view(name.strip(), dict(job_id=job['id'], fields=fields,
                                 product_field=job['config'].get('product_field', 'product_id')))
            self.show_views()
        self.alert(perform)

    def scope_changed(self):
        self.clear_result()
        self.records.setRowCount(0)
        self.heading.setText('接入与联合查询 · 当前产品：' + (self.scope() or '未选择'))

    def query_product(self):
        if self.current_product.isChecked() and not self.scope():
            raise DataCenterError('当前未选择产品；请选择产品或明确取消“限定当前产品”。')
        return self.scope() if self.current_product.isChecked() else ''

    def clear_result(self):
        self.last_result = None
        self.results.setRowCount(0)
        self.details.clear()
        self.physical_plan.clear()

    def completed(self, message):
        if self.host is not None and hasattr(self.host, 'status'):
            self.host.status.setText(message)

    def explain(self):
        self.alert(lambda: self.details.setPlainText(pretty(self.federation.plan(self.sql.toPlainText(), self.query_product()))))

    def execute(self):
        def perform():
            product = self.query_product()
            self.clear_result()
            self.runner('执行跨源只读查询', lambda: self.federation.execute(self.sql.toPlainText(), product), self.show_result)
        self.alert(perform)

    def show_result(self, result):
        if result['plan']['product_id'] != self.query_product():
            self.clear_result()
            return
        self.last_result = result
        self.results.setColumnCount(len(result['columns']))
        self.results.setHorizontalHeaderLabels(result['columns'])
        fill_table(self.results, result['rows'])
        self.results.resizeColumnsToContents()
        for column in range(self.results.columnCount()):
            self.results.setColumnWidth(column, max(110, min(self.results.columnWidth(column), 400)))
        detail = {k: v for k, v in result.items() if k not in ('rows', 'physical_plan')}
        self.details.setPlainText(pretty(detail))
        self.physical_plan.setPlainText(result['physical_plan'])
        self.completed('联合查询完成 · %s行 · %.3f秒%s；各源为独立只读快照。' %
                       (len(result['rows']), result['seconds'], ' · 结果超过1000行，已截断显示' if result['truncated'] else ''))

    def shutdown(self):
        self.engine.stop_event.set()
        stopped = self.engine.stop(timeout=.05)
        if stopped:
            self.timer.stop()
        return stopped
