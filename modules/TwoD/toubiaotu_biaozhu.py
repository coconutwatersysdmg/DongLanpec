# cad_dimension_utils.py
import os
import shutil

from types import SimpleNamespace

from modules.TwoD.cad_context import CAD_CTX
from modules.TwoD.TwoD_peizhi import get_autocad_instance, get_current_doc, com_retry


def is_dimension_object(obj):
    dim_types = [
        "AcDbAlignedDimension", "AcDbAngularDimension", "AcDb2LineAngularDimension",
        "AcDb3PointAngularDimension", "AcDbRotatedDimension", "AcDbDiametricDimension",
        "AcDbRadialDimension", "AcDbOrdinateDimension", "AcDbArcDimension",
        "AlignedDimension", "RotatedDimension"
    ]
    has_dim_props = hasattr(obj, 'Measurement') and hasattr(obj, 'TextOverride')
    return obj.ObjectName in dim_types or has_dim_props or 'Dimension' in obj.ObjectName


def extract_dimensions(doc):
    """提取所有标注信息"""
    print("【标注对象】")
    for obj in doc.ModelSpace:   # ✅ 改这里：遍历当前文档的 ModelSpace
        try:
            if is_dimension_object(obj):
                actual_value = getattr(obj, "Measurement", None)
                display_text = getattr(obj, "TextOverride", "") or str(actual_value)

                print(f"标注类型: {obj.ObjectName}")
                print(f"实际值: {actual_value}")
                print(f"显示文字: {display_text}")
                print(f"位置: {getattr(obj, 'TextPosition', 'N/A')}")
                print(f"图层: {obj.Layer}")
                print(f"Handle: {obj.Handle}")
                print("─" * 30)
        except Exception as e:
            print(f"处理标注时出错: {e}")
            continue



def is_dimension(obj):
    return hasattr(obj, 'Measurement') or 'Dimension' in obj.ObjectName


import time
try:
    import pywintypes
    com_error = pywintypes.com_error
except ImportError:
    com_error = Exception  # IDE fallback，不影响运行
def get_acad():
    # 总图标注沿用已就绪的实例和目标文档，不能每个 handle 都另走自动启动。
    acad = get_autocad_instance()
    doc = get_current_doc()
    if acad is None or doc is None:
        raise RuntimeError("没有可用的总图文档，无法修改尺寸标注。")
    return SimpleNamespace(app=acad, doc=doc)
def modify_dimension(handle, new_text=None, new_value=None, retries=3, delay=0.2):
    acad = get_acad()  # ⚡ 关键：重新获取 CAD COM 对象
    for i in range(retries):
        try:
            obj = acad.doc.HandleToObject(handle)
            if not obj:
                print(f"❌ Handle {handle} 不存在")
                return False

            if not is_dimension(obj):
                print(f"❌ Handle {handle} 不是标注对象")
                return False

            if new_text is not None:
                obj.TextOverride = new_text
                print(f"✅ Handle {handle}：文字改为 → '{new_text}'")

            if new_value is not None:
                if hasattr(obj, 'Measurement'):
                    obj.Measurement = float(new_value)
                    print(f"✅ Handle {handle}：测量值改为 → {new_value}")
                else:
                    print(f"⚠️ Handle {handle}：该对象不支持设置测量值")
            return True

        except com_error as e:
            print(f"⚠️ RPC 出错 Handle {handle} (第{i+1}次): {e}")
            time.sleep(delay)

    return False


def safe_update(doc, handle, value, retries=3, delay=0.1):
    """
    安全修改 AutoCAD 对象
    :param doc: AutoCAD 文档对象
    :param handle: 对象句柄
    :param value: 要更新的值（通常是字符串或数值）
    """
    for i in range(retries):
        try:
            obj = doc.HandleToObject(handle)

            # DBText / MText
            if hasattr(obj, "TextString"):
                obj.TextString = str(value)
                return True

            # AttributeReference
            elif hasattr(obj, "TextString") and hasattr(obj, "TagString"):
                obj.TextString = str(value)
                return True

            # Dimension (标注)
            elif hasattr(obj, "TextOverride"):
                obj.TextOverride = str(value)
                return True

            # BlockReference (块参照里的属性)
            elif hasattr(obj, "GetAttributes"):
                for att in obj.GetAttributes():
                    att.TextString = str(value)
                return True

            # 如果是支持数值的几何对象，比如线长、半径等，可以根据需求扩展
            elif hasattr(obj, "Radius"):
                obj.Radius = float(value)
                return True
            elif hasattr(obj, "Length"):
                # 部分版本支持 Length，可选
                obj.Length = float(value)
                return True

            # 最后兜底：直接尝试通用属性
            elif hasattr(obj, "Text"):
                obj.Text = str(value)
                return True

            print(f"⚠️ Handle {handle} 类型不支持修改: {type(obj)}")
            return False

        except com_error as e:
            print(f"修改失败 Handle {handle}: {e}, 第{i + 1}次重试")
            time.sleep(delay)

    return False
