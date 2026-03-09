# modules/cailiaodingyi/funcs/check_dianpian.py
from modules.cailiaodingyi.db_cnt import get_connection
from PyQt5.QtWidgets import QMessageBox
from PyQt5 import QtWidgets
from modules.cailiaodingyi.funcs.funcs_pdf_change import update_element_name_data, query_element_name_param_value

PN_USER_INPUT_CACHE = {}

def mark_pn_user_input(product_id, gasket_id):
    try:
        PN_USER_INPUT_CACHE[(str(product_id or ''), str(gasket_id or ''))] = True
    except Exception:
        pass

def clear_pn_user_input(product_id, gasket_id):
    try:
        PN_USER_INPUT_CACHE.pop((str(product_id or ''), str(gasket_id or '')), None)
    except Exception:
        pass

def is_pn_user_input(product_id, gasket_id):
    try:
        return bool(PN_USER_INPUT_CACHE.get((str(product_id or ''), str(gasket_id or '')), False))
    except Exception:
        return False

def _norm_out(v):
    if v is None:
        return "程序推荐"
    s = str(v).strip()
    return s if s else "程序推荐"

DIM_USER_INPUT_CACHE = {}

def mark_dim_user_input(product_id, gasket_id, param_name):
    try:
        DIM_USER_INPUT_CACHE[(str(product_id or ''), str(gasket_id or ''), str(param_name or ''))] = True
    except Exception:
        pass

def clear_dim_user_input(product_id, gasket_id, param_name):
    try:
        DIM_USER_INPUT_CACHE.pop((str(product_id or ''), str(gasket_id or ''), str(param_name or '')), None)
    except Exception:
        pass

def is_dim_user_input_cached(product_id, gasket_id, param_name):
    try:
        return bool(DIM_USER_INPUT_CACHE.get((str(product_id or ''), str(gasket_id or ''), str(param_name or '')), False))
    except Exception:
        return False

def is_dim_user_input(product_id, element_name, param_name):
    return False

def is_dim_user_input_any(product_id, gasket_id, element_name, param_name):
    try:
        return is_dim_user_input_cached(product_id, gasket_id, param_name) or is_dim_user_input(product_id, element_name, param_name)
    except Exception:
        return False

def is_dim_weak(product_id, element_name, param_name):
    try:
        val = query_element_name_param_value(product_id, element_name, param_name)
        s = str(val).strip() if val is not None else ""
        return s == "" or s == "程序推荐"
    except Exception:
        return True

db_config1 = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "产品设计活动库"
}

db_config2 = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "材料库"
}


