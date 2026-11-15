"""Optional locator for the production source used only as a read-only reference."""
import os
from pathlib import Path


def locate_source() -> Path | None:
    configured = os.environ.get("DONG_LANPEC_SOURCE")
    candidates = [Path(configured)] if configured else []
    here = Path(__file__).resolve()
    candidates.extend(parent / "DongLanpec" for parent in here.parents)
    for candidate in candidates:
        if candidate and (candidate / "modules/buguan/buguan_ziyong/My_Piping.py").is_file():
            return candidate
    return None


SOURCE = locate_source()


def require_source() -> Path:
    if SOURCE is None:
        raise RuntimeError("未找到 DongLanpec 工程；本 Demo 仍可独立运行，但不能打开源码参考。")
    return SOURCE