from PyQt5.QtWidgets import QMessageBox, QApplication
import sys

def apply_dimension_labels(handle_text_dict, parent=None):
    doc = get_current_doc()
    if doc is None:
        raise RuntimeError("总图没有成功打开，已停止标注和后续图纸生成。")
    results = {}
    for handle, text in handle_text_dict.items():
        try:
            success = modify_dimension(handle, new_text=text)
            results[handle] = (text, success)
        except Exception as e:
            results[handle] = (text, False)
            print(f"⚠️ 修改标注 {handle} 失败: {e}")

    # ✅ 直接保存当前副本，不再另存第二份
    save_current_doc(doc)

    return results
def save_current_doc(doc):
    import time

    try:
        try:
            com_retry(lambda: doc.Regen(1), quiet=True)
            time.sleep(0.3)
        except Exception:
            pass

        com_retry(lambda: doc.Save(), quiet=True)
        print(f"✅ 当前图纸已保存: {getattr(doc, 'FullName', getattr(doc, 'Name', '未命名图纸'))}")
        return True
    except Exception as e:
        raise RuntimeError(f"当前图纸保存失败，本次生成已停止：{e}") from e
from modules.TwoD.toubiaotu_wenziduixiang_flange_ao import twoDgeneration as twoDgeneration_flange_ao
from modules.TwoD.toubiaotu_wenziduixiang_flange_ao_fuceng import twoDgeneration as twoDgeneration_flange_ao_fuceng
from modules.TwoD.toubiaotu_wenziduixiang_flange_tu import twoDgeneration as twoDgeneration_flange_tu
from modules.TwoD.toubiaotu_wenziduixiang_flange_tu_fuceng import twoDgeneration as twoDgeneration_flange_tu_fuceng
from modules.TwoD.toubiaotu_wenziduixiang_flange_pinggai import twoDgeneration as twoDgeneration_flange_pinggai
from modules.TwoD.toubiaotu_wenziduixiang_flange_pinggai_fuceng import twoDgeneration as twoDgeneration_flange_pinggai_fuceng

import time

from datetime import datetime

import os
import shutil
import tempfile
import time
from datetime import datetime

def generate_and_save_flange(product_id, flange_info, save_dir=None):
    """
    生成法兰 DWG。
    只保留生成函数内部创建的那一个副本，这里不再二次 SaveAs。
    flange_info: list of dict，每个 dict 包含：
        "法兰名称", "密封面", "覆层"
    """
    for item in flange_info:
        flange = item.get("法兰名称", "") or ""
        face = item.get("密封面", "") or ""
        coating = item.get("覆层", "") or "否"

        print(f"\n🔹 开始生成法兰: {flange}, 密封面: {face}, 覆层: {coating}")

        CAD_CTX["doc"] = None
        CAD_CTX["target_dwg"] = None
        doc = None

        # 选择生成函数
        if "凹" in face and coating == "否":
            doc = twoDgeneration_flange_ao(product_id, flange)
        elif "凹" in face and coating == "是":
            doc = twoDgeneration_flange_ao_fuceng(product_id, flange)
        elif "凸" in face and coating == "否":
            doc = twoDgeneration_flange_tu(product_id, flange)
        elif "凸" in face and coating == "是":
            doc = twoDgeneration_flange_tu_fuceng(product_id, flange)
        elif flange == "管箱平盖" and coating == "否":
            doc = twoDgeneration_flange_pinggai(product_id, flange)
        elif flange == "管箱平盖" and coating == "是":
            doc = twoDgeneration_flange_pinggai_fuceng(product_id, flange)
        elif flange == "前端管箱平盖" and coating == "否":
            doc = twoDgeneration_flange_pinggai(product_id, flange)
        elif flange == "前端管箱平盖" and coating == "是":
            doc = twoDgeneration_flange_pinggai_fuceng(product_id, flange)
        elif not face or not coating:
            doc = twoDgeneration_flange_ao(product_id, flange)
        else:
            raise RuntimeError(f"法兰 {flange} 的密封面或覆层参数不符合生成条件，本次生成已停止。")

        if doc is None:
            raise RuntimeError(f"法兰 {flange} 未生成成功，本次生成已停止。")

        try:
            try:
                doc.Regen(0)
            except Exception:
                pass

            try:
                for obj in doc.ModelSpace:
                    if "Dimension" in getattr(obj, "ObjectName", ""):
                        try:
                            obj.Update()
                        except Exception:
                            pass
            except Exception:
                pass

            # ✅ 这里只保存当前文档，不再另存为第二个副本
            com_retry(lambda: doc.Save(), quiet=True)

            final_path = getattr(doc, "FullName", "") or CAD_CTX.get("target_dwg", "")
            print(f"✅ 法兰 {flange} 已保存: {final_path}")

        except Exception as e:
            raise RuntimeError(f"法兰 {flange} 保存失败，本次生成已停止：{e}") from e
