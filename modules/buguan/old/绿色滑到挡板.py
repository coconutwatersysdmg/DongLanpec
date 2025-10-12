# # 滑道功能（调用接口）
    # def on_green_slide_click(self):
    #     """从接口获取滑道坐标并绘制绿色滑道"""
    #     # 1) 读参数
    #     DL = None
    #     do = None
    #     table = self.param_table

    #     # 清空之前的数据
    #     self.left_data_pd = pd.DataFrame(columns=["参数名", "参数值"])

    #     for row in range(table.rowCount()):
    #         param_name = table.item(row, 1).text()  # 第1列是参数名
    #         param_value = table.cellWidget(row, 2)

    #         if param_value and isinstance(param_value, QComboBox):
    #             param_value = param_value.currentText()  # 如果是QComboBox，下拉选的值
    #         else:
    #             item = table.item(row, 2)
    #             if item:
    #                 param_value = item.text()  # 如果是普通文本
    #             else:
    #                 param_value = ""  # 如果空着，也不要报错

    #         # 保存到列表
    #         new_row = {
    #             "参数名": param_name,
    #             "参数值": param_value
    #         }
    #         self.left_data_pd = pd.concat([self.left_data_pd, pd.DataFrame([new_row])], ignore_index=True)

    #         if param_name == "壳体内直径 Di":
    #             try:
    #                 DL = float(param_value)
    #             except:
    #                 pass
    #         elif param_name == "换热管外径 do":
    #             try:
    #                 do = float(param_value)
    #                 self.r = float(do / 2)
    #             except:
    #                 pass

    #     if DL is None:
    #         QMessageBox.warning(self, "提示", "请先填写'壳体内直径 Di'参数。")
    #         return
    #     if do is None:
    #         QMessageBox.warning(self, "提示", "请先填写'换热管外径 do'参数。")
    #         return

    #     # 构造 JSON 映射字典
    #     param_mapping = {
    #         "换热管布置方式": ("LB_IsRangeCenter", {"对中": "0", "跨中": "1", "任意": "2"}),
    #         "旁路挡板厚度": ("LB_BPBThick", None),
    #         "分程隔板两侧相邻管中心距": ("LB_SN", None),
    #         "热交换器类型": ("LB_HEType", None),
    #         "分程隔板两侧相邻管中心距（水平）": ("LB_SNH", None),
    #         "滑道高度": ("LB_SlipWayHeight", None),
    #         "滑道厚度": ("LB_SlipWayThick", None),
    #         "滑道与竖直中心线夹角": ("LB_SlipWayAngle", None),
    #         "拉杆直径": ("LB_TieRodD", None),
    #         "管程程数": ("LB_TubePassCount", None),
    #         "热交换器类型": ("LB_HEType", None),
    #         "公称直径 DN": ("LB_DN", None),
    #         "壳体内直径 Di": ("LB_Di", None),
    #         "布管限定圆 DL": ("LB_DL", None),
    #         "换热管孔需求数量": ("LB_TotalTubesCountNeed", None),
    #         "换热管外径 do": ("LB_TubeD", None),
    #         "换热管壁厚 δ": ("LB_TubeThick", None),
    #         "换热管排列方式": (
    #             "LB_RangeType", {"正三角形": "0", "转角正三角形": "1", "正方形": "2", "转角正方形": "3"}),
    #         "换热管公称长度 LN": ("LB_TubeLong", None),
    #         "换热管中心距 S": ("LB_S", None),
    #         "折流板切口方向": ("LB_BaffleDirection", {"水平上下": "1", "垂直左右": "2"}),
    #         "折流板要求切口率 (%)": ("LB_BafflePerStr", None),
    #         "折流/支持板间距": ("LB_BaffleToODistance", None),
    #         "折流板外径": ("LB_BaffleOD", None),
    #         "分程隔板两侧相邻管中心距Sn（竖直）": ("LB_SNH", None),
    #         "分程隔板两侧相邻管中心距Sn（竖直）": ("LB_SN", None),
    #         "拉杆直径": ("LB_TieRodD", None),
    #         "分程隔板放置型式": ("LB_ClapboardType", {"未选择": "0", "形式1": "1", "形式2": "2", "形式3": "3"})
    #     }

    #     input_json = {}
    #     for _, row in self.left_data_pd.iterrows():
    #         param_name = row["参数名"]
    #         param_value = str(row["参数值"]).strip()

    #         if param_name in param_mapping:
    #             json_key, value_map = param_mapping[param_name]
    #             if value_map:
    #                 # 处理映射值
    #                 mapped_value = value_map.get(param_value, "0")  # 默认为 0
    #                 input_json[json_key] = mapped_value
    #             else:
    #                 # 直接使用原始值
    #                 input_json[json_key] = param_value

    #     # 测试
    #     # with open(r"buguan_api\input.json", "r", encoding="utf-8") as file:
    #     #     input_json = json.load(file)  # 解析 JSON
    #     # print("input_json：", input_json)

    #     # 确保必要参数存在
    #     if "LB_TubeD" not in input_json:
    #         input_json["LB_TubeD"] = str(do)
    #     if "LB_Di" not in input_json:
    #         input_json["LB_Di"] = str(DL)

    #     # 特殊处理：拉杆直径默认等于换热管外径
    #     if "LB_TieRodD" not in input_json:
    #         input_json["LB_TieRodD"] = input_json.get("LB_TubeD", str(do))

    #     # 清除上次绘制的滑道图形项
    #     for item in getattr(self, "green_slide_items", []):
    #         self.graphics_scene.removeItem(item)
    #     self.green_slide_items = []

    #     # # 打开文件
    #     # with open(r"buguan_api/input.json", "r", encoding="utf-8") as file:
    #     #     input_json = json.load(file)  # 解析 JSON
    #     # print("input_json：", input_json)

    #     try:
    #         # 调用接口获取滑道数据
    #         response = run_layout_tube_calculate(json.dumps(input_json, indent=2, ensure_ascii=False))

    #         # 检查响应是否为字典类型
    #         if not isinstance(response, dict):
    #             try:
    #                 # 尝试解析为JSON
    #                 response = json.loads(response)
    #             except:
    #                 raise Exception(f"接口返回无效格式: {type(response)}")

    #         # 1. 检查错误信息
    #         if "错误" in response:
    #             error_msg = response.get("错误", "未知错误")
    #             raise Exception(f"接口返回错误: {error_msg}")

    #         # 2. 检查是否有错误信息在顶层
    #         if "错误" in response.get("message", "") or "错误" in response.get("error", ""):
    #             error_msg = response.get("message", response.get("error", "未知错误"))
    #             raise Exception(f"接口错误: {error_msg}")

    #         # 3. 获取滑道数据 (修正数据结构)
    #         slip_ways = response.get("SlipWays", [])
    #         if not slip_ways:
    #             # 检查是否有其他可能的键名
    #             for key in ["SlipWays", "slide_ways", "滑道"]:
    #                 if key in response:
    #                     slip_ways = response[key]
    #                     break

    #             if not slip_ways:
    #                 # 尝试从顶层直接获取滑道数据
    #                 if "P1" in response and "P2" in response and "P3" in response and "P4" in response:
    #                     slip_ways = [response]
    #                 else:
    #                     raise Exception("接口未返回滑道数据")

    #         # 4. 遍历滑道数据
    #         for slide in slip_ways:
    #             # 确保坐标点是数字类型
    #             points = []
    #             for point_key in ["P1", "P2", "P3", "P4"]:
    #                 if point_key in slide:
    #                     point_data = slide[point_key]
    #                     try:
    #                         x = float(point_data.get("X", 0))
    #                         y = float(point_data.get("Y", 0))
    #                         points.append((x, y))
    #                     except:
    #                         # 尝试不同的键名格式
    #                         try:
    #                             x = float(point_data.get("x", point_data.get("X", 0)))
    #                             y = float(point_data.get("y", point_data.get("Y", 0)))
    #                             points.append((x, y))
    #                         except:
    #                             raise Exception(f"无效的坐标数据: {point_data}")

    #             if len(points) != 4:
    #                 # 尝试从字典中直接获取点
    #                 if len(points) < 4:
    #                     for i in range(1, 5):
    #                         point_key = f"P{i}"
    #                         if point_key in slide:
    #                             point_data = slide[point_key]
    #                             try:
    #                                 x = float(point_data.get("X", 0))
    #                                 y = float(point_data.get("Y", 0))
    #                                 points.append((x, y))
    #                             except:
    #                                 pass

    #                 if len(points) != 4:
    #                     raise Exception(f"滑道点数量不足: 期望4个点, 实际{len(points)}个点")

    #             # 创建多边形
    #             polygon = QPolygonF([QPointF(x, y) for x, y in points])
    #             item = QGraphicsPolygonItem(polygon)
    #             item.setBrush(QColor(0, 100, 0))  # 深绿色
    #             item.setPen(QPen(Qt.NoPen))
    #             self.graphics_scene.addItem(item)
    #             self.green_slide_items.append(item)

    #         QMessageBox.information(self, "滑道绘制", f"已成功绘制 {len(slip_ways)} 个滑道")

    #         # 添加操作记录
    #         if not hasattr(self, 'operations'):
    #             self.operations = []

    #         self.operations.append({
    #             "type": "huadao",
    #             "source": "api",
    #             "slide_count": len(slip_ways),
    #             "params": input_json
    #         })

    #     except Exception as e:
    #         # 记录详细错误信息
    #         error_details = traceback.format_exc()
    #         logging.error(f"绘制滑道失败: {error_details}")

    #         QMessageBox.warning(
    #             self,
    #             "错误",
    #             f"绘制滑道失败：{str(e)}\n\n"
    #             f"输入参数：\n{json.dumps(input_json, indent=2)}\n\n"
    #             f"请检查参数是否正确并重试。"
    #         )