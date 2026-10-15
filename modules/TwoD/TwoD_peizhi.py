import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import uuid
from contextlib import contextmanager
from tkinter import filedialog, messagebox

import psutil
import pymysql
import win32api
import win32com
import win32com.client
import win32con
import win32security

import os
import time, pythoncom
import pywintypes  # 来自 pywin32

from modules.TwoD.cad_context import CAD_CTX
from modules.TwoD.autocad_startup_probe import WORKER_FLAG, registered_autocad_servers

# 这些 HRESULT 是常见的“忙/稍后再试/被拒绝”
_RPC_BUSY_CODES = {
    -2147417846,   # 常见：消息筛选器显示应用程序正在使用中
    -2147417830,   # RPC_E_SERVERCALL_RETRYLATER
    -2147418111,   # RPC_E_CALL_REJECTED（偶尔也会遇到）
}


def get_value_teshu(sql, params=None):
    conn = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor
    )
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    row = cursor.fetchone()
    return row[0] if row and row[0] is not None else None
def com_retry(callable_fn, retries=30, base_sleep=0.05, max_sleep=0.5, quiet=False):
    """
    在 AutoCAD 繁忙时对 COM 调用做自动重试。
    - retries: 最大重试次数
    - base_sleep: 初始重试间隔
    - max_sleep: 最大间隔上限
    """
    last_error = None
    for i in range(retries):
        try:
            return callable_fn()
        except pywintypes.com_error as e:
            last_error = e
            # 取 HRESULT
            hr = getattr(e, "hresult", None)
            if hr is None:
                # 有些版本把 hr 放在 args[0]
                try:
                    hr = e.args[0]
                except Exception:
                    hr = None

            busy = (hr in _RPC_BUSY_CODES) or ("应用程序正在使用中" in str(e))
            if not busy:
                # 非忙类错误，直接抛出
                raise

            # 忙：泵消息 + 渐进等待后重试
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass

            # 线性退避
            slp = min(max_sleep, base_sleep * (i + 1))
            if not quiet:
                # 你也可以换成 log_info
                print(f"⌛ AutoCAD 繁忙，重试第 {i+1}/{retries} 次，等待 {slp:.2f}s …")
            time.sleep(slp)
            continue

    # 以前重试耗尽后会隐式返回 None，后续代码继续访问 COM 对象时才报出
    # 无关的 AttributeError。保留最初的 RPC 错误，便于上层正确清理文档。
    if last_error is not None:
        raise last_error
    raise RuntimeError("COM 调用重试结束但没有返回结果。")

def open_drawing_with_wait(file_path, timeout=300):
    """用 COM 打开 DWG，并等待文档就绪后返回 (acad, doc)。不走 os.startfile / SendCommand。"""
    import time, pythoncom, os

    # 1) 规范化 & 必须是存在的 .dwg 文件（绝对路径）
    path = ensure_dwg_path(file_path)
    if not must_exist_file(path):
        raise FileNotFoundError(f"DWG 文件不存在，本次生成已停止：{path}")

    # 2) 获取 AutoCAD 实例
    acad = get_autocad_instance()
    if acad is None:
        raise RuntimeError("没有可用的 CAD 实例，本次生成已停止。")

    # ★ 打开前先等一下空闲（降低“忙”概率）
    if not wait_cad_idle(acad, timeout=20):
        raise RuntimeError("CAD 未进入空闲状态，本次停止打开图纸，请先结束 CAD 命令或关闭弹窗。")

    # 3) 已开即用（避免重复打开）
    def _norm(p):
        return os.path.normcase(os.path.normpath(p or ""))

    target = _norm(path)
    def _scan():
        for i in range(acad.Documents.Count):
            d = acad.Documents.Item(i)
            if _norm(getattr(d, "FullName", "")) == target:
                return d
        return None

    doc = com_retry(_scan, retries=10, base_sleep=0.05, max_sleep=0.3, quiet=True)

    # 4) 只用 COM 打开（关键！）
    try:
        if doc is None:
            doc = com_retry(lambda: acad.Documents.Open(path), retries=40, base_sleep=0.05, max_sleep=0.5)
        else:
            com_retry(lambda: doc.Activate(), retries=10, base_sleep=0.05, max_sleep=0.3, quiet=True)
    except Exception as e:
        log_error(f"⚠️ COM Open 失败：{e}")
        raise RuntimeError(f"CAD 打开或激活图纸失败，本次生成已停止：{path}；{e}") from e

    # 5) 等待就绪（消息泵 + 轻量轮询）
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        _check_cad_startup_cancelled()
        try:
            pythoncom.PumpWaitingMessages()
        except Exception:
            pass
        try:
            _ = com_retry(lambda: getattr(doc, "Name", None), retries=10, base_sleep=0.05, max_sleep=0.3, quiet=True)
            _ = com_retry(lambda: int(doc.ModelSpace.Count), retries=10, base_sleep=0.05, max_sleep=0.3, quiet=True)
            if _norm(com_retry(lambda: doc.FullName, quiet=True)) != target:
                raise RuntimeError("CAD 返回了其它图纸，无法确认目标文档。")
            break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"图纸在 {timeout} 秒内未完成加载，本次生成已停止：{path}")

    return acad, doc
