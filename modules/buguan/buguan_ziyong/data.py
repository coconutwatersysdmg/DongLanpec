import ast
import os
import textwrap

def split_classes_to_files(py_file_path, output_dir=None, keep_common=True):
    """
    自动将一个包含多个类的 Python 文件拆分为多个文件。
    每个文件包含：
      - 原始 import 语句
      - 对应的类定义
    可选地保存非类定义部分到 common_imports.py。
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(py_file_path), "split_output")
    os.makedirs(output_dir, exist_ok=True)

    # 读取源代码
    with open(py_file_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # 解析 AST
    tree = ast.parse(source)

    # 提取 import 语句和类定义
    imports = []
    other_nodes = []
    classes = []

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        elif isinstance(node, ast.ClassDef):
            classes.append(node)
        else:
            other_nodes.append(node)

    # --- 将 import 转回源码 ---
    def unparse(node):
        """简单版本：Python 3.9+ 可用 ast.unparse"""
        try:
            return ast.unparse(node)
        except Exception:
            import astor
            return astor.to_source(node).strip()

    import_code = "\n".join([unparse(node) for node in imports])
    if import_code:
        import_code += "\n\n"

    # --- 写出每个类文件 ---
    created_files = []
    for cls in classes:
        class_code = textwrap.indent(ast.unparse(cls), "")
        file_name = f"{cls.name}.py"
        file_path = os.path.join(output_dir, file_name)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(import_code + class_code + "\n")

        created_files.append(file_path)

    # --- 处理非类部分（函数、全局变量等）---
    if keep_common and other_nodes:
        other_code = "\n".join([ast.unparse(node) for node in other_nodes])
        common_file = os.path.join(output_dir, "common_imports.py")
        with open(common_file, "w", encoding="utf-8") as f:
            f.write(import_code + other_code + "\n")
        created_files.append(common_file)

    print(f"\n✅ 拆分完成，共生成 {len(created_files)} 个文件：")
    for path in created_files:
        print(" -", os.path.basename(path))

    print(f"\n📂 输出目录：{output_dir}")
    return created_files
split_classes_to_files("My_Piping.py")
