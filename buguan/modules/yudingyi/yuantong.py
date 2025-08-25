from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QTableWidget, QHBoxLayout,
    QVBoxLayout, QCheckBox, QMessageBox, QRadioButton
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
import json

def yuantonghoudupeizhi(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(31)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['圆筒结构厚度与长度相关配置'])

        bold_font = QFont()
        bold_font.setBold(True)

        defaults = {
            # 1）忽略圆筒设计余量
            "ignore_cb1": False,
            "ignore_cb2": False,
            "ignore_val": "0.8",

            # 2）统一厚度
            "unify_cb": False,
            "unify_val": "2",

            # 3）增加厚度
            "increase_cb1": False,
            "increase_cb2": False,
            "increase_cb3": False,
            "increase_cb4": False,
            "increase_val": "4",

            # 4）统一管/壳程
            "unify_pipe_shell_cb1": False,
            "unify_pipe_shell_cb2": False,

            # 5）轴向入口
            "axis_cb1": False,
            "axis_cb2": False,
            "axis_cb3": False,
            "axis_round_val": "10",

            # 6）径向入口
            "radial_cb1": False,
            "radial_cb2": False,
            "radial_cb3": False,
            "radial_cb4": False,
            "radial_cb5": False,
            "radial_std1": False,
            "radial_std2": False,
            "radial_std3": False,
            "radial_round_val": "10",

            # 7）浮头式换热器
            "float_rb": "1",  # 默认选第一个单选项
            "float_val": "5",

            # 8）外头盖结构参数
            "head_min_gap": "10",
            "head_expand_step": "50"
        }

        # 读取旧值
        cursor.execute("SELECT `忽略圆筒设计余量（厚度附加余量）`, `统一圆筒（管箱、外头盖）与封头的厚度`, `增加圆筒（管箱、壳体、外头盖）厚度`, `统一管/壳程圆筒厚度`,`管箱圆筒长度的确定（采用轴向入口接管的管箱）`, `管箱圆筒长度的确定（采用径向入口接管的管箱）`, `浮头式热交换器，壳程圆筒长度的确定`, `外头盖圆筒结构参数` FROM 圆筒预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                mapping = [
                    "忽略设计余量", "统一厚度", "增加厚度", "统一管壳程",
                    "轴向入口", "径向入口", "浮头换热器", "外头盖结构"
                ]
                raw_values = dict(zip(mapping, result))

                def find_val(key: str, contains: str):
                    s = raw_values.get(key, "") or ""
                    return contains in s

                def extract_number(key: str, prefix: str = "", suffix: str = ""):
                    import re
                    s = raw_values.get(key, "") or ""
                    pattern = rf"{re.escape(prefix)}(\d+\.?\d*){re.escape(suffix)}"
                    m = re.search(pattern, s)
                    return m.group(1) if m else ""

                # 用原始字段值设置 defaults
                defaults.update({
                    "ignore_cb1": find_val("忽略设计余量", "附加余量前"),
                    "ignore_cb2": find_val("忽略设计余量", "改变许用应力"),
                    "ignore_val": extract_number("忽略设计余量", "偏差）>", "mm"),

                    "unify_cb": find_val("统一厚度", "统一后材料许用应力不变"),
                    "unify_val": extract_number("统一厚度", "厚度）≤", "mm"),

                    "increase_cb1": find_val("增加厚度", "封头厚度"),
                    "increase_cb2": find_val("增加厚度", "外压控制"),
                    "increase_cb3": find_val("增加厚度", "局部应力校核"),
                    "increase_cb4": find_val("增加厚度", "耐压试验"),
                    "increase_val": extract_number("增加厚度", "厚度 - 圆筒厚度）>", "mm"),

                    "unify_pipe_shell_cb1": find_val("统一管壳程", "材质一致"),
                    "unify_pipe_shell_cb2": find_val("统一管壳程", "设计压力、温度、材质一致"),

                    "axis_cb1": find_val("轴向入口", "流通面积"),
                    "axis_cb2": find_val("轴向入口", "接管深度≥"),
                    "axis_cb3": find_val("轴向入口", "接管深度<"),
                    "axis_round_val": extract_number("轴向入口", "最大值的", "的倍数"),

                    "radial_cb1": find_val("径向入口", "流通面积"),
                    "radial_cb2": find_val("径向入口", "公称直径×2"),
                    "radial_cb3": find_val("径向入口", "补强圈外径"),
                    "radial_cb4": find_val("径向入口", "补强区宽度"),
                    "radial_cb5": find_val("径向入口", "2.5×√"),
                    "radial_std1": find_val("径向入口", "WRC107"),
                    "radial_std2": find_val("径向入口", "WRC297"),
                    "radial_std3": find_val("径向入口", "CSCBPV-TD001-2013"),
                    "radial_round_val": extract_number("径向入口", "最大值的", "的倍数"),

                    "float_rb": "1" if "壳程圆筒长度" in raw_values["浮头换热器"] else "2",
                    "float_val": extract_number("浮头换热器", "取", "mm"),

                    "head_min_gap": extract_number("外头盖结构", "最小距离为", "mm"),
                    "head_expand_step": extract_number("外头盖结构", "按", "mm")
                })
            except Exception as e:
                print(f"[警告] 配置解析失败: {e}")

        table._yuantong_widgets = {}
        row = 0

        # 小标题：1）忽略圆筒设计余量
        label1 = QLabel("1）忽略圆筒设计余量（厚度附加余量）")
        label1.setFont(bold_font)
        table.setCellWidget(row, 0, label1)
        row += 1

        # 规则1
        r1 = QWidget()
        l1 = QHBoxLayout(r1)
        l1.setContentsMargins(5, 0, 0, 0)
        cb1 = QCheckBox()
        cb1.setChecked(defaults["ignore_cb1"])
        l1.addWidget(cb1)
        l1.addWidget(QLabel("如圆筒考虑厚度附加余量前，（圆筒名义厚度-设计厚度-厚度负偏差）≥附加余量值时。"))
        l1.addStretch()
        table.setCellWidget(row, 0, r1)
        table._yuantong_widgets["ignore_cb1"] = cb1
        row += 1

        # 规则2
        r2 = QWidget()
        l2 = QHBoxLayout(r2)
        l2.setContentsMargins(5, 0, 0, 0)
        cb2 = QCheckBox()
        cb2.setChecked(defaults["ignore_cb2"])
        val1 = QLineEdit(defaults["ignore_val"])
        val1.setMaximumWidth(60)
        l2.addWidget(cb2)
        l2.addWidget(QLabel("如附加余量增加会改变许用应力，且（名义厚度-设计厚度-负偏差）>"))
        l2.addWidget(val1)
        l2.addWidget(QLabel("mm"))
        l2.addStretch()
        table.setCellWidget(row, 0, r2)
        table._yuantong_widgets.update({"ignore_cb2": cb2, "ignore_val": val1})
        row += 1

        # 小标题：2）统一厚度
        label2 = QLabel("2）统一圆筒（管箱、外头盖）与封头的厚度")
        label2.setFont(bold_font)
        table.setCellWidget(row, 0, label2)
        row += 1

        # 规则3
        r3 = QWidget()
        l3 = QHBoxLayout(r3)
        l3.setContentsMargins(5, 0, 0, 0)
        cb3 = QCheckBox()
        cb3.setChecked(defaults["unify_cb"])
        val2 = QLineEdit(defaults["unify_val"])
        val2.setMaximumWidth(60)
        l3.addWidget(cb3)
        l3.addWidget(QLabel("当（封头厚度 - 圆筒厚度）≤"))
        l3.addWidget(val2)
        l3.addWidget(QLabel("mm 且统一后材料许用应力不变。"))
        l3.addStretch()
        table.setCellWidget(row, 0, r3)
        table._yuantong_widgets.update({"unify_cb": cb3, "unify_val": val2})
        row += 1

        # 小标题：3）增加圆筒厚度
        label3 = QLabel("3）增加圆筒（管箱、壳体、外头盖）厚度")
        label3.setFont(bold_font)
        table.setCellWidget(row, 0, label3)
        row += 1

        # 规则4~7
        rules = [
            "当（封头厚度 - 圆筒厚度）>",
            "当圆筒厚度受外压控制时；",
            "当圆筒附属接管局部应力校核不通过时；",
            "当耐压试验压力下圆筒应力校核不满足规范时。"
        ]
        for i in range(4):
            r = QWidget()
            l = QHBoxLayout(r)
            l.setContentsMargins(5, 0, 0, 0)
            cb = QCheckBox()
            cb.setChecked(defaults[f"increase_cb{i+1}"])
            l.addWidget(cb)
            if i == 0:
                val = QLineEdit(defaults["increase_val"])
                val.setMaximumWidth(60)
                l.addWidget(QLabel(rules[i]))
                l.addWidget(val)
                l.addWidget(QLabel("mm，增加至≤该值（以校核通过为准）。"))
                table._yuantong_widgets["increase_val"] = val
            else:
                l.addWidget(QLabel(rules[i]))
            l.addStretch()
            table.setCellWidget(row, 0, r)
            table._yuantong_widgets[f"increase_cb{i+1}"] = cb
            row += 1

        # 绑定保存按钮
        if not hasattr(table, "_save_connected_yuantong"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_yuantonghoudu_config(table, cursor.connection, user_id, config_type))
                table._save_connected_yuantong = True
        # 小标题：4）统一管/壳程圆筒厚度
        label4 = QLabel("4）统一管/壳程圆筒厚度")
        label4.setFont(bold_font)
        table.setCellWidget(row, 0, label4)
        row += 1

        # 规则1：材质一致
        r41 = QWidget()
        l41 = QHBoxLayout(r41)
        l41.setContentsMargins(5, 0, 0, 0)
        cb41 = QCheckBox()
        cb41.setChecked(defaults.get("unify_pipe_shell_cb1", False))
        l41.addWidget(cb41)
        l41.addWidget(QLabel("当管/壳程圆筒材质一致时，统一管/壳程圆筒厚度。"))
        l41.addStretch()
        table.setCellWidget(row, 0, r41)
        table._yuantong_widgets["unify_pipe_shell_cb1"] = cb41
        row += 1

        # 规则2：压力温度材质均一致
        r42 = QWidget()
        l42 = QHBoxLayout(r42)
        l42.setContentsMargins(5, 0, 0, 0)
        cb42 = QCheckBox()
        cb42.setChecked(defaults.get("unify_pipe_shell_cb2", False))
        l42.addWidget(cb42)
        l42.addWidget(QLabel("当管/壳程圆筒设计压力、设计温度、材质一致时，统一管/壳程圆筒厚度。"))
        l42.addStretch()
        table.setCellWidget(row, 0, r42)
        table._yuantong_widgets["unify_pipe_shell_cb2"] = cb42
        row += 1
        # 小标题：5）管箱圆筒长度的确定（采用轴向入口接管的管箱）
        label5 = QLabel("5）管箱圆筒长度的确定（采用轴向入口接管的管箱）")
        label5.setFont(bold_font)
        table.setCellWidget(row, 0, label5)
        row += 1

        for i in range(1, 4):
            cb = QCheckBox()
            cb.setChecked(defaults.get(f"axis_cb{i}", False))
            r = QWidget()
            l = QHBoxLayout(r)
            l.setContentsMargins(5, 0, 0, 0)
            l.addWidget(cb)
            if i == 1:
                l.addWidget(QLabel("满足GB/T 151-2014中对流通面积的相关要求。"))
            elif i == 2:
                l.addWidget(QLabel("接管深度≥接管内径1/3，最小值=max(0×接管内径, 0mm, 0×√(DN×δ_n ), 2×法兰厚度)"))
            elif i == 3:
                l.addWidget(QLabel("接管深度<接管内径1/3，最小值=max(1/3×接管内径, 100mm, 0×√(DN×δ_n ), 2×法兰厚度)"))
            l.addStretch()
            table.setCellWidget(row, 0, r)
            table._yuantong_widgets[f"axis_cb{i}"] = cb
            row += 1

        axis_val = QLineEdit(defaults.get("axis_round_val", "10"))
        axis_val.setMaximumWidth(60)
        r = QWidget()
        l = QHBoxLayout(r)
        l.setContentsMargins(5, 0, 0, 0)
        l.addWidget(QLabel("长度取上述条款确定值"))
        l.addWidget(axis_val)
        l.addWidget(QLabel("的倍数向上圆整作为设计长度。"))
        l.addStretch()
        table.setCellWidget(row, 0, r)
        table._yuantong_widgets["axis_round_val"] = axis_val
        row += 1

        # 小标题：6）管箱圆筒长度的确定（采用径向入口接管的管箱）
        label6 = QLabel("6）管箱圆筒长度的确定（采用径向入口接管的管箱）")
        label6.setFont(bold_font)
        table.setCellWidget(row, 0, label6)
        row += 1

        for i in range(1, 6):
            cb = QCheckBox()
            cb.setChecked(defaults.get(f"radial_cb{i}", False))
            r = QWidget()
            l = QHBoxLayout(r)
            l.setContentsMargins(5, 0, 0, 0)
            l.addWidget(cb)
            if i == 1:
                l.addWidget(QLabel("满足GB/T 151-2014中对流通面积的相关要求。"))
            elif i == 2:
                l.addWidget(QLabel("最大接管公称直径×2 + 法兰厚度×1（如有）"))
            elif i == 3:
                l.addWidget(QLabel("最大接管或补强圈外径 + 6×厚度(≥80mm) + 法兰厚度"))
            elif i == 4:
                l.addWidget(QLabel("最大接管补强区宽度B + 厚度 + 法兰厚度"))
            elif i == 5:
                l.addWidget(QLabel("最大接管公称直径×2 + 2.5×√(DN×δ_n)"))
            l.addStretch()
            table.setCellWidget(row, 0, r)
            table._yuantong_widgets[f"radial_cb{i}"] = cb
            row += 1

        r = QWidget()
        l = QHBoxLayout(r)
        l.setContentsMargins(5, 0, 0, 0)
        cb1 = QCheckBox("WRC107")
        cb2 = QCheckBox("WRC297")
        cb3 = QCheckBox("CSCBPV-TD001-2013")
        cb1.setChecked(defaults.get("radial_std1", False))
        cb2.setChecked(defaults.get("radial_std2", False))
        cb3.setChecked(defaults.get("radial_std3", False))
        l.addWidget(QLabel("满足"))
        l.addWidget(cb1)
        l.addWidget(cb2)
        l.addWidget(cb3)
        l.addWidget(QLabel("对圆筒长度的限制要求"))
        l.addStretch()
        table.setCellWidget(row, 0, r)
        table._yuantong_widgets["radial_std1"] = cb1
        table._yuantong_widgets["radial_std2"] = cb2
        table._yuantong_widgets["radial_std3"] = cb3
        row += 1

        radial_val = QLineEdit(defaults.get("radial_round_val", "10"))
        radial_val.setMaximumWidth(60)
        r = QWidget()
        l = QHBoxLayout(r)
        l.setContentsMargins(5, 0, 0, 0)
        l.addWidget(QLabel("长度取上述条款确定值"))
        l.addWidget(radial_val)
        l.addWidget(QLabel("的倍数向上圆整作为设计长度。"))
        l.addStretch()
        table.setCellWidget(row, 0, r)
        table._yuantong_widgets["radial_round_val"] = radial_val
        row += 1

        # 小标题：7）浮头式换热器，壳程圆筒长度的确定
        label7 = QLabel("7）浮头式换热器，壳程圆筒长度的确定")
        label7.setFont(bold_font)
        table.setCellWidget(row, 0, label7)
        row += 1

        rb1 = QRadioButton("壳程圆筒长度取整数倍")
        rb2 = QRadioButton("壳体（法兰密封面间）取整数倍")
        rb1.setChecked(defaults.get("float_rb", "1") == "1")
        rb2.setChecked(defaults.get("float_rb", "1") == "2")
        float_val = QLineEdit(defaults.get("float_val", "5"))
        float_val.setMaximumWidth(60)
        r = QWidget()
        l = QHBoxLayout(r)
        l.setContentsMargins(5, 0, 0, 0)
        l.addWidget(rb1)
        l.addWidget(rb2)
        l.addWidget(QLabel("取"))
        l.addWidget(float_val)
        l.addWidget(QLabel("mm的整数倍"))
        l.addStretch()
        table.setCellWidget(row, 0, r)
        table._yuantong_widgets["float_rb1"] = rb1
        table._yuantong_widgets["float_rb2"] = rb2
        table._yuantong_widgets["float_val"] = float_val
        row += 1

        # 小标题：8）外头盖圆筒结构参数
        label8 = QLabel("8）外头盖圆筒结构参数")
        label8.setFont(bold_font)
        table.setCellWidget(row, 0, label8)
        row += 1

        r = QWidget()
        l = QHBoxLayout(r)
        l.setContentsMargins(5, 0, 0, 0)
        gap_val = QLineEdit(defaults.get("head_min_gap", "10"))
        gap_val.setMaximumWidth(60)
        l.addWidget(QLabel("圆筒内径距浮头法兰外径最小距离为"))
        l.addWidget(gap_val)
        l.addWidget(QLabel("mm"))
        l.addStretch()
        table.setCellWidget(row, 0, r)
        table._yuantong_widgets["head_min_gap"] = gap_val
        row += 1

        r = QWidget()
        l = QHBoxLayout(r)
        l.setContentsMargins(5, 0, 0, 0)
        step_val = QLineEdit(defaults.get("head_expand_step", "50"))
        step_val.setMaximumWidth(60)
        l.addWidget(QLabel("为满足浮头法兰强度，法兰直径增大时，内径按"))
        l.addWidget(step_val)
        l.addWidget(QLabel("mm增加"))
        l.addStretch()
        table.setCellWidget(row, 0, r)
        table._yuantong_widgets["head_expand_step"] = step_val
        row += 1

    except Exception as e:
        print(f"[错误] 加载配置失败: {e}")