def strip_quotes(p: str) -> str:
    p = (p or "").strip()
    if len(p) >= 2 and ((p[0]==p[-1]=='"') or (p[0]==p[-1]=="'")):
        return p[1:-1]
    return p

def ensure_dwg_path(p: str) -> str:
    p = os.path.normpath(strip_quotes(p))
    if not p:
        return ""
    if os.path.isdir(p):
        return ""  # 传的是目录就直接判错
    root, ext = os.path.splitext(p)
    p = p if ext.lower() == ".dwg" else (root + ".dwg")
    return os.path.abspath(p)   # ★ 一律转为绝对路径

def must_exist_file(p: str) -> bool:
    try:
        return os.path.isfile(p)
    except Exception:
        return False

_AUTOCAD_CONNECT_LOCK = threading.RLock()
AUTOCAD_STARTUP_TIMEOUT = 180.0
_CAD_STARTUP_LOCAL = threading.local()
_AUTOCAD_PROGIDS = (
    "AutoCAD.Application",
    *(f"AutoCAD.Application.{ver}" for ver in range(40, 9, -1)),
)


@contextmanager
def cad_startup_feedback(status_callback, cancelled, waiting_callback=None):
    """同一个生成线程共用已就绪实例，反馈进度并允许取消启动等待。"""
    previous = vars(_CAD_STARTUP_LOCAL).copy()
    _CAD_STARTUP_LOCAL.status_callback = status_callback
    _CAD_STARTUP_LOCAL.cancelled = cancelled
    _CAD_STARTUP_LOCAL.waiting_callback = waiting_callback
    _CAD_STARTUP_LOCAL.acad = None
    try:
        yield
    finally:
        vars(_CAD_STARTUP_LOCAL).clear()
        vars(_CAD_STARTUP_LOCAL).update(previous)


def _check_cad_startup_cancelled():
    cancelled = getattr(_CAD_STARTUP_LOCAL, "cancelled", None)
    if cancelled and cancelled():
        raise RuntimeError("用户取消生成")


def _cad_startup_status(message):
    callback = getattr(_CAD_STARTUP_LOCAL, "status_callback", None)
    if callback:
        callback(message)
    else:
        print("[CAD] " + message)


@contextmanager
def _cad_probe_wait_scope():
    callback = getattr(_CAD_STARTUP_LOCAL, "waiting_callback", None)
    if callback:
        callback(True)
    try:
        yield
    finally:
        if callback:
            callback(False)


