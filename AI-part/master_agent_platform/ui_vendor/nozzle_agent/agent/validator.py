# -*- coding: utf-8 -*-
"""
管口参数校验器：给出"哪些不合法 + 为什么 + 建议怎么改"。

校验分两级：
- error   ：不允许写入表格（该字段保持空白并标红）
- warning ：允许写入，但提示工程上可能存在问题（黄色标记）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import spec


@dataclass
class Issue:
    field: str
    level: str          # error / warning
    message: str
    suggestion: str = ""
    code: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {
            "field": self.field, "level": self.level,
            "message": self.message, "suggestion": self.suggestion,
        }


CODE_RE = re.compile(r"^[A-Za-z]{1,3}\d{1,3}$")


class NozzleValidator:
    def __init__(self, existing_codes: Optional[List[str]] = None,
                 editing_code: Optional[str] = None):
        self.existing_codes = [c.upper() for c in (existing_codes or [])]
        self.editing_code = (editing_code or "").upper()

    # ------------------------------------------------------------------ 入口
    def validate(self, row: Dict[str, Any], mode: str = "add") -> List[Issue]:
        issues: List[Issue] = []
        if mode == "add":
            issues += self._check_required(row)
        issues += self._check_code(row)
        issues += self._check_size(row)
        issues += self._check_pressure(row)
        issues += self._check_standard(row)
        issues += self._check_flange_type(row)
        issues += self._check_sealing_face(row)
        issues += self._check_weld_end(row)
        # 单项本身就不合法时，不再叠一条"组合不存在"，避免同一个原因报两遍
        broken = {i.field for i in issues if i.level == "error"}
        if not broken & {"法兰标准", "压力等级", "法兰型式", "密封面型式"}:
            issues += self._check_combo(row)
        issues += self._check_use_element(row)
        issues += self._check_position(row)
        return issues

    # -------------------------------------------------------------- 必填项
    def _check_required(self, row: Dict[str, Any]) -> List[Issue]:
        required = {
            "管口代号": "管口代号",
            "公称尺寸": "公称尺寸（DN 或 NPS）",
            "压力等级类型": "压力等级类型（PN 或 Class）",
            "压力等级": "压力等级数值",
        }
        out = []
        for key, label in required.items():
            val = row.get(key)
            if val in (None, ""):
                out.append(Issue(
                    field=key, level="error", code="required",
                    message=f"缺少必填项：{label}",
                    suggestion=self._required_hint(key),
                ))
        return out

    @staticmethod
    def _required_hint(key: str) -> str:
        return {
            "管口代号": "例如 N1、N2",
            "公称尺寸": "例如 DN50、DN100",
            "压力等级类型": "PN（欧标）或 Class（美标）",
            "压力等级": "PN 体系填 16/25/40，Class 体系填 150/300/600",
        }.get(key, "")

    # ---------------------------------------------------------------- 代号
    def _check_code(self, row: Dict[str, Any]) -> List[Issue]:
        code = str(row.get("管口代号") or "").strip()
        if not code:
            return []
        if not CODE_RE.match(code):
            return [Issue("管口代号", "error", f"管口代号「{code}」格式不合法",
                          "应为 1~3 个字母 + 1~3 位数字，如 N1、N12、A3", "code_format")]
        upper = code.upper()
        if upper in self.existing_codes and upper != self.editing_code:
            return [Issue("管口代号", "error", f"管口代号「{code}」已存在，不能重复",
                          "换一个代号，或改用「把 N2 改成…」的修改说法", "code_dup")]
        return []

    # ---------------------------------------------------------------- 尺寸
    def _check_size(self, row: Dict[str, Any]) -> List[Issue]:
        val = row.get("公称尺寸")
        if val in (None, ""):
            return []
        unit = row.get("尺寸单位") or "DN"
        if unit == "NPS":
            text = str(val).strip()
            if text not in spec.NPS_SERIES:
                return [Issue("公称尺寸", "error",
                              f"NPS「{text}」不是标准尺寸系列",
                              f"可选：{'、'.join(spec.NPS_SERIES)}", "size_series")]
            return []
        try:
            dn = float(val)
        except (TypeError, ValueError):
            return [Issue("公称尺寸", "error", f"公称尺寸「{val}」不是数字", "例如 50、100", "size_type")]
        if dn not in spec.DN_SERIES:
            near = spec.nearest_dn(dn)
            nbr = spec.REF.neighbors(float(near)) if near else []
            alt = "、".join(f"DN{x}" for x in nbr)
            return [Issue("公称尺寸", "error",
                          f"DN{dn:g} 不在 公称尺寸表 的标准系列内",
                          f"最接近的是 DN{near}" + (f"，相邻规格 {alt}" if alt else ""), "size_series")]
        if dn < 15:
            return [Issue("公称尺寸", "warning", f"DN{dn:g} 偏小，接管刚度与焊接空间可能不足",
                          "换热器接管通常不小于 DN20", "size_small")]
        if dn > 600:
            return [Issue("公称尺寸", "warning", f"DN{dn:g} 属于大口径，需核对法兰标准是否覆盖该规格",
                          "PN 体系 HG/T 20592 一般到 DN600，更大规格需另选标准", "size_large")]
        return []

    @staticmethod
    def _neighbor(dn: float) -> str:
        return " / DN".join(spec.REF.neighbors(float(dn)))

    # ---------------------------------------------------------------- 压力
    def _check_pressure(self, row: Dict[str, Any]) -> List[Issue]:
        ptype = row.get("压力等级类型")
        pvalue = row.get("压力等级")
        out: List[Issue] = []
        if ptype not in ("PN", "Class"):
            if ptype not in (None, ""):
                out.append(Issue("压力等级类型", "error",
                                 f"压力等级类型「{ptype}」只能是 PN 或 Class",
                                 "欧洲体系写 PN，美洲体系写 Class", "ptype"))
            return out
        if pvalue in (None, ""):
            return out
        try:
            value = float(pvalue)
        except (TypeError, ValueError):
            return out + [Issue("压力等级", "error", f"压力等级「{pvalue}」不是数字",
                                "例如 16、25、40 或 150、300", "pvalue_type")]
        # 压力等级按「法兰标准 + 压力类型」分别取值，与 管口压力等级表 一致
        std = str(row.get("法兰标准") or "").strip()
        series_text = spec.REF.levels(std, ptype)
        if not series_text:
            series_text = [str(x) for x in (spec.PN_SERIES if ptype == "PN" else spec.CLASS_SERIES)]
        series = [float(x) for x in series_text]
        if value not in series:
            near = min(series, key=lambda x: abs(x - value)) if series else value
            cross = ""
            if ptype == "PN" and 100 <= value <= 2500:
                cross = "；这个数值更像 Class 磅级，若确为美标请把类型写成 Class"
            scope = f"{std} " if std else ""
            out.append(Issue("压力等级", "error",
                             f"{scope}{ptype}{value:g} 不是标准压力等级",
                             f"{scope}{ptype} 体系可选：{'、'.join('%g' % x for x in series)}；"
                             f"最接近的是 {ptype}{near:g}{cross}", "pvalue_series"))
        if ptype == "Class" and value in (400.0, 900.0, 1500.0, 2500.0):
            out.append(Issue("压力等级", "warning", f"Class{value:g} 法兰采购周期通常较长",
                             "若设计压力不高，可优先考虑 Class300 及以下", "pvalue_long_lead"))
        return out

    # ---------------------------------------------------------------- 标准
    def _check_standard(self, row: Dict[str, Any]) -> List[Issue]:
        std = row.get("法兰标准")
        if std in (None, ""):
            return []
        if std not in spec.FLANGE_STANDARDS:
            return [Issue("法兰标准", "error", f"法兰标准「{std}」不在 公称压力类型标准对应表 内",
                          f"可选：{'、'.join(spec.FLANGE_STANDARDS)}", "std_unknown")]
        ptype = row.get("压力等级类型")
        if ptype in ("PN", "Class"):
            allowed = spec.STANDARDS_BY_TYPE.get(ptype, [])
            if allowed and std not in allowed:
                return [Issue("法兰标准", "error",
                              f"{ptype} 体系不能用 {std}",
                              f"{ptype} 体系可选：{'、'.join(allowed)}", "std_mismatch")]
        return []

    # ------------------------------------------------------------ 法兰型式
    def _check_flange_type(self, row: Dict[str, Any]) -> List[Issue]:
        ftype = row.get("法兰型式")
        if ftype in (None, ""):
            return []
        if ftype not in spec.FLANGE_TYPES:
            cn = "、".join(f"{k}({v})" for k, v in spec.FLANGE_TYPE_CN.items()
                           if k in spec.FLANGE_TYPES)
            return [Issue("法兰型式", "error", f"法兰型式「{ftype}」不在 管口关系对应表 内",
                          f"可选代号：{'、'.join(spec.FLANGE_TYPES)}；常见含义：{cn}", "ftype")]
        dn = row.get("公称尺寸")
        if ftype == "PL" and spec.is_num(dn) and float(dn) >= 600:
            return [Issue("法兰型式", "warning", "DN600 及以上用板式平焊法兰刚性偏弱",
                          "建议 WN 带颈对焊法兰", "ftype_pl_large")]
        if ftype == "Th" and str(row.get("管口功能") or "").startswith(("管程入口", "壳程入口")):
            return [Issue("法兰型式", "warning", "工艺介质主进出口用螺纹法兰较少见，密封可靠性偏低",
                          "改 WN 或 SO 法兰", "ftype_thread_main")]
        return []

    # ------------------------------------------------------------ 密封面
    def _check_sealing_face(self, row: Dict[str, Any]) -> List[Issue]:
        face = row.get("密封面型式")
        if face in (None, ""):
            return []
        if face not in spec.SEALING_FACES:
            cn = "、".join(f"{k}({v})" for k, v in spec.SEALING_FACE_CN.items())
            return [Issue("密封面型式", "error", f"密封面型式「{face}」不在 管口关系对应表 内",
                          f"可选代号：{'、'.join(spec.SEALING_FACES)}；常见含义：{cn}", "face_unknown")]
        # 具体能不能配，由 _check_combo 按项目关系表判定，这里只给工程提示
        ptype, pvalue = row.get("压力等级类型"), row.get("压力等级")
        try:
            pv = float(pvalue)
        except (TypeError, ValueError):
            pv = None
        out: List[Issue] = []
        if face in ("MF", "TG", "M", "FM", "T", "G") and pv is not None:
            if (ptype == "PN" and pv <= 6) or (ptype == "Class" and pv <= 150):
                out.append(Issue("密封面型式", "warning",
                                 f"凹凸面/榫槽面在 {ptype}{pv:g} 低压下较少使用且垫片难采购",
                                 "优先 RF 突面", "face_low"))
        if face == "RF" and ptype == "Class" and pv is not None and pv >= 900:
            out.append(Issue("密封面型式", "warning", f"Class{pv:g} 高压用 RF 突面密封可靠性偏低",
                             "建议 RJ 环连接面", "face_rf_high"))
        return out

    # ------------------------------------------------------------ 组合合法性
    def _check_combo(self, row: Dict[str, Any]) -> List[Issue]:
        """
        用 管口关系对应表 判断「标准 + 压力等级 + 法兰型式 + 密封面」这套组合
        在正式项目里能否选得出来。这是线上真正的硬规则。
        """
        std = row.get("法兰标准")
        pval = row.get("压力等级")
        ftype = row.get("法兰型式")
        face = row.get("密封面型式")
        ptype = row.get("压力等级类型")
        if not all(str(x or "").strip() for x in (std, pval, ftype, face, ptype)):
            return []

        ref = spec.REF
        if ref.combo_exists(std, pval, ftype, face, ptype):
            return []

        hints = ref.combo_hints(std, pval, ftype, face, ptype)
        ft_ok = hints.get("法兰型式") or []
        fc_ok = hints.get("密封面型式") or []
        pv_ok = hints.get("压力等级") or []

        # 只换一项就能成立时，指出该换哪个
        parts = []
        if ft_ok:
            parts.append(f"法兰型式改为 {' / '.join(ft_ok[:5])}")
        if fc_ok:
            parts.append(f"密封面型式改为 {' / '.join(fc_ok[:5])}")
        if pv_ok:
            parts.append(f"压力等级改为 {' / '.join(('Class' if ptype == 'Class' else 'PN') + x for x in pv_ok[:5])}")

        if not parts:
            # 这套组合在别的标准下存在，说明应该换标准而不是换参数
            alt_std = [s for s in spec.STANDARDS_BY_TYPE.get(ptype, [])
                       if s != std and ref.combo_exists(s, pval, ftype, face, ptype)]
            hint = ("改用 " + " / ".join(alt_std) + f" 标准，这套组合才存在") if alt_std else \
                   "这三个参数需同时调整，建议先定压力等级再选型式和密封面"
            return [Issue(
                "法兰型式", "error",
                f"{std} 在 {ptype}{pval} 下没有「{ftype} + {face}」这套组合",
                hint, "combo_none")]

        alt_std = [s for s in spec.STANDARDS_BY_TYPE.get(ptype, [])
                   if s != std and ref.combo_exists(s, pval, ftype, face, ptype)]
        if parts and alt_std:
            parts.append(f"或改用 {' / '.join(alt_std)} 标准（该组合在这些标准下存在）")

        return [Issue(
            "法兰型式", "error",
            f"{std} 在 {ptype}{pval} 下不存在「{ftype} + {face}」组合",
            "保持其它参数不变，可改为：" + "；或 ".join(parts), "combo")]

    # ------------------------------------------------------------ 焊端规格
    def _check_weld_end(self, row: Dict[str, Any]) -> List[Issue]:
        val = row.get("焊端规格")
        if val in (None, ""):
            return []
        unit = row.get("焊端规格单位") or "Sch"
        if unit == "Sch":
            text = str(val).replace(" ", "")
            # 「程序推荐」是 管口默认表 里的合法初始值
            if text == "程序推荐":
                return []
            if text not in spec.SCH_VALUES:
                return [Issue("焊端规格", "error", f"焊端规格「{val}」不在 焊端规格类型表 内",
                              f"可选：{'、'.join(spec.SCH_VALUES)}（界面显示为 Sch，库里存代号）", "sch_unknown")]
            return []
        try:
            wall = float(val)
        except (TypeError, ValueError):
            return [Issue("焊端规格", "error", f"壁厚「{val}」不是数字", "例如 3.9、5.0", "wall_type")]
        if wall <= 0:
            return [Issue("焊端规格", "error", "壁厚必须大于 0", "例如 3.9", "wall_zero")]
        if wall > 60:
            return [Issue("焊端规格", "error", f"壁厚 {wall:g} mm 明显超出接管常规范畴",
                          "核对是否把外径当成壁厚填了", "wall_large")]
        dn = row.get("公称尺寸")
        if isinstance(dn, (int, float)):
            rec = spec.suggest_wall(int(dn))
            if wall < rec * 0.6:
                return [Issue("焊端规格", "warning",
                              f"DN{dn:g} 接管壁厚 {wall:g} mm 明显小于常规值 {rec:g} mm",
                              f"按内压与刚度建议不小于 {rec:g} mm", "wall_thin")]
        return []

    # -------------------------------------------------- 功能与所属元件一致性
    def _check_use_element(self, row: Dict[str, Any]) -> List[Issue]:
        func = str(row.get("管口功能") or "").strip()
        elem = str(row.get("管口所属元件") or "").strip()
        out: List[Issue] = []

        if func and func not in spec.FUNCTION_VALUES:
            out.append(Issue("管口功能", "error", f"管口功能「{func}」不在允许取值内",
                             f"可选：{'、'.join(spec.FUNCTION_VALUES)}", "func_unknown"))
            return out

        # 功能决定程别：管程接管不能挂在壳体元件上，反之亦然
        process = spec.PROCESS_OF_USE.get(func)
        if process and elem:
            if process == "管程" and elem in spec.SHELL_SIDE_ELEMENTS:
                out.append(Issue("管口所属元件", "error",
                                 f"「{func}」属于管程，不能开在壳体侧元件「{elem}」上",
                                 "管程接管应挂在 管箱圆筒 / 管箱封头", "use_elem_tube"))
            if process == "壳程" and elem in spec.TUBE_SIDE_ELEMENTS:
                out.append(Issue("管口所属元件", "error",
                                 f"「{func}」属于壳程，不能开在管箱侧元件「{elem}」上",
                                 "壳程接管应挂在 壳体圆筒 / 壳体封头", "use_elem_shell"))
        return out

    # ---------------------------------------------------------------- 位置
    def _check_position(self, row: Dict[str, Any]) -> List[Issue]:
        out: List[Issue] = []

        def num(key):
            v = row.get(key)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        az = num("周向方位(°)")
        if az is not None and not (0 <= az <= 360):
            out.append(Issue("周向方位(°)", "error", f"周向方位 {az:g}° 超出 0~360° 范围",
                             "方位角按顺时针计量，0 与 360 等价", "az_range"))
        ang = num("轴向夹角")
        if ang is not None and not (0 <= ang <= 180):
            out.append(Issue("轴向夹角", "error", f"轴向夹角 {ang:g}° 超出 0~180° 范围",
                             "轴向夹角描述接管中心线与筒体轴线的夹角，取 0~180°", "ang_range"))
        ecc = num("偏心距")
        if ecc is not None and ecc < 0:
            out.append(Issue("偏心距", "error", "偏心距不能为负值", "填 0 表示正对接管", "ecc_neg"))
        ext = num("外伸高度")
        dn = num("公称尺寸")
        if ext is not None and ext < 0:
            out.append(Issue("外伸高度", "error", "外伸高度不能为负值", "填 0 表示不伸出", "ext_neg"))
        if ext is not None and dn is not None and ext >= 0:
            thk = spec.FLANGE_THK_PN16.get(int(dn)) if dn in spec.FLANGE_THK_PN16 or dn in [float(k) for k in spec.FLANGE_THK_PN16] else None
            if thk and ext < thk:
                out.append(Issue("外伸高度", "error",
                                 f"外伸高度 {ext:g} mm 小于法兰厚度 {thk} mm，法兰装不上去",
                                 f"至少取 {thk} mm，考虑保温与螺母空间建议 ≥ {thk + 40} mm", "ext_short"))
            elif thk and ext < thk + 40:
                out.append(Issue("外伸高度", "warning",
                                 f"外伸高度 {ext:g} mm 装法兰后余量偏小",
                                 f"考虑保温层与扳手空间，建议 ≥ {thk + 40} mm", "ext_tight"))
        loc = num("轴向定位距离")
        if loc is not None and loc < 0:
            out.append(Issue("轴向定位距离", "error", "轴向定位距离不能为负值", "以基准面为 0 向一侧为正", "loc_neg"))
        return out

    # -------------------------------------------------------------- 辅助判断
    @staticmethod
    def has_error(issues: List[Issue]) -> bool:
        return any(i.level == "error" for i in issues)

    @staticmethod
    def bad_fields(issues: List[Issue]) -> List[str]:
        return sorted({i.field for i in issues if i.level == "error"})

    @staticmethod
    def warn_fields(issues: List[Issue]) -> List[str]:
        return sorted({i.field for i in issues if i.level == "warning"})
