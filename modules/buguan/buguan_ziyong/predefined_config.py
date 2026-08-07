#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
布管 / 管束设计 — 预定义读取（配置库 user_config）

==========================================================================
什么叫「预定义操作」
--------------------------------------------------------------------------
从配置库数据库「配置库」的表 user_config 中，按 id 读取 value 字段，
供布管界面与管束相关计算使用。本文件是这类读库操作的统一入口。

什么不算本文件职责
--------------------------------------------------------------------------
- 产品设计活动库 / 材料库 等其它库查询
- 写死在代码里的对照表（如名义孔桥本地表 nominal_bridge_width.py）
- UI 写回、弹窗确认、按材料牌号选列等业务逻辑（仍在 Editor / 业务文件）

分层
--------------------------------------------------------------------------
L1 通用读库：get_user_config_value / get_user_config_values
L2 按 id 解析 + 缓存：见下方各 get_* 函数；新增 id 请在此增加 getter

已知 id（布管侧）
--------------------------------------------------------------------------
- 2.10.1.1  换热管外径 do + 排列方式 → 中心距 S
- 2.14.3.1  公称直径 DN → 滑道推荐厚度/高度表
- 2.14.9.1  板式滑道相对名义孔桥的间距倍数 k
- 2.18.5.1 / 2.18.5.2 / 2.18.5.3  锥壳相关阈值（壳体设计侧也会用）

