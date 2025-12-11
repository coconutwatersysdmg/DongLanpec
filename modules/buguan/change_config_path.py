import configparser
import os

def update_config_directory(ini_path):
    # 当前 Python 脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    abs_dependency_path = os.path.join(base_dir, 'modules/buguan/dependencies').replace('\\', '/')

    # 初始化 configparser 并读取 ini 文件（使用 utf-8 编码）
    config = configparser.ConfigParser()
    config.read(ini_path, encoding='utf-8')

    if 'ProjectInfo' in config:
        config['ProjectInfo']['PRODUCT_DIRECTORY'] = abs_dependency_path
        config['ProjectInfo']['PRODUCT_TYPE_ID'] = 'guankeshirejiaohuanqi_BEU'

        # 保存配置文件
        with open(ini_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        print(f"✅ 已更新 PRODUCT_DIRECTORY 为: {abs_dependency_path}")
        print(f"✅ 已设置 PRODUCT_TYPE_ID 为: guankeshirejiaohuanqi_BEU")
    else:
        print("❌ 配置文件中未找到 [ProjectInfo] 段落")

def update_project_directory(file_path, key_name):
    # 当前 Python 脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    new_path = os.path.join(base_dir, 'modules/buguan/dependencies').replace('\\', '/')

    with open(file_path, 'r', encoding='gbk') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key_name}="):
            new_lines.append(f"{key_name}={new_path}\n")
        else:
            new_lines.append(line)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"✅ 已将 {key_name} 更新为: {new_path}")


# if __name__ == "__main__":
#
#     # 示例使用
#     update_config_directory("modules/buguan/dependencies/config/config.ini")
#
#     # 示例用法
#     update_project_directory("modules/buguan/dependencies/config/projectManagementInfo.ini", "PROJECT_DEFAULT_DIR")
