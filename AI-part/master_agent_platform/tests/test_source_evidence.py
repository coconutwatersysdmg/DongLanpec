import __future__
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest

import fitz
from platform_core.source_evidence import (bind_condition_sources, field_evidence,
    product_reference, file_digest, match_material_chunk)


class EvidenceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.pdf = self.home/'part.pdf'
        with fitz.open() as doc:
            for i in range(3):
                page = doc.new_page()
                page.insert_text((40, 40), 'Recorded page '+str(i+1))
            doc.save(self.pdf)
        self.source = dict(path=str(self.pdf), sha256=file_digest(self.pdf), original_pages=[7, 9])
        self.data = dict(product_source=self.source, sources=[])
        self.row = dict(value='3.2', source='pdf', source_path=str(self.pdf), page=2)

    def tearDown(self): self.temp.cleanup()


class SourceEvidenceTests(EvidenceFixture, unittest.TestCase):
    def test_missing_row_and_missing_file_do_not_fall_back_to_product_pdf(self):
        for row in (None, {}, dict(value='3.2', page=2), dict(value='', source_path=str(self.pdf), page=2)):
            value = field_evidence(self.data, row)
            self.assertEqual(value['kind'], 'missing')
            self.assertNotIn('path', value)

    def test_pdf_requires_explicit_in_range_integer_page_without_clamping(self):
        for page in (None, 0, -1, 4, 1.5, True, 'bad'):
            value = field_evidence(self.data, dict(self.row, page=page))
            self.assertEqual(value['kind'], 'invalid', page)
            self.assertNotIn('path', value)

    def test_local_page_maps_to_original_page_without_changing_rendered_page(self):
        result = field_evidence(self.data, self.row)
        self.assertEqual((result['kind'], result['page'], result['original_page']), ('document', 2, 8))

    def test_another_product_or_unregistered_file_is_not_a_field_source(self):
        other = self.home/'other-product.pdf'
        other.write_bytes(self.pdf.read_bytes())
        result = field_evidence(self.data, dict(self.row, source_path=str(other)))
        self.assertEqual(result['kind'], 'invalid')

    def test_changed_or_missing_source_version_is_rejected(self):
        for checksum in ('wrong', None):
            data = dict(self.data, product_source=dict(self.source, sha256=checksum))
            self.assertEqual(field_evidence(data, self.row)['kind'], 'invalid')
        self.assertEqual(field_evidence(self.data, dict(self.row, source_sha256='wrong'))['kind'], 'invalid')

    def test_human_default_and_unsaved_values_do_not_inherit_old_document_evidence(self):
        for origin in ('human', 'manual', 'default', 'scoped-template', 'na'):
            result = field_evidence(self.data, dict(self.row, review_origin=origin))
            self.assertEqual(result['kind'], 'basis')
            self.assertNotIn('path', result)
        self.assertEqual(field_evidence(self.data, self.row, changed=True)['kind'], 'basis')

    def test_material_auto_completion_does_not_borrow_the_grades_pdf_evidence(self):
        row = dict(evidence=dict(file_path=str(self.pdf), page=2), 材料牌号='S31603', 材料标准='GB/T 24511',
            _source_values={'材料牌号': 'S31603', '材料标准': ''})
        self.assertEqual(field_evidence(self.data, dict(row, _selected_field='材料牌号'))['kind'], 'document')
        standard = field_evidence(self.data, dict(row, _selected_field='材料标准'))
        self.assertEqual(standard['kind'], 'basis')
        self.assertNotIn('path', standard)

    def test_recheck_uses_the_candidate_source_not_the_old_rows_source(self):
        candidate = dict(self.row, page=3)
        result = field_evidence(self.data, dict(self.row, review_origin='source-recheck', review_evidence=candidate))
        self.assertEqual(result['page'], 3)
        self.assertEqual(result['original_page'], 9)

    def test_invalid_highlight_cannot_point_outside_the_recorded_page(self):
        result = field_evidence(self.data, dict(evidence=dict(file_path=str(self.pdf), page=2, bbox=[0, 0, 9999, 9999])))
        self.assertEqual(result['kind'], 'document')
        self.assertIsNone(result['bbox'])
        self.assertTrue(result['warning'])

    def test_product_reference_is_separate_from_field_evidence(self):
        self.assertEqual(field_evidence(self.data, {})['kind'], 'missing')
        reference = product_reference(self.data)
        self.assertEqual(reference['kind'], 'reference')
        self.assertEqual((reference['page'], reference['original_page']), (1, 7))

    def test_resource_alias_opens_its_registered_managed_copy(self):
        data = dict(sources=[dict(self.source, original_path=str(self.home/'removed-original.pdf'))])
        result = field_evidence(data, dict(self.row, source_path=str(self.home/'removed-original.pdf')))
        self.assertEqual(result['path'], str(self.pdf))

    def test_condition_boundary_binds_document_rows_and_leaves_defaults_without_file(self):
        original = dict(std_rows=[dict(source='pdf', page=2), dict(source='default', page=None)],
                        ndt_rows=[dict(source='conflict', page=3)])
        value = bind_condition_sources(original, self.pdf)
        self.assertEqual(Path(value['std_rows'][0]['source_path']), self.pdf.resolve())
        self.assertEqual(value['ndt_rows'][0]['source_sha256'], self.source['sha256'])
        self.assertNotIn('source_path', value['std_rows'][1])
        self.assertNotIn('source_path', original['std_rows'][0])

    def chunks(self):
        return [SimpleNamespace(file_path='first.pdf', page=1, sheet='', text='irrelevant text', table_rows=[], screenshot_path='', source_tag='其它'),
                SimpleNamespace(file_path='second.pdf', page=3, sheet='', text='Tube material S31603', table_rows=[], screenshot_path='', source_tag='数据表')]

    def test_model_quote_must_uniquely_match_a_real_chunk(self):
        chunks = self.chunks()
        self.assertIs(match_material_chunk('Tube material S31603', chunks), chunks[1])
        self.assertIsNone(match_material_chunk('', chunks))
        self.assertIsNone(match_material_chunk('fabricated grade', chunks))
        chunks[0].text = chunks[1].text
        self.assertIsNone(match_material_chunk('Tube material S31603', chunks))

    def test_both_real_model_adapters_preserve_unmatched_data_without_fake_location(self):
        base = Path(__file__).resolve().parents[1]
        for directory in ('vendor', 'ui_vendor'):
            tree = ast.parse((base/directory/'elements_agent/nodes/extract.py').read_text(encoding='utf-8-sig'))
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_extract_with_llm')
            namespace = dict(json=json, re=re, _EXTRACT_SYSTEM='', Evidence=SimpleNamespace, MaterialIntent=SimpleNamespace)
            exec(compile(ast.Module(body=[function], type_ignores=[]), '<model-adapter>', 'exec', flags=__future__.annotations.compiler_flag), namespace)
            for quote, expected in (('Tube material S31603', 'second.pdf'), ('unmatched S30403', None), ('', None)):
                namespace['chat_completion'] = lambda *args, q=quote, **kwargs: json.dumps([dict(raw_name='Tube', snippet=q, 材料牌号='S31603')])
                result = namespace['_extract_with_llm'](self.chunks(), None)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].材料牌号, 'S31603')
                self.assertEqual(result[0].evidence.file_path if result[0].evidence else None, expected)


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QLabel
from platform_core.evidence_view import EvidenceActions, evidence_dialog


