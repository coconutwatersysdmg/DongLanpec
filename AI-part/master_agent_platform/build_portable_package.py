"""Package the platform code, bundled database and notices without local state."""
import argparse
import hashlib
import json
import itertools
from pathlib import Path
import zipfile

from platform_core.bundled_database import load_bundle

BASE = Path(__file__).resolve().parent
DIRECTORIES = {'platform_core', 'contracts', 'docs', 'tests', 'vendor', 'ui_vendor', 'bundled_database'}
EXCLUDED = {'__pycache__', '.git', '.venv', 'venv', 'output', 'outputs', 'logs'}
LOCAL_FILES = {'api_key.txt', 'local_config.py', 'config.local.json', 'records.jsonl', '_last_project_path.txt'}
ROOT_FILES = {'README.md', 'requirements.txt', 'start.bat', 'start.ps1', 'run.py', 'run_pipeline.py',
    'agent_worker.py', 'module_runtime.py', 'evidence_runtime.py', 'bootstrap_agents.py', 'bootstrap_database.py',
    'ui-vendor-manifest.json', 'vendor-manifest.json', 'build_bundled_database.py', 'build_portable_package.py',
    'verify_bundled_database.py', 'verify_portable_package.py', 'verify_live_chat.py', 'verify_original_ui.py', 'verify_unified_bridge.py',
    'verify_unified_platform.py', 'verify_new_chat.py'}


def package_paths(base=BASE):
    base = Path(base)
    sources = itertools.chain((base / name for name in sorted(ROOT_FILES)),
        *(sorted((base / name).rglob('*')) for name in sorted(DIRECTORIES)))
    for path in sources:
        if not path.is_file(): continue
        rel = path.relative_to(base)
        if len(rel.parts) > 1 and rel.parts[0] not in DIRECTORIES: continue
        if any(part in EXCLUDED for part in rel.parts) or path.name in LOCAL_FILES or path.suffix.lower() in {'.pyc', '.pdb', '.log', '.pem', '.key'}: continue
        if str(rel).replace('\\', '/') in {'vendor/nozzle_agent/config.json', 'ui_vendor/nozzle_agent/config.json'}: continue
        if len(rel.parts) == 1 and path.suffix.lower() not in {'.py', '.md', '.json', '.ps1', '.bat', '.txt'}: continue
        yield path, str(rel).replace('\\', '/')


def build(destination):
    destination = Path(destination).resolve()
    load_bundle(BASE / 'bundled_database')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists(): raise RuntimeError('Package already exists; select a new output file.')
    records = []
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source, relative in package_paths():
            content = source.read_bytes()
            archive.writestr('EngineeringAgent/'+relative, content)
            records.append(dict(path=relative, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
        archive.writestr('EngineeringAgent/PACKAGE-RECEIPT.json', json.dumps(dict(
            schema='donglanpec.portable-package/1', bundled_database=True, python_interpreter_included=False,
            local_credentials_included=False, runtime_workspace_included=False, files=records), ensure_ascii=False, indent=2))
    value = hashlib.sha256()
    with destination.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): value.update(block)
    receipt = dict(file=str(destination), bytes=destination.stat().st_size, sha256=value.hexdigest(), files=len(records))
    destination.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(BASE / 'workspace/releases/EngineeringAgent-Windows-BundledDB.zip'))
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False))
