# cad_dimension_utils.py
import os
import shutil

from pyautocad import Autocad

acad = Autocad(create_if_not_exists=True)


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
    # 每次都创建新的 Autocad 实例
    return Autocad(create_if_not_exists=True)
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
    """
    批量修改标注显示文字，并用 PyQt5 弹窗提示修改情况
    :param handle_text_dict: 字典 {handle: label_text}
    :param parent: 父窗口对象，可传入主窗口
    """
    results = {}

    for handle, text in handle_text_dict.items():
        try:
            success = modify_dimension(handle, new_text=text)
            results[handle] = (text, success)
        except Exception as e:
            results[handle] = (text, False)
            print(f"⚠️ 修改标注 {handle} 失败: {e}")

    # 汇总未更新的标注
    failed = {h: t for h, (t, ok) in results.items() if not ok or t in ("默认", "", None)}

    # 弹窗
    app_created = False
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app_created = True

    if failed:
        msg = "以下标注未能正确更新：\n"
        msg += "\n".join([f"- Handle {h} → {t}" for h, t in failed.items()])
        # QMessageBox.warning(parent, "更新结果", msg)
    else:
        # QMessageBox.information(parent, "更新结果", "✅ 所有标注均已更新成功")
        pass
    # 自动保存副本
    try:
        doc = get_current_doc()  # 获取当前 DWG COM 文档
        if doc:
            auto_save_copy(doc, suffix="_生成")
        else:
            print("⚠️ 当前文档不存在，无法保存副本")
    except Exception as e:
        print(f"⚠️ auto_save_copy 出错: {e}")

    if app_created:
        app.exec_()

def get_current_doc():
    acad = Autocad(create_if_not_exists=True)
    try:
        return acad.app.ActiveDocument   # 而不是 acad.doc
    except Exception as e:
        print(f"⚠️ 获取当前文档失败: {e}")
        return None

def auto_save_copy(doc_or_path, suffix="_生成"):
    """
    安全保存 DWG 副本，自动加时间戳
    doc_or_path: COM 文档对象 或 DWG 文件路径字符串
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    if not doc_or_path:
        print("❌ 保存失败: 参数为空")
        return

    # 传入路径字符串
    if isinstance(doc_or_path, str):
        full_path = os.path.abspath(doc_or_path.strip())
        if not full_path or not os.path.exists(full_path):
            print(f"❌ 文件不存在: {full_path}")
            return

        dir_path, filename = os.path.split(full_path)
        name, ext = os.path.splitext(filename)
        new_filename = f"{name.replace(' ','_')}{suffix}_{timestamp}{ext}"
        new_full_path = os.path.join(dir_path, new_filename)

        try:
            shutil.copyfile(full_path, new_full_path)
            print(f"✅ 文件副本保存成功: {new_full_path}")
        except Exception as e:
            print(f"❌ 文件副本保存失败: {e}")
        return

    # 传入 COM 文档对象
    doc = doc_or_path
    doc_name = getattr(doc, "Name", "未命名图纸")
    full_path = getattr(doc, "FullName", None)

    # 统一使用 SaveAs 保存副本，避免 Save 出错
    try:
        if full_path and full_path.strip():
            dir_path, filename = os.path.split(full_path)
            name, ext = os.path.splitext(filename)
        else:
            # 未保存文档，存到当前目录
            name = doc_name
            ext = ".dwg"

        new_filename = f"{name.replace(' ','_')}{suffix}_{timestamp}{ext}"
        new_full_path = os.path.join(new_filename)

        # 刷新 COM 文档
        try:
            doc.Regen()
            time.sleep(0.3)  # 等待内存刷新
        except:
            pass

        # 保存副本
        doc.SaveAs(new_full_path)
        print(f"✅ {doc_name} SaveAs 副本成功: {new_full_path}")

    except Exception as e:
        print(f"❌ {doc_name} 保存失败: {e}")
from modules.TwoD.toubiaotu_wenziduixiang_flange_ao import twoDgeneration as twoDgeneration_flange_ao
from modules.TwoD.toubiaotu_wenziduixiang_flange_ao_fuceng import twoDgeneration as twoDgeneration_flange_ao_fuceng
from modules.TwoD.toubiaotu_wenziduixiang_flange_tu import twoDgeneration as twoDgeneration_flange_tu
from modules.TwoD.toubiaotu_wenziduixiang_flange_tu_fuceng import twoDgeneration as twoDgeneration_flange_tu_fuceng

import time
from datetime import datetime

import os
import shutil
import tempfile
import time
from datetime import datetime

def generate_and_save_flange(product_id, flange_info):
    """
    安全生成法兰 DWG 并保存副本，自动加时间戳
    flange_info: list of dict，每个 dict 包含：
        "法兰名称", "密封面", "覆层"
    """
    for item in flange_info:
        flange = item["法兰名称"]
        face = item["密封面"]
        coating = item["覆层"]
        print(f"\n🔹 开始生成法兰: {flange}, 覆层: {coating}")

        # 选择生成函数
        if "凹" in face and coating == "否":
            doc = twoDgeneration_flange_ao(product_id, flange)
        elif "凹" in face and coating == "是":
            doc = twoDgeneration_flange_ao_fuceng(product_id, flange)
        elif "凸" in face and coating == "否":
            doc = twoDgeneration_flange_tu(product_id, flange)
        elif "凸" in face and coating == "是":
            doc = twoDgeneration_flange_tu_fuceng(product_id, flange)
        else:
            print(f"⚠️ 法兰 {flange} 不符合生成条件，跳过")
            continue

        # 生成安全文件名
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        safe_flange = "".join(c if c.isalnum() or c in "_-" else "_" for c in flange)
        final_name = f"{safe_flange}_{timestamp}.dwg"
        final_path = final_name  # 当前工作目录

        if doc is None:
            print(f"❌ 法兰 {flange} 生成返回 None，检查生成函数内部步骤")
            cur_doc = get_current_doc()
            if cur_doc:
                print(f"⚠️ 当前活动文档: {getattr(cur_doc, 'Name', '未知')}")
            else:
                print("⚠️ 当前没有活动文档")
            continue
        else:
            print(f"✅ 法兰 {flange} 生成成功，返回 COM 文档对象: {doc}")

        try:
            # 🔹 强制刷新文档视口
            try:
                doc.Regen(0)
            except:
                pass

            # 🔹 更新所有标注对象
            try:
                for obj in doc.ModelSpace:
                    if "Dimension" in getattr(obj, "ObjectName", ""):
                        obj.Update()
            except:
                pass

            # 🔹 保存 DWG
            doc.SaveAs(final_path)
            print(f"✅ 法兰 {flange} 已保存: {final_path}")

        except Exception as e:
            print(f"❌ 法兰 {flange} 保存失败: {e}")
            continue

