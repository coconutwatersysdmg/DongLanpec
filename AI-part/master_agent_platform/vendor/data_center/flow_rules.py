"""Reviewed business semantics. These describe code, never executable bindings.

Paths/functions are resolved against the rebuildable source index. Row mappings
are deliberately narrower than table-level input/output documentation.
"""
from dataclasses import dataclass


def table(name):
    return '产品设计活动表_' + name + '表'


CDT = 'modules/condition_input/hrq_funcs_cdt_input.py'
PDF = 'modules/cailiaodingyi/funcs/funcs_pdf_change.py'
DM = 'modules/cailiaodingyi/controllers/datamanager.py'
PIPE = 'modules/guankoudingyi/funcs/funs_enter_key.py'
LAYOUT = 'modules/buguan/buguan_ziyong/My_Piping.py'
CALC = 'modules/qiangdujisuan/jiekou_python/combine_json_new.py'


@dataclass(frozen=True)
class InputRule:
    title: str
    module: str
    control: str
    target: str
    fields: tuple
    trigger: str
    path: str
    function: str
    mapping: str


INPUTS = [
    InputRule(title, '条件输入', control, table(title), fields,
              '确认 → check_and_save_data → save_all_tables', CDT, 'save_all_tables', mapping)
    for title, control, fields, mapping in (
        ('产品标准数据', 'tableWidget_product_std', ('规范/标准名称', '规范/标准代号'), '表格行 → 标准名称/代号；按产品ID保存'),
        ('设计数据', 'tableWidget_design_data', ('壳程数值', '管程数值'), '参数名称定位行；管程/壳程值分别保存，必填校验通过后写入'),
        ('通用数据', 'tableWidget_general_data', ('数值',), '参数名称定位行；数值含界面计算缓存，保存时整理'),
        ('无损检测数据', 'tableWidget_trail_data', ('接头种类', '检测方法', '壳程_技术等级', '壳程_检测比例', '壳程_合格级别', '管程_技术等级', '管程_检测比例', '管程_合格级别'), '接头种类/检测方法及两侧检测条件 → 同名列'),
        ('涂漆数据', 'tableWidget_coating_data', ('用途', '油漆类别', '颜色', '干膜厚度（μm）', '涂漆面积', '备注'), '涂漆表格 → 同名列；按产品ID保存'),
    )
] + [
    InputRule('元件参数', '元件定义', 'tableWidget_detail / tableWidget_para', table('元件附加参数'), ('参数值',),
              'pushButton_detail → on_confirm_param_update', PDF, 'update_param_table_data',
              '第0列参数名称、第1列值（单元格/下拉框）；产品ID + 元件ID + 参数名称'),
    InputRule('材料信息投影', '元件定义', 'tableWidget_detail / tableWidget_para', table('元件材料'), ('材料类型', '材料牌号', '材料标准', '供货状态', '定义状态'),
              '元件参数确认', PDF, 'update_left_table_db_from_param_table',
              '参数名别名取首个非空值；材料信息投影到左表；定义状态由必填项判定'),
    InputRule('合并元件参数', '元件定义', 'tabWidget_2 / dynamic_element_merged_para_tabs[当前Tab]', table('元件附加参数合并'), ('参数值',),
              'pushButton_fixed_saddle_confirm → on_confirm_element_merged_para_param', DM, 'update_element_merged_para_tab_data_from_table',
              '按产品ID、元件ID和当前Tab分类保存参数；支座关键参数另同步其他Tab'),
    InputRule('管口分类参数', '元件定义', 'tableWidget_guankou / tableWidget_define1', table('管口附加参数'), ('参数值',),
              'pushButton_guankouparam → on_confirm_guankouparam', PDF, 'insert_or_update_guankou_para_data',
              '分类页签内的参数名和值 → 类别/模板/参数值'),
    InputRule('管口零件参数', '元件定义', 'tableWidget_guankou_2 / tableWidget_define1_5', table('管口零件材料参数'), ('参数值',),
              '管口零件参数确认', PDF, 'update_guankou_param', '产品ID + 管口零件ID + 参数名称；保存参数值'),
    InputRule('附件参数', '元件定义', 'tabWidget_attachment / dynamic_attachment_param_tabs[当前Tab]', table('管口附件附加参数'), ('参数数值',),
              'pushButton_attachment_confirm', 'modules/cailiaodingyi/funcs/funcs_attachment_render.py', 'on_confirm_attachment_param_update',
              '附件Tab分类/模板、参数名称 → 参数数值'),
    InputRule('管口定义', '管口及附件定义', 'tableWidget_pipe', table('管口'),
              ('管口代号', '管口功能', '管口用途', '公称尺寸', '法兰标准', '压力等级', '法兰型式', '密封面型式', '焊端规格', '管口所属元件', '轴向定位基准', '轴向定位距离', '轴向夹角（°）', '周向方位（°）', '偏心距', '外伸高度', '内伸高度', '管口附件', '管口载荷'),
              'pushButton_affirm → save_all_data_combined', PIPE, 'save_all_pipe_data',
              '动态表头映射到同名列；隐藏管口ID稳定定位；校验管口代号，换热器另校验功能'),
    InputRule('附件定义', '管口及附件定义', 'tableWidget_attachment', table('附件'),
              ('元件名称', '附件名称', '类型', '附属', '位置近', '轴向定位值', '元件类型', '所属元件', '轴向定位基准', '轴向定位距离mm', '数量', '间距', '方位（°）', '轴向夹角（°）', '周向方位（°）', '偏心距', '夹角（°）', '外伸高度', '备注'),
              'pushButton_affirm → save_all_data_combined', PIPE, 'save_all_attachment_define_data',
              '按表头列映射；产品ID + 隐藏元件ID；空白占位行不保存'),
    InputRule('管口规格制式', '管口及附件定义', 'tableWidget_pipe 表头选择框', table('管口类型选择'), ('公称尺寸类型', '公称压力类型', '焊端规格类型'),
              'pushButton_affirm → save_all_data_combined', PIPE, 'save_pipe_type_selection', '表头制式选择 → 三种类型列'),
    InputRule('管口载荷', '管口及附件定义', '载荷弹窗：justlike / zaihecanshu / yinglijisuan', table('管口载荷'), ('*',),
              '载荷弹窗 save_btn', 'modules/guankoudingyi/funcs/funcs_pipe_Load.py', 'save_pipe_load_data_by_table',
              '载荷数值按弹窗模式映射；产品ID + 管口ID；具体列见SQL读写清单'),
    InputRule('布管参数', '管束设计', 'TubeLayoutEditor.param_table', table('布管输入'), ('key', 'value'),
              'calculate_piping_layout / _calculate_piping_layout_local', LAYOUT, 'TubeLayoutEditor.save_layout_input',
              '界面参数与业务库数据组装input_data；key/value为当次布管输入快照'),
    InputRule('管束布置', '管束设计', 'TubeLayoutEditor 布置画布与轴向参数', table('布管元件信息'), ('序号', '距前一个元件的距离/mm', '元件厚度/mm', '元件类型'),
              'actual_save_operation', LAYOUT, 'TubeLayoutEditor.actual_save_operation', '布置结果整理后保存；其他几何表见同一流程的SQL生成器'),
    InputRule('布管参数设置', '管束设计', '外部界面文件：布管输入参数.json', table('布管参数'), ('参数值',),
              'JsonHandler.save_piping_params_to_db', 'modules/buguan/main.py', 'run_tube_design_gui.JsonHandler.save_piping_params_to_db',
              '文件变更监听接收界面JSON，按产品ID和参数名更新参数值'),
    InputRule('管板连接', '管束设计', '外部界面文件：管板连接.json', table('管板连接'), ('参数值', '管板连接方式', '管板类型'),
              'JsonHandler.save_connection_to_db', 'modules/buguan/main.py', 'run_tube_design_gui.JsonHandler.save_connection_to_db', '连接参数JSON → 管板连接记录'),
    InputRule('管板形式', '管束设计', '外部界面文件：管板连接形式.json', table('管板形式'), ('默认值', '管板类型', '参数符号'),
              'JsonHandler.save_form_to_db', 'modules/buguan/main.py', 'run_tube_design_gui.JsonHandler.save_form_to_db', '形式参数JSON → 管板形式记录'),
]


