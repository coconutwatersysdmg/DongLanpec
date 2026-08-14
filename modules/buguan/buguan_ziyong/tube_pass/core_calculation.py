# core_calculation.py
import math

EPS = 1e-9
MAX_LOOP = 5000


def compute_centers(
    Cat,
    D: float,
    Snv: float,
    Snh: float,
    Wx0: float,
    Wx1: float,
    Wy0: float,
    Wy1: float,
    Wy2: float,
    S: float,
    d: float,
    Layout: str,
    Arr: int,
    Cut: str,
):
    # ---------- 2.1 角度换算 ----------
    if Arr == 30 and Cut == "HUD":
        Ang = 60
    elif Arr == 60 and Cut == "HUD":
        Ang = 30
    else:
        Ang = Arr
    rad = math.pi / 180

    # ---------- 2.2 圆心行间距dv、同行间距dh ----------
    if Ang in (30, 45):
        dh = 2 * S * math.cos(Ang * rad)
    else:
        dh = S
    if Ang in (30, 45, 60):
        dv = S * math.sin(Ang * rad)
    else:
        dv = S

    # ---------- 2.3 大圆边界约束 ----------
    R_big = 0.5 * D
    r_small = 0.5 * d
    R = R_big - r_small  # 有效填充半径
    R_sq = R * R

    half_dh = 0.5 * dh
    half_Snh = 0.5 * Snh
    half_Snv = 0.5 * Snv

    OA = []
    
    # ---------- 初始化所有可能返回的变量 ----------
    RowAmax = 0.0
    RowBmax = 0.0
    RowCmax = 0.0
    ColAmax = 0.0
    ColCmax = 0.0

    # ---------- 辅助函数 ----------
    def generate_row(xs, y, x_limit=None, y_limit=None, check_x_min=False, x_min=0.0):
        m = 0
        while m < MAX_LOOP:
            xm = xs + m * dh

            if x_limit is not None and xm > x_limit + EPS:
                break

            if check_x_min and xm < x_min - EPS:
                m += 1
                continue

            if y_limit is not None and y > y_limit + EPS:
                break

            if xm * xm + y * y > R_sq + EPS:
                break

            OA.append([xm, y])
            m += 1

    # ---------- xstart规则函数 ----------
    def xstart_rule_A(odd_row):
        """RegionA xstart规则（从0开始）"""
        if Ang in (30, 45, 60):
            if Layout == "S":
                return half_dh if odd_row else 0.0
            else:
                return 0.0 if odd_row else half_dh
        else:
            return half_dh if Layout == "S" else 0.0

    def xstart_rule_Snh(odd_row):
        """基于Snh的xstart规则（从0.5*Snh开始）"""
        if Ang in (30, 45, 60):
            if Layout == "C":
                return half_Snh if odd_row else (half_Snh + half_dh)
            else:
                return (half_Snh + half_dh) if odd_row else half_Snh
        else:
            return half_Snh

    def xstart_rule_Snh_xmin(odd_row):
        """12c专用：基于Snh的xstart规则，带x下限检查"""
        if Ang in (30, 45, 60):
            if Layout == "C":
                return half_Snh if odd_row else (half_Snh + half_dh)
            else:
                return (half_Snh + half_dh) if odd_row else half_Snh
        else:
            return half_Snh

    # ---------- 按 Cat 生成 ----------
    if Cat == 1 or Cat == "1":
        # Cat=1: 从y=0开始
        k = 0
        while True:
            yk = k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == 2 or Cat == "2":
        # Cat=2: 从y=0.5*Snv开始
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "4a":
        # RegionA: y从0.5*Snv开始，到Wy0-0.5*Snv
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionB: y从Snv+RowAmax开始，到R
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "4b":
        # RegionA: y从0.5*Snv开始，x从0.5*Snh开始
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = half_Snh if odd else half_Snh + half_dh
                else:
                    xs = half_Snh + half_dh if odd else half_Snh
            else:
                xs = half_Snh
            generate_row(xs, yk, check_x_min=True, x_min=half_Snh)
            k += 1

    elif Cat == "4c":
        # RegionA: y从0开始，到Wy0-0.5*Snv
        k = 0
        while True:
            yk = k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionB: y从Snv+RowAmax开始，到R
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "6a":
        # RegionA: y从0.5*Snv开始，到Wy0-0.5*Snv
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionB: y从Snv+RowAmax开始，到R
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "6b":
        # RegionA: y从0开始，到Wy0-0.5*Snv
        k = 0
        while True:
            yk = k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionB: y从Snv+RowAmax开始，到R
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "8a":
        # RegionA: y从0.5*Snv开始，到Wy0-0.5*Snv，x到Wx0-0.5*Snh
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk, x_limit=Wx0 - half_Snh)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        ColAmax = max([p[0] for p in OA]) if OA else 0.0
        # RegionB: 从x=Snh+ColAmax开始
        base_x = Snh + ColAmax
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = base_x if odd else base_x + half_dh
                else:
                    xs = base_x + half_dh if odd else base_x
            else:
                xs = base_x
            generate_row(xs, yk, x_limit=R)
            k += 1
        # RegionC: y从Snv+RowAmax开始，到R
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "8b":
        # RegionA: y从0.5*Snv开始，x到Wx0-0.5*Snh
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk, x_limit=Wx0 - half_Snh)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        ColAmax = max([p[0] for p in OA]) if OA else 0.0
        # RegionB: 从x=Snh+ColAmax开始，y上限受大圆限制
        base_x = Snh + ColAmax
        y_max_B = math.sqrt(R_sq - base_x * base_x) if base_x < R else 0.0
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > y_max_B + EPS or yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = base_x if odd else base_x + half_dh
                else:
                    xs = base_x + half_dh if odd else base_x
            else:
                xs = base_x
            generate_row(xs, yk, x_limit=R)
            k += 1
        # RegionC: y从Snv+RowAmax开始，x到ColAmax
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk, x_limit=ColAmax)
            k += 1

    elif Cat == "8c":
        # ===================== RegionA =====================
        # 第1行在y=0，范围: 0 ≤ y ≤ (Wy0-0.5*Snv)
        k = 0
        while True:
            yk = k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0

        # ===================== RegionB =====================
        # y从Snv+RowAmax开始，到Wy1-0.5*Snv
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > Wy1 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowBmax = max([p[1] for p in OA]) if OA else 0.0

        # ===================== RegionC =====================
        # y从Snv+RowBmax开始，到R，使用独立xstart规则
        k = 0
        y_start = Snv + RowBmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            # RegionC独立xstart规则
            if Ang in (30, 45, 60):
                if Layout == "S":
                    xs = half_dh if odd else 0.0
                else:
                    xs = 0.0 if odd else half_dh
            else:
                xs = half_dh if Layout == "S" else 0.0
            generate_row(xs, yk)
            k += 1

    elif Cat == "8d":
        # ===================== RegionA =====================
        # 范围: 0.5*Snv ≤ x ≤ R, 0 ≤ y ≤ (Wy0-0.5*Snv)
        k = 0
        y_limit_A = Wy0 - half_Snv
        while True:
            yk = half_Snv + k * dv
            if yk > y_limit_A + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = half_Snh if odd else half_Snh + half_dh
                else:
                    xs = half_Snh + half_dh if odd else half_Snh
            else:
                xs = half_Snh
            generate_row(xs, yk, x_limit=R, y_limit=y_limit_A, check_x_min=True, x_min=half_Snv)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0

        # ===================== RegionB =====================
        # 范围: 0.5*Snv ≤ x ≤ R, (Snv+RowAmax) ≤ y ≤ R
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = half_Snh if odd else half_Snh + half_dh
                else:
                    xs = half_Snh + half_dh if odd else half_Snh
            else:
                xs = half_Snh
            generate_row(xs, yk, x_limit=R, y_limit=R, check_x_min=True, x_min=half_Snv)
            k += 1

    elif Cat == "10a":
        # RegionA: y从0.5*Snv开始，x到Wx0-0.5*Snh
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk, x_limit=Wx0 - half_Snh)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        ColAmax = max([p[0] for p in OA]) if OA else 0.0
        # RegionB
        base_x = Snh + ColAmax
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = base_x if odd else base_x + half_dh
                else:
                    xs = base_x + half_dh if odd else base_x
            else:
                xs = base_x
            generate_row(xs, yk, x_limit=R)
            k += 1
        # RegionC
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "10b":
        # RegionA: y从0.5*Snv开始
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionB
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > Wy1 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowBmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionC
        k = 0
        y_start = Snv + RowBmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "12a":
        # RegionA
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk, x_limit=Wx0 - half_Snh)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        ColAmax = max([p[0] for p in OA]) if OA else 0.0
        # RegionB
        base_x = Snh + ColAmax
        k = 0
        while True:
            yk = half_Snv + k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = base_x if odd else base_x + half_dh
                else:
                    xs = base_x + half_dh if odd else base_x
            else:
                xs = base_x
            generate_row(xs, yk, x_limit=R)
            k += 1
        # RegionC
        y_start = Snv + RowAmax
        k = 0
        OE = []
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            m = 0
            while m < MAX_LOOP:
                xm = xs + m * dh
                if xm > Wx1 - half_Snh + EPS:
                    break
                if xm * xm + yk * yk > R_sq + EPS:
                    break
                OE.append([xm, yk])
                m += 1
            k += 1
        ColCmax = max([p[0] for p in OE]) if OE else 0.0
        OA.extend(OE)
        # RegionD
        base_x = Snh + ColCmax
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            if Ang in (30, 45, 60):
                if Layout == "S":
                    xs = base_x + half_dh if odd else base_x
                else:
                    xs = base_x if odd else base_x + half_dh
            else:
                xs = base_x
            generate_row(xs, yk, x_limit=R)
            k += 1

    elif Cat == "12b":
        # RegionA: y从0开始
        k = 0
        while True:
            yk = k * dv
            if yk > Wy0 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowAmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionB
        k = 0
        y_start = Snv + RowAmax
        while True:
            yk = y_start + k * dv
            if yk > Wy1 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowBmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionC
        k = 0
        y_start = Snv + RowBmax
        while True:
            yk = y_start + k * dv
            if yk > Wy2 - half_Snv + EPS:
                break
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_Snh(odd)
            generate_row(xs, yk)
            k += 1
        RowCmax = max([p[1] for p in OA]) if OA else 0.0
        # RegionD
        k = 0
        y_start = Snv + RowCmax
        while True:
            yk = y_start + k * dv
            if yk > R + EPS:
                break
            odd = (k % 2 == 0)
            xs = xstart_rule_A(odd)
            generate_row(xs, yk)
            k += 1

    elif Cat == "12c":
        # ===================== RegionA 点位生成 =====================
        y_max_A = Wy0 - half_Snv
        k = 0
        while k < MAX_LOOP:
            yk = half_Snv + k * dv
            if yk > y_max_A + EPS:
                break
            is_odd_row = (k % 2 == 0)
            # A xstart规则
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = half_Snh if is_odd_row else (half_Snh + half_dh)
                else:
                    xs = (half_Snh + half_dh) if is_odd_row else half_Snh
            else:
                xs = half_Snh
            m = 0
            while m < MAX_LOOP:
                xm = xs + m * dh
                # 区域x下限约束
                if xm < half_Snv - EPS:
                    m += 1
                    continue
                if xm > R + EPS:
                    break
                # 大圆边界约束
                if xm ** 2 + yk ** 2 > R_sq + EPS:
                    break
                OA.append([xm, yk])
                m += 1
            k += 1
        RowAmax = max([p[1] for p in OA]) if len(OA) > 0 else 0.0

        # ===================== RegionB 点位生成 =====================
        y_start_B = Snv + RowAmax
        k = 0
        while k < MAX_LOOP:
            yk = y_start_B + k * dv
            if yk > Wy1-0.5*Snv + EPS:  # 是Wy1
                break
            is_odd_row = (k % 2 == 0)
            # B xstart同A
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = half_Snh if is_odd_row else (half_Snh + half_dh)
                else:
                    xs = (half_Snh + half_dh) if is_odd_row else half_Snh
            else:
                xs = half_Snh
            m = 0
            while m < MAX_LOOP:
                xm = xs + m * dh
                if xm < half_Snv - EPS:
                    m += 1
                    continue
                if xm > R + EPS:
                    break
                if xm ** 2 + yk ** 2 > R_sq + EPS:
                    break
                OA.append([xm, yk])
                m += 1
            k += 1
        RowBmax = max([p[1] for p in OA]) if len(OA) > 0 else 0.0

        # ===================== RegionC 点位生成（xstart与A/B统一） =====================
        y_start_C = Snv + RowBmax
        k = 0
        while k < MAX_LOOP:
            yk = y_start_C + k * dv
            if yk > R + EPS:
                break
            is_odd_row = (k % 2 == 0)
            # C xstart与A/B完全一致
            if Ang in (30, 45, 60):
                if Layout == "C":
                    xs = half_Snh if is_odd_row else (half_Snh + half_dh)
                else:
                    xs = (half_Snh + half_dh) if is_odd_row else half_Snh
            else:
                xs = half_Snh
            m = 0
            while m < MAX_LOOP:
                xm = xs + m * dh
                if xm < half_Snv - EPS:
                    m += 1
                    continue
                if xm > R + EPS:
                    break
                if xm ** 2 + yk ** 2 > R_sq + EPS:
                    break
                OA.append([xm, yk])
                m += 1
            k += 1

    # ---------- 列表处理 ----------
    OB = [[-x, y] for x, y in OA if abs(x) > EPS]
    OC = OA + OB
    OD = [[x, -y] for x, y in OC if abs(y) > EPS]
    XY_raw = OC + OD

    # 3位小数去重
    seen = set()
    XY = []
    for x, y in XY_raw:
        rx = round(x, 3)
        ry = round(y, 3)
        key = (rx, ry)
        if key not in seen:
            seen.add(key)
            XY.append([x, y])

    return {
        "XY": XY,
        "ColAmax": ColAmax if ColAmax != 0.0 else None,
        "ColCmax": ColCmax if ColCmax != 0.0 else None,
        "RowAmax": RowAmax if RowAmax != 0.0 else None,
        "RowBmax": RowBmax if RowBmax != 0.0 else None,
        "RowCmax": RowCmax if RowCmax != 0.0 else None,
        "R": R,
        "R_big": R_big,
        "d": d,
        "D": D,
        "dh": dh,
        "dv": dv,
        "Ang": Ang,
        "S": S,
    }