def save_yuantonghoudu_config(table: QTableWidget, db_conn, user_id, config_type=None):
    try:
        w = table._yuantong_widgets

        # 每组语句按勾选拼接为一段文字（; 分隔）
        def section(*args):
            return '; '.join([text for ok, text in args if ok])

        values = {
            "忽略设计余量": section(
                (w["ignore_cb1"].isChecked(), "如圆筒考虑厚度附加余量前，（圆筒名义厚度-设计厚度-厚度负偏差）≥附加余量值时"),
                (w["ignore_cb2"].isChecked(), f"如附加余量改变许用应力，且（名义厚度-设计厚度-负偏差）>{w['ignore_val'].text()}mm")
            ),
            "统一厚度": section(
                (w["unify_cb"].isChecked(), f"当（封头厚度 - 圆筒厚度）≤{w['unify_val'].text()}mm 且统一后材料许用应力不变")
            ),
            "增加厚度": section(
                (w["increase_cb1"].isChecked(), f"当（封头厚度 - 圆筒厚度）>{w['increase_val'].text()}mm，增加至≤该值（以校核通过为准）"),
                (w["increase_cb2"].isChecked(), "当圆筒厚度受外压控制时"),
                (w["increase_cb3"].isChecked(), "当圆筒附属接管局部应力校核不通过时"),
                (w["increase_cb4"].isChecked(), "当耐压试验压力下圆筒应力校核不满足规范时")
            ),
            "统一管壳程": section(
                (w["unify_pipe_shell_cb1"].isChecked(), "当管/壳程圆筒材质一致时，统一厚度"),
                (w["unify_pipe_shell_cb2"].isChecked(), "当设计压力、温度、材质一致时，统一厚度")
            ),
            "轴向入口": section(
                (w["axis_cb1"].isChecked(), "满足GB/T 151-2014中对流通面积的相关要求"),
                (w["axis_cb2"].isChecked(), "接管深度≥接管内径1/3，最小值=max(0×接管内径, 0mm, 0×√(DN×δ_n ), 2×法兰厚度)"),
                (w["axis_cb3"].isChecked(), "接管深度<接管内径1/3，最小值=max(1/3×接管内径, 100mm, 0×√(DN×δ_n ), 2×法兰厚度)"),
                (True, f"设计长度为上述最大值的{w['axis_round_val'].text()}的倍数向上圆整")
            ),
            "径向入口": section(
                (w["radial_cb1"].isChecked(), "满足GB/T 151-2014中对流通面积的相关要求"),
                (w["radial_cb2"].isChecked(), "最大接管公称直径×2 + 法兰厚度"),
                (w["radial_cb3"].isChecked(), "最大接管或补强圈外径 + 6×厚度(≥80mm) + 法兰厚度"),
                (w["radial_cb4"].isChecked(), "最大接管补强区宽度B + 厚度 + 法兰厚度"),
                (w["radial_cb5"].isChecked(), "最大接管公称直径×2 + 2.5×√(DN×δ_n)"),
                (w["radial_std1"].isChecked(), "WRC107"),
                (w["radial_std2"].isChecked(), "WRC297"),
                (w["radial_std3"].isChecked(), "CSCBPV-TD001-2013"),
                (True, f"设计长度为上述最大值的{w['radial_round_val'].text()}的倍数向上圆整")
            ),
            "浮头换热器": section(
                (True, f"{'壳程圆筒长度' if w['float_rb1'].isChecked() else '法兰密封面间'}取{w['float_val'].text()}mm整数倍")
            ),
            "外头盖结构": section(
                (True, f"圆筒内径距浮头法兰最小距离为{w['head_min_gap'].text()}mm"),
                (True, f"法兰增大时，内径按{w['head_expand_step'].text()}mm递增")
            )
        }

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 圆筒预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("""
            INSERT INTO 圆筒预定义用户表 (user_id, `忽略圆筒设计余量（厚度附加余量）`, `统一圆筒（管箱、外头盖）与封头的厚度`, `增加圆筒（管箱、壳体、外头盖）厚度`, `统一管/壳程圆筒厚度`,
            `管箱圆筒长度的确定（采用轴向入口接管的管箱）`, `管箱圆筒长度的确定（采用径向入口接管的管箱）`, `浮头式热交换器，壳程圆筒长度的确定`, `外头盖圆筒结构参数`)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            values["忽略设计余量"],
            values["统一厚度"],
            values["增加厚度"],
            values["统一管壳程"],
            values["轴向入口"],
            values["径向入口"],
            values["浮头换热器"],
            values["外头盖结构"]
        ))
        db_conn.commit()
        cursor.close()
        QMessageBox.information(table, "保存成功", "圆筒结构配置已保存至配置库")
    except Exception as e:
        QMessageBox.critical(table, "保存失败", f"保存时出错: {e}")