class EvidenceViewTests(EvidenceFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_buttons_distinguish_no_source_document_and_manual_basis(self):
        host, button, reference = QWidget(), QPushButton(), QPushButton()
        selected = [None, False]
        actions = EvidenceActions(host, button, reference, lambda: selected, lambda: self.data)
        try:
            actions.refresh()
            self.assertFalse(button.isEnabled())
            self.assertTrue(reference.isEnabled())
            selected[:] = [deepcopy(self.row), False]
            actions.refresh()
            self.assertTrue(button.isEnabled())
            self.assertEqual(button.text(), '查看抽取依据')
            selected[1] = True
            actions.refresh()
            self.assertEqual(button.text(), '查看形成依据')
            selected[:] = [{}, False]
            actions.refresh()
            self.assertFalse(button.isEnabled())
        finally: host.close()

    def test_metadata_dialog_has_no_document_opener(self):
        for evidence in (field_evidence(self.data, {}), field_evidence(self.data, dict(self.row, review_origin='default'))):
            dialog = evidence_dialog(None, evidence, {})
            try:
                self.assertIsNone(dialog.findChild(QPushButton, 'openEvidenceFile'))
                self.assertIsNone(dialog.findChild(QLabel, 'evidencePreview'))
            finally: dialog.close()

    def test_document_dialog_shows_both_page_numbers_and_the_exact_page(self):
        dialog = evidence_dialog(None, field_evidence(self.data, self.row), self.row)
        try:
            label = dialog.findChild(QLabel, 'evidenceLocation').text()
            self.assertIn('文件页 2', label)
            self.assertIn('原文页 8', label)
            self.assertFalse(dialog.findChild(QLabel, 'evidencePreview').pixmap().isNull())
        finally: dialog.close()


if __name__ == '__main__': unittest.main()
