"""出图失败回归；运行真实业务函数，以 CAD/数据库替身注入关键故障。"""

import ast
from contextlib import contextmanager
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import traceback
import unittest
from unittest.mock import MagicMock, Mock, patch

from modules.TwoD import TwoD_peizhi as cad
from modules.TwoD.cad_context import CAD_CTX


ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    # TwoD_tab 的顶层导入会创建产品 UI。仅载入原函数 AST，保持真实函数体，
    # 这样本测试不触碰用户当前窗口、产品或数据库。
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    nodes = [node for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@contextmanager
def isolated_context():
    previous = CAD_CTX.copy()
    CAD_CTX.update(product_id=None, doc=None, target_dwg=None, save_dir=None)
    try:
        yield
    finally:
        CAD_CTX.clear()
        CAD_CTX.update(previous)


class DocumentFailureTests(unittest.TestCase):
    def test_no_target_cannot_fall_back_to_blank_active_document(self):
        with isolated_context(), patch.object(cad.win32com.client, "GetActiveObject") as active:
            self.assertIsNone(cad.get_current_doc("current"))
        active.assert_not_called()

    def test_previous_product_or_wrong_file_cannot_be_used(self):
        doc = SimpleNamespace(FullName=str(ROOT / "other.dwg"))
        with isolated_context():
            CAD_CTX.update(product_id="previous", doc=doc, target_dwg=str(ROOT / "current.dwg"))
            with self.assertRaisesRegex(RuntimeError, "其它产品"):
                cad.get_current_doc("current")
            CAD_CTX["product_id"] = "current"
            with self.assertRaisesRegex(RuntimeError, "不一致"):
                cad.get_current_doc("current")

    def test_rejected_idle_call_does_not_use_empty_command_as_ready(self):
        app = MagicMock()
        app.GetAcadState.side_effect = RuntimeError("COM 被拒绝")
        app.ActiveDocument.GetVariable.return_value = ""
        self.assertFalse(cad.wait_cad_idle(app, timeout=0.01, poll=0.001))
        app.ActiveDocument.GetVariable.assert_not_called()

    def test_open_failure_is_reported_to_caller(self):
        app = MagicMock()
        app.Documents.Count = 0
        app.Documents.Open.side_effect = RuntimeError("打开失败")
        with patch.object(cad, "get_autocad_instance", return_value=app), \
                patch.object(cad, "must_exist_file", return_value=True), \
                patch.object(cad, "wait_cad_idle", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "本次生成已停止"):
                cad.open_drawing_with_wait("first.dwg")

    def test_existing_document_activation_failure_does_not_open_duplicate(self):
        path = str(ROOT / "first.dwg")
        app, doc = MagicMock(), MagicMock()
        doc.FullName = path
        app.Documents.Count = 1
        app.Documents.Item.return_value = doc
        doc.Activate.side_effect = RuntimeError("激活失败")
        with patch.object(cad, "get_autocad_instance", return_value=app), \
                patch.object(cad, "must_exist_file", return_value=True), \
                patch.object(cad, "wait_cad_idle", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "本次生成已停止"):
                cad.open_drawing_with_wait(path)
        app.Documents.Open.assert_not_called()

    def label_namespace(self):
        return load_functions(ROOT / "modules/TwoD/toubiaotu_biaozhu.py",
                              {"apply_dimension_labels", "save_current_doc", "generate_and_save_flange"},
                              {"get_current_doc": cad.get_current_doc, "com_retry": cad.com_retry,
                               "modify_dimension": Mock(), "CAD_CTX": CAD_CTX})

    def test_dimensions_are_not_attempted_if_master_never_opened(self):
        ns = self.label_namespace()
        with isolated_context(), self.assertRaisesRegex(RuntimeError, "总图没有成功打开"):
            ns["apply_dimension_labels"]({"123": "100"})
        ns["modify_dimension"].assert_not_called()

    def test_master_save_failure_is_not_returned_as_success(self):
        ns = self.label_namespace()
        doc = MagicMock()
        doc.FullName = str(ROOT / "first.dwg")
        doc.Save.side_effect = RuntimeError("写入失败")
        with isolated_context(), patch("time.sleep"):
            CAD_CTX.update(doc=doc, target_dwg=doc.FullName)
            with self.assertRaisesRegex(RuntimeError, "图纸保存失败"):
                ns["apply_dimension_labels"]({})

    def test_failed_flange_is_not_skipped_as_completed(self):
        ns = self.label_namespace()
        ns["twoDgeneration_flange_ao"] = Mock(return_value=None)
        with isolated_context(), self.assertRaisesRegex(RuntimeError, "未生成成功"):
            ns["generate_and_save_flange"]("current", [{"法兰名称": "法兰", "密封面": "凹", "覆层": "否"}])


class GenerationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(prefix="cad-generation-test-")
        self.addCleanup(self.folder.cleanup)
        self.target = Path(self.folder.name) / "master.dwg"
        self.target.write_bytes(b"drawing-test-fixture")
        self.doc = SimpleNamespace(FullName=str(self.target), Application=MagicMock())
        cursor, connection = MagicMock(), MagicMock()
        cursor.__enter__.return_value = cursor
        connection.cursor.return_value = cursor
        current = {}

        def execute(sql, params):
            current["sql"] = sql
            current["params"] = params

        def fetchone():
            sql = current["sql"]
            if "SELECT 产品类型, 产品型式" in sql:
                return {"产品类型": "换热器", "产品型式": "BEU"}
            if "管程程数" in sql:
                return {"参数值": "2"}
            if "管程分程形式" in sql:
                return {"参数值": "2.1"}
            if "法兰密封面" in sql:
                return {"参数值": "凸"}
            if "是否添加覆层" in sql:
                return {"参数值": "否"}
            raise AssertionError(sql)

        cursor.execute.side_effect = execute
        cursor.fetchone.side_effect = fetchone
        cursor.fetchall.return_value = [{"元件名称": "法兰"}]

        def reset_context():
            CAD_CTX.update(product_id=None, save_dir=None, doc=None, target_dwg=None)

        def generate_master(product_id):
            CAD_CTX.update(product_id=product_id, doc=self.doc, target_dwg=str(self.target))

        self.ns = load_functions(ROOT / "modules/TwoD/TwoD_tab.py", {"run_generation_core"}, {
            "selected_keys": {"main", "flange::法兰", "tube_layout"},
            "self": SimpleNamespace(worker=SimpleNamespace(cancel_requested=False)),
            "pymysql": SimpleNamespace(connect=Mock(return_value=connection),
                                       cursors=SimpleNamespace(DictCursor=object)),
            "CAD_CTX": CAD_CTX, "reset_cad_context": reset_context, "os": os,
            "get_autocad_instance": Mock(return_value=self.doc.Application),
            "get_current_doc": cad.get_current_doc,
            "toubiaotu_BEU_2": Mock(side_effect=generate_master),
            "draw_buguan_from_coord_json": Mock(return_value=str(self.target)),
            "generate_and_save_flange": Mock(),
            "draw_buguan_from_coord_json_dandu": Mock(return_value="layout.dwg"),
        })
        self.progress = []

    def run_pipeline(self):
        return self.ns["run_generation_core"]("current", lambda pct, msg: self.progress.append(msg))

    def assert_not_completed(self):
        self.ns["generate_and_save_flange"].assert_not_called()
        self.ns["draw_buguan_from_coord_json_dandu"].assert_not_called()
        self.assertNotIn("ROW|main|已完成", self.progress)
        self.assertNotIn("全部完成", self.progress)

    def test_startup_failure_stops_before_first_drawing(self):
        self.ns["get_autocad_instance"].side_effect = RuntimeError("启动超时")
        with isolated_context(), self.assertRaisesRegex(RuntimeError, "启动超时"):
            self.run_pipeline()
        self.ns["toubiaotu_BEU_2"].assert_not_called()
        self.assert_not_completed()

    def test_first_master_failure_stops_all_later_drawings(self):
        self.ns["toubiaotu_BEU_2"].side_effect = RuntimeError("总图打开失败")
        with isolated_context(), self.assertRaisesRegex(RuntimeError, "总图打开失败"):
            self.run_pipeline()
        self.ns["draw_buguan_from_coord_json"].assert_not_called()
        self.assert_not_completed()

    def test_previous_document_is_cleared_before_attempting_new_master(self):
        self.ns["toubiaotu_BEU_2"].side_effect = None
        with isolated_context():
            CAD_CTX.update(product_id="previous", doc=self.doc, target_dwg=str(self.target))
            with self.assertRaisesRegex(RuntimeError, "总图未生成成功"):
                self.run_pipeline()
        self.ns["draw_buguan_from_coord_json"].assert_not_called()
        self.assert_not_completed()

    def test_missing_output_file_cannot_be_marked_completed(self):
        self.target.unlink()
        with isolated_context(), self.assertRaisesRegex(RuntimeError, "没有成功保存"):
            self.run_pipeline()
        self.assert_not_completed()

    def test_successful_master_still_allows_selected_components(self):
        with isolated_context():
            self.run_pipeline()
        self.ns["draw_buguan_from_coord_json"].assert_called_once()
        self.ns["generate_and_save_flange"].assert_called_once()
        self.ns["draw_buguan_from_coord_json_dandu"].assert_called_once()
        self.assertIn("ROW|main|已完成", self.progress)
        self.assertEqual(self.progress[-1], "全部完成")


class HeatExchangerErrorsTests(unittest.TestCase):
    def test_all_active_master_generators_propagate_connection_failure(self):
        paths = set()
        for path in (ROOT / "modules/TwoD").glob("toubiaotu_tuzhi_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and "wenziduixiang" in (node.module or ""):
                    paths.add(ROOT.joinpath(*node.module.split(".")).with_suffix(".py"))
        self.assertEqual(len(paths), 45)
        for path in sorted(paths):
            with self.subTest(template=path.name), isolated_context():
                cause = RuntimeError("绘图接口中断")
                ns = load_functions(path, {"twoDgeneration"}, {
                    "get_autocad_instance": Mock(side_effect=cause),
                    "pymysql": MagicMock(), "CAD_CTX": CAD_CTX,
                    "logging": Mock(), "traceback": Mock(),
                })
                with self.assertRaisesRegex(RuntimeError, "生成总图失败") as result:
                    ns["twoDgeneration"]("current")
                self.assertIs(result.exception.__cause__, cause)
                self.assertIsNone(CAD_CTX["doc"])


if __name__ == "__main__":
    unittest.main()
