"""Build distributable foundations from the platform's private, verified copy.

Only library/template rows and the default configuration are exported. Product
schemas are exported without any rows. No source credentials enter the bundle.
"""
import argparse
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil

import pymysql

from platform_core.bundled_database import BUNDLE_SCHEMA, encode_value, file_hash, rows_hash
from platform_core.private_database import FOUNDATIONS, PRODUCT_STRUCTURES, _options, assert_private, atomic_json, quote

BASE = Path(__file__).resolve().parent
SECRET = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def copy_runtime(source, destination):
    """Retain the server, release DLLs/plugins, messages, and vendor notices."""
    import pefile  # Build-machine dependency only; not needed by users.
    source, destination = Path(source), Path(destination)
    files = [source / 'bin/mysqld.exe', source / 'LICENSE', source / 'README']
    files += [p for p in (source / 'bin').glob('*.dll') if 'debug' not in p.name.lower()]
    files += [p for p in (source / 'share').rglob('*') if p.is_file()]
    files += [p for p in (source / 'lib/plugin').rglob('*.dll') if 'debug' not in [v.lower() for v in p.parts]]
    for path in files:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    # Include app-local VC runtime dependencies; never copy Windows OS DLLs.
    candidates = [destination / 'bin', Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32']
    todo = list(destination.rglob('*.dll')) + [destination / 'bin/mysqld.exe']
    seen = set()
    while todo:
        path = todo.pop()
        if path in seen: continue
        seen.add(path)
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            names = [d.dll.decode('ascii') for d in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])]
        for name in names:
            if not name.lower().startswith(('msvcp', 'vcruntime', 'concrt')): continue
            target = destination / 'bin' / name
            if not target.is_file():
                original = next((d / name for d in candidates if (d / name).is_file()), None)
                if original is None: raise RuntimeError('Missing app-local runtime dependency: '+name)
                shutil.copyfile(original, target)
            todo.append(target)
    (destination / 'RUNTIME-NOTICE.txt').write_text(
        'MySQL Community Server: see LICENSE and README in this directory.\n'
        'Microsoft Visual C++ runtime DLLs remain subject to their Microsoft runtime license terms.\n'
        'Only runtime binaries are included; no MySQL data directory, account or password is shipped.\n', encoding='utf-8')


def build(workspace, output):
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    if output.exists(): raise RuntimeError('Build output already exists; select a new directory: '+str(output))
    config = json.loads((workspace / 'mysql/connection.local.json').read_text(encoding='utf-8'))
    source_receipt = json.loads((workspace / 'snapshots/foundation-snapshot.json').read_text(encoding='utf-8'))
    if source_receipt.get('status') != 'copied-and-verified': raise RuntimeError('Private foundations are not verified.')
    output.mkdir(parents=True)
    (output / '.gitattributes').write_text('* -text\n', encoding='ascii')
    copy_runtime(config['mysql_home'], output / 'mysql')
    tables, databases = [], []
    with pymysql.connect(**_options(config)) as conn:
        assert_private(conn, config)
        with conn.cursor() as cur:
            cur.execute('SELECT VERSION()')
            version = cur.fetchone()[0]
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            for database in FOUNDATIONS+PRODUCT_STRUCTURES:
                cur.execute('SELECT DEFAULT_CHARACTER_SET_NAME,DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (database,))
                charset, collation = cur.fetchone()
                databases.append(dict(name=database, charset=charset, collation=collation))
                cur.execute("SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", (database,))
                for name, engine in cur.fetchall():
                    full = quote(database)+'.'+quote(name)
                    cur.execute('SHOW CREATE TABLE '+full)
                    create = cur.fetchone()[1]
                    cur.execute('SELECT * FROM '+full+' LIMIT 0')
                    columns = [v[0] for v in cur.description]
                    rows = []
                    policy = 'schema-only'
                    if database in FOUNDATIONS:
                        if database == '配置库' and 'name' in columns:
                            # Active per-project settings are replaced by the shipped default.
                            source_table = quote(database)+'.'+quote('user_config_beifen' if name == 'user_config' else name)
                            cur.execute('SELECT '+','.join(quote(c) for c in columns)+' FROM '+source_table+' WHERE name=%s', ('默认',))
                            policy = 'default-config-only'
                        else:
                            cur.execute('SELECT * FROM '+full)
                            policy = 'foundation-data'
                        rows = cur.fetchall()
                    filename = 'seed/table-'+str(len(tables)+1).zfill(4)+'.jsonl.gz'
                    path = output / filename
                    path.parent.mkdir(exist_ok=True)
                    header = dict(columns=columns, create_sql=create)
                    with path.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
                        with io.TextIOWrapper(zipped, encoding='utf-8', newline='\n') as text:
                            text.write(json.dumps(header, ensure_ascii=False)+'\n')
                            for row in rows:
                                line = json.dumps([encode_value(v) for v in row], ensure_ascii=False)
                                if SECRET.search(line.encode('utf-8')):
                                    raise RuntimeError('Credential-like data in a foundation table: '+full)
                                text.write(line+'\n')
                    import hashlib
                    tables.append(dict(database=database, table=name, engine=engine,
                        mode='data' if database in FOUNDATIONS else 'schema-only', policy=policy,
                        rows=len(rows), file=filename, bytes=path.stat().st_size, sha256=file_hash(path),
                        ddl_sha256=hashlib.sha256(create.encode('utf-8')).hexdigest(), logical_rows_sha256=rows_hash(rows)))
            conn.rollback()
    runtime = [dict(file=str(p.relative_to(output)).replace('\\', '/'), bytes=p.stat().st_size, sha256=file_hash(p))
               for p in sorted((output / 'mysql').rglob('*')) if p.is_file()]
    manifest = dict(schema=BUNDLE_SCHEMA, mysql_version=version, target='windows-x64', databases=databases, tables=tables,
        runtime=dict(home='mysql', files=runtime), product_rows_included=False, project_configurations_included=False,
        connection_credentials_included=False, foundations=list(FOUNDATIONS), configuration='默认')
    atomic_json(output / 'manifest.json', manifest)
    return dict(status='built', path=str(output), tables=len(tables), rows=sum(t['rows'] for t in tables),
                runtime_files=len(runtime), bytes=sum(r['bytes'] for r in runtime)+sum(t['bytes'] for t in tables))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', default=str(BASE / 'workspace'))
    parser.add_argument('--output', default=str(BASE / 'bundled_database'))
    args = parser.parse_args()
    print(json.dumps(build(args.workspace, args.output), ensure_ascii=False))
