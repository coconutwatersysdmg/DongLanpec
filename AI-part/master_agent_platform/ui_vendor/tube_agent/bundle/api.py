"""布管计算引擎：直接复用正式程序 DongLanpec 的 HE3DTB.dll 接口。

正式程序 `modules/buguan/buguan_ziyong/api.py` 通过 pythonnet 调用
`HE3DTB.tbInterface.LayoutTubeCalculate(json)` 生成换热管孔坐标。Demo 把该
DLL 复制进 `bundle/dll/`，用同一接口、同一入参格式计算，因此换热管坐标
不是 Demo 自己编造的，而是正式程序的几何计算结果。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

DLL_DIR = Path(__file__).resolve().parent / "dll"

_lock = threading.Lock()
_instance = None


class LayoutEngineError(RuntimeError):
    """DLL 不可用或计算失败时抛出，调用方必须显式提示，不能静默降级。"""


def _load_interface():
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        if not (DLL_DIR / "HE3DTB.dll").exists():
            raise LayoutEngineError(
                f"缺少布管计算组件：{DLL_DIR / 'HE3DTB.dll'}。"
                "请从正式程序 modules/buguan/buguan_ziyong/ 复制该文件到 bundle/dll/。"
            )
        try:
            import clr  # pythonnet
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise LayoutEngineError(
                "未安装 pythonnet，无法调用正式程序的布管计算组件。请执行 pip install pythonnet。"
            ) from exc

        old_cwd = os.getcwd()
        added = []
        try:
            os.chdir(str(DLL_DIR))
            if str(DLL_DIR) not in sys.path:
                sys.path.append(str(DLL_DIR))
                added.append(str(DLL_DIR))
            os.environ["PATH"] = str(DLL_DIR) + os.pathsep + os.environ.get("PATH", "")
            clr.AddReference(str(DLL_DIR / "HE3DTB.dll"))
            clr.AddReference(str(DLL_DIR / "Newtonsoft.Json.dll"))
            from HE3DTB import tbInterface  # type: ignore

            _instance = tbInterface()
        except Exception as exc:  # pragma: no cover - 依赖本机 DLL
            raise LayoutEngineError(f"加载布管计算组件失败：{exc}") from exc
        finally:
            os.chdir(old_cwd)
        return _instance


def run_layout_tube_calculate(input_json: str) -> str:
    """与正式程序同名同签名的布管计算调用。"""
    interface = _load_interface()
    try:
        result = interface.LayoutTubeCalculate(input_json)
    except Exception as exc:  # pragma: no cover - 依赖本机 DLL
        raise LayoutEngineError(f"布管计算失败：{exc}") from exc
    if not result or not str(result).strip().startswith("{"):
        raise LayoutEngineError(f"布管计算返回了非预期内容：{str(result)[:200]}")
    return str(result)


def available() -> tuple[bool, str]:
    try:
        _load_interface()
        return True, "可用"
    except LayoutEngineError as exc:
        return False, str(exc)


if __name__ == "__main__":
    payload = json.dumps(
        {
            "LB_DN": "1200", "LB_Di": "1144", "LB_TubePassCount": "2", "LB_IsRangeCenter": "1",
            "LB_TotalTubesCountNeed": "10000", "LB_TubeD": "25", "LB_TubeThick": "2",
            "LB_RangeType": "3", "LB_TubeLong": "4500", "LB_BaffleDirection": "1",
            "LB_BafflePerStr": "25", "LB_BaffleToODistance": "123.2", "LB_S": "32",
            "LB_SN": "100", "LB_BaffleOD": "1138", "LB_BPBThick": "0", "LB_HEType": "2",
            "LB_SNH": "0", "LB_DL": "1128.0", "LB_TieRodD": "16", "LB_ClapboardType": "1",
            "LB_SlipWayHeight": "150", "LB_SlipWayThick": "10", "LB_SlipWayAngle": "30",
        }
    )
    out = json.loads(run_layout_tube_calculate(payload))
    print({k: v for k, v in out.items() if not isinstance(v, list)})
