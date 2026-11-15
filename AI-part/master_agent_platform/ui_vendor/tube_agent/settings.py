"""DeepSeek settings with optional Windows-account encryption."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from ai_support.api_client import APIConfig, DEEPSEEK_BASE_URL


CONFIG_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "DongLanpecAgentDemo" / "settings.json"


def protect(data: bytes, decrypt=False):
    if os.name != "nt":
        raise ValueError("仅 Windows 支持本机账户加密记住密钥")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("Windows 账户加密操作失败")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def load_settings(path=CONFIG_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    stored_base = str(data.get("base_url") or "")
    if stored_base and not stored_base.startswith(DEEPSEEK_BASE_URL):
        # The previous demo stored Bailian credentials in the same settings file.
        # Never reinterpret that encrypted key as a DeepSeek credential.
        data = {}
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DONG_LANPEC_AI_API_KEY") or ""
    if data.get("encrypted_key"):
        try:
            key = protect(base64.b64decode(data["encrypted_key"]), decrypt=True).decode("utf-8")
        except Exception:
            pass
    return APIConfig(str(data.get("base_url") or DEEPSEEK_BASE_URL), key, str(data.get("model") or "deepseek-v4-flash"))


def save_settings(config, remember, path=CONFIG_PATH):
    config.endpoint()
    if not config.configured:
        raise ValueError("请填写完整的 DeepSeek API Key")
    data = {"base_url": config.base_url, "model": config.model}
    if remember:
        data["encrypted_key"] = base64.b64encode(protect(config.api_key.encode("utf-8"))).decode("ascii")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def settings_dialog(parent, config):
    from PyQt5.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

    dialog = QDialog(parent)
    dialog.setWindowTitle("DeepSeek 设置")
    dialog.resize(570, 280)
    root = QVBoxLayout(dialog)
    root.addWidget(QLabel("粘贴 DeepSeek API Key。密钥不会写入项目代码、日志或截图。"))
    key = QLineEdit(config.api_key)
    key.setEchoMode(QLineEdit.Password)
    key.setPlaceholderText("DeepSeek API Key")
    form = QFormLayout()
    form.addRow("API Key", key)
    root.addLayout(form)
    remember = QCheckBox("使用当前 Windows 账户加密记住密钥")
    remember.setChecked(os.name == "nt")
    remember.setEnabled(os.name == "nt")
    root.addWidget(remember)
    advanced = QCheckBox("更多设置")
    root.addWidget(advanced)
    box = QWidget()
    extra = QFormLayout(box)
    base = QLineEdit(config.base_url)
    model = QLineEdit(config.model)
    extra.addRow("服务地址", base)
    extra.addRow("模型", model)
    box.hide()
    root.addWidget(box)
    advanced.toggled.connect(box.setVisible)
    note = QLabel("默认模型为 deepseek-v4-flash。未配置密钥时，仍可使用离线审核和演示数据库流程。")
    note.setWordWrap(True)
    root.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Save).setText("保存并返回")
    buttons.button(QDialogButtonBox.Cancel).setText("取消")
    root.addWidget(buttons)
    chosen = []

    def do_save():
        candidate = APIConfig(base.text().strip(), key.text().strip(), model.text().strip())
        try:
            save_settings(candidate, remember.isChecked())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(dialog, "设置未保存", str(exc))
            return
        chosen.append(candidate)
        dialog.accept()

    buttons.accepted.connect(do_save)
    buttons.rejected.connect(dialog.reject)
    return chosen[0] if dialog.exec_() == QDialog.Accepted else config
