# -*- coding: utf-8 -*-
"""布管保存后，将计算得到的管板分程处面积 Ad 同步到元件定义。"""
from decimal import Decimal, InvalidOperation


PARAMETER_NAME = "管板分程处面积 Ad"
ELEMENT_NAME = "固定管板"
RECOMMENDED_VALUE = "程序推荐"
CALCULATION_NAME = "管板分程处面积Ad"
FIVE_PERCENT = Decimal("0.05")


def _as_nonnegative_decimal(value, label):
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise ValueError(f"{label}不是有效数值: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{label}必须是大于等于0的有限数值: {value!r}")
    return parsed


def _calculated_value_text(value):
    """与布管计算结果保持一致：四舍五入到小数点后 3 位。"""
    return str(round(float(value), 3))


def _matches_previous_calculation(stored_value, previous_calculated_value):
    """元件值与上次程序计算值一致时，仍按“程序推荐”状态处理。"""
    if previous_calculated_value is None:
        return False
    try:
        stored = _as_nonnegative_decimal(stored_value, "元件用户值")
        previous = _as_nonnegative_decimal(previous_calculated_value, "上次布管计算值")
    except ValueError:
        return False
    return _calculated_value_text(stored) == _calculated_value_text(previous)


def _difference_exceeds_five_percent(calculated_value, user_value):
    """按 abs(1 - 用户值 / 布管值) 判断，恰好 5% 不超限。"""
    if calculated_value == 0:
        return user_value > 0
    return abs(Decimal("1") - user_value / calculated_value) > FIVE_PERCENT


def get_previous_calculated_ad(connection, product_id):
    """读取本次保存覆盖前的布管 AD，用于识别持续的“程序推荐”状态。"""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 计算值
            FROM 产品设计活动表_布管计算结果表
            WHERE 产品ID = %s
              AND 计算值名称 = %s
            ORDER BY 计算ID DESC
            LIMIT 1
            """,
            (product_id, CALCULATION_NAME),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return row.get("计算值")


def sync_tube_sheet_ad(
    connection,
    product_id,
    calculated_value,
    confirm_update,
    previous_calculated_value=None,
):
    """
    更新当前产品已有的固定管板 Ad 参数行。

    ``confirm_update(calculated_text, user_text)`` 仅在自定义值差距超过 5%
    时调用并返回是否更新。缺少参数行时不补建，由元件定义模块负责建行。
    """
    calculated = _as_nonnegative_decimal(calculated_value, "布管计算值")
    calculated_text = _calculated_value_text(calculated)
    calculated = Decimal(calculated_text)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 元件附加参数ID, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = %s
              AND 参数名称 = %s
            ORDER BY 元件附加参数ID
            """,
            (product_id, ELEMENT_NAME, PARAMETER_NAME),
        )
        rows = cursor.fetchall() or []

    if not rows:
        return "missing"

    row = rows[0]
    stored_text = str(row.get("参数值") or "").strip()
    if stored_text == RECOMMENDED_VALUE or _matches_previous_calculation(
        stored_text, previous_calculated_value
    ):
        result = "updated_recommended"
    else:
        try:
            user_value = _as_nonnegative_decimal(stored_text, "元件用户值")
        except ValueError:
            return "invalid_user_value"

        if not _difference_exceeds_five_percent(calculated, user_value):
            return "kept_within_tolerance"
        if not confirm_update(calculated_text, stored_text):
            return "kept_by_user"
        result = "updated_by_user"

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE 产品设计活动表_元件附加参数表
            SET 参数值 = %s
            WHERE 产品ID = %s
              AND 元件附加参数ID = %s
            """,
            (calculated_text, product_id, row["元件附加参数ID"]),
        )
    connection.commit()
    return result
