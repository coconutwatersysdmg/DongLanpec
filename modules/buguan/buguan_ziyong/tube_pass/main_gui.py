# gui_app.py
import math
import tkinter as tk
from tkinter import ttk, scrolledtext
from collections import defaultdict

from core_calculation import compute_centers

# 精度常量
EPS = 1e-9
DRAW_EPS = 1e-6


class MainWindow:
    def __init__(self, root):
        self.root = root
        root.title("小圆填充计算工具")
        root.geometry("1750x920")
        root.resizable(True, True)
        PANEL_RIGHT_WIDTH = 300

        # 全局绘图缓存
        self.all_xy = []
        self.dh_g = 0.0
        self.dv_g = 0.0
        self.ang_g = 0.0
        self.s_dist = 0.0
        self.scale = 2.5
        self.min_scale = 0.3
        self.max_scale = 12.0
        self.off_x = 0
        self.off_y = 0
        self.D_global = 0.0
        self.R_global = 0.0
        self.d_global = 0.0

        # 主布局
        main_frame = ttk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        left_container = ttk.Frame(main_frame)
        right_panel = ttk.Frame(main_frame, width=PANEL_RIGHT_WIDTH)
        right_panel.pack_propagate(False)
        left_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH)

        # 顶部参数输入栏
        input_bar = ttk.Frame(left_container, padding=6)
        input_bar.pack(fill=tk.X)
        input_items = [
            ("Cat", "combo", "Cat", "1", ["1", "2", "4a", "4b", "4c", "6a", "6b", "8a", "8b", "8c", "8d", "10a", "10b", "12a", "12b", "12c"]),
            ("D (mm)", "entry", "D", "800"),
            ("Snv", "entry", "Snv", "40"),
            ("Snh", "entry", "Snh", "40"),
            ("Wy0", "entry", "Wy0", "120"),
            ("Wy1", "entry", "Wy1", "210"),
            ("Wy2", "entry", "Wy2", "300"),
            ("Layout", "combo", "Layout", "C", ["C", "S"]),
            ("Arr", "combo", "Arr", "60", ["30", "45", "60", "90"]),
            ("Cut", "combo", "Cut", "VSR", ["HUD", "VSR"]),
            ("S (mm)", "entry", "S", "25"),
            ("d (mm)", "entry", "d", "19"),
            ("Wx0", "entry", "Wx0", "100"),
            ("Wx1", "entry", "Wx1", "200"),
        ]
        self.widgets = {}
        col = 0
        for item in input_items:
            lbl_text, w_type, key, default, *opts = item
            ttk.Label(input_bar, text=lbl_text).grid(row=0, column=col, padx=3)
            if w_type == "entry":
                w = ttk.Entry(input_bar, width=8)
                w.insert(0, default)
            else:
                w = ttk.Combobox(input_bar, width=8, values=opts[0], state="readonly")
                w.set(default)
            self.widgets[key] = w
            w.grid(row=0, column=col+1, padx=3)
            col += 2

        # 功能按钮
        btn_calc = ttk.Button(input_bar, text="计算并绘图")
        btn_fit_view = ttk.Button(input_bar, text="⤸ 视图重置")
        btn_calc.grid(row=0, column=col, padx=6)
        btn_fit_view.grid(row=0, column=col+1, padx=6)

        # 画布与右侧结果文本框
        self.canvas = tk.Canvas(left_container, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.txt_result = scrolledtext.ScrolledText(right_panel)
        self.txt_result.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # 画布拖拽、滚轮缩放绑定
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.canvas.bind("<Button-1>", self.mouse_down)
        self.canvas.bind("<B1-Motion>", self.mouse_drag)
        self.canvas.bind("<MouseWheel>", self.mouse_wheel)
        self.canvas.bind("<Button-4>", self.mouse_wheel)
        self.canvas.bind("<Button-5>", self.mouse_wheel)

        btn_fit_view.config(command=self.fit_view)
        btn_calc.config(command=self.calc_and_draw)

        # Cat变化时灰化输入框
        self.widgets["Cat"].bind('<<ComboboxSelected>>', self.on_cat_changed)
        self.on_cat_changed(None)

    def on_cat_changed(self, event):
        """根据Cat灰化/锁定输入框"""
        cat = self.widgets["Cat"].get()
        # 判断哪些参数可用
        wx0_enabled = cat in ["8a", "8b", "10a", "12a"]
        wx1_enabled = cat in ["12a"]
        wy0_enabled = cat in ["4a", "4c", "6a", "6b", "8a", "8b", "8c", "8d", "10a", "10b", "12a", "12b", "12c"]
        wy1_enabled = cat in ["8c", "10b", "12b", "12c"]
        wy2_enabled = cat in ["12b"]

        entries = [
            (self.widgets["Wx0"], wx0_enabled),
            (self.widgets["Wx1"], wx1_enabled),
            (self.widgets["Wy0"], wy0_enabled),
            (self.widgets["Wy1"], wy1_enabled),
            (self.widgets["Wy2"], wy2_enabled),
        ]
        for entry, enabled in entries:
            if enabled:
                entry.config(state='normal')
            else:
                entry.config(state='disabled')

    def mouse_down(self, event):
        self.drag_start_x, self.drag_start_y = event.x, event.y

    def mouse_drag(self, event):
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        self.off_x += dx
        self.off_y += dy
        self.drag_start_x, self.drag_start_y = event.x, event.y
        self.refresh_draw()

    def mouse_wheel(self, event):
        delta = 0.1
        if event.num == 4:
            self.scale += delta
        elif event.num == 5:
            self.scale -= delta
        else:
            self.scale += event.delta // 120 * delta
        self.scale = max(self.min_scale, min(self.max_scale, self.scale))
        self.refresh_draw()

    def fit_view(self):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 50 or ch < 50 or self.D_global < EPS:
            self.scale = 2.5
            self.off_x = 0
            self.off_y = 0
            self.refresh_draw()
            return
        margin = 100
        avail_w = cw - margin * 2
        avail_h = ch - margin * 2
        half_r = self.R_global
        s_w = avail_w / (half_r * 2)
        s_h = avail_h / (half_r * 2)
        fit_s = min(s_w, s_h)
        self.scale = max(self.min_scale, min(self.max_scale, fit_s))
        self.off_x = 0
        self.off_y = 0
        self.refresh_draw()

    def calc_and_draw(self):
        self.txt_result.delete(1.0, tk.END)
        self.canvas.delete(tk.ALL)

        try:
            Cat = self.widgets["Cat"].get()
            Cat = int(Cat) if Cat.isdigit() else Cat

            D = float(self.widgets["D"].get())
            Snv = float(self.widgets["Snv"].get())
            Snh = float(self.widgets["Snh"].get())
            Wy0 = float(self.widgets["Wy0"].get())
            Wy1 = float(self.widgets["Wy1"].get())
            Wy2 = float(self.widgets["Wy2"].get())
            Wx0 = float(self.widgets["Wx0"].get())
            Wx1 = float(self.widgets["Wx1"].get())
            Layout = self.widgets["Layout"].get()
            Arr = int(self.widgets["Arr"].get())
            Cut = self.widgets["Cut"].get()
            S = float(self.widgets["S"].get())
            d = float(self.widgets["d"].get())
        except Exception as e:
            self.txt_result.insert(tk.END, f"参数输入错误：{str(e)}\n请输入有效数字")
            return

        if D <= 0 or S <= 0 or d <= 0 or Snv < 0 or Snh < 0:
            self.txt_result.insert(tk.END, "错误：D/S/d必须大于0，Snv/Snh不可为负数")
            return
        if D <= d:
            self.txt_result.insert(tk.END, "错误：大圆直径D必须大于小圆直径d")
            return

        result = compute_centers(
            Cat=Cat,
            D=D,
            Snv=Snv,
            Snh=Snh,
            Wx0=Wx0,
            Wx1=Wx1,
            Wy0=Wy0,
            Wy1=Wy1,
            Wy2=Wy2,
            S=S,
            d=d,
            Layout=Layout,
            Arr=Arr,
            Cut=Cut,
        )

        XY = result["XY"]
        self.all_xy = XY
        self.D_global = D
        self.R_global = result["R"]
        self.d_global = d
        self.dh_g = result["dh"]
        self.dv_g = result["dv"]
        self.ang_g = result["Ang"]
        self.s_dist = S

        # ---- 统计信息 ----
        Nt = len(XY)
        half_Snv = 0.5 * Snv
        half_Snh = 0.5 * Snh

        info = f"总点数 Nt = {Nt}\n"
        info += "-" * 30 + "\n"

        # 宽度校验
        if result.get("ColAmax") is not None:
            WXA = half_Snh + result["ColAmax"]
            if abs(WXA - Wx0) > 1e-4:
                info += f"程序已按Snh要求修正输入Wx0值：{Wx0:.3f} → {WXA:.3f}\n"
        if result.get("ColCmax") is not None:
            WXB = half_Snh + result["ColCmax"]
            if abs(WXB - Wx1) > 1e-4:
                info += f"程序已按Snh要求修正输入Wx1值：{Wx1:.3f} → {WXB:.3f}\n"

        # 高度校验
        if result.get("RowAmax") is not None:
            WYA = half_Snv + result["RowAmax"]
            if abs(WYA - Wy0) > 1e-4:
                info += f"程序已按Snv要求修正输入Wy0值：{Wy0:.3f} → {WYA:.3f}\n"
        if result.get("RowBmax") is not None:
            WYB = half_Snv + result["RowBmax"]
            if abs(WYB - Wy1) > 1e-4:
                info += f"程序已按Snv要求修正输入Wy1值：{Wy1:.3f} → {WYB:.3f}\n"
        if result.get("RowCmax") is not None:
            WYC = half_Snv + result["RowCmax"]
            if abs(WYC - Wy2) > 1e-4:
                info += f"程序已按Snv要求修正输入Wy2值：{Wy2:.3f} → {WYC:.3f}\n"

        # 行统计
        rows = defaultdict(int)
        for x, y in XY:
            rows[round(y, 3)] += 1
        RN = len(rows)
        info += f"\n总行数 RN = {RN}\n"
        info += "每行小圆数量 (按y分组):\n"
        for y, count in sorted(rows.items()):
            info += f"  y={y:.3f}: {count}个\n"

        # 列统计
        cols = defaultdict(int)
        for x, y in XY:
            cols[round(x, 3)] += 1
        CN = len(cols)
        info += f"\n总列数 CN = {CN}\n"
        info += "每列小圆数量 (按x分组):\n"
        for x, count in sorted(cols.items()):
            info += f"  x={x:.3f}: {count}个\n"

        # 坐标列表
        info += "\n全部圆心坐标 (x, y):\n"
        for i, (x, y) in enumerate(XY):
            info += f"{i+1:5d} | x={x:.3f}, y={y:.3f}\n"

        self.txt_result.insert(tk.END, info)
        self.fit_view()

    def refresh_draw(self):
        self.canvas.delete(tk.ALL)
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        cx = cw / 2 + self.off_x
        cy = ch / 2 + self.off_y

        if not self.all_xy or self.R_global <= 0:
            return

        r_big_px = (self.D_global / 2) * self.scale
        r_small_px = (self.d_global / 2) * self.scale
        axis_ext = (self.D_global / 20) * self.scale

        # ---- 大圆（黑色轮廓，线宽2px） ----
        self.canvas.create_oval(cx - r_big_px, cy - r_big_px,
                                cx + r_big_px, cy + r_big_px,
                                outline="black", width=2)

        # ---- 坐标轴（蓝色#0000ff，延伸D/20，线宽2px） ----
        self.canvas.create_line(cx - r_big_px - axis_ext, cy,
                                cx + r_big_px + axis_ext, cy,
                                fill="#0000ff", width=2)
        self.canvas.create_line(cx, cy - r_big_px - axis_ext,
                                cx, cy + r_big_px + axis_ext,
                                fill="#0000ff", width=2)

        # ---- 计算Linexy ----
        if self.ang_g == 90:
            line_xy = self.s_dist
        else:
            rad = math.pi / 180
            line_xy = max(2 * math.cos(self.ang_g * rad), 2 * math.sin(self.ang_g * rad))

        # ---- 按y分组 ----
        y_group = {}
        for idx, (px, py) in enumerate(self.all_xy):
            ry = round(py, 3)
            if ry not in y_group:
                y_group[ry] = []
            y_group[ry].append((px, py, idx))

        y_list = sorted(y_group.keys())
        line_cache = set()

        # ---- 同行水平相邻连线 ----
        for yk in y_list:
            row = y_group[yk]
            for i in range(len(row) - 1):
                x1, y1, id1 = row[i]
                x2, y2, id2 = row[i + 1]
                dist = math.hypot(x1 - x2, y1 - y2)
                if abs(dist - self.dh_g) < DRAW_EPS:
                    pair = tuple(sorted([id1, id2]))
                    if pair not in line_cache:
                        line_cache.add(pair)
                        p1x = cx + x1 * self.scale
                        p1y = cy - y1 * self.scale
                        p2x = cx + x2 * self.scale
                        p2y = cy - y2 * self.scale
                        self.canvas.create_line(p1x, p1y, p2x, p2y,
                                                fill="#aaaaaa", width=0.5)

        # ---- 斜向/竖直相邻连线 ----
        for i in range(1, len(y_list)):
            y_prev = y_list[i - 1]
            y_curr = y_list[i]
            pts_prev = y_group[y_prev]
            pts_curr = y_group[y_curr]

            for x1, y1, id1 in pts_prev:
                for x2, y2, id2 in pts_curr:
                    dist = math.hypot(x1 - x2, y1 - y2)
                    dx = abs(x1 - x2)
                    dy = abs(y1 - y2)
                    pair = tuple(sorted([id1, id2]))
                    if pair in line_cache:
                        continue
                    if self.ang_g == 90:
                        # 90度竖直相邻判定
                        if abs(dy - self.dv_g) < DRAW_EPS and dx < DRAW_EPS * 2:
                            line_cache.add(pair)
                            p1x = cx + x1 * self.scale
                            p1y = cy - y1 * self.scale
                            p2x = cx + x2 * self.scale
                            p2y = cy - y2 * self.scale
                            self.canvas.create_line(p1x, p1y, p2x, p2y,
                                                    fill="#aaaaaa", width=0.5)
                    else:
                        # 30/45/60斜向相邻判定
                        if abs(dist - self.s_dist) < DRAW_EPS * 2 and \
                           abs(dx - self.dh_g/2) < DRAW_EPS * 2 and \
                           abs(dy - self.dv_g) < DRAW_EPS * 2:
                            line_cache.add(pair)
                            p1x = cx + x1 * self.scale
                            p1y = cy - y1 * self.scale
                            p2x = cx + x2 * self.scale
                            p2y = cy - y2 * self.scale
                            self.canvas.create_line(p1x, p1y, p2x, p2y,
                                                    fill="#aaaaaa", width=0.5)

        # ---- 绘制红色空心小圆 ----
        for px, py in self.all_xy:
            pix_x = cx + px * self.scale
            pix_y = cy - py * self.scale
            self.canvas.create_oval(pix_x - r_small_px, pix_y - r_small_px,
                                    pix_x + r_small_px, pix_y + r_small_px,
                                    outline="red", width=0.5)


def main():
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()