def _stop_startup_probe(process):
    # 只清理探测进程，绝不结束 CAD 或关闭用户的图纸。
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _wait_cad_startup_probe(progids, timeout):
    """把可能阻塞的 COM 探测放到独立进程，父线程负责总时限与取消。"""
    command = ([sys.executable, WORKER_FLAG] if getattr(sys, "frozen", False) else
               [sys.executable, os.path.join(os.path.dirname(__file__), "autocad_startup_probe.py")])
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    options = dict(stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    started = time.monotonic()
    with _cad_probe_wait_scope(), tempfile.TemporaryDirectory(prefix="donglanpec_cad_probe_") as folder:
        input_path = os.path.join(folder, "input.json")
        events_path = os.path.join(folder, "events.jsonl")
        log_path = os.path.join(folder, "probe.log")
        with open(input_path, "w", encoding="utf-8") as stream:
            json.dump({"progids": list(progids)}, stream)
        deadline = started + max(0.0, timeout)
        last_report = -float("inf")
        stage, last_error = "正在等待 CAD 启动", ""
        offset, pending = 0, ""
        with open(log_path, "wb") as log:
            process = subprocess.Popen(command + [input_path, events_path], stdout=log, **options)
            try:
                while True:
                    _check_cad_startup_cancelled()
                    now = time.monotonic()
                    if now >= deadline:
                        raise RuntimeError(
                            f"等待 CAD 就绪已超过 {timeout:g} 秒，本次生成已停止。当前阶段：{stage}。"
                            "请查看 CAD 窗口是否有启动、许可或配置弹窗，处理后重新生成。"
                            + (f" 最后响应：{last_error}" if last_error else ""))
                    if now - last_report >= 2:
                        _cad_startup_status(f"{stage}（已等待 {int(now - started)} 秒，最长 {timeout:g} 秒，可取消）")
                        last_report = now
                    if os.path.isfile(events_path):
                        with open(events_path, "r", encoding="utf-8") as stream:
                            stream.seek(offset)
                            pending += stream.read()
                            offset = stream.tell()
                        lines = pending.split("\n")
                        pending = lines.pop()
                        for line in lines:
                            update = json.loads(line)
                            stage = update.get("stage", stage)
                            last_error = update.get("error", last_error)
                            if update.get("ready"):
                                _cad_startup_status("CAD 已就绪，开始生成图纸")
                                return update["progid"]
                    if process.poll() is not None:
                        with open(log_path, "r", encoding="utf-8", errors="replace") as stream:
                            detail = stream.read()[-1500:]
                        raise RuntimeError(f"CAD 启动检测异常结束，本次生成已停止：{detail or last_error or stage}")
                    time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
            finally:
                _stop_startup_probe(process)


def choose_cad_exe():
    root = tk.Tk()
    root.withdraw()
    try:
        exe_path = filedialog.askopenfilename(
            title="选择 AutoCAD 程序 (acad.exe)",
            filetypes=[("AutoCAD 可执行文件", "acad.exe"), ("可执行文件", "*.exe")]
        )
        if not exe_path:
            return None

        exe_path = os.path.abspath(exe_path)
        if os.path.basename(exe_path).lower() != "acad.exe":
            messagebox.showerror("选择错误", "请选择 AutoCAD 安装目录中的 acad.exe。")
            return None
        return exe_path
    finally:
        root.destroy()


def _process_logon_identity(pid):
    """读取实际进程令牌；USERNAME/USERPROFILE 环境变量不能代表进程身份。"""
    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            logon = win32security.GetTokenInformation(token, win32security.TokenStatistics)["AuthenticationId"]
            session = win32security.GetTokenInformation(token, win32security.TokenSessionId)
            return win32security.ConvertSidToStringSid(sid), logon, session
        finally:
            token.Close()
    finally:
        handle.Close()


def _autocad_process_running():
    """只复用当前用户、当前登录会话的 CAD，其它会话没有本次可用的 COM 接口。"""
    current_identity = _process_logon_identity(os.getpid())
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() != "acad.exe":
                continue
            if _process_logon_identity(proc.info["pid"]) == current_identity:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, pywintypes.error):
            continue
    return False


def _attach_running_autocad(timeout=AUTOCAD_STARTUP_TIMEOUT, poll=0.25):
    """限定时间检测绘图接口与空闲状态，再在当前 COM 线程附着。"""
    servers = registered_autocad_servers()
    progids = [name for name, _ in servers] or list(_AUTOCAD_PROGIDS)
    progid = _wait_cad_startup_probe(progids, timeout)
    try:
        acad = win32com.client.GetActiveObject(progid)
    except Exception as exc:
        raise RuntimeError(f"CAD 就绪后连接失效，本次生成已停止：{exc}") from exc
    print(f"[CAD] 已附着现有 AutoCAD：{progid}")
    return acad
