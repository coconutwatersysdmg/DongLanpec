"""Verify new-chat closure and unsaved-draft retention using real module processes."""
import json
import os
from pathlib import Path
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from run import MainWindow, BASE
from verify_original_ui import fixture
from platform_core.fabric import digest
from platform_core.private_database import atomic_json


def verify(summary_path):
    original = json.loads(Path(summary_path).read_text(encoding='utf-8'))
    original_paths = [Path(p['draft_path']).parent / 'draft-product.json' for p in original['products'] if p.get('draft_path')]
    original_hashes = {str(p): digest(p) for p in original_paths}
    summary = fixture(summary_path)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.on_complete(summary)
    window.show()
    replies = []
    window.module_panel.reply.connect(replies.append)
    home = BASE / 'workspace/evidence/new-chat'
    home.mkdir(parents=True, exist_ok=True)

    def wait_until(predicate, seconds=55):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(40)
        if not predicate():
            raise AssertionError(window.module_panel.status.text())

    try:
        panel = window.module_panel
        for module in ('project', 'conditions', 'elements', 'nozzles', 'tube_bundle'):
            panel.module.setCurrentIndex(panel.module.findData(module))
            panel.open_current()
            wait_until(lambda: not panel.busy and any(s['info']['module'] == module and s.get('attached') for s in panel.sessions))
            print('Opened module: ' + module, flush=True)
        window.prompt.setPlainText(summary['products'][0]['tag'] + ' 壳程设计压力改为 2.35 MPa')
        window.begin.click()
        wait_until(lambda: bool(replies))
        assert '2.35' in replies[-1], replies
        sessions = {s['info']['module']: s['path'] for s in panel.sessions}
        data_paths = [Path(p['draft_path']).parent / 'draft-product.json' for p in summary['products']]
        data_hashes = {str(p): digest(p) for p in data_paths}
        old_chat = window.chat_id
        started = time.monotonic()
        window.new_chat_button.click()
        wait_until(lambda: not window.pending_new_chat, 35)
        assert not panel.sessions
        assert window.chat_id != old_chat and window.active_run_id is None
        assert window.pages.currentIndex() == 0
        assert not window.execution.tasks and window.data_space.snapshot is None
        copies = {m: json.loads((p / 'working-copy.json').read_text(encoding='utf-8')) for m, p in sessions.items()}
        assert len(copies) == 5 and all(v.get('confirmed') is False for v in copies.values())
        row = next(r for r in copies['conditions']['conditions']['design_rows'] if r['param'] == '设计压力*' and r['side'] == 'shell')
        assert row['value'] == '2.35'
        assert all(digest(p) == sha for p, sha in data_hashes.items()), 'Unsaved changes were applied to the task.'
        assert all(digest(p) == sha for p, sha in original_hashes.items()), 'Source run changed.'
        previous = json.loads((window.workspace / 'conversations' / (old_chat + '.json')).read_text(encoding='utf-8'))
        assert previous['run_id'] == summary['run_id']
        window.grab().save(str(home / 'new-chat.png'))
        receipt = dict(ok=True, run_id=summary['run_id'], modules_closed=list(copies),
                       unsaved_condition_value=row['value'], all_working_copies_unconfirmed=True,
                       task_data_unchanged=True, source_run_unchanged=True,
                       old_conversation_retained=True, new_chat_seconds=round(time.monotonic()-started, 3),
                       screenshot=str(home / 'new-chat.png'), sessions={m: str(p) for m, p in sessions.items()})
        atomic_json(home / 'verification.json', receipt)
        return receipt
    finally:
        window.module_panel.request_close_all()
        deadline = time.monotonic()+10
        while window.module_panel.sessions and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(40)
            window.module_panel.request_close_all()
        for session in list(window.module_panel.sessions):
            session['process'].kill()  # Disposable test editors only.
            session['process'].waitForFinished(3000)
        window.close()
        app.processEvents()


if __name__ == '__main__':
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
