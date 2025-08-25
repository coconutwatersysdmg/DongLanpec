import os
import filecmp
import difflib

def get_cs_files(directory):
    cs_files = {}
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".cs"):
                rel_path = os.path.relpath(os.path.join(root, file), directory)
                cs_files[rel_path] = os.path.join(root, file)
    return cs_files

def compare_cs_files(dir1, dir2):
    files1 = get_cs_files(dir1)
    files2 = get_cs_files(dir2)

    common_files = set(files1.keys()) & set(files2.keys())
    only_in_dir1 = set(files1.keys()) - set(files2.keys())
    only_in_dir2 = set(files2.keys()) - set(files1.keys())

    if only_in_dir1:
        print("仅在路径1中的文件：")
        for f in only_in_dir1:
            print(f"  {f}")
    if only_in_dir2:
        print("仅在路径2中的文件：")
        for f in only_in_dir2:
            print(f"  {f}")

    for file in common_files:
        with open(files1[file], 'r', encoding='utf-8') as f1, open(files2[file], 'r', encoding='utf-8') as f2:
            content1 = f1.readlines()
            content2 = f2.readlines()
            if content1 != content2:
                print(f"\n❗ 文件不同: {file}")
                diff = difflib.unified_diff(content1, content2, fromfile='dir1/' + file, tofile='dir2/' + file, lineterm='')
                print('\n'.join(diff))
# 使用示例：替换为你的两个路径
dir_path_1 = r"C:\Users\zifeng qi\Desktop\蓝滨代码(1)\蓝滨代码"
dir_path_2 = r"C:\Users\zifeng qi\Desktop\蓝滨代码"

compare_cs_files(dir_path_1, dir_path_2)
