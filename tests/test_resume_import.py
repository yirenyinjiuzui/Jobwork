from base64 import b64encode
from io import BytesIO
import json
import shutil
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from resume_import import parse_text, preview_resume
from server import WorkbenchServer


def docx(lines):
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        paragraphs = ''.join(f'<w:p><w:r><w:t>{escape(s)}</w:t></w:r></w:p>' for s in lines)
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                         f'wordprocessingml/2006/main"><w:body>{paragraphs}</w:body></w:document>')
    return buffer.getvalue()


def demo_pdf(content):
    # Minimal one-page synthetic PDF, including a byte-accurate cross-reference table.
    items = [b'<</Type/Catalog/Pages 2 0 R>>', b'<</Type/Pages/Kids[3 0 R]/Count 1>>',
             b'<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>',
             b'<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>',
             f'<</Length {len(content)}>>\nstream\n'.encode() + content + b'\nendstream']
    raw = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(items, 1):
        offsets.append(len(raw))
        raw.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    tail = len(raw)
    raw.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        raw.extend(f'{offset:010d} 00000 n \n'.encode())
    raw.extend(f'trailer\n<</Size {len(offsets)}/Root 1 0 R>>\nstartxref\n{tail}\n%%EOF'.encode())
    return bytes(raw)


class ResumeImport(unittest.TestCase):
    def test_labeled_rows_and_ambiguous_contact(self):
        result = parse_text('姓名：演示用户 | 性别：女 | 电子邮箱：a@example.invalid\n邮箱：b@example.invalid\n'
                            '教育经历\n学校：示例大学 | 专业：机械\n入学年月：2022.9\n'
                            '学校：示例学院 | 专业：材料\n毕业时间：2026年6月\n'
                            '证明人信息\n姓名：示例证明人 | 手机：13900000000')
        self.assertEqual(result['fields'], {'full_name':'演示用户'})
        self.assertEqual(result['details'], {'gender':'女'})
        self.assertEqual(result['records']['education'], [
            {'school':'示例大学','major':'机械','start':'2022-09'},
            {'school':'示例学院','major':'材料','end':'2026-06'}])
        self.assertTrue(result['warnings'])

    def test_dated_headings_keep_records_separate(self):
        result = parse_text('教育背景\n2020.09–2024.06 示例大学 机械 本科\n'
                            '示例学院 | 电子 | 硕士 | 2024年9月至2027年6月\n实习经历\n'
                            '2025/01 - 2025/06 示例技术公司 测试实习生\n职责：整理演示样本')
        self.assertEqual(result['records']['education'][1], {'school':'示例学院','major':'电子','degree':'硕士',
                                                           'start':'2024-09','end':'2027-06'})
        self.assertEqual(result['records']['internships'], [{'company':'示例技术公司','role':'测试实习生',
                                                          'start':'2025-01','end':'2025-06','description':'整理演示样本'}])
        self.assertEqual(result['warnings'], [])

    def test_word_and_txt(self):
        lines = ['姓名','演示同学','项目经历','项目名称：演示讲解板','角色：开发者']
        for filename, raw in [('sample.docx',docx(lines)), ('sample.TXT','\n'.join(lines).encode('utf-8-sig'))]:
            with self.subTest(filename=filename):
                result = preview_resume(filename, raw)
                self.assertEqual(result['fields'], {'full_name':'演示同学'})
                self.assertEqual(result['records'], {'projects':[{'name':'演示讲解板','role':'开发者'}]})

    def test_name_and_record_description_boundaries(self):
        result = parse_text('求职简历\n林晓禾\n邮箱：demo@example.invalid\n实习经历\n'
                            '2025.1–至今 示例设备公司 运维实习生\n• 完成设备巡检\n职责：整理台账\n协助归档设备记录。\n'
                            '• 证明人是某某\n附加说明\n• 该条不应进入职责\n项目经历\n'
                            '项目名称：演示仪表\n• 调试传感器\n• 家庭成员另附\n'
                            '项目名称：模拟装置\n• 整理样本')
        self.assertEqual(result['fields']['full_name'], '林晓禾')
        self.assertNotIn('full_name', parse_text('求职简历\n移动开发\n邮箱：demo@example.invalid')['fields'])
        job = result['records']['internships'][0]
        self.assertEqual(job['date_range'], '2025.1–至今')
        self.assertNotIn('end', job)
        self.assertEqual(job['description'], '完成设备巡检\n整理台账\n协助归档设备记录。')
        self.assertEqual([r['description'] for r in result['records']['projects']], ['调试传感器','整理样本'])
        self.assertTrue(any('结束年月' in warning for warning in result['warnings']))

    def test_word_table_label_value_columns(self):
        buffer = BytesIO()
        def cell(*lines):
            return '<w:tc>' + ''.join(f'<w:p><w:r><w:t>{s}</w:t></w:r></w:p>' for s in lines) + '</w:tc>'
        def row(*cells):
            return '<w:tr>' + ''.join(cells) + '</w:tr>'
        body = ('<w:tbl>' + row(cell('姓名','性别'), cell('演示同学','女')) + '</w:tbl>'
                '<w:p><w:r><w:t>教育经历</w:t></w:r></w:p><w:tbl>' + row(cell('学校'),cell('专业')) +
                row(cell('示例大学'),cell('机械')) + row(cell('示例学院'),cell('材料')) + '</w:tbl>')
        with ZipFile(buffer,'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                             f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
        result = preview_resume('demo.docx', buffer.getvalue())
        self.assertEqual(result['fields'], {'full_name':'演示同学'})
        self.assertEqual(result['details'], {'gender':'女'})
        self.assertEqual(result['records']['education'], [{'school':'示例大学','major':'机械'},{'school':'示例学院','major':'材料'}])

    def test_limits_valid_dates_and_ongoing_explicit_end(self):
        result = parse_text('工作经历\n公司：' + '示'*450 + '\n职责：' + '例'*2900 + '\n结束年月：至今\n'
                            '基本信息\n入党时间：2022年3月9日')
        row = result['records']['work_experience'][0]
        self.assertEqual((len(row['company']),len(row['description'])), (400,2800))
        self.assertEqual(row['date_range'], '至今')
        self.assertEqual(result['details']['party_join_date'], '2022-03-09')

    @unittest.skipUnless(shutil.which('pdftotext'), 'requires local pdftotext')
    def test_text_pdf_and_scanned_pdf(self):
        result = preview_resume('demo.pdf', demo_pdf(b'BT /F1 12 Tf 40 730 Td (demo@example.invalid) Tj ET'))
        self.assertEqual(result['fields'], {'email':'demo@example.invalid'})
        with self.assertRaisesRegex(ValueError, '未提取到文字'):
            preview_resume('demo.pdf', demo_pdf(b''))

    def test_invalid_or_unavailable_inputs(self):
        for filename, raw in [('wrong.docx', b'bad'), ('unsupported.doc', b'demo'),
                              ('wrong.txt', b'\xff'), ('wrong.txt', b'\x00a'), ('big.txt', b'x'*150001)]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                preview_resume(filename, raw)
        with patch('resume_import.shutil.which', return_value=None), self.assertRaisesRegex(ValueError, 'pdftotext'):
            preview_resume('demo.pdf', demo_pdf(b''))

    def test_http_preview_never_calls_store(self):
        store = Mock(spec=[])
        with WorkbenchServer(('127.0.0.1', 0), store) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/api/profile/import-preview'
                def post(encoded, origin=None):
                    body = json.dumps(dict(filename='demo.txt', content_base64=encoded)).encode()
                    headers = {'Content-Type':'application/json'}
                    if origin:
                        headers['Origin'] = origin
                    return urlopen(Request(url, body, headers=headers), timeout=6)
                value = b64encode('姓名：演示同学'.encode()).decode()
                with post(value) as response:
                    self.assertEqual(json.load(response)['fields'], {'full_name':'演示同学'})
                for data, origin, status in [(value, 'https://example.invalid', 403), ('bad%', None, 400),
                                              (b64encode(b'x'*(5*1024*1024+1)).decode(), None, 400)]:
                    with self.subTest(status=status), self.assertRaises(HTTPError) as e:
                        post(data, origin)
                    self.assertEqual(e.exception.code, status)
                self.assertEqual(store.mock_calls, [])
            finally:
                server.shutdown()
                thread.join(timeout=3)