def get_gasket_elements(product_id):
    """
    查询指定产品ID的所有垫片配套法兰明细
    返回结构：[
        {
          "产品ID":..., "垫片名称":..., "垫片元件ID":..., "垫片管壳程":...,
          "配套法兰名称":..., "法兰元件ID":..., "法兰管壳程":..., "法兰材料牌号": [...],
          "管程设计压力":..., "壳程设计压力":...,
          "管程设计温度":..., "壳程设计温度":...,
          "管程公称直径":..., "壳程公称直径":...
        }, ...
    ]
    """
    # === STEP1 & STEP2: 查垫片元件 ===
    conn = get_connection(**db_config1)
    gasket_ids, gasket_names = [], {}
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 元件ID
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 元件名称 LIKE %s
            """, (product_id, "%垫片%"))
            rows = cursor.fetchall()
            gasket_ids = [row["元件ID"] for row in rows]

            for eid in gasket_ids:
                cursor.execute("""
                    SELECT 元件名称
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件ID = %s
                    LIMIT 1
                """, (product_id, eid))
                row = cursor.fetchone()
                if row:
                    gasket_names[eid] = row["元件名称"]
    finally:
        conn.close()

    if not gasket_ids:
        return []

    # === STEP3-5: 查配套法兰 + 法兰元件ID + 材料牌号 ===
    result = []
    conn2 = get_connection(**db_config2)
    try:
        with conn2.cursor() as cursor2:
            for gid, gname in gasket_names.items():
                cursor2.execute("""
                    SELECT *
                    FROM 垫片配套法兰映射表
                    WHERE 垫片名称 = %s
                """, (gname,))
                rows = cursor2.fetchall()

                for r in rows:
                    flange_name = r.get("配套法兰") or r.get("法兰名称")
                    gasket_course = r.get("垫片管壳程") if "垫片管壳程" in r else None
                    flange_course = r.get("法兰管壳程") if "法兰管壳程" in r else None

                    # === STEP4: 查配套法兰元件ID ===
                    conn3 = get_connection(**db_config1)
                    try:
                        with conn3.cursor() as cursor3:
                            cursor3.execute("""
                                SELECT 元件ID
                                FROM 产品设计活动表_元件材料表
                                WHERE 产品ID = %s AND 元件名称 = %s
                            """, (product_id, flange_name))
                            flange_rows = cursor3.fetchall()
                            flange_ids = [fr["元件ID"] for fr in flange_rows]

                            for fid in flange_ids:
                                # === STEP5: 查材料牌号 ===
                                cursor3.execute("""
                                    SELECT 参数值
                                    FROM 产品设计活动表_元件附加参数表
                                    WHERE 产品ID = %s AND 元件ID = %s AND 参数名称 = '材料牌号'
                                """, (product_id, fid))
                                mrows = cursor3.fetchall()
                                mvals = [mr["参数值"] for mr in mrows if mr.get("参数值")]

                                # 先存起来，等STEP6加设计数据后再统一返回
                                result.append({
                                    "产品ID": product_id,
                                    "垫片名称": gname,
                                    "垫片元件ID": gid,
                                    "垫片管壳程": gasket_course,
                                    "配套法兰名称": flange_name,
                                    "法兰元件ID": fid,
                                    "法兰管壳程": flange_course,
                                    "法兰材料牌号": mvals
                                })
                    finally:
                        conn3.close()
    finally:
        conn2.close()

    # === STEP6: 查设计数据表 ===
    design_data = {
        "管程设计压力": None,
        "壳程设计压力": None,
        "管程设计温度": None,
        "壳程设计温度": None,
        "管程公称直径": None,
        "壳程公称直径": None,
    }
    conn4 = get_connection(**db_config1)
    try:
        with conn4.cursor() as cursor4:
            cursor4.execute("""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
                  AND 参数名称 IN ('设计压力*', '设计温度（最高）*', '公称直径*')
            """, (product_id,))
            rows = cursor4.fetchall()

            for r in rows:
                pname = r["参数名称"]
                if pname == "设计压力*":
                    design_data["管程设计压力"] = r.get("管程数值")
                    design_data["壳程设计压力"] = r.get("壳程数值")
                elif pname == "设计温度（最高）*":
                    design_data["管程设计温度"] = r.get("管程数值")
                    design_data["壳程设计温度"] = r.get("壳程数值")
                elif pname == "公称直径*":
                    design_data["管程公称直径"] = r.get("管程数值")
                    design_data["壳程公称直径"] = r.get("壳程数值")
    finally:
        conn4.close()

    # 把设计数据加到每一条记录里
    for item in result:
        item.update(design_data)
    return result

def clear_all_pn_user_input_for_product(product_id):
    items = get_gasket_elements(product_id)
    ids = set()
    for it in items:
        gid = it.get("垫片元件ID")
        if gid:
            ids.add(gid)
    try:
        conn = get_connection(**db_config1)
        with conn.cursor() as cursor:
            for gid in ids:
                try:
                    cursor.execute(
                        """
                        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        LIMIT 1
                        """,
                        (product_id, gid)
                    )
                    r0 = cursor.fetchone()
                    cur_val = (r0.get("参数值") if isinstance(r0, dict) else (r0[0] if r0 else None))
                    cur_text = str(cur_val).strip() if cur_val is not None else ""
                    if cur_text == "" or cur_text == "程序推荐":
                        clear_pn_user_input(product_id, gid)
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

def force_recompute_and_update_pn(product_id):
    from modules.cailiaodingyi.funcs.funcs_pdf_change import compute_pn_for_gasket
    items = get_gasket_elements(product_id)
    groups = {}
    for it in items:
        gid = it.get("垫片元件ID")
        gname = (it.get("垫片名称") or "").strip()
        if gid:
            groups[(gid, gname)] = True
    if not groups:
        return
    conn = get_connection(**db_config1)
    nonstd_names = []  # 收集非标垫片名称，统一提示
    try:
        with conn.cursor() as cursor:
            for gid, gname in groups.keys():
                current_pn_val = None
                try:
                    cursor.execute(
                        """
                        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        LIMIT 1
                        """,
                        (product_id, gid)
                    )
                    r0 = cursor.fetchone()
                    if r0:
                        current_pn_val = (r0.get("参数值") if isinstance(r0, dict) else (r0[0] if r0 else None))
                except Exception:
                    current_pn_val = None
                cur_text = str(current_pn_val).strip() if current_pn_val is not None else ""
                is_user_manual = is_pn_user_input(product_id, gid)
                if is_user_manual and (cur_text != "" and cur_text != "程序推荐"):
                    pass
                else:
                    try:
                        pn_inline = compute_pn_for_gasket(product_id, gname or "")
                    except Exception:
                        pn_inline = None
                    val_to_write = "程序推荐" if pn_inline is None else str(pn_inline)
                    try:
                        cursor.execute(
                            """
                            UPDATE 产品设计活动表_元件附加参数表
                            SET 参数值=%s
                            WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                            """,
                            (val_to_write, product_id, gid)
                        )
                        conn.commit()
                    except Exception:
                        continue
                    try:
                        clear_pn_user_input(product_id, gid)
                    except Exception:
                        pass
                try:
                    from modules.cailiaodingyi.funcs.funcs_pdf_change import resolve_gasket_dimensions, query_element_name_param_value
                    gasket_standard = query_element_name_param_value(product_id, gname, "垫片标准") or ""
                    if str(gasket_standard).strip() == "非标垫片":
                        # 收集非标垫片，后续统一提示
                        nonstd_names.append(gname)
                        continue
                    gasket_type = query_element_name_param_value(product_id, gname, "垫片型式") or query_element_name_param_value(product_id, gname, "垫片类型") or ""
                    spec = resolve_gasket_dimensions(product_id, gname, gasket_standard, gasket_type, pn=(cur_text if (is_user_manual and (cur_text != "" and cur_text != "程序推荐")) else str(val_to_write)))
                    try:
                        d_val = spec.get("外直径D")
                        d_in = spec.get("内直径d")
                        d1 = spec.get("环内径d1")
                        update_element_name_data(product_id, gname, "环内径d1", _norm_out(d1))
                        update_element_name_data(product_id, gname, "垫片名义外径D2n", _norm_out(d_val))
                        update_element_name_data(product_id, gname, "垫片名义内径D1n", _norm_out(d_in))
                        print(f"[条件保存后][DB] 已更新产品{product_id}, 垫片ID={gid}, D2n/D1n/d1={_norm_out(d_val)}/{_norm_out(d_in)}/{_norm_out(d1)}")
                    except Exception as e:
                        print(f"[条件保存后][DB] 更新D2n/D1n/d1失败: {e}")
                except Exception as e:
                    print(f"[条件保存后] 计算并更新垫片尺寸失败: {e}")
        # 统一弹窗提示所有非标垫片
        if nonstd_names:
            try:
                parent = QtWidgets.QApplication.activeWindow()
                msg = f"{'、'.join(nonstd_names)}为非标垫片，无法计算内外径！"
                box = QMessageBox(QMessageBox.Information, "提示", msg, QMessageBox.NoButton, parent)
                ok = box.addButton("确认", QMessageBox.YesRole)
                box.setDefaultButton(ok)
                box.exec_()
            except Exception:
                pass
    finally:
        conn.close()

def check_gasket_params(self):
    product_id = getattr(self, "last_confirmed_product_id", None)

    # === 规则表（垫片名称 → 校验函数） ===
    GASKET_CHECK_RULES = {
        "管箱垫片": check_general_gasket,
        "头盖垫片": check_general_gasket,
        "平盖垫片": check_general_gasket,
        "管箱侧垫片": check_general_gasket,
        "浮头垫片": check_floating_head_gasket,
        "外头盖垫片": check_outer_head_gasket,
    }

    if not product_id:
        return

    try:
        gasket_data = get_gasket_elements(product_id)
        if not gasket_data:
            return

        all_msgs = []
        for i, item in enumerate(gasket_data, 1):
            gasket_name = item.get("垫片名称")
            check_func = GASKET_CHECK_RULES.get(gasket_name)
            if check_func:
                try:
                    res = check_func(item)
                    if isinstance(res, tuple) and len(res) == 3:
                        level, msg, pn_single = res
                    else:
                        level, msg = res
                        pn_single = None
                    item["_pn_val"] = pn_single
                    if msg:
                        all_msgs.append(f"[{level.upper()}] {msg}")
                except Exception as inner_e:
                    print(f"[垫片校验][ERROR] 校验函数出错: {inner_e}, item={item}")
            else:
                print(f"[垫片校验] ⚠️ 未定义校验规则: {gasket_name}")

        if all_msgs:
            # 汇总结果
            msg_text = "；".join(all_msgs)
            print("[垫片校验][汇总] 检查结果：\n  " + "\n  ".join(all_msgs))

            # 输出到界面 line_tip
            self.line_tip.setText(msg_text)
            self.line_tip.setToolTip(msg_text)
            self.line_tip.setStyleSheet("color: black;")
        else:
            print("[垫片校验][汇总] 所有配套法兰校验通过")
            self.line_tip.setText("所有配套法兰校验通过")
            self.line_tip.setToolTip("所有配套法兰校验通过")
            self.line_tip.setStyleSheet("color: black;")

        groups = {}
        for it in gasket_data:
            gid = it.get("垫片元件ID")
            gname = (it.get("垫片名称") or "").strip()
            groups.setdefault((gid, gname), []).append(it)
        for (gid, gname), items in groups.items():
            flanges = [ (it.get("配套法兰名称") or "").strip() for it in items ]
            print(f"[垫片校验][组] 垫片ID={gid}, 名称={gname}, 配套法兰={flanges}")
            chosen_pn = None
            if gname == "平盖垫片":
                pn_map = {}
                for it2 in items:
                    nm2 = (it2.get("配套法兰名称") or "").strip()
                    pv2 = it2.get("_pn_val")
                    if pv2 is not None:
                        pn_map[nm2] = pv2
                        print(f"[垫片校验][平盖校验] 垫片={gname}, 法兰={nm2}, PN={pv2}")
                if "管箱法兰" in pn_map:
                    chosen_pn = pn_map["管箱法兰"]
                    print(f"[垫片校验][平盖选择] 垫片={gname}, 选法兰=管箱法兰, PN={chosen_pn}")
                else:
                    for it2 in items:
                        nm2 = (it2.get("配套法兰名称") or "").strip()
                        if nm2 in pn_map:
                            chosen_pn = pn_map[nm2]
                            print(f"[垫片校验][平盖选择] 垫片={gname}, 选法兰={nm2}, PN={chosen_pn}")
                            break
            else:
                pn_vals = []
                for it in items:
                    pv = it.get("_pn_val")
                    if pv is not None:
                        pn_vals.append(pv)
                if pn_vals:
                    try:
                        chosen_pn = max(pn_vals)
                    except Exception:
                        chosen_pn = pn_vals[-1]
                    print(f"[垫片校验][聚合最大] 垫片={gname}, 候选PN={pn_vals} → 取最大={chosen_pn}")
            if chosen_pn is not None:
                try:
                    conn = get_connection(**db_config1)
                    with conn.cursor() as cursor:
                        current_pn_val = None
                        pn_source = None
                        try:
                            cursor.execute(
                                """
                                SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                                WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                                LIMIT 1
                                """,
                                (product_id, gid)
                            )
                            r0 = cursor.fetchone()
                            if r0:
                                current_pn_val = (r0.get("参数值") if isinstance(r0, dict) else (r0[0] if r0 else None))
                        except Exception:
                            pass

                        cur_text = str(current_pn_val).strip() if current_pn_val is not None else ""
                        is_user_manual = is_pn_user_input(product_id, gid)

                        if (not is_user_manual) or (cur_text == "" or cur_text == "程序推荐"):
                            cursor.execute(
                                """
                                UPDATE 产品设计活动表_元件附加参数表
                                SET 参数值=%s
                                WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                                """,
                                (chosen_pn, product_id, gid)
                            )
                            conn.commit()
                            try:
                                clear_pn_user_input(product_id, gid)
                            except Exception:
                                pass
                            try:
                                from modules.cailiaodingyi.funcs.funcs_pdf_change import resolve_gasket_dimensions, query_element_name_param_value
                                gasket_standard = query_element_name_param_value(product_id, gname, "垫片标准") or ""
                                gasket_type = query_element_name_param_value(product_id, gname, "垫片型式") or query_element_name_param_value(product_id, gname, "垫片类型") or ""
                                spec = resolve_gasket_dimensions(product_id, gname, gasket_standard, gasket_type, pn=str(chosen_pn))
                                try:
                                    d_val = spec.get("外直径D")
                                    d_in = spec.get("内直径d")
                                    d1 = spec.get("环内径d1")
                                    if (not is_dim_user_input_any(product_id, gid, gname, "环内径d1")) and is_dim_weak(product_id, gname, "环内径d1"):
                                        update_element_name_data(product_id, gname, "环内径d1", _norm_out(d1))
                                    if (not is_dim_user_input_any(product_id, gid, gname, "垫片名义外径D2n")) and is_dim_weak(product_id, gname, "垫片名义外径D2n"):
                                        update_element_name_data(product_id, gname, "垫片名义外径D2n", _norm_out(d_val))
                                    if (not is_dim_user_input_any(product_id, gid, gname, "垫片名义内径D1n")) and is_dim_weak(product_id, gname, "垫片名义内径D1n"):
                                        update_element_name_data(product_id, gname, "垫片名义内径D1n", _norm_out(d_in))
                                    print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gid}, D2n/D1n/d1={_norm_out(d_val)}/{_norm_out(d_in)}/{_norm_out(d1)}")
                                except Exception as e:
                                    print(f"[垫片校验][DB] 更新D2n/D1n/d1失败: {e}")
                            except Exception as e:
                                print(f"[垫片校验] 计算并更新垫片尺寸失败: {e}")
                            print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gid}, 公称压力={chosen_pn}")
                        else:
                            print(f"[垫片校验][DB] 保留当前PN，不覆盖推荐={chosen_pn}")
                finally:
                    conn.close()


    except Exception as e:
        print(f"[垫片校验] 执行出错: {e}")

# === 法兰校验函数示例 ===
def check_general_gasket(item):
    """
    校验函数：管箱垫片/头盖垫片/平盖垫片/管箱侧垫片
    """
    gasket_name = item["垫片名称"]
    product_id = item["产品ID"]
    gasket_id = item["垫片元件ID"]
    material_list = item.get("法兰材料牌号", [])

    if not material_list:
        return "warn", f"[{gasket_name}] 未找到材料牌号，无法校验", None

    material = material_list[0]
    messages = []
    pn_candidates = []

    # === 直径校验（同前，略） ===
    # ...

    # === 压力校验 ===
    course_flange = item["法兰管壳程"]
    p_val = item.get("管程设计压力") if course_flange == "管程" else item.get("壳程设计压力")
    t_val = item.get("管程设计温度") if course_flange == "管程" else item.get("壳程设计温度")

    flange_name = item["配套法兰名称"]
    print(f"[垫片校验][逐条] 垫片={gasket_name}, 法兰={flange_name}, 侧别={course_flange}, 材料={material}, P={p_val}, T={t_val}")
    level, msg, pn_val = calc_pressure_limit(
        material, t_val, p_val,
        product_id, gasket_id,
        gasket_name, flange_name
    )
    if msg:
        messages.append(msg)
    pn_out = pn_val if pn_val else None
    if pn_out is not None:
        try:
            conn = get_connection(**db_config1)
            with conn.cursor() as cursor:
                current_pn_val = None
                pn_source = None
                try:
                    cursor.execute(
                        """
                        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        LIMIT 1
                        """,
                        (product_id, gasket_id)
                    )
                    r0 = cursor.fetchone()
                    if r0:
                        current_pn_val = (r0.get("参数值") if isinstance(r0, dict) else (r0[0] if r0 else None))
                except Exception:
                    pass

                cur_text = str(current_pn_val).strip() if current_pn_val is not None else ""
                is_user_manual = is_pn_user_input(product_id, gasket_id)

                if (not is_user_manual) or (cur_text == "" or cur_text == "程序推荐"):
                    cursor.execute(
                        """
                        UPDATE 产品设计活动表_元件附加参数表
                        SET 参数值=%s
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        """,
                        (pn_out, product_id, gasket_id)
                    )
                    conn.commit()
                    try:
                        clear_pn_user_input(product_id, gasket_id)
                    except Exception:
                        pass
                    try:
                        from modules.cailiaodingyi.funcs.funcs_pdf_change import resolve_gasket_dimensions, query_element_name_param_value
                        gasket_standard = query_element_name_param_value(product_id, gasket_name, "垫片标准") or ""
                        gasket_type = query_element_name_param_value(product_id, gasket_name, "垫片型式") or query_element_name_param_value(product_id, gasket_name, "垫片类型") or ""
                        spec = resolve_gasket_dimensions(product_id, gasket_name, gasket_standard, gasket_type, pn=str(pn_out))
                        try:
                            d_val = spec.get("外直径D")
                            d_in = spec.get("内直径d")
                            d1 = spec.get("环内径d1")
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "环内径d1")) and is_dim_weak(product_id, gasket_name, "环内径d1"):
                                update_element_name_data(product_id, gasket_name, "环内径d1", _norm_out(d1))
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "垫片名义外径D2n")) and is_dim_weak(product_id, gasket_name, "垫片名义外径D2n"):
                                update_element_name_data(product_id, gasket_name, "垫片名义外径D2n", _norm_out(d_val))
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "垫片名义内径D1n")) and is_dim_weak(product_id, gasket_name, "垫片名义内径D1n"):
                                update_element_name_data(product_id, gasket_name, "垫片名义内径D1n", _norm_out(d_in))
                            print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gasket_id}, D2n/D1n/d1={_norm_out(d_val)}/{_norm_out(d_in)}/{_norm_out(d1)}")
                        except Exception as e:
                            print(f"[垫片校验][DB] 更新D2n/D1n/d1失败: {e}")
                    except Exception as e:
                        print(f"[垫片校验] 计算并更新垫片尺寸失败: {e}")
                    print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gasket_id}, 公称压力={pn_out}")
                else:
                    print(f"[垫片校验][DB] 保留当前PN，不覆盖推荐={pn_out}")
        finally:
            conn.close()
    if messages:
        return "warn", "；".join(messages), pn_out
    return "ok", "", pn_out

def check_floating_head_gasket(item):
    """
    校验函数：浮头垫片
    - 设计压力/温度：取 max(管程, 壳程)
    - 公称直径：同普通规则（空/程序推荐跳过）
    - 设计压力：调用 calc_pressure_limit（返回候选PN，汇总取最大）
    """
    gasket_name = item["垫片名称"]
    flange_name = item["配套法兰名称"]
    course_gasket = item["垫片管壳程"]
    product_id = item["产品ID"]
    gasket_id = item["垫片元件ID"]
    material_list = item.get("法兰材料牌号", [])

    if not material_list:
        return "warn", f"[{gasket_name}-{flange_name}] 未找到材料牌号，无法校验", None

    material = material_list[0]
    messages = []
    pn_candidates = []

    # === STEP1: 查压力等级表基本范围 ===
    conn = get_connection(**db_config2)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DNmin, DNmax, Tmin, Tmax
                FROM 压力等级表
                WHERE Name = %s
                LIMIT 1
            """, (material,))
            row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return "warn", f"[{gasket_name}-{flange_name}] 材料牌号 {material} 未在压力等级表中找到"

    dn_min, dn_max = float(row["DNmin"]), float(row["DNmax"])
    t_min, t_max = float(row["Tmin"]), float(row["Tmax"])

    # === STEP2: 取设计压力 / 温度（最大值，允许为空）===
    try:
        p_candidates = [float(v) for v in (
            item.get("管程设计压力"), item.get("壳程设计压力")
        ) if v not in (None, "", "程序推荐")]
        t_candidates = [float(v) for v in (
            item.get("管程设计温度"), item.get("壳程设计温度")
        ) if v not in (None, "", "程序推荐")]

        p_val = max(p_candidates) if p_candidates else None
        t_val = max(t_candidates) if t_candidates else None
    except Exception as e:
        print(f"[浮头垫片][ERROR] 压力/温度转换失败: {e}")
        p_val, t_val = None, None

    # === STEP3: 公称直径校验 ===
    if course_gasket == "管程":
        dn_val = item.get("管程公称直径")
    else:
        dn_val = item.get("壳程公称直径")

    if not dn_val or str(dn_val).strip() in ("", "程序推荐"):
        print(f"[直径校验][INFO] {gasket_name}-{flange_name} 公称直径为空/程序推荐 → 跳过直径校核")
    else:
        try:
            dn_val_f = float(dn_val)
            print(f"[直径校验][DEBUG] {gasket_name}-{flange_name} 公称直径={dn_val_f}, 限值=[{dn_min}, {dn_max}]")
            if not (dn_min <= dn_val_f <= dn_max):
                messages.append(f"[{gasket_name}-{flange_name}] 公称直径已超限，垫片尺寸将由程序推荐，用户可对其进行更改")
        except Exception as e:
            print(f"[直径校验][ERROR] {gasket_name}-{flange_name} 公称直径值无效: {dn_val}, 错误={e}")

    # === STEP4: 温度校验 ===
    if not t_val:
        print(f"[温度校验][INFO] {gasket_name}-{flange_name} 设计温度为空 → 跳过校核")
    else:
        if not (t_min <= t_val <= t_max):
            messages.append(f"[{gasket_name}-{flange_name}] 设计温度超限，垫片尺寸将由程序推荐，用户可对其进行更改")

    # === STEP5: 设计压力校验 ===
    print(f"[垫片校验][逐条] 垫片={gasket_name}, 法兰={flange_name}, 侧别={course_gasket}, 材料={material}, P={p_val}, T={t_val}")
    level, msg, pn_val = calc_pressure_limit(
        material, t_val, p_val,
        product_id, gasket_id,
        gasket_name, flange_name
    )
    if msg:
        messages.append(msg)
    pn_out = pn_val if pn_val else None
    if pn_out is not None:
        try:
            conn = get_connection(**db_config1)
            with conn.cursor() as cursor:
                current_pn_val = None
                pn_source = None
                try:
                    cursor.execute(
                        """
                        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        LIMIT 1
                        """,
                        (product_id, gasket_id)
                    )
                    r0 = cursor.fetchone()
                    if r0:
                        current_pn_val = (r0.get("参数值") if isinstance(r0, dict) else (r0[0] if r0 else None))
                except Exception:
                    pass

                def _to_float_safe(x):
                    try:
                        s = str(x).strip()
                        if s.upper().startswith("PN"):
                            s = s[2:].strip()
                        return float(s)
                    except Exception:
                        return None

                cur_text = str(current_pn_val).strip() if current_pn_val is not None else ""
                is_user_manual = is_pn_user_input(product_id, gasket_id)

                if (not is_user_manual) or (cur_text == "" or cur_text == "程序推荐"):
                    cursor.execute(
                        """
                        UPDATE 产品设计活动表_元件附加参数表
                        SET 参数值=%s
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        """,
                        (pn_out, product_id, gasket_id)
                    )
                    conn.commit()
                    try:
                        clear_pn_user_input(product_id, gasket_id)
                    except Exception:
                        pass
                    try:
                        from modules.cailiaodingyi.funcs.funcs_pdf_change import resolve_gasket_dimensions, query_element_name_param_value
                        gasket_standard = query_element_name_param_value(product_id, gasket_name, "垫片标准") or ""
                        gasket_type = query_element_name_param_value(product_id, gasket_name, "垫片型式") or query_element_name_param_value(product_id, gasket_name, "垫片类型") or ""
                        spec = resolve_gasket_dimensions(product_id, gasket_name, gasket_standard, gasket_type, pn=str(pn_out))
                        try:
                            d_val = spec.get("外直径D")
                            d_in = spec.get("内直径d")
                            d1 = spec.get("环内径d1")
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "环内径d1")) and is_dim_weak(product_id, gasket_name, "环内径d1"):
                                update_element_name_data(product_id, gasket_name, "环内径d1", _norm_out(d1))
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "垫片名义外径D2n")) and is_dim_weak(product_id, gasket_name, "垫片名义外径D2n"):
                                update_element_name_data(product_id, gasket_name, "垫片名义外径D2n", _norm_out(d_val))
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "垫片名义内径D1n")) and is_dim_weak(product_id, gasket_name, "垫片名义内径D1n"):
                                update_element_name_data(product_id, gasket_name, "垫片名义内径D1n", _norm_out(d_in))
                            print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gasket_id}, D2n/D1n/d1={_norm_out(d_val)}/{_norm_out(d_in)}/{_norm_out(d1)}")
                        except Exception as e:
                            print(f"[垫片校验][DB] 更新D2n/D1n/d1失败: {e}")
                    except Exception as e:
                        print(f"[垫片校验] 计算并更新垫片尺寸失败: {e}")
                    print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gasket_id}, 公称压力={pn_out}")
                else:
                    print(f"[垫片校验][DB] 保留当前PN，不覆盖推荐={pn_out}")
        finally:
            conn.close()
    if messages:
        return "warn", "；".join(messages), pn_out
    return "ok", "", pn_out