def get_current_doc(product_id=None):
    """只返回本次生成的目标文档，避免把空白图或上一张图当成总图。"""
    doc = CAD_CTX.get("doc")
    if doc is None:
        return None
    if product_id is not None and str(CAD_CTX.get("product_id")) != str(product_id):
        raise RuntimeError("当前文档属于其它产品，本次生成已停止。")
    target = CAD_CTX.get("target_dwg")
    if not target:
        raise RuntimeError("没有记录本次目标图纸路径，生成已停止。")
    try:
        actual = com_retry(lambda: doc.FullName, quiet=True)
    except Exception as exc:
        raise RuntimeError(f"本次目标图纸连接失效，生成已停止：{exc}") from exc
    normalize = lambda value: os.path.normcase(os.path.abspath(value))
    if not actual or normalize(actual) != normalize(target):
        raise RuntimeError(f"当前文档与本次目标图纸不一致，生成已停止：{target}")
    return doc
def try_start_autocad_com(timeout=AUTOCAD_STARTUP_TIMEOUT):
    """
    获取 AutoCAD COM 实例。

    若 acad.exe 已存在，只等待并附着；没有进程时从注册的安装路径启动。
    不使用同步 Dispatch 启动，避免它阻塞在超时循环之外。
    """
    with _AUTOCAD_CONNECT_LOCK:
        _check_cad_startup_cancelled()
        if _autocad_process_running():
            print("[CAD] 检测到 AutoCAD 正在启动，等待 COM 接口就绪...")
            return _attach_running_autocad(timeout=timeout)
        servers = registered_autocad_servers()
        if not servers:
            return None
        return start_autocad_by_path(servers[0][1], timeout=timeout)


def start_autocad_by_path(exe_path, timeout=AUTOCAD_STARTUP_TIMEOUT):
    """从明确的 acad.exe 启动一次，然后只轮询附着该实例。"""
    with _AUTOCAD_CONNECT_LOCK:
        exe_path = os.path.abspath(exe_path or "")
        if (
            not os.path.isfile(exe_path)
            or os.path.basename(exe_path).lower() != "acad.exe"
        ):
            print("[CAD] 无效的 AutoCAD 路径，必须选择 acad.exe")
            return None

        _check_cad_startup_cancelled()
        # 文件选择期间 CAD 可能已由用户打开，启动前再检查一次。
        if _autocad_process_running():
            return _attach_running_autocad(timeout=timeout)

        try:
            subprocess.Popen(
                [exe_path],
                cwd=os.path.dirname(exe_path),
                close_fds=True,
            )
        except Exception as exc:
            print(f"[CAD] 启动 AutoCAD 失败：{exc}")
            return None

        print(f"[CAD] 已启动 AutoCAD，正在等待 COM：{exe_path}")
        return _attach_running_autocad(timeout=timeout)


def get_autocad_instance(timeout=AUTOCAD_STARTUP_TIMEOUT):
    """
    TwoD 获取 AutoCAD 的唯一公共入口。

    整段流程加锁，避免多个绘图步骤在 CAD 尚未注册到 ROT 时重复启动。
    """
    with _AUTOCAD_CONNECT_LOCK:
        _check_cad_startup_cancelled()
        cached = getattr(_CAD_STARTUP_LOCAL, "acad", None)
        if cached is not None:
            return cached
        acad = try_start_autocad_com(timeout=timeout)
        if acad is not None:
            if getattr(_CAD_STARTUP_LOCAL, "status_callback", None):
                _CAD_STARTUP_LOCAL.acad = acad
            return acad

        # COM 通用 ProgID 不可用，且没有已运行进程时才让用户指定安装路径。
        if _autocad_process_running():
            print("[CAD] AutoCAD 已运行，但 COM 接口不可访问；为避免多开，本次不再启动。")
            return None

        exe_path = choose_cad_exe()
        if exe_path is None:
            print("[CAD] 未选择有效的 AutoCAD 程序，退出。")
            return None
        acad = start_autocad_by_path(exe_path, timeout=timeout)
        if acad is not None and getattr(_CAD_STARTUP_LOCAL, "status_callback", None):
            _CAD_STARTUP_LOCAL.acad = acad
        return acad
