"""Unpack the release into a clean Chinese path and exercise its real application."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

BASE = Path(__file__).resolve().parent

CONTROLLER = r'''
import json,os,pathlib,sys,time
app_root=pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0,str(app_root))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['PYTHONPATH']=''
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from PyQt5.QtGui import QFontDatabase
import run
import pymysql
from platform_core.private_database import _options,assert_private,atomic_json
from platform_core.bundled_database import process_alive
assert pathlib.Path(run.__file__).resolve().parent==app_root
forbidden={3306,int(sys.argv[3])}; attempted=[]
def audit(event,args):
    if event=='socket.connect' and len(args)>1 and isinstance(args[1],tuple) and args[1][1] in forbidden:
        attempted.append(args[1][1]);raise AssertionError('Source DB connection attempted')
sys.addaudithook(audit)
app=QApplication([])
for font in ('msyh.ttc','msyhbd.ttc'):QFontDatabase.addApplicationFont(str(pathlib.Path('C:/Windows/Fonts')/font))
window=run.MainWindow();window.show();config=None
def wait_until(predicate,seconds):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();QTest.qWait(40)
    if not predicate():raise AssertionError(window.state.text()+' | '+window.report.toPlainText()[:500])
started=time.monotonic()
try:
    window.prepare_database()
    wait_until(lambda:window.database_worker is None,150)
    assert '已就绪' in window.data_badge.text(),window.messages
    database_seconds=time.monotonic()-started
    config=json.loads((app_root/'workspace/mysql/connection.local.json').read_text(encoding='utf-8'))
    assert config['port'] not in forbidden
    assert pathlib.Path(config['mysql_home']).resolve()==app_root/'bundled_database/mysql'
    print(json.dumps(dict(database_ready=True,seconds=round(database_seconds,2),port=config['port'])),flush=True)
    window.inputs=[sys.argv[2]];window.update_attachments()
    window.prompt.setPlainText('迁移包验收：整理输入中的全部产品并自动复核。')
    window.begin.click()
    wait_until(lambda:window.worker is None,330)
    result=window.last_result
    assert result and len(result['products'])==11,window.report.toPlainText()
    assert not any(p['status']=='processing_failed' for p in result['products']),window.report.toPlainText()
    assert window.chat_scroll.widget().isAncestorOf(window.module_panel)
    assert window.chat_scroll.widget().isAncestorOf(window.execution)
    pipeline_seconds=window.elapsed_value
    print(json.dumps(dict(products=11,pipeline_seconds=round(pipeline_seconds,2))),flush=True)
    before=result['products'][0]['draft_data_sha256'];replies=[]
    window.module_panel.reply.connect(replies.append)
    window.prompt.setPlainText(result['products'][0]['tag']+' 壳程设计压力改为 2.25 MPa')
    window.begin.click();wait_until(lambda:bool(replies),70)
    assert '2.25' in replies[-1],replies
    window.prompt.setPlainText('保存并继续审核');window.begin.click()
    wait_until(lambda:window.last_result['products'][0]['draft_data_sha256']!=before and not window.module_panel.busy,70)
    identity=window.last_result['products'][0]['id']
    with pymysql.connect(**_options(config)) as conn:
        assert_private(conn,config)
        with conn.cursor() as cur:
            cur.execute("SELECT 壳程数值 FROM 产品设计活动库.产品设计活动表_设计数据表 WHERE 产品ID=%s AND 参数名称='设计压力*'",(identity,))
            assert float(cur.fetchone()[0])==2.25
    print('Packaged module edit/save/private DB readback passed.',flush=True)
    window.navigate(3)
    for _ in range(5):app.processEvents();QTest.qWait(50)
    window.grab().save(sys.argv[4])
    graph=window.fabric.execution(result['run_id'])
    receipt=dict(ok=True,application_root=str(app_root),run_id=result['run_id'],products=11,
        database_start_seconds=round(database_seconds,3),pipeline_seconds=round(pipeline_seconds,3),
        actual_calls=len(graph['tasks']),module_saved_value=2.25,source_database_connections=attempted,
        private_port=config['port'],source_configuration_required=False,inline_cards=True,
        full_product_generated=False,calculation_input_generated=False)
    atomic_json(pathlib.Path(sys.argv[5]),receipt)
finally:
    if window.worker:
        window.worker.cancelled.set();wait_until(lambda:window.worker is None,25)
    window.module_panel.request_close_all()
    wait_until(lambda:not window.module_panel.sessions and not window.module_panel.busy,25)
    window.close();app.processEvents()
    if config:
        data=pathlib.Path(config['datadir']).resolve()
        assert data.is_relative_to(app_root/'workspace')
        pid=json.loads((data.parent/'process.json').read_text(encoding='utf-8'))['pid']
        try:
            with pymysql.connect(**_options(config)) as conn:
                assert_private(conn,config)
                with conn.cursor() as cur:cur.execute('SHUTDOWN')
        except pymysql.OperationalError as exc:
            if exc.args[0] not in (2006,2013):raise
        deadline=time.monotonic()+25
        while process_alive(pid) and time.monotonic()<deadline:time.sleep(.1)
        assert not process_alive(pid)
'''


def verify(archive_path):
    archive_path = Path(archive_path).resolve()
    # Keep the whole application test at a normal install-path depth. The
    # database-specific verification separately exercises much deeper paths.
    root = Path(tempfile.mkdtemp(prefix='agent-pkg-')) / '迁移包测试 A'
    root.mkdir(parents=True)
    config = json.loads((BASE / 'workspace/mysql/connection.local.json').read_text(encoding='utf-8'))
    actual_password = config['password'].encode('utf-8')
    with zipfile.ZipFile(archive_path) as archive:
        receipt = json.loads(archive.read('EngineeringAgent/PACKAGE-RECEIPT.json'))
        assert not receipt['python_interpreter_included'] and not receipt['local_credentials_included']
        for record in receipt['files']:
            name = record['path']
            assert not name.startswith('workspace/')
            assert Path(name).name not in {'api_key.txt', 'connection.local.json', 'private-instance.json', 'config.local.json'}
            value = archive.read('EngineeringAgent/'+name)
            assert len(value) == record['bytes'] and hashlib.sha256(value).hexdigest() == record['sha256']
            assert actual_password not in value, 'Local database password leaked into package'
        for name in archive.namelist():
            if not (root / name).resolve().is_relative_to(root.resolve()): raise RuntimeError('Invalid archive path')
        archive.extractall(root)
    app_root = root / 'EngineeringAgent'
    controller = root / 'verify_application.py'
    controller.write_text(CONTROLLER, encoding='utf-8')
    source_root = BASE / 'workspace/runs/457f34ae30d241abb7121551a520aebf'
    source = next(s for s in json.loads((source_root / 'sources.json').read_text(encoding='utf-8')) if '管壳式换热器数据表' in s['title'])
    target = root / source['title']
    shutil.copyfile(source['path'], target)
    output = BASE / 'workspace/evidence/portable-package-verification.json'
    screenshot = BASE / 'workspace/evidence/portable-package-execution.png'
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8', PYTHONPATH='')
    process = subprocess.run([sys.executable, '-X', 'faulthandler', str(controller), str(app_root), str(target),
                              str(config['port']), str(screenshot), str(output)], cwd=str(app_root), env=environment,
                             timeout=600)
    if process.returncode: raise RuntimeError('Packaged application verification failed')
    result = json.loads(output.read_text(encoding='utf-8'))
    result.update(archive=str(archive_path), archive_sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                  all_packaged_file_hashes_verified=True, local_database_password_absent=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    print(json.dumps(verify(parser.parse_args().archive), ensure_ascii=False))
