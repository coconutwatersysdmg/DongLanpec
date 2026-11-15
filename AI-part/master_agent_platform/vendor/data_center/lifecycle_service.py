"""Product versions, quality assessment, frozen baselines and recorded lineage."""
from __future__ import annotations

import shutil
import hashlib
from pathlib import Path

from .lifecycle_store import LifecycleStore, sha256, dumps
from .models import DataCenterError
from .quality import evaluate
from .resource_store import now, _hash_file
from .runtime import software_signature
from .snapshots import capture_product, snapshot_content, compare_snapshots


class LifecycleService:
    def __init__(self, backend, resources=None):
        self.backend = backend
        self.store = LifecycleStore(resources.home if resources else None)
        self.resources = resources or self.store.resources

    def capture(self, product_id, databases=None):
        snapshot = capture_product(self.backend, product_id, databases)
        entity_id = self.store.add_entity(product_id, 'product-database', 'database-snapshot',
                                          '产品数据库快照', snapshot_content(snapshot),
                                          metadata=dict(started=snapshot['started'], ended=snapshot['ended']))
        return entity_id, snapshot

    def check_quality(self, product_id, databases=None):
        entity_id, snapshot = self.capture(product_id, databases)
        report = evaluate(snapshot, self.store.rules(product_id))
        report_id = self.store.add_entity(product_id, 'product-quality', 'quality', '产品质量检查', report,
                                          metadata=dict(snapshot=entity_id))
        return dict(snapshot=entity_id, report=report, report_id=report_id)

    def freeze(self, product_id, name, actor, *, databases=None, include_shared=False):
        product_id = str(product_id).strip()
        name = name.strip()
        if not product_id or not name:
            raise DataCenterError('创建基线需要产品ID和基线名称。')
        if any(entry['name'] == name for entry in self.store.baselines(product_id)):
            raise DataCenterError('同一产品的基线名称已存在，请使用新名称保留历史。')
        files, excluded = [], []
        # First pin actual file contents. Recheck after DB capture so files that
        # changed during the consistent DB snapshot cannot form a mixed baseline.
        for resource in self.resources.list(product_id):
            if not include_shared and not resource['product_id']:
                continue
            if resource['mode'] == 'endpoint' or resource['kind'] == 'sqlite':
                excluded.append(dict(id=resource['id'], title=resource['title'], reason='源端数据未冻结，未作为静态文件复制'))
                continue
            if resource['mode'] == 'managed':
                self.resources.refresh(resource['id'])
            path = self.resources.local_path(resource['id'])
            if not path.is_file():
                raise DataCenterError('基线文件不存在，请修复资源位置后重试：' + resource['title'])
            before = path.stat()
            if before.st_size > 256 * 1024 * 1024:
                raise DataCenterError('文件超过 256 MiB 基线证据上限：' + resource['title'])
            data = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise DataCenterError('文件在冻结期间变化，请保存后重试：' + resource['title'])
            entity_id = self.store.add_entity(product_id, 'resource-file:' + resource['id'], 'file',
                                              resource['title'], data, raw=True,
                                              metadata=dict(resource_id=resource['id'], name=Path(resource['locator']).name,
                                                            locator=resource['locator']))
            files.append(dict(resource_id=resource['id'], title=resource['title'], entity_id=entity_id,
                              sha256=sha256(data), observed_path=str(path), size=len(data)))
        entity_id, snapshot = self.capture(product_id, databases)
        for file in files:
            if _hash_file(file['observed_path']) != file['sha256']:
                raise DataCenterError('文件在数据库快照期间变化，未发布基线：' + file['title'])
        report = evaluate(snapshot, self.store.rules(product_id))
        if report['errors']:
            raise DataCenterError('质量检查发现 %s 个错误，未冻结基线。请先运行质量检查查看明细。' % report['errors'])
        report_id = self.store.add_entity(product_id, 'product-quality', 'quality', '基线质量检查', report,
                                          metadata=dict(snapshot=entity_id))
        runs = [dict(id=run['id'], title=run['title'], status=run['status'], started=run['started'], ended=run['ended'])
                for run in self.store.runs(product_id) if run['status'] != 'running']
        manifest = dict(format=1, product_id=product_id, snapshot=entity_id, files=files,
                        include_shared_files=include_shared,
                        excluded_resources=excluded, quality=report, quality_id=report_id,
                        software=software_signature(), runs=runs, captured=now(),
                        scope='固定所选产品数据库快照和所选文件；源端接口未冻结，运行记录不证明整条工程流程已通过。')
        baseline_id = self.store.publish_baseline(product_id, name, manifest, actor)
        return self.store.baseline(baseline_id)

    def compare(self, before_id, after_id):
        before, after = self.store.baseline(before_id), self.store.baseline(after_id)
        a = self.store.entity(before['manifest']['snapshot'], content=True)['content']
        b = self.store.entity(after['manifest']['snapshot'], content=True)['content']
        result = compare_snapshots(a, b)
        old = {f['resource_id']: f for f in before['manifest']['files']}
        new = {f['resource_id']: f for f in after['manifest']['files']}
        result['files'] = [dict(title=(new.get(k) or old[k])['title'], before=old.get(k, {}).get('sha256'),
                                after=new.get(k, {}).get('sha256')) for k in sorted(set(old) | set(new))
                           if old.get(k, {}).get('sha256') != new.get(k, {}).get('sha256')]
        return result

    def compare_current(self, baseline_id):
        baseline = self.store.baseline(baseline_id)
        a = self.store.entity(baseline['manifest']['snapshot'], content=True)['content']
        databases = sorted({t['database'] for t in a['tables']})
        b = capture_product(self.backend, baseline['product_id'], databases)
        result = compare_snapshots(a, b)
        result['files'] = []
        for file in baseline['manifest']['files']:
            try:
                item = self.resources.get(file['resource_id'])
                # A managed resource has to observe its original source anew.
                self.resources.refresh(item['id'])
                path = self.resources.local_path(item['id'])
                current = _hash_file(path)
                status = self.resources.get(item['id'])['status']
            except Exception as exc:
                current, status = None, str(exc)
            if current != file['sha256'] or '缺失' in status or '失败' in status:
                result['files'].append(dict(title=file['title'], before=file['sha256'], after=current, status=status))
        previous = {file['resource_id'] for file in baseline['manifest']['files']}
        for item in self.resources.list(baseline['product_id']):
            if item['id'] in previous or item['mode'] == 'endpoint' or item['kind'] == 'sqlite':
                continue
            if not item['product_id'] and not baseline['manifest'].get('include_shared_files', False):
                continue
            try:
                self.resources.refresh(item['id'])
                current, status = _hash_file(self.resources.local_path(item['id'])), '新增资源'
            except Exception as exc:
                current, status = None, '新增资源不可用：' + str(exc)
            result['files'].append(dict(title=item['title'], before=None, after=current, status=status))
        return result

    def import_center_history(self):
        # MySQL's history row was committed atomically with the business values.
        # Import is idempotent; failed local publication can be retried later.
        def history_entries():
            revision = 0
            while True:
                batch = self.backend.history(after_revision=revision, limit=200)
                if not batch:
                    return
                yield from batch
                revision = batch[-1]['revision']
        for entry in history_entries():
            source_key = dumps([self.backend.config.get('host'), self.backend.config.get('port'),
                                self.backend.metadata_database, entry['revision'], str(entry['time'])])
            with self.store.connection() as conn:
                if conn.execute('SELECT 1 FROM lc_imports WHERE source_key=?', (source_key,)).fetchone():
                    continue
            plan = entry['plan']
            products = {str(change['ref']['keys'].get('产品ID', '')) for change in plan['changes']}
            before = {dumps(e['target']): e for e in plan['edges_before']}
            after = {dumps(e['target']): e for e in plan['edges_after']}
            for target in set(before) | set(after):
                if before.get(target) != after.get(target):
                    products.add(str((after.get(target) or before[target])['target']['keys'].get('产品ID', '')))
            products.discard('')
            for product_id in products or {''}:
                # All inputs/outputs are the transaction's own before/after values,
                # never a subsequent read of the current database.
                metadata = plan.get('execution', {})
                run_id = hashlib.sha256(dumps([source_key, product_id]).encode('utf-8')).hexdigest()
                with self.store.connection() as conn:
                    existing = conn.execute('SELECT status FROM lc_runs WHERE id=?', (run_id,)).fetchone()
                if existing and existing[0] == 'completed':
                    continue
                if not existing:
                    self.store.start_run(product_id, entry['action'], entry['actor'] or '未记录',
                        software=metadata.get('software', {'version': '历史事务未记录程序版本'}),
                        actor_source='数据库事务日志', run_id=run_id, observed_started=metadata.get('started', ''))
                used = self.store.add_entity(product_id, 'center-before', 'field-values', '事务实际校验的输入值',
                                              dict(observed=plan['observed'], edges=plan['edges_before']))
                produced = self.store.add_entity(product_id, 'center-after', 'field-values', '事务读回确认的输出值',
                                                  dict(changes=plan['changes'], edges=plan['edges_after']))
                self.store.link(run_id, used, 'used')
                self.store.link(run_id, produced, 'generated')
                self.store.finish_run(run_id, 'completed', dict(revision=entry['revision'],
                    committed_at=str(entry['time']), evidence_origin='MySQL 同事务 dc_history', execution=metadata,
                    scope='多产品联动时本条记录保留完整事务范围，不能将整笔事务拆成独立提交。'),
                    observed_ended=str(entry['time']))
            with self.store.connection() as conn:
                conn.execute('INSERT OR IGNORE INTO lc_imports VALUES (?,?)', (source_key, run_id))

    def export_baseline(self, baseline_id, destination):
        baseline = self.store.baseline(baseline_id)
        destination = Path(destination).resolve()
        if destination.exists():
            raise DataCenterError('导出目录已经存在，请选择新的目录名称。')
        destination.mkdir(parents=True)
        ids = {baseline['manifest_id'], baseline['manifest']['snapshot'], baseline['manifest']['quality_id']}
        ids.update(f['entity_id'] for f in baseline['manifest']['files'])
        runs = []
        for entry in baseline['manifest']['runs']:
            run = self.store.run(entry['id'])
            ids.update(entity['id'] for entity in run['entities'])
            runs.append(run)
        entities = []
        for entity_id in ids:
            entity = self.store.entity(entity_id, content=True)
            entity.pop('content')
            source = self.store.home / entity['blob_key']
            target = destination / entity['blob_key']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(target))
            if _hash_file(target) != entity['blob_sha']:
                raise DataCenterError('基线导出校验失败。')
            entities.append(entity)
        (destination / 'baseline.json').write_text(dumps(dict(baseline=baseline, entities=entities, runs=runs)), encoding='utf-8')
        (destination / 'COMPLETE').write_text(now(), encoding='utf-8')
        return destination

    def run_graph(self, run_id):
        from .lineage import Graph
        from .provenance import TraceNode, TraceEdge
        class RecordedNode(TraceNode):
            @property
            def keys(self):
                return (('依据', '已观察的运行记录 · 只读'),)
        run = self.store.run(run_id)
        focus = RecordedNode('operation', run_id, '真实运行 · ' + run['status'], run['title'], run['actor'], dumps(run))
        graph = Graph(focus, {focus: run['started']}, {}, [])
        for entity in run['entities']:
            node = RecordedNode('input' if entity['role'] == 'used' else 'table', entity['id'],
                '真实证据 · ' + entity['role'], entity['label'], 'v%s · %s' % (entity['version'], entity['content_sha'][:12]),
                dumps({k: v for k, v in entity.items() if k != 'metadata'}))
            graph.values[node] = entity['kind']
            if entity['role'] == 'generated':
                graph.edges.append(TraceEdge(focus, node, '已实际生成 / 已提交，不表示工程校核通过'))
            else:
                label = '实际使用' if entity['role'] == 'used' else '上下文 / 环境依据，不代表逐字段取值'
                graph.edges.append(TraceEdge(node, focus, label))
        for child in run['children']:
            node = RecordedNode('operation', child['id'], '子运行 · ' + child['status'], child['title'], child['id'][:12],
                             '在运行列表中选择该记录查看其实际输入和输出。')
            graph.values[node] = child['status']
            graph.edges.append(TraceEdge(focus, node, '实际调用的子操作'))
        graph.notes.append('运行证据是只读历史；上下文、SQL提交和 DLL 输入输出分别标明，不把静态代码关系当作已执行事实。')
        return graph
