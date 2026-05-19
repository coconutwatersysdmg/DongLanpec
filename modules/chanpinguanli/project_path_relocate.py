# -*- coding: utf-8 -*-
# 0509新修改--项目路径变更处理
# 0515新修改-项目路径变更处理
"""启动时校验上次项目在本机磁盘；打开项目时可按所选目录同步更新库内路径与活动表产品路径。"""
import os

import modules.chanpinguanli.common_usage as common_usage


def get_project_root_folder(project_info):
    """根据项目需求表一行记录，得到「业主_项目名」文件夹绝对路径。"""
    if not project_info:
        return None
    save_path = str(project_info.get("项目保存路径") or "").strip()
    owner = str(project_info.get("业主名称") or "").strip()
    name = str(project_info.get("项目名称") or "").strip()
    if not save_path or not owner or not name:
        return None
    from modules.chanpinguanli.project_confirm_btn import normalize_project_save_path

    save_path = normalize_project_save_path(save_path)
    return os.path.normpath(os.path.join(save_path, f"{owner}_{name}"))


def disk_matches_project(project_id, project_root_folder):
    """项目根目录存在且 id.csv 中的 ID 与 project_id 一致。"""
    if not project_root_folder or not project_id:
        return False
    csv_path = os.path.join(project_root_folder, "id.csv")
    if not os.path.isdir(project_root_folder) or not os.path.isfile(csv_path):
        return False
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            fid = f.read().strip()
        return fid == str(project_id).strip()
    except OSError:
        return False


def verify_last_session_path(project_id, project_info):
    """上次会话记录在库中的路径是否仍指向同一项目目录。"""
    root = get_project_root_folder(project_info)
    return disk_matches_project(project_id, root)


def _sync_activity_table_paths(project_id, old_folder, new_folder):
    """与 project_confirm_btn 修改项目时一致：批量更新产品设计活动表绝对路径。"""
    old_folder = os.path.normpath(old_folder) if old_folder else ""
    new_folder = os.path.normpath(new_folder)

    conn_act = common_usage.get_mysql_connection_active()
    cursor_act = conn_act.cursor()
    cursor_act.execute(
        "SELECT 产品ID, 产品文件夹绝对路径 FROM 产品设计活动表 WHERE 项目ID = %s",
        (project_id,),
    )
    products = cursor_act.fetchall()
    updated_count = 0
    for product in products:
        if isinstance(product, dict):
            pid = product.get("产品ID")
            old_path = product.get("产品文件夹绝对路径")
        else:
            pid = product[0]
            old_path = product[1]
        if not old_path:
            continue
        try:
            if old_folder and old_folder in old_path:
                new_product_path = old_path.replace(old_folder, new_folder)
            else:
                product_folder_name = os.path.basename(old_path)
                new_product_path = os.path.join(new_folder, product_folder_name)
            new_product_path = os.path.normpath(new_product_path)
            cursor_act.execute(
                "UPDATE 产品设计活动表 SET 产品文件夹绝对路径 = %s WHERE 产品ID = %s",
                (new_product_path, pid),
            )
            updated_count += 1
        except Exception as e:
            print(f"[project_path_relocate] 更新产品路径失败 产品ID={pid}: {e}")
    conn_act.commit()
    cursor_act.close()
    conn_act.close()
    print(f"[project_path_relocate] 已同步 {updated_count} 条产品设计活动表路径")


def relocate_project_paths(project_id, project_info, new_root_folder):
    """
    用户已选择新的项目根目录（内含 id.csv，与「打开项目」选中的层级一致）。
    更新 项目需求表.项目保存路径 及 产品设计活动表。
    """
    from modules.chanpinguanli.project_confirm_btn import normalize_project_save_path

    new_root_folder = os.path.normpath(os.path.abspath(new_root_folder))
    new_save_path = normalize_project_save_path(os.path.dirname(new_root_folder))
    old_folder = get_project_root_folder(project_info)

    conn = common_usage.get_mysql_connection_project()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE 项目需求表 SET 项目保存路径 = %s WHERE 项目ID = %s",
        (new_save_path, project_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    _sync_activity_table_paths(project_id, old_folder, new_root_folder)
    print(
        f"[project_path_relocate] 项目 {project_id} 已更新保存路径为: {new_save_path}"
    )
    return True