def check_outer_head_gasket(item):
    """
    校验函数：外头盖垫片
    - 公称直径从外头盖圆筒获取
    - 如果公称直径=="程序推荐" 或为空，则跳过直径校验
    - 温度校验：空值跳过
    - 设计压力校验：调用 calc_pressure_limit（返回候选PN，汇总取最大）
    """
    gasket_name = item["垫片名称"]
    flange_name = item["配套法兰名称"]
    course_flange = item["法兰管壳程"]
    product_id = item["产品ID"]
    gasket_id = item["垫片元件ID"]
    material_list = item.get("法兰材料牌号", [])

    if not material_list:
        return "warn", f"[{gasket_name}-{flange_name}] 未找到材料牌号，无法校验", None

    material = material_list[0]
    messages = []
    pn_candidates = []

    # === STEP1: 查压力等级表基本范围 ===
    conn = get_connection(**db_config2)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DNmin, DNmax, Tmin, Tmax
                FROM 压力等级表
                WHERE Name = %s
                LIMIT 1
            """, (material,))
            row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return "warn", f"[{gasket_name}-{flange_name}] 材料牌号 {material} 未在压力等级表中找到"

    dn_min, dn_max = float(row["DNmin"]), float(row["DNmax"])
    t_min, t_max = float(row["Tmin"]), float(row["Tmax"])

    # === STEP2: 获取外头盖圆筒的公称直径 ===
    dn_val = None
    conn = get_connection(**db_config1)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 元件ID
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 元件名称 = %s
                LIMIT 1
            """, (product_id, "外头盖圆筒"))
            row = cursor.fetchone()
            if row:
                yuanjian_id = row["元件ID"]
                cursor.execute("""
                    SELECT 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件ID = %s AND 参数名称 = '公称直径'
                    LIMIT 1
                """, (product_id, yuanjian_id))
                row2 = cursor.fetchone()
                if row2:
                    dn_val = row2["参数值"]
    finally:
        conn.close()

    # === STEP3: 公称直径校验 ===
    if not dn_val or str(dn_val).strip() in ("", "程序推荐"):
        print(f"[直径校验][INFO] {gasket_name}-{flange_name} 公称直径为空/程序推荐 → 跳过直径校核")
    else:
        try:
            dn_val_f = float(dn_val)
            print(f"[直径校验][DEBUG] {gasket_name}-{flange_name} 公称直径={dn_val_f}, 限值=[{dn_min}, {dn_max}]")
            if not (dn_min <= dn_val_f <= dn_max):
                messages.append(f"[{gasket_name}-{flange_name}] 公称直径已超限，垫片尺寸将由程序推荐，用户可对其进行更改")
        except Exception as e:
            print(f"[直径校验][ERROR] {gasket_name}-{flange_name} 公称直径值无效: {dn_val}, 错误={e}")

    # === STEP4: 温度校验 ===
    t_val = None
    if course_flange == "管程":
        t_val = item.get("管程设计温度")
    elif course_flange == "壳程":
        t_val = item.get("壳程设计温度")

    if not t_val or str(t_val).strip() == "":
        print(f"[温度校验][INFO] {gasket_name}-{flange_name} 设计温度为空 → 跳过校核")
    else:
        try:
            t_val_f = float(t_val)
            if not (t_min <= t_val_f <= t_max):
                messages.append(f"[{gasket_name}-{flange_name}] 设计温度超限，垫片尺寸将由程序推荐，用户可对其进行更改")
        except Exception as e:
            print(f"[温度校验][ERROR] {gasket_name}-{flange_name} 温度值无效: {t_val}, 错误={e}")
            t_val_f = None

    # === STEP5: 设计压力校验 ===
    if course_flange == "管程":
        p_val = item.get("管程设计压力")
        t_val = item.get("管程设计温度")
    elif course_flange == "壳程":
        p_val = item.get("壳程设计压力")
        t_val = item.get("壳程设计温度")
    else:
        p_val, t_val = None, None

    print(f"[垫片校验][逐条] 垫片={gasket_name}, 法兰={flange_name}, 侧别={course_flange}, 材料={material}, P={p_val}, T={t_val}")
    level, msg, pn_val = calc_pressure_limit(
        material, t_val, p_val,
        product_id, gasket_id,
        gasket_name, flange_name
    )
    if msg:
        messages.append(msg)
    pn_out = pn_val if pn_val else None
    if pn_out is not None:
        try:
            conn = get_connection(**db_config1)
            with conn.cursor() as cursor:
                current_pn_val = None
                try:
                    cursor.execute(
                        """
                        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        LIMIT 1
                        """,
                        (product_id, gasket_id)
                    )
                    r0 = cursor.fetchone()
                    if r0:
                        current_pn_val = (r0.get("参数值") if isinstance(r0, dict) else (r0[0] if r0 else None))
                except Exception:
                    pass

                cur_text = str(current_pn_val).strip() if current_pn_val is not None else ""
                is_user_manual = is_pn_user_input(product_id, gasket_id)

                if (not is_user_manual) or (cur_text == "" or cur_text == "程序推荐"):
                    cursor.execute(
                        """
                        UPDATE 产品设计活动表_元件附加参数表
                        SET 参数值=%s
                        WHERE 产品ID=%s AND 元件ID=%s AND 参数名称='公称压力PN'
                        """,
                        (pn_out, product_id, gasket_id)
                    )
                    conn.commit()
                    try:
                        clear_pn_user_input(product_id, gasket_id)
                    except Exception:
                        pass
                    try:
                        from modules.cailiaodingyi.funcs.funcs_pdf_change import resolve_gasket_dimensions, query_element_name_param_value
                        gasket_standard = query_element_name_param_value(product_id, gasket_name, "垫片标准") or ""
                        gasket_type = query_element_name_param_value(product_id, gasket_name, "垫片型式") or query_element_name_param_value(product_id, gasket_name, "垫片类型") or ""
                        spec = resolve_gasket_dimensions(product_id, gasket_name, gasket_standard, gasket_type, pn=str(pn_out))
                        try:
                            d_val = spec.get("外直径D")
                            d_in = spec.get("内直径d")
                            d1 = spec.get("环内径d1")
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "环内径d1")) and is_dim_weak(product_id, gasket_name, "环内径d1"):
                                update_element_name_data(product_id, gasket_name, "环内径d1", _norm_out(d1))
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "垫片名义外径D2n")) and is_dim_weak(product_id, gasket_name, "垫片名义外径D2n"):
                                update_element_name_data(product_id, gasket_name, "垫片名义外径D2n", _norm_out(d_val))
                            if (not is_dim_user_input_any(product_id, gasket_id, gasket_name, "垫片名义内径D1n")) and is_dim_weak(product_id, gasket_name, "垫片名义内径D1n"):
                                update_element_name_data(product_id, gasket_name, "垫片名义内径D1n", _norm_out(d_in))
                            print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gasket_id}, D2n/D1n/d1={_norm_out(d_val)}/{_norm_out(d_in)}/{_norm_out(d1)}")
                        except Exception as e:
                            print(f"[垫片校验][DB] 更新D2n/D1n/d1失败: {e}")
                    except Exception as e:
                        print(f"[垫片校验] 计算并更新垫片尺寸失败: {e}")
                    print(f"[垫片校验][DB] 已更新产品{product_id}, 垫片ID={gasket_id}, 公称压力={pn_out}")
                else:
                    print(f"[垫片校验][DB] 保留当前PN，不覆盖推荐={pn_out}")
        finally:
            conn.close()
    if messages:
        return "warn", "；".join(messages), pn_out
    return "ok", "", pn_out