@dataclass(frozen=True)
class FlowRule:
    title: str
    sources: tuple
    targets: tuple
    path: str
    function: str
    trigger: str
    mapping: str


FLOWS = [
    FlowRule('条件保存：腐蚀裕量 → 元件参数', (table('设计数据'),), (table('元件附加参数'),), CDT, 'sync_design_params_to_element_params',
             '条件输入确认保存后', '腐蚀裕量*：管程数值/壳程数值 → 固定管板、浮动管板、球冠形封头、浮头法兰的管程侧/壳程侧腐蚀裕量；空值不写入'),
    FlowRule('条件保存：管口腐蚀裕量分流', (table('设计数据'), table('管口类别')), (table('管口类别'),), CDT, 'sync_corrosion_to_guankou_param',
             '条件输入保存 / 管口分类同步', '两侧数值相同取共同值；不同则按管口所属侧判断；无法统一时保持空值。输出接管腐蚀裕量1/2/3'),
    FlowRule('条件保存：开孔焊接接头系数', (table('设计数据'), table('管口类别')), (table('管口类别'), table('管口附加参数')), CDT, 'sync_opening_weld_joint_coeff_to_guankou_param',
             '条件保存；由手动标志决定是否重置默认值', '按分类与管程/壳程选择默认系数；手动设置保护分支；详见函数条件'),
    FlowRule('元件确认：参数与材料状态', (), (table('元件附加参数'), table('元件材料')), PDF, 'update_left_table_db_from_param_table',
             '元件界面确认同次保存', '共同来源是右侧参数控件；材料别名取首个非空值，定义状态由必填项判定；不代表直接读取参数表复制'),
    FlowRule('元件确认：参数 → 布管设置', (), (table('元件附加参数'), table('布管参数')), DM, 'sync_component_params_to_buguan',
             '元件参数同步；输入为当前参数表控件', '换热管外径 → 换热管外径 do；防冲板、滑道、中间挡板、旁路挡板参数按MAPPING_DICT映射；共同界面输入'),
    FlowRule('管口确认：分类与载荷标识', (table('管口'),), (table('管口类别'), table('管口载荷')), PIPE, 'save_all_pipe_data',
             '管口及附件定义确认保存', '产品ID + 管口ID定位；代号同步至类别与载荷；所属元件同步至类别；材料分类按产品类型、所属元件变化与已有分类决定'),
    FlowRule('布管计算：输入与结果快照', (table('布管参数'), table('设计数据'), table('通用数据'), table('元件附加参数')), (table('布管输入'), table('布管结果')), LAYOUT, 'TubeLayoutEditor.calculate_piping_layout',
             '布管计算', '界面与业务数据组装输入JSON；save_layout_input保存输入；计算接口返回后save_layout_result展平结果。输入表是快照，计算直接接收JSON'),
    FlowRule('布管保存：几何与轴向布置', (), tuple(table(x) for x in ('布管坐标', '布管拉杆', '布管元件', '布管元件信息', '布管换热管信息', '布管计算结果')),
             LAYOUT, 'TubeLayoutEditor.actual_save_operation', '布管画布确认保存', '计算结果经画布调整后，由SQL生成器保存几何坐标、元件布置和统计；数据库结果快照不是唯一输入'),
    FlowRule('强度计算：提交快照与结果回写', tuple(table(x) for x in ('设计数据', '通用数据', '元件附加参数', '元件附加参数合并', '管口', '管板连接', '管板形式', '布管参数')),
             tuple(table(x) for x in ('计算提交', '管口计算提交', '设计数据计算提交', '元件计算结果', '计算结果日志')),
             CALC, 'calculate_heat_exchanger_strength', '设计运算；按产品型式分派combine_json_new系列',
             '组装JSON：DictDatas→元件提交，TTDict→管口提交，WSList/DesignParams→设计提交。DLL实际读取同次JSON；DictOutDatas.Datas→Id/Name/Value，Logs/IsSuccess→结果日志；提交表为快照'),
]


@dataclass(frozen=True)
class FieldRule:
    title: str
    source_table: str
    source_column: str
    source_filter: tuple
    target_table: str
    target_column: str
    target_filter: tuple
    join: tuple
    flow: int

    def matches(self, ref, row, source):
        name, column, filters = (self.source_table, self.source_column, self.source_filter) if source else (self.target_table, self.target_column, self.target_filter)
        return ref.table == name and ref.column == column and all(str(row.get(k, '')) == v for k, v in filters)


FIELD_RULES = [
    FieldRule(side + '腐蚀裕量 → ' + part, table('设计数据'), side + '数值', (('参数名称', '腐蚀裕量*'),),
              table('元件附加参数'), '参数值', (('元件名称', part), ('参数名称', side + '侧腐蚀裕量')),
              (('产品ID', '产品ID'),), 0)
    for side in ('管程', '壳程') for part in ('固定管板', '浮动管板', '球冠形封头', '浮头法兰')
] + [
    FieldRule('管口标识同步', table('管口'), column, (), table(target), column, (),
              (('产品ID', '产品ID'), ('管口ID', '管口ID')), 5)
    for target, columns in (('管口类别', ('管口代号', '管口所属元件')), ('管口载荷', ('管口代号',))) for column in columns
]