# === [NEW] 通过 产品ID -> 项目ID -> 项目保存路径 ===
def get_project_save_dir(product_id: str) -> str:
    """
    从产品设计活动表读取默认保存目录（产品文件夹绝对路径）
    返回：绝对路径字符串；取不到返回 ""。 ZQ-Copyright-Marker: DongLanpec-Core-2026
    """
    conn = pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 产品文件夹绝对路径
                FROM 产品设计活动表
                WHERE 产品ID=%s
                LIMIT 1
            """, (product_id,))
            row = cur.fetchone()
            p = (row.get("产品文件夹绝对路径") if row else "") or ""
            p = str(p).strip()
            if not p:
                return ""
            return os.path.abspath(p)
    finally:
        conn.close()
def wait_cad_idle(acad, timeout=10, poll=0.05):
    """等待 AutoCAD 空闲（不同版本均可用）。"""
    import time, pythoncom
    t0 = time.monotonic()
    stable_checks = 0
    while time.monotonic() - t0 < timeout:
        _check_cad_startup_cancelled()
        idle = False
        try:
            pythoncom.PumpWaitingMessages()
        except Exception:
            pass

        # 每轮重新取得状态代理；文档切换后旧的 AcadState 也可能失效。
        try:
            state = acad.GetAcadState()
            idle = bool(state.IsQuiescent)
        except AttributeError:
            # 某些 AutoCAD 版本/代理不支持 GetAcadState，使用 CMDNAMES 判断
            # 是否仍有命令在执行。
            try:
                document = acad.ActiveDocument
                idle = not str(document.GetVariable("CMDNAMES") or "").strip()
            except Exception:
                idle = False
        except Exception:
            # 被拒绝的 COM 调用不是“不支持接口”，继续等，不能误判为空闲。
            idle = False

        stable_checks = stable_checks + 1 if idle else 0
        if stable_checks >= 2:
            return True
        time.sleep(poll)
    return False

def refresh_doc(doc):
    """强制刷新视图/数据库，避免看不到更新或后续操作挂起。"""
    try:
        acAllViewports = 1
        doc.Regen(acAllViewports)
    except Exception:
        pass
    try:
        doc.Update()
    except Exception:
        pass
def _norm(p):
    return os.path.normcase(os.path.normpath(p or ""))

def _find_open_doc(acad, full_path):
    target = _norm(full_path)
    for i in range(acad.Documents.Count):
        try:
            d = acad.Documents.Item(i)
            if _norm(getattr(d, "FullName", "")) == target:
                return d
        except Exception:
            pass
    return None

def modify_text_by_handle2(doc, handle, new_text, retries=50, delay=5):
    if doc is None:
        doc = get_current_doc()
        print("⚠️ 未获取当前文档")
        return False

    safe_text = str(new_text).replace("\r", "").replace("\n", "").replace("\t", "")

    # 强制刷新文档状态
    try:
        doc.Regen()
    except:
        pass

    # 等待 COM 对象稳定
    time.sleep(0.2)

    for attempt in range(retries):
        try:
            obj = doc.HandleToObject(handle)
            if obj is None:
                print(f"⚠️ Handle {handle} 不存在，第 {attempt + 1} 次重试...")
                time.sleep(delay)
                continue

            if hasattr(obj, 'TextString'):
                old = obj.TextString
                obj.TextString = safe_text
                print(f"✅ 修改成功: Handle {handle} → '{safe_text}'")
                return True
            elif hasattr(obj, 'Value'):
                old = obj.Value
                obj.Value = safe_text
                print(f"✅ 修改成功: Handle {handle} → '{safe_text}'")
                return True
            else:
                print(f"⚠️ Handle {handle} 对象不支持 TextString/Value")
                return False

        except Exception as e:
            print(f"⚠️ 第 {attempt + 1} 次修改失败: {e}")
            log_error(f"⚠️ 第 {attempt + 1} 次修改失败: {e}")

            time.sleep(delay)

    print(f"❌ 修改失败: {handle}")
    return False
def safe_modify2(doc, handle, value):
    """如果 value 没有值，则替换成 '/'，再修改句柄"""
    if value in (None, "", "None"):
        value = "/"
    modify_text_by_handle2(doc, handle, str(value))
def modify_text_by_handle(doc, handle, new_text, retries=5, delay=0.5):
    if doc is None:
        doc = get_current_doc()
        print("⚠️ 未获取当前文档")
        return False

    safe_text = str(new_text).replace("\r", "").replace("\n", "").replace("\t", "")

    # 强制刷新文档状态
    try:
        doc.Regen()
    except:
        pass

    # 等待 COM 对象稳定
    time.sleep(0.2)

    for attempt in range(retries):
        try:
            obj = doc.HandleToObject(handle)
            if obj is None:
                print(f"⚠️ Handle {handle} 不存在，第 {attempt + 1} 次重试...")
                time.sleep(delay)
                continue

            if hasattr(obj, 'TextString'):
                old = obj.TextString
                obj.TextString = safe_text
                print(f"✅ 修改成功: Handle {handle} → '{safe_text}'")
                return True
            elif hasattr(obj, 'Value'):
                old = obj.Value
                obj.Value = safe_text
                print(f"✅ 修改成功: Handle {handle} → '{safe_text}'")
                return True
            else:
                print(f"⚠️ Handle {handle} 对象不支持 TextString/Value")
                return False

        except Exception as e:
            print(f"⚠️ 第 {attempt + 1} 次修改失败: {e}")
            log_error(f"⚠️ 第 {attempt + 1} 次修改失败: {e}")

            time.sleep(delay)

    print(f"❌ 修改失败: {handle}")
    return False


def safe_modify(doc, handle, value):
    """如果 value 没有值，则替换成 '/'，再修改句柄"""
    if value in (None, "", "None"):
        value = "/"
    modify_text_by_handle(doc, handle, str(value))
def make_unique_dwg_path(save_dir, base_name):
    """
    生成唯一 DWG 路径
    例如：AEM投标图_20260306_153010_123_3E2F.dwg
    """
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    uid = uuid.uuid4().hex[:4].upper()
    fn = f"{base_name}_{ts}_{uid}.dwg"
    return os.path.abspath(os.path.join(save_dir, fn))


def copy_template_to_target(template_path, save_dir, base_name):
    """
    模板只复制一次，返回唯一副本路径
    """
    template_path = os.path.abspath(template_path)
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"模板不存在: {template_path}")

    os.makedirs(save_dir, exist_ok=True)

    target = make_unique_dwg_path(save_dir, base_name)
    while os.path.exists(target):
        target = make_unique_dwg_path(save_dir, base_name)

    shutil.copy2(template_path, target)

    try:
        os.chmod(target, 0o666)
    except Exception:
        pass

    return target


def choose_save_dir(default_dir: str, title="选择DWG保存文件夹") -> str:
    """
    让用户选择保存目录；取消则返回 default_dir
    优先使用 tkinter；如果失败就回退默认目录
    """
    default_dir = os.path.abspath(default_dir or os.getcwd())

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.lift()
        root.attributes("-topmost", True)
        root.update()

        chosen = filedialog.askdirectory(
            parent=root,
            title=title,
            initialdir=default_dir,
            mustexist=True
        )

        root.destroy()

        if chosen and os.path.isdir(chosen):
            return os.path.abspath(chosen)

    except Exception as e:
        print(f"⚠️ 弹出目录选择框失败，改用默认目录。原因: {e}")

    return default_dir


def close_temp_drawings(acad):
    """
    关闭 AutoCAD 自动产生的空白图纸，例如 Drawing1 / Drawing2
    """
    try:
        docs_to_close = []
        for i in range(acad.Documents.Count):
            doc_i = acad.Documents.Item(i)
            name = (doc_i.Name or "").lower()
            full = (doc_i.FullName or "").strip()

            # 只关没有落盘路径的空白图纸
            if name.startswith("drawing") and not full:
                docs_to_close.append(doc_i)

        for d in docs_to_close:
            try:
                d.Close(False)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ 关闭临时空白图纸失败: {e}")


def close_same_fullname_docs(acad, full_path):
    """
    如果这个目标文件已经被打开，先关闭旧实例，避免重复打开同一路径
    """
    full_path = os.path.abspath(full_path).lower()
    try:
        docs_to_close = []
        for i in range(acad.Documents.Count):
            doc_i = acad.Documents.Item(i)
            doc_full = os.path.abspath(doc_i.FullName).lower() if (doc_i.FullName or "").strip() else ""
            if doc_full == full_path:
                docs_to_close.append(doc_i)

        for d in docs_to_close:
            try:
                d.Close(False)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ 关闭重复打开的目标文件失败: {e}")


def open_target_dwg_only(acad, target_dwg):
    """
    只打开目标副本，不打开模板，不另存为，不复制第二次
    """
    target_dwg = os.path.abspath(target_dwg)

    close_same_fullname_docs(acad, target_dwg)
    close_temp_drawings(acad)

    wait_cad_idle(acad, timeout=20)

    try:
        doc = acad.Documents.Open(target_dwg)
        wait_cad_idle(acad, timeout=30)
        refresh_doc(doc)
        return acad, doc
    except Exception as e:
        print(f"❌ 打开目标DWG失败: {e}")
        return acad, None

# === 日志记录函数 ===
LOG_FILE = "出图可能错误.txt"

def log_error(msg: str):
    """把错误信息追加写入 error_log.txt，同时打印控制台"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{timestamp}] {msg}\n"
    print(text.strip())  # 仍然控制台打印
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"⚠️ 写入日志失败: {e}")