def calc_pressure_limit(material, T, P, product_id, gasket_id, gasket_name, flange_name):
    """
    根据压力等级表计算设计压力是否超限
    返回: (level, message, pn_val)
    """
    print(f"[设计压力校验][DEBUG] 开始校验 → 垫片={gasket_name}, 法兰={flange_name}, 材料={material}, T={T}, P={P}")

    # === 空值保护 ===
    if not T or not P or str(T).strip() == "" or str(P).strip() == "" or str(P).strip() == "程序推荐":
        print(f"[设计压力校验][INFO] {gasket_name}-{flange_name} 设计压力/温度为空或程序推荐 → 跳过校核")
        return "ok", "", None

    try:
        T = float(T)
        P = float(P)
    except Exception as e:
        print(f"[设计压力校验][ERROR] 转换失败: T={T}, P={P}, 错误={e}")
        return "warn", f"[{gasket_name}-{flange_name}] 设计压力/温度值无效", None

    # === 查库 ===
    conn = get_connection(**db_config2)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM 压力等级表 WHERE Name=%s", (material,))
            rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return "warn", f"[{gasket_name}-{flange_name}] 材料牌号 {material} 未在压力等级表中找到", None

    # 工具函数
    def get_col_value(row, temp):
        for k in row.keys():
            try:
                if float(k) == float(temp):
                    return float(row[k])
            except:
                continue
        return None

    temp_cols = [float(k) for k in rows[0].keys()
                 if k not in ("Name", "PN", "DNmin", "DNmax", "Tmin", "Tmax")]
    temp_cols.sort()
    print(f"[设计压力校验][DEBUG] 可用温度列: {temp_cols}")

    candidate = None
    candidate_row = None

    for row in rows:
        PN_val = row.get("PN")
        print(f"[设计压力校验][DEBUG] 检查行: PN={PN_val}")

        px_val = get_col_value(row, T)
        if px_val is not None:
            print(f"[设计压力校验][DEBUG] 命中温度列 T={T}℃ → px_val={px_val}")
        else:
            lower = max([x for x in temp_cols if x < T], default=None)
            upper = min([x for x in temp_cols if x > T], default=None)
            if lower is None or upper is None:
                print(f"[设计压力校验][WARN] 温度 {T} 超范围 → 跳过")
                continue
            y1 = get_col_value(row, lower)
            y2 = get_col_value(row, upper)
            if y1 is None or y2 is None:
                print(f"[设计压力校验][WARN] 行缺失: PN={PN_val}, lower={lower}, upper={upper}")
                continue
            px_val = y1 + (y2 - y1) * (T - lower) / (upper - lower)
            print(f"[设计压力校验][DEBUG] 插值: ({lower},{y1})-({upper},{y2}) → px_val={px_val}")

        print(f"[设计压力校验][DEBUG] 对比 P={P}, px_val={px_val}")
        if px_val >= P:
            if candidate is None or px_val < candidate:
                candidate = px_val
                candidate_row = row
                print(f"[设计压力校验][DEBUG] 更新候选: PN={PN_val}, px_val={px_val}")

    if candidate is None:
        return "warn", f"[{gasket_name}-{flange_name}] 设计压力已超限", None

    PN_val = candidate_row.get("PN")
    print(f"[设计压力校验][RESULT] 选中 PN={PN_val}, px_val={candidate}")
    return "ok", "", PN_val



