import sys
import pymysql
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QTableWidget,
    QPushButton, QHeaderView
)
from PyQt5.QtCore import Qt

from HHAfengtouchengxinghoudujianbaolv import HHAfengtouchengxinghoudujianbaolv
from bancaipeizhi import handle_board_spec  # 引入板材规格逻辑
from diexinghetuoyuanxingfengtoujianbaolv import diexinghetuoyuanxingfengtoujianbaolv
from fanlanshejifanfaheyouhua import create_falan_sheji_youhua_config
from fengtoupinjie import fengtoupinjie
from guancaipeizhi import handle_pipe_spec
  # 新增导入
from jieguanjiegouchicunjibenyaoqiu import jieguanjiegouchicunjibenyaoqiu
from bancaijuanzhijieguanxianzhitiaojian import bancaijuanzhijieguanxianzhitiaojian
from kechengjieguandingwei import shechengjiegou_l1_l2_l3
from cailiaofupiancha import cailiaofupiancha
from shejiyuliang import shejiyuliang
from yezhujingyali import yezhujingyali
from youfengjieguanhanjiejietouxishu import youfengjieguanhanjiejietouxishu
from huanreguanzhizaofangfa import huanreguanzhizaofangfa
from yuantong import yuantonghoudupeizhi
from yuantongzuixiaohoudu import yuantong_min_thickness_editor
from zhongxiaoxingduanjiandingyi import zhongxiaoxingduanjiandingyi
from duanjianfenji import duanjianfenji
from jieguanxuanyongyouxianji import jieguancailiaoyouxianji
from jieguanshenchuchangdukongzhi import jieguanshenchuchangdu
from jieguanshenchuchangdukongzhi_continue import jieguanshenchuchangdukongzhi_continue
from duijieduanchicun import duijieduanchicun
from fengtouxingshixuanyong import fengtouxingshixuanyong
from fentoubuchongguize import fengtoubuchongguize
from fengtouzhibiangaodudingyi import fengtouzhibiangaodudingyi
from falanjiegou import flange_structure_config
from falanxingshixuanze import create_rongqifalanxingshi_config
from falanpeitaojigujianchangyongguige import create_jingujian_guige_config
from rongqifalanyongjingujianguigefanwei import create_rongqifalanjingujian_config
from falanjisuanguize import falanjisuan_guize_config_static
from kaikongbuqiangshejifangfa import kaikongbq_fangfa_config
from bulingxingbuqiang import bql_not_reinforce_config
from dengmianjibuqiangfangfa import build_reinforce_general_config
from buqiangquanshiyongxianzhi import buqiangquan_xianzhi_config
from fenxifayibanyaoqiu import fenxifa_yiban_config
from buqiangquanjiegouchicun import buqiangquan_jiegou_chicun_config
from chaochuzhongliangxianzhidiaoershezhi import diaoerzhixian_config
from diaoershezhiguize import diaoerjiegou_config
from HPdiaoershezhi import hp_diaoer_guiize_config
from dianban import dianban_guiize_config
from huluefutougaishejiyuliang import ignore_futougaigai_config
from anzhuangpiancha import anzhuang_piancha_config
from futoufalandianpiankuandu import toufalan_dianpian_kuandu_config
from futouzuixiaojuli import futou_zuixiao_juli_config
from waitougaineijingdizengzhi import stepd_config
from guanbanyudingyi import guanban_config
from huanreguanzhongxinju import huanreqi_zhongxinju_config
from huanreguanzhongxinju_buchong import center_distance_supplement_config
from huanremianji import huanreqiang_area_config
from laganjiegou import lagan_jiegou_config
from luowenlaganzhijingxuanyong import luowen_lagan_zhijing_config
from laganshuliang import lagan_shuliang_config
from pangludangban import bypass_dangban_config
from zhichengban import zhichengban_config
from huadao import huadao_config
from huadaozuixiaohoudu import huadaohoudu_config
from zheliuban import zheliuban_config
from zhichibanzengliang import zhichibanzengliang_config
from fangsongzhier import fangsong_zhier_config
from fangchongdangban import fangchong_dangban_config
from baowenzhichengjianju import baowen_zhicheng_config
from baowenzhichengchicuntongyong import baowen_zhichi_chicun_config
from luoshuanlianjiezhier import create_bolted_support_lug_config
from hanjiezhier import create_welded_support_lug_config
from luoshuanlianjiedezhichengban import zhichengban_chicun_config
from yurongqihanjiedezhichengban import hanjiezhichengban_chicun_config
from yuzhierluoshuangxiangliandezhichenghuan import zhichenghuan_config
from yuzhierhanjiexiangliandezhichenghuan import zhichenghuan_jiejie_config
from yurongqizhijiehanjiedezhichenghuan import zhichenghuan_rongqi_config
from dingjuguan import dingjuguan_config
from weibuzhicheng import weibuzhicheng_config
from fenchenggeban import fenchenggeban_config







DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '配置库',
    'charset': 'utf8mb4'
}


TEST_USER_ID = "user"





class ConfigManager(QWidget):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.setWindowTitle(f"配置管理器 - 用户 {self.user_id}")
        self.resize(1600, 900)

        layout = QHBoxLayout()
        self.setLayout(layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("配置项")
        layout.addWidget(self.tree, 2)

        self.table = QTableWidget()
        layout.addWidget(self.table, 8)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.save_button = QPushButton("保存配置")
        layout.addWidget(self.save_button)

        self.conn = pymysql.connect(**DB_CONFIG)

        self.init_tree()
        self.tree.itemClicked.connect(self.load_config)

    def init_tree(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, 名称 FROM config_tree WHERE parent_id IS NULL')
        for row in cursor.fetchall():
            node = QTreeWidgetItem(self.tree, [row[1]])
            self.add_tree_item(node, row[0])
        self.tree.expandAll()

    def add_tree_item(self, parent, parent_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, 名称 FROM config_tree WHERE parent_id=%s', (parent_id,))
        for row in cursor.fetchall():
            child = QTreeWidgetItem(parent, [row[1]])
            self.add_tree_item(child, row[0])

    def load_config(self, item, column):
        self.current_config_type = item.text(0)
        cursor = self.conn.cursor()

        if self.current_config_type == "常用板材规格":
            handle_board_spec(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "常用管材规格":
            handle_pipe_spec(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "板材卷制接管限制条件":
            bancaijuanzhijieguanxianzhitiaojian(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "厚壁锻管/嵌入式接管结构尺寸基本要求":
            jieguanjiegouchicunjibenyaoqiu(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "有缝接管焊接接头系数":
            youfengjieguanhanjiejietouxishu(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "换热管制造方法":
            huanreguanzhizaofangfa(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "中小型锻件定义":
            zhongxiaoxingduanjiandingyi(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "锻件分级":
            duanjianfenji(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "接管材料类型选用优先级":
            jieguancailiaoyouxianji(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "接管伸出长度控制1":
            jieguanshenchuchangdu(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "接管伸出长度控制2":
            jieguanshenchuchangdukongzhi_continue(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "接管与管法兰或外部对接端尺寸":
            duijieduanchicun(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "封头形式选用":
            fengtouxingshixuanyong(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "封头选用补充规则":
            fengtoubuchongguize(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "封头直边高度h定义":
            fengtouzhibiangaodudingyi(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "蝶形和椭圆形封头成型减薄率":
            diexinghetuoyuanxingfengtoujianbaolv(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "HAA封头成型减薄率":
            HHAfengtouchengxinghoudujianbaolv(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "封头拼接":
            fengtoupinjie(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "液柱静压力":
            yezhujingyali(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "圆筒(文本）":
            yuantonghoudupeizhi(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "圆筒（自定义最小厚度）":
            yuantong_min_thickness_editor(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "壳程接管定位":
            shechengjiegou_l1_l2_l3(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "容器法兰设计方法及优化原则":
            create_falan_sheji_youhua_config(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "法兰结构确定":
            flange_structure_config(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "容器法兰形式选择":
            create_rongqifalanxingshi_config(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "容器法兰配套紧固件常用规格":
            create_jingujian_guige_config(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "容器法兰用紧固件规格范围选用表（含浮头法兰）（GB/T 150计算）":
            create_rongqifalanjingujian_config(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "任意式法兰计算规则":
            falanjisuan_guize_config_static(self.table, cursor, self.user_id, self.current_config_type)
        if self.current_config_type == "开孔补强的设计方法选用":
            kaikongbq_fangfa_config(self.table, cursor, self.user_id)
        if self.current_config_type == "不另行补强":
            bql_not_reinforce_config(self.table, cursor, self.user_id)
        if self.current_config_type == "等面积补强方法的一般要求":
            build_reinforce_general_config(self.table, cursor, self.user_id)
        if self.current_config_type == "补强圈的使用限制":
            buqiangquan_xianzhi_config(self.table, cursor, self.user_id)
        if self.current_config_type == "分析法一般要求":
            fenxifa_yiban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "补强圈结构尺寸的确定":
            buqiangquan_jiegou_chicun_config(self.table, cursor, self.user_id)
        if self.current_config_type == "当以下零部件重量超出限制值时，设置吊耳":
            diaoerzhixian_config(self.table, cursor, self.user_id)
        if self.current_config_type == "吊耳设置规则":
            diaoerjiegou_config(self.table, cursor, self.user_id)
        if self.current_config_type == "HP吊耳设置":
            hp_diaoer_guiize_config(self.table, cursor, self.user_id)
        if self.current_config_type == "垫板":
            dianban_guiize_config(self.table, cursor, self.user_id)
        if self.current_config_type == "忽略浮头盖设计余量（厚度附加余量）":
            ignore_futougaigai_config(self.table, cursor, self.user_id)
        if self.current_config_type == "安装偏差":
            anzhuang_piancha_config(self.table, cursor, self.user_id)
        if self.current_config_type == "浮头法兰垫片宽度":
            toufalan_dianpian_kuandu_config(self.table, cursor, self.user_id)
        if self.current_config_type == "最小距离":
            futou_zuixiao_juli_config(self.table, cursor, self.user_id)
        if self.current_config_type == "外头盖内径递增值StepD":
            stepd_config(self.table, cursor, self.user_id)
        if self.current_config_type == "管板":
            guanban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "换热管中心距":
            huanreqi_zhongxinju_config(self.table, cursor, self.user_id)
        if self.current_config_type == "换热管中心距（补充）":
            center_distance_supplement_config(self.table, cursor, self.user_id)
        if self.current_config_type == "换热面积":
            huanreqiang_area_config(self.table, cursor, self.user_id)
        if self.current_config_type == "拉杆结构":
            lagan_jiegou_config(self.table, cursor, self.user_id)
        if self.current_config_type == "螺纹拉杆直径选用":
            luowen_lagan_zhijing_config(self.table, cursor, self.user_id)
        if self.current_config_type == "拉杆数量选用":
            lagan_shuliang_config(self.table, cursor, self.user_id)
        if self.current_config_type == "旁路挡板":
            bypass_dangban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "支撑板":
            zhichengban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "滑道基本配置":
            huadao_config(self.table, cursor, self.user_id)
        if self.current_config_type == "滑道最小厚度":
            huadaohoudu_config(self.table, cursor, self.user_id)
        if self.current_config_type == "折流板/支持板配置":
            zheliuban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "最后一块支持板配置":
            zhichibanzengliang_config(self.table, cursor, self.user_id)
        if self.current_config_type == "防松支耳":
            fangsong_zhier_config(self.table, cursor, self.user_id)
        if self.current_config_type == "防冲挡板":
            fangchong_dangban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "保温（保冷）支撑间距":
            baowen_zhicheng_config(self.table, cursor, self.user_id)
        if self.current_config_type == "通用":
            baowen_zhichi_chicun_config(self.table, cursor, self.user_id)
        if self.current_config_type == "螺栓连接支耳":
            create_bolted_support_lug_config(self.table, cursor, self.user_id)
        if self.current_config_type == "焊接连接支耳":
            create_welded_support_lug_config(self.table, cursor, self.user_id)
        if self.current_config_type == "与支耳焊接/螺栓连接的支撑板":
            zhichengban_chicun_config(self.table, cursor, self.user_id)
        if self.current_config_type == "与容器直接焊接的支撑板":
            hanjiezhichengban_chicun_config(self.table, cursor, self.user_id)
        if self.current_config_type == "与支耳螺栓连接的支撑环":
            zhichenghuan_config(self.table, cursor, self.user_id)
        if self.current_config_type == "与支耳焊接连接的支撑环":
            zhichenghuan_jiejie_config(self.table, cursor, self.user_id)
        if self.current_config_type == "与容器直接焊接的支撑环":
            zhichenghuan_rongqi_config(self.table, cursor, self.user_id)
        if self.current_config_type == "定距管":
            dingjuguan_config(self.table, cursor, self.user_id)
        if self.current_config_type == "尾部支撑":
            weibuzhicheng_config(self.table, cursor, self.user_id)
        if self.current_config_type == "分程隔板":
            fenchenggeban_config(self.table, cursor, self.user_id)
        if self.current_config_type == "材料负偏差":
            cailiaofupiancha(self.table, cursor, self.user_id)
        if self.current_config_type == "设计余量":
            shejiyuliang(self.table, cursor, self.user_id, self.current_config_type)
    def closeEvent(self, event):
        self.conn.close()
        event.accept()

if __name__ == "__main__":
    import json
    from modules.utils.predifined_reader import get_full_user_json

    # 判断是否为 JSON 模式
    if len(sys.argv) >= 2 and sys.argv[1] == "--json":
        user_id = sys.argv[2] if len(sys.argv) >= 3 else "user"
        json_data = get_full_user_json(user_id=user_id, fallback_user_id="default")
        print(json.dumps(json_data, ensure_ascii=False, indent=2))
    else:
        # 默认 GUI 模式
        user_id = sys.argv[1] if len(sys.argv) >= 2 else "user"
        app = QApplication(sys.argv)
        win = ConfigManager(user_id)
        win.show()
        sys.exit(app.exec_())