调用约定
--------------------------------------------------------------------------
业务代码优先：from modules.buguan.buguan_ziyong import predefined_config
My_Piping.TubeLayoutEditor.get_config_value 已转发至本模块 L1，旧调用可不变。
==========================================================================
"""

from __future__ import annotations

import ast

# L2 缓存：None 表示尚未尝试加载；加载后为 dict（可能为空）
_TUBE_CENTER_DISTANCE_MAP_CACHE = None
_SLIDEWAY_SIZE_TABLE_CACHE = None


def _create_config_connection():
    """连接配置库。延迟导入 My_Piping 中的实现，避免循环依赖且保持原弹窗行为。"""
    from modules.buguan.buguan_ziyong.My_Piping import create_config_connection

    return create_config_connection()


# ---------------------------------------------------------------------------
# L1 通用读库
# ---------------------------------------------------------------------------

def get_user_config_value(config_id):
    """
    按 id 读取 user_config.value。
    未找到或失败返回 None（与历史 get_config_value 行为一致）。
    """
    conn = None
    try:
        conn = _create_config_connection()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT value FROM user_config WHERE id = %s",
                    (config_id,),
                )
                result = cursor.fetchone()
                if result:
                    return result["value"]
                print(f"未找到配置项: {config_id}")
                return None
        return None
    except Exception as e:
        print(f"查询配置库失败: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_user_config_values(config_ids):
    """
    按多个 id 批量读取 user_config.value。
    返回 {id_str: value}；查不到的 id 不出现在结果中。
    """
    ids = [str(x).strip() for x in (config_ids or []) if str(x).strip()]
    if not ids:
        return {}
    conn = None
    try:
        conn = _create_config_connection()
        if not conn:
            return {}
        placeholders = ", ".join(["%s"] * len(ids))
        sql = f"SELECT id, value FROM user_config WHERE id IN ({placeholders})"
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(ids))
            rows = cursor.fetchall() or []
        out = {}
        for row in rows:
            if isinstance(row, dict):
                kid = str(row.get("id") or "").strip()
                if kid:
                    out[kid] = row.get("value")
        return out
    except Exception as e:
        print(f"批量查询配置库失败: {e}")
        return {}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# L2：2.10.1.1 换热管中心距 S
# ---------------------------------------------------------------------------

def _parse_tube_center_distance_map(config_value):
    """解析 2.10.1.1 value → {(do, '三角形排列'|'正方形排列'): S}"""
    cache = {}
    if not config_value:
        return cache
    try:
        config_rows = (
            ast.literal_eval(config_value)
            if isinstance(config_value, str)
            else config_value
        )
        do_row = tri_s_row = sq_s_row = None
        for r in config_rows or []:
            if not r or len(r) < 2:
                continue
            name = str(r[0]).strip()
            if name == "换热管外径d":
                do_row = r
            elif name == "换热管中心距S（三角形排列）":
                tri_s_row = r
            elif name == "换热管中心距S（正方形排列）":
                sq_s_row = r
        if not (do_row and tri_s_row and sq_s_row):
            return cache
        do_values = [float(x) for x in do_row[1:] if str(x).strip() != ""]
        tri_values = [float(x) for x in tri_s_row[1:] if str(x).strip() != ""]
        sq_values = [float(x) for x in sq_s_row[1:] if str(x).strip() != ""]
        for i, do_value in enumerate(do_values):
            if i < len(tri_values):
                cache[(do_value, "三角形排列")] = tri_values[i]
            if i < len(sq_values):
                cache[(do_value, "正方形排列")] = sq_values[i]
    except Exception as e:
        print(f"[predefined_config] 解析2.10.1.1失败: {e}")
    return cache


def get_tube_center_distance_map():
    """
    读取预定义 2.10.1.1，返回中心距映射表（带进程内缓存）。
    键：(换热管外径do:float, '三角形排列'|'正方形排列') → S:float
    """
    global _TUBE_CENTER_DISTANCE_MAP_CACHE
    if _TUBE_CENTER_DISTANCE_MAP_CACHE is None:
        raw = get_user_config_value("2.10.1.1")
        _TUBE_CENTER_DISTANCE_MAP_CACHE = _parse_tube_center_distance_map(raw)
    return _TUBE_CENTER_DISTANCE_MAP_CACHE


# ---------------------------------------------------------------------------
# L2：2.14.3.1 滑道推荐高/厚表
# ---------------------------------------------------------------------------

def _parse_slipway_size_table(config_value):
    """解析 2.14.3.1 value → {round(DN,1): {thickness_carbon, thickness_high, height}}"""
    cache = {}
    if not config_value:
        return cache
    try:
        rows = (
            ast.literal_eval(config_value)
            if isinstance(config_value, str)
            else config_value
        )
        for r in rows[1:] if isinstance(rows, list) and len(rows) > 1 else []:
            if not isinstance(r, (list, tuple)) or len(r) < 5:
                continue
            try:
                dn = float(r[0])
                cache[round(dn, 1)] = {
                    "thickness_carbon": float(r[2]),
                    "thickness_high": float(r[3]),
                    "height": float(r[4]),
                }
            except Exception:
                continue
    except Exception as e:
        print(f"[predefined_config] 解析2.14.3.1失败: {e}")
    return cache


def get_slipway_size_table():
    """
    读取预定义 2.14.3.1，返回 DN→滑道尺寸表（带进程内缓存）。
    值字段：thickness_carbon / thickness_high / height
    """
    global _SLIDEWAY_SIZE_TABLE_CACHE
    if _SLIDEWAY_SIZE_TABLE_CACHE is None:
        raw = get_user_config_value("2.14.3.1")
        _SLIDEWAY_SIZE_TABLE_CACHE = _parse_slipway_size_table(raw)
    return _SLIDEWAY_SIZE_TABLE_CACHE


# ---------------------------------------------------------------------------
# L2：2.14.9.1 板式滑道孔桥倍数
# ---------------------------------------------------------------------------

def get_slipway_bridge_factor(default=1.0):
    """
    读取预定义 2.14.9.1 的 value，作为相对名义孔桥宽度的倍数 k。
    读失败或非法（含负数）时返回 default（默认 1.0）。
    """
    try:
        raw = get_user_config_value("2.14.9.1")
        if raw is None or str(raw).strip() == "":
            return float(default)
        factor = float(str(raw).strip())
        if factor < 0:
            print(
                f"[predefined_config] 2.14.9.1 倍数非法({factor})，回退 {default}"
            )
            return float(default)
        return factor
    except Exception as e:
        print(f"[predefined_config] 读取2.14.9.1失败: {e}，回退 {default}")
        return float(default)


# ---------------------------------------------------------------------------
# L2：2.18.5.x 数值型阈值（批量）
# ---------------------------------------------------------------------------

def get_float_config_map(config_ids, parse_float=None):
    """
    批量读取若干 id 的 value 并转为 float。
    parse_float: 可选回调；默认 float(str)。
    返回 {id: float}，解析失败的 id 不放入结果。
    """
    raw_map = get_user_config_values(config_ids)
    out = {}
    for kid, val in (raw_map or {}).items():
        try:
            if parse_float is not None:
                num = parse_float(val)
            else:
                num = float(str(val).strip())
            if num is not None:
                out[kid] = num
        except Exception:
            continue
    return out
