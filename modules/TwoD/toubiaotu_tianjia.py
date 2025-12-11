from pyautocad import Autocad, APoint

acad = Autocad(create_if_not_exists=True)
print(f"连接到图纸: {acad.doc.Name}\n")

def insert_external_dwg(file_path, insert_point=(0, 0, 0), scale=1.0, rotation=0):
    try:
        point = APoint(*insert_point)
        block_ref = acad.model.InsertBlock(point, file_path, scale, scale, scale, rotation)
        print(f"成功插入 DWG 文件 '{file_path}' 于 {insert_point}，Handle: {block_ref.Handle}")
    except Exception as e:
        print(f"插入 DWG 文件失败: {e}")

# 示例：将某个 DWG 文件插入到 (100, 200, 0)
insert_external_dwg(r"D:\博士\蓝翼\二维图\零件二维图\管箱法兰.dwg", insert_point=(6092.4816, 375.4332, 0))