def get_mingpai_fushu(product_id):
    """
    查询产品设计活动表_元件附件参数合并表中的“铭牌附属元件”有效值
    只返回非空的那一条
    """

    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID=%s AND 参数名称='铭牌附属元件'
            """, (product_id,))

            rows = cursor.fetchall()

            # 遍历所有，找到唯一有值的
            for row in rows:
                v = row.get("参数值")
                if v not in (None, "", "None", "无"):
                    return str(v).strip()

            # 如果都没有有效值，返回空字符串
            return ""

    except Exception as e:
        print("❌ get_mingpai_fushu 查询失败：", e)
        return ""

    finally:
        conn.close()
import math
import pymysql

def clean_val(v):
    if v is None:
        return ""
    v = str(v).strip()
    if v.lower() == "none":
        return ""
    return v

def get_float_value(cursor, product_id, component_name, name, default=0.0):
    """
    从 产品设计活动表_元件计算结果表 读取指定 Name 的 Value，并转 float
    """
    cursor.execute(
        """
        SELECT Value
        FROM 产品设计活动表_元件计算结果表
        WHERE 产品ID = %s AND 元件名称 = %s AND Name = %s
        LIMIT 1
        """,
        (product_id, component_name, name)
    )
    row = cursor.fetchone()
    try:
        return float(row["Value"]) if row and row.get("Value") not in (None, "", "None") else default
    except Exception:
        return default


def calc_nozzle_H(product_id: str, component_name: str,
                  host="localhost", user="root", password="123456") -> float:
    """
    计算 H_xxx = l1 - h - sqrt(c^2 - a^2)

    component_name 示例：
      '排气口接管', '排液口接管', '管程入口接管', '管程出口接管', '壳程入口接管', '壳程出口接管'
    """
    # component_name -> func_like（管口功能）
    func_like = component_name[:-2] if component_name.endswith("接管") else component_name

    conn_product = pymysql.connect(
        host=host, user=user, password=password,
        database="产品设计活动库", charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    conn_material = pymysql.connect(
        host=host, user=user, password=password,
        database="材料库", charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    conn_component = pymysql.connect(
        host=host, user=user, password=password,
        database="元件库", charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        cur = conn_product.cursor()
        cur2 = conn_material.cursor()
        cur3 = conn_component.cursor()

        # --- a: 接管大端外径/2，若为0则用小端外径/2 ---
        a = get_float_value(cur, product_id, component_name, "接管大端外径", 0.0) / 2.0
        if a == 0.0:
            a = get_float_value(cur, product_id, component_name, "接管小端外径", 0.0) / 2.0

        # --- l1: 接管总外伸高度 ---
        l1 = get_float_value(cur, product_id, component_name, "接管总外伸高度", 0.0)

        # --- c: 开孔元件内径/2 ---
        c = get_float_value(cur, product_id, component_name, "开孔元件内径", 0.0) / 2.0

        # === 1. 获取管口表数据 ===
        cur.execute(
            """
            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口','壳程入口', '壳程出口')
            """,
            (product_id,)
        )
        ports = cur.fetchall() or []

        # === 2. 获取管口类型选择表 ===
        cur.execute(
            """
            SELECT 公称尺寸类型, 公称压力类型
            FROM 产品设计活动表_管口类型选择表
            WHERE 产品ID = %s
            LIMIT 1
            """,
            (product_id,)
        )
        type_info = cur.fetchone()
        size_type = type_info["公称尺寸类型"] if type_info else "DN"
        press_type = type_info["公称压力类型"] if type_info else "PN"

        # === 3. NPS→DN 对照 ===
        cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
        nps_rows = cur3.fetchall() or []
        nps_map = {clean_val(r.get("NPS")): clean_val(r.get("DN")) for r in nps_rows}

        # === 4. 管法兰质量表 ===
        cur2.execute("SELECT * FROM 管法兰质量表")
        flange_rows = cur2.fetchall() or []

        # === 5. 匹配得到 h ===
        h = 0.0
        matched_type_db = ""  # ✅ 记录最终命中的型式代号
        matched_row = None  # ✅ 记录最终命中的那一行（用于取 N1）
        for port in ports:
            func = clean_val(port.get("管口功能"))
            if func != func_like:
                continue

            std = clean_val(port.get("法兰标准"))
            size = clean_val(port.get("公称尺寸"))
            pressure = clean_val(port.get("压力等级"))
            flange_type = clean_val(port.get("法兰型式"))
            face_type = clean_val(port.get("密封面型式"))
            print(face_type,"face_type")
            if size_type.upper() == "NPS":
                size = nps_map.get(size, size)

            for row in flange_rows:
                std_db = clean_val(row.get("标准"))
                dn_db  = clean_val(row.get("DN"))
                pn_db  = clean_val(row.get("PN"))
                cls_db = clean_val(row.get("Class"))
                type_db = clean_val(row.get("法兰型式代号"))

                if std_db and std_db != std:
                    continue
                if dn_db and dn_db != size:
                    continue

                if press_type.upper() == "PN":
                    if pn_db and pn_db != pressure:
                        continue
                elif press_type.upper() == "CLASS":
                    if cls_db and cls_db != pressure:
                        continue

                if type_db and flange_type and type_db != flange_type:
                    continue

                if face_type:
                    face_col = f"H{face_type}"
                    hv = clean_val(row.get(face_col)) if face_col in row else ""
                    try:
                        h = float(hv) if hv != "" else 0.0
                    except Exception:
                        h = 0.0
                    # ✅ 记录命中行（用于 LWN 后续取 N1）
                    matched_type_db = type_db
                    matched_row = row
        # === LWN：用 N1/2 与 a 取大者替换 a ===
        if matched_type_db == "LWN" and matched_row is not None:
            n1v = clean_val(matched_row.get("N1"))  # ✅ N1 列（如果你表头不是 N1，改这里）
            try:
                n1 = float(n1v) if n1v != "" else 0.0
            except Exception:
                n1 = 0.0

            # ✅ 用 max(N1/2, a) 替换 a
            a = max(float(a or 0.0), n1 / 2.0)
        # === 最终公式 ===
        inside = c ** 2 - a ** 2
        if inside < 0:
            inside = 0.0  # 防止 sqrt 负数

        H = l1 - h - math.sqrt(inside)
        print("图纸")
        print(l1,"l1")
        print(h,"h")
        print(c,"c")
        print(a,"a")
        print(inside,"inside")
        print(H,"H")
        return H

    finally:
        try: conn_product.close()
        except: pass
        try: conn_material.close()
        except: pass
        try: conn_component.close()
        except: pass
