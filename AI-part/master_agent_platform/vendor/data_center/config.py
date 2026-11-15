"""Standalone configuration; never imports the DongLanpec application."""
import json
import os
from pathlib import Path


def project_home():
    return Path(__file__).resolve().parent.parent


def settings():
    path = Path(os.environ.get('DATA_CENTER_CONFIG') or project_home() / 'config.local.json').expanduser()
    if not path.is_file():
        if os.environ.get('DATA_CENTER_CONFIG'):
            raise ValueError('指定的数据中心配置文件不存在：' + str(path))
        return {}
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or not isinstance(value.get('database', {}), dict):
        raise ValueError('数据中心配置格式无效，请参照 config.example.json。')
    return value


def database_config():
    allowed = {'host', 'port', 'user', 'password', 'charset', 'connect_timeout', 'read_timeout', 'write_timeout'}
    result = dict(host='localhost', port=3306, user='root', password='', charset='utf8mb4', connect_timeout=5)
    result.update({k: v for k, v in settings().get('database', {}).items() if k in allowed})
    for option in ('host', 'port', 'user', 'password'):
        variable = 'DATA_CENTER_DB_' + option.upper()
        if variable in os.environ:
            result[option] = int(os.environ[variable]) if option == 'port' else os.environ[variable]
    return result


def source_root():
    value = os.environ.get('DONGLANPEC_SOURCE_ROOT') or settings().get('source_root')
    return Path(value).expanduser().resolve() if value else None
