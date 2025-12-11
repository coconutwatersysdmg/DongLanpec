# 全局变量
app = None
main_window = None
project_info_group = None
product_info_group = None
product_definition_group = None
work_information_group = None

current_username = None

# 项目信息控件
owner_input = None
project_number_input = None
project_name_input = None
department_input = None
contractor_input = None
project_path_input = None
date_edit = None

# 产品表格
product_table = None

# 产品定义控件
product_type_combo = None
product_form_combo = None
product_model_input = None
drawing_prefix_input = None
image_label = None
image_area = None

#工作信息控件
design_input = None
proofread_input = None
review_input = None
standardization_input = None
approval_input = None
co_signature_input = None

# 初始化为new
project_mode = "new"
product_mode = "start"

old_owner = None
old_project_name = None
old_project_path = None

current_project_id = None


# 点击当前行 对应的产品id
product_id = None
# 新建产品的时候的暂存的产品id
current_product_id = None

# 初始化状态表
# 产品信息的字典
product_table_row_status = {}

cur_row_new = 4
cur_row_update = 0
# 保存点击时时 哪行哪列当前的行列 产品信息
colum = None
row = None

last_cell_content = ""

# 产品信息 下拉框 产品类型和产品型式 应该是字典
type_form_mapping = {}

# 设计阶段 列表
mapping_design_t = []

# 示意图
confirm_curr_image_relative_path = None

# 二维单元格内容
copied_cells_data = []  # 用于存储复制的二维单元格内容

last_project_path = None

# 判断是点击单元格 还是点击表头
is_header_highlighting = False