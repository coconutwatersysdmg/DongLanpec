# cad_dimension_utils.py

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


def extract_dimensions():
    """提取所有标注信息"""
    print("【标注对象】")
    for obj in acad.iter_objects():
        try:
            if is_dimension_object(obj):
                actual_value = obj.Measurement
                display_text = obj.TextOverride if obj.TextOverride else str(actual_value)
                print(f"标注类型: {obj.ObjectName}")
                print(f"实际值: {actual_value}")
                print(f"显示文字: {display_text}")
                print(f"位置: {obj.TextPosition if hasattr(obj, 'TextPosition') else 'N/A'}")
                print(f"图层: {obj.Layer}")
                print(f"Handle: {obj.Handle}")
                print("─" * 30)
        except Exception as e:
            print(f"处理标注时出错: {e}")
            continue


def is_dimension(obj):
    return hasattr(obj, 'Measurement') or 'Dimension' in obj.ObjectName


def modify_dimension(handle, new_text=None, new_value=None):
    try:
        obj = acad.doc.HandleToObject(handle)
        if not obj:
            print(f"❌ Handle {handle} 不存在")
            return

        if not is_dimension(obj):
            print(f"❌ Handle {handle} 不是标注对象")
            return

        if new_text is not None:
            obj.TextOverride = new_text
            print(f"✅ Handle {handle}：文字改为 → '{new_text}'")

        if new_value is not None:
            if hasattr(obj, 'Measurement'):
                obj.Measurement = float(new_value)
                print(f"✅ Handle {handle}：测量值改为 → {new_value}")
            else:
                print(f"⚠️ Handle {handle}：该对象不支持设置测量值")
    except Exception as e:
        print(f"修改失败 Handle {handle}: {e}")


def apply_dimension_labels(handle_text_dict):
    """
    批量修改标注显示文字
    :param handle_text_dict: 字典 {handle: label_text}
    """
    for handle, text in handle_text_dict.items():
        modify_dimension(handle, new_text=text)
    auto_save_copy()
def auto_save_copy(suffix="_副本"):
    """
    自动以当前图纸名 + 后缀 的方式另存副本
    """
    try:
        import os
        full_path = acad.doc.FullName  # 当前图纸完整路径
        if not full_path:
            print("⚠️ 当前图纸未保存，无法另存副本")
            return

        dir_path, filename = os.path.split(full_path)
        name, ext = os.path.splitext(filename)
        new_filename = f"{name}{suffix}{ext}"
        new_full_path = os.path.join(dir_path, new_filename)

        acad.doc.SaveAs(new_full_path)
        print(f"✅ 已自动另存为副本: {new_full_path}")
    except Exception as e:
        print(f"❌ 自动另存副本失败: {e}")

