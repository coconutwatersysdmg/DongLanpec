from pyautocad import Autocad
import pymysql

from modules.chanpinguanli.chanpinguanli_main import product_manager
acad = Autocad(create_if_not_exists=True)

def extract_text():
    print("【文字对象】")
    for obj in acad.iter_objects(['Text', 'MText']):
        try:
            print(
                f"{obj.ObjectName}: '{obj.TextString}' 位置: {obj.InsertionPoint} 图层: {obj.Layer} Handle: {obj.Handle}")
        except Exception as e:
            print(f"读取对象时出错: {e}")
            continue