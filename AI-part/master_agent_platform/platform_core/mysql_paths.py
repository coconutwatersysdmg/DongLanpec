"""ASCII launch aliases for Windows MySQL; actual data stays in the workspace."""
import ctypes
import hashlib
import os
from pathlib import Path
import struct
import tempfile


def short_path(path):
    value = str(path)
    function = ctypes.windll.kernel32.GetShortPathNameW
    size = function(value, None, 0)
    if not size: return value
    buffer = ctypes.create_unicode_buffer(size)
    return buffer.value if function(value, buffer, size) else value


def make_junction(path, target):
    target = Path(target).resolve()
    path = Path(path)
    if path.exists():
        if path.resolve() == target: return
        if path.resolve() != path.absolute() or any(path.iterdir()):
            raise RuntimeError("数据库兼容路径已被占用，原目录已保留："+str(path))
    else: path.mkdir()
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x02000000 | 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    try:
        substitute = ('\\??\\'+str(target)).encode('utf-16-le')
        printable = str(target).encode('utf-16-le')
        paths = substitute+b'\0\0'+printable+b'\0\0'
        mount = struct.pack('<HHHH', 0, len(substitute), len(substitute)+2, len(printable))+paths
        record = struct.pack('<IHH', 0xA0000003, len(mount), 0)+mount
        buffer = ctypes.create_string_buffer(record)
        returned = wintypes.DWORD()
        if not kernel.DeviceIoControl(handle, 0x000900A4, buffer, len(record), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally: kernel.CloseHandle(handle)
    if path.resolve() != target: raise RuntimeError('数据库兼容路径校验失败。')


def launch_paths(mysql_home, instance):
    mysql_home, instance = Path(mysql_home).resolve(), Path(instance).resolve()
    values = (str(mysql_home), str(instance))
    if os.name != 'nt' or all(v.isascii() and ' ' not in v and len(v) < 180 for v in values):
        return dict(home=str(mysql_home), instance=str(instance))
    candidates = [Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'DongLanpecAgent/DatabasePaths',
                  Path(tempfile.gettempdir()) / 'DongLanpecAgentDatabasePaths',
                  Path(os.environ.get('ProgramData', 'C:/ProgramData')) / 'DongLanpecAgent/DatabasePaths']
    compatible = None
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            text = short_path(base)
            if text.isascii() and ' ' not in text:
                compatible = Path(text)
                break
        except OSError: continue
    if compatible is None: raise RuntimeError('无法建立数据库兼容路径，请检查本机应用数据目录的写入权限。')
    identity = hashlib.sha256(('\n'.join(values)).encode('utf-8')).hexdigest()[:20]
    root = compatible / identity
    root.mkdir(exist_ok=True)
    make_junction(root / 'engine', mysql_home)
    make_junction(root / 'instance', instance)
    # Keep the ASCII alias strings. Resolving them would expand Unicode paths.
    return dict(home=str(root / 'engine'), instance=str(root / 'instance'))
