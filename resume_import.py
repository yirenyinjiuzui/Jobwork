"""Extract a local résumé into review candidates without opening a database."""
import io
import re
import shutil
import subprocess
import zipfile
import zlib
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from workbench import RESUME_SCHEMA

MAX_TEXT = 150000
WORD = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class DocumentTree(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('不支持含自定义 XML 声明的 Word 文档。')


def word_text(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            part = archive.getinfo('word/document.xml')
            if part.file_size > 8 * 1024 * 1024:
                raise ValueError('Word 文档正文过大，请精简后重试。')
            root = ET.fromstring(archive.read(part), parser=ET.XMLParser(target=DocumentTree()))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError, EOFError, zlib.error) as exc:
        raise ValueError('无法读取 DOCX，请确认文件完整且未加密。') from exc
    def paragraph(block):
        return ''.join((node.text or '') if node.tag == WORD + 't' else
                       '\n' if node.tag == WORD + 'br' else '\t' if node.tag == WORD + 'tab' else ''
                       for node in block.iter()).strip()

    labels = set(BASIC) | set(DETAIL)
    for keys in RECORD_LABELS.values():
        labels.update(keys)

    def is_label(line):
        return line.rstrip('：:') in labels

    def table_lines(table):
        headers = []
        for tr in table.findall(WORD + 'tr'):
            cells = [[s for p in td.iter(WORD + 'p') if (s := paragraph(p))] for td in tr.findall(WORD + 'tc')]
            if cells and all(len(c) == 1 and is_label(c[0]) for c in cells):
                headers = [c[0].rstrip('：:') for c in cells]
            elif cells and len(cells) % 2 == 0 and all(
                a and len(a) == len(b) and all(map(is_label, a)) for a, b in zip(cells[::2], cells[1::2])
            ):
                headers = []
                for a, b in zip(cells[::2], cells[1::2]):
                    yield from (k.rstrip('：:') + '：' + v for k, v in zip(a, b))
            elif headers and len(headers) == len(cells):
                yield from (label + '：' + ' '.join(values) for label, values in zip(headers, cells) if values)
            else:
                headers = []
                yield from (v for c in cells for v in c)

    lines = []
    pending = [root]
    while pending:
        block = pending.pop()
        if block.tag == WORD + 'p':
            lines.append(paragraph(block))
        elif block.tag == WORD + 'tbl':
            lines.extend(table_lines(block))
        else:
            pending.extend(reversed(block))
    return '\n'.join(lines)


def pdf_text(raw):
    binary = shutil.which('pdftotext')
    if not binary:
        raise ValueError('本机缺少 pdftotext，支持用 DOCX 或 UTF-8 TXT 导入同一份简历。')
    if not raw.startswith(b'%PDF-'):
        raise ValueError('文件内容不是有效 PDF。')
    try:
        result = subprocess.run([binary, '-layout', '-enc', 'UTF-8', '-l', '41', '-', '-'],
                                input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('本机 PDF 解析未完成，请改用 DOCX 或 TXT。') from exc
    if result.returncode:
        raise ValueError('无法读取 PDF，请确认文件完整且未加密。')
    if result.stdout.count(b'\x0c') > 40:
        raise ValueError('单次最多解析 40 页 PDF，请先选取简历正文。')
    if len(result.stdout) > MAX_TEXT * 4:
        raise ValueError('请将简历正文精简至 15 万字以内。')
    if not result.stdout.strip():
        raise ValueError('PDF 未提取到文字，扫描件请先转成可选中文字的 PDF、DOCX 或 TXT。')
    return result.stdout.decode('utf-8')


def preview_resume(filename, raw):
    suffix = Path(filename).suffix.lower() if isinstance(filename, str) else ''
    if suffix == '.docx':
        text = word_text(raw)
    elif suffix == '.pdf':
        text = pdf_text(raw)
    elif suffix == '.txt':
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('TXT 请另存为 UTF-8 编码后重试。') from exc
    else:
        raise ValueError('请选择 TXT、DOCX 或 PDF 文件。')
    if not text.strip() or '\x00' in text or len(text) > MAX_TEXT:
        raise ValueError('请确认文档含有可读正文，且不超过 15 万字。')
    return parse_text(text)


BASIC = {'姓名':'full_name', '常用名':'preferred_name', '手机':'phone', '手机号':'phone',
         '手机号码':'phone', '联系电话':'phone', '电话':'phone', '邮箱':'email', '电子邮箱':'email',
         '现居地':'city', '现居城市':'city', '学校':'school', '毕业院校':'school', '学历':'degree',
         '最高学历':'degree', '专业':'major', '毕业时间':'graduation', '预计毕业时间':'graduation',
         '可到岗时间':'available_from'}
DETAIL = {'政治面貌':'political_status', '生源地':'student_origin', '应届身份':'candidate_status',
          '目标岗位':'target_position', '意向岗位':'target_position', '期望行业':'target_industry',
          '期望城市':'target_city', '期望工作城市':'target_city', '技能专长':'skills', '自我评价':'self_evaluation'}
DETAIL.update({label:key for _, fields in RESUME_SCHEMA['sections'] for key, label, *_ in fields})
GROUPS = {heading:key for key, title, item, *_ in RESUME_SCHEMA['records'] for heading in (title, item)}
GROUPS.update({'教育背景':'education', '工作经验':'work_experience', '项目经验':'projects', '获奖经历':'awards',
               '荣誉奖项':'awards', '实习经验':'internships', '语言能力':'languages', '家庭成员信息':'family_relations'})
PERSONAL = {'个人简历', '求职简历', '简历', '个人资料', '个人信息', '基本信息', '求职意向', '联系方式', '最高学历'}
SKIP = {'证明人', '证明人信息', '紧急联系人', '紧急联系人信息', '家庭信息', '推荐人', '推荐人信息'}
RECORD_LABELS = {}
IDENTITY = {}
KINDS = {None:{field[0]:field[2] for _, fields in RESUME_SCHEMA['sections'] for field in fields if len(field) > 2}}
for key, _, _, primary, extra in RESUME_SCHEMA['records']:
    RECORD_LABELS[key] = {label:keyname for keyname, label, *_ in primary + extra}
    IDENTITY[key] = primary[0][0]
    KINDS[key] = {field[0]:field[2] for field in primary + extra if len(field) > 2}
RECORD_LABELS['education'].update({'院校':'school', '学历':'degree', '入学时间':'start', '毕业时间':'end'})
for group in ('work_experience', 'internships'):
    RECORD_LABELS[group].update({'公司':'company', '公司名称':'company', '单位名称':'company', '职位':'role', '职责':'description'})
RECORD_LABELS['projects'].update({'角色':'role', '项目描述':'description'})
RECORD_LABELS['awards'].update({'获奖名称':'name', '授奖单位':'issuer', '奖项等级':'level'})
RECORD_LABELS['languages'].update({'外语':'language', '分数':'score'})

# Keep an unknown labelled column from becoming part of the preceding value.
LABEL = re.compile(r'(?:^|[\t |｜;；，,])\s*([\u3400-\u9fffA-Za-z0-9（）()／/]{1,18})\s*[:：]\s*')
SEPARATORS = r'[\t|｜;；]'
MONTH = r'(?:19|20)\d{2}[./年-](?:1[0-2]|0?[1-9])月?'
RANGE = re.compile(r'(?<!\d)(' + MONTH + r')\s*(?:至|到|[-~—–～]+|(?=至今))\s*(' + MONTH + r'|至今|现在)(?!\d)')
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
PHONE = re.compile(r'(?:\+?86[- ]?)?1[3-9]\d{9}|(?:\+852[- ]?)?[2-9]\d{7}')
PRIVATE_TEXT = re.compile(r'身份证|证件|护照|户籍|籍贯|家庭|家属|家人|联系人|证明人|推荐人|父亲|母亲|配偶|监护人|地址[：:]|电话[：:]|手机[：:]|邮箱[：:]|\d{17}[\dxX]|1[3-9]\d{9}|@')
BULLET = re.compile(r'^(?:[-•●▪◆·]|[1-9]\d?[、.)）])\s*(.+)')
DESCRIPTION = {'description', 'responsibilities', 'work_content', 'personal_responsibility'}


def name_in_header(lines):
    header = next((i for i, s in enumerate(lines[:3]) if s not in ('个人简历', '求职简历', '简历')), None)
    if header is None:
        return None
    candidate = lines[header]
    if not re.fullmatch('[赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜谢邹苏潘范彭鲁韦马苗方任袁柳唐程邓傅姚林罗梁宋徐胡高刘黄郭谭肖陆叶江杜顾龚卢白丁段侯夏钟田廖石蔡欧董尹贾薛]'
                        r'[\u4e00-\u9fff]{1,2}', candidate):
        return None
    if candidate in BASIC or candidate in PERSONAL or candidate in GROUPS:
        return None
    if any(EMAIL.search(s[:400]) or PHONE.search(s[:400]) or re.search(r'性别\s*[:：]', s[:400]) for s in lines[header+1:header+4]):
        return header
    return None


def month(value):
    if not re.fullmatch(MONTH, value):
        return ''
    year, number = re.findall(r'\d+', value)
    return f'{year}-{int(number):02d}'


def control_value(kind, value):
    if kind == 'month':
        return month(value)
    if kind == 'date':
        parts = re.fullmatch(r'((?:19|20)\d{2})[./年-](\d{1,2})[./月-](\d{1,2})日?', value)
        if parts:
            try:
                return date(*(int(n) for n in parts.groups())).isoformat()
            except ValueError:
                pass
        return ''
    if kind == 'number' and not re.fullmatch(r'-?\d+(?:\.\d+)?', value):
        return ''
    return value


def dated_record(line, group):
    """Accept only unambiguous dated headings with a recognizable organization or school."""
    if group not in ('education', 'internships', 'work_experience'):
        return None
    match = RANGE.search(line)
    if not match:
        return None
    rest = line[:match.start()] + ' ' + line[match.end():]
    parts = [s for s in re.split(r'[\s|｜;；]+', rest.strip()) if s]
    suffix = r'(?:大学|学院|学校)' if group == 'education' else r'(?:公司|研究院|研究所|集团|工厂|银行|中心)'
    orgs = [s for s in parts if re.fullmatch(r'[\w（）()·-]{2,50}' + suffix, s)]
    if len(orgs) != 1:
        return None
    row = {IDENTITY[group]:orgs[0], 'start':month(match[1])}
    if end := month(match[2]):
        row['end'] = end
    else:
        row['date_range'] = match[0]
    others = [s for s in parts if s != orgs[0]]
    if group == 'education':
        degrees = [s for s in others if s in ('本科','专科','大专','硕士','博士','学士','硕士研究生','博士研究生')]
        if len(degrees) == 1:
            row['degree'] = degrees[0]
            others.remove(degrees[0])
        if len(others) == 1 and len(others[0]) <= 32:
            row['major'] = others[0]
    elif len(others) == 1 and len(others[0]) <= 32:
        row['role'] = others[0]
    return row


def parse_text(text):
    fields, details, records, warnings = {}, {}, {}, []
    group = None
    row = {}
    ignored = 0
    conflicts = set()
    continuation = None

    def limit(value, kind):
        maximum = 2800 if kind == 'textarea' else 400
        if len(value) > maximum and '较长字段已按资料页长度限制截取，请核对。' not in warnings:
            warnings.append('较长字段已按资料页长度限制截取，请核对。')
        return value[:maximum]

    def finish_row():
        if row and group in IDENTITY:
            if row.get(IDENTITY[group]) and len(records.get(group, [])) < 20:
                records.setdefault(group, []).append(row.copy())
            elif '部分经历缺少名称或超出每类 20 条上限，请人工核对。' not in warnings:
                warnings.append('部分经历缺少名称或超出每类 20 条上限，请人工核对。')
        row.clear()

    def add_scalar(key, value):
        if key in conflicts:
            return
        dest = fields if key in BASIC.values() else details
        if key in dest and value != dest[key]:
            dest.pop(key)
            conflicts.add(key)
        else:
            dest[key] = value

    lines = [re.sub(r'[ \t]+', ' ', line.strip()) for line in text.splitlines() if line.strip()]
    pending = ''
    header_name = name_in_header(lines)
    for index, original in enumerate(lines):
        line = original
        if index == header_name:
            add_scalar('full_name', line)
            continue
        heading = re.sub(r'\s+', '', line.strip('【】# :：'))
        heading = re.sub(r'[（(]?第[一二三四五六七八九十\d]+[条段项][）)]?$', '', heading)
        if heading in GROUPS or heading in PERSONAL or heading in SKIP or heading in ('自我评价', '个人评价', '专业技能', '技能专长'):
            finish_row()
            group = GROUPS.get(heading)
            if heading in SKIP:
                group = 'skip'
            if heading in ('自我评价', '个人评价', '专业技能', '技能专长'):
                group = 'self_evaluation' if '评价' in heading else 'skills'
            pending = ''
            continuation = None
            continue
        if group == 'skip':
            ignored += 1
            continue
        if group in ('skills', 'self_evaluation'):
            details[group] = limit('\n'.join(filter(None, [details.get(group), line])), 'textarea')
            continue
        labels = RECORD_LABELS[group] if group else BASIC | DETAIL
        # A Word table often places a bare field label and its value in adjacent cells.
        if line.rstrip('：:') in labels:
            pending = line.rstrip('：:')
            continue
        matches = list(LABEL.finditer(line))
        if not matches and pending:
            line = pending + '：' + line
            matches = list(LABEL.finditer(line))
        pending = ''
        if matches:
            continuation = None
            for i, match in enumerate(matches):
                key = labels.get(match[1])
                value = line[match.end():matches[i+1].start() if i+1 < len(matches) else None].strip(' \t|｜；;，,')
                if not key or not value:
                    ignored += 1
                    continue
                kind = KINDS[group].get(key)
                if kind == 'month' and key == 'end' and value in ('至今', '现在'):
                    row['date_range'] = (row['start'] + ' 至 ' if row.get('start') else '') + value
                    continue
                value = control_value(kind, value)
                if not value or (key == 'email' and not EMAIL.fullmatch(value)) or (key in DESCRIPTION and PRIVATE_TEXT.search(value)):
                    ignored += 1
                    continue
                if group:
                    if key == IDENTITY[group] and key in row:
                        finish_row()
                    if key in row and row[key] != value:
                        if key in DESCRIPTION:
                            value = row[key] + '\n' + value
                        else:
                            ignored += 1
                            continue
                    row[key] = limit(value, kind)
                    if key in DESCRIPTION:
                        continuation = key
                    elif 'description' in KINDS[group] and not continuation:
                        continuation = 'bullet'
                else:
                    add_scalar(key, limit(value, 'textarea' if key in ('skills','self_evaluation') else kind))
            if PRIVATE_TEXT.search(line):
                continuation = None
            continue
        if group:
            natural = dated_record(line, group)
            if natural:
                finish_row()
                row.update(natural)
                continuation = 'bullet'
                continue
            if continuation and row.get(IDENTITY[group]) and not PRIVATE_TEXT.search(line):
                bullet = BULLET.match(line)
                sentence = continuation != 'bullet' and re.match(r'完成|负责|协助|参与|组织|搭建|维护|设计|整理|编写|开发|实施|优化|.{6,}[。；;]$', line)
                if bullet or sentence:
                    key = 'description' if continuation == 'bullet' else continuation
                    part = bullet[1] if bullet else line
                    row[key] = limit('\n'.join(filter(None, [row.get(key), part])), 'textarea')
                    continue
            continuation = None
        else:
            contact = False
            for token in re.split(SEPARATORS + r'|\s+', line):
                if EMAIL.fullmatch(token) or PHONE.fullmatch(token):
                    add_scalar('email' if '@' in token else 'phone', token)
                    contact = True
            if contact:
                continue
        ignored += 1
    finish_row()
    if any(re.search('至今|现在', r.get('date_range','')) for rows in records.values() for r in rows):
        warnings.append('仍在进行的经历保留了原起止时间，结束年月留空。')
    if conflicts:
        warnings.append('同一项个人资料出现不同的值，已留空，请对照原件填写。')
    if ignored:
        warnings.append('部分内容无法可靠归类，请对照原件补充。')
    if not (fields or details or records):
        warnings.append('没有识别到可导入项目。可使用带有“姓名：”“教育经历”等标签的简历。')
    return dict(fields=fields, details=details, records=records, warnings=warnings)
