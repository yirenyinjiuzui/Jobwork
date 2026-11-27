"""Local, deterministic extraction and reconciliation of recruitment notices.

This is a conservative preview parser, not a source of confirmed hiring decisions.
All writes and history are the caller's responsibility.
"""
from datetime import date, datetime, time, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
import unicodedata

HKT = timezone(timedelta(hours=8), 'HKT')
STATUS_ACTION = {
    'saved': '核对岗位要求，决定是否投递',
    'submitted': '等待招聘方回复',
    'waiting': '等待招聘方回复',
    'assessment': '查看原通知并完成笔试／网测',
    'interview': '核对面试时间并准备面试',
    'offer': '阅读 Offer，核对回复要求',
    'closed': '',
}
PHASE = {'saved': 0, 'submitted': 1, 'waiting': 2, 'assessment': 3, 'interview': 4, 'offer': 5, 'closed': 6}
_MONTHS = {month: i for i, month in enumerate((
    'january february march april may june july august september october november december'
).split(), start=1)}
_MONTH = r'Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?'
_DATES = [
    re.compile(r'(?<!\d)(?P<y>20\d{2})(?:[-/.]|\s*年\s*)(?P<m>\d{1,2})(?:[-/.]|\s*月\s*)(?P<d>\d{1,2})(?:\s*[日号號])?(?!\d)', re.I),
    re.compile(r'(?<!\d)(?:(?P<y>20\d{2})\s+)?(?P<d>\d{1,2})(?:st|nd|rd|th)?[ ,\-]+(?P<english>' + _MONTH + r')\.?\b(?:[ ,\-]+(?P<y2>20\d{2})(?![:\d]))?', re.I),
    re.compile(r'\b(?P<english>' + _MONTH + r')\.?[ ,\-]+(?P<d>\d{1,2})(?:st|nd|rd|th)?\b(?:[ ,\-]+(?P<y>20\d{2})(?![:\d]))?', re.I),
    re.compile(r'(?<![\d年])(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号號]', re.I),
]
_CLOCK = re.compile(
    r'^[\s,T，]*(?:(?:at|on|time|时间|時間)\s*[:：]?\s*)?'
    r'(?:(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)[,. ]+|[（(](?:周|週|星期)[一二三四五六日天][）)]\s*)?'
    r'(?P<half>上午|下午|晚上|中午)?\s*(?P<h>\d{1,2})'
    r'(?:[:：](?P<minute>\d{2})(?::\d{2})?|[点點时時](?P<zhminute>\d{1,2})?\s*分?|(?=\s*[ap]\.?m\.?\b))'
    r'\s*(?P<meridiem>[ap]\.?m\.?)?(?!\d)', re.I)
_RELATIVE = re.compile(
    r'(?:(?:within|another|next|extended\s+(?:by|for)|延长|延長|额外|額外|接下[来來])\s*(?:the\s+next\s+|another\s+)?'
    r'(?P<n1>\d{1,3}|one|two|three|four|five|six|seven)\s*(?P<u1>business\s+days?|working\s+days?|calendar\s+days?|days?|hours?|小[时時]|[个個]?工作[日天]|天|日)|'
    r'(?P<n2>\d{1,3})\s*(?P<u2>小[时時]|[个個]?工作[日天]|天|日)\s*(?:内|內|之[内內]))', re.I)
_DEADLINE = re.compile(r'deadline|due(?:\s+(?:by|on|at))?|no later than|(?:complete|submit|respond|reply|finish)\b[^.\n]{0,80}\b(?:by|before|within)\b|closes?|expires?|cutoff|cut-off|截止|最[晚遲迟]|限期|[内內]完成|延[期至长長]|須於|须于|請於|请于', re.I)
_EVENT = re.compile(r'interview|面[试試]|date\s*/\s*time|面談|面谈', re.I)
_CANCELLED = re.compile(r'interview\s+(?:(?:has been|was|is)\s+)?cancel(?:led|ed)|已取消.{0,15}面[试試]|面[试試].{0,15}已取消', re.I)
_NOT_OLD = re.compile(r'previous(?:ly)?|original(?:ly)?|formerly|old (?:time|date)|原定|原时间|原時間|旧时|舊時', re.I)
_NEW = re.compile(r'rescheduled\s*(?:to|for)|new\s+(?:time|date|deadline)|updated\s+(?:time|date|deadline)|extended\s+to|改[为為到至]|新(?:时间|時間|日期|截止)|延期至|延長至|延长至|调整[至到为]|調整[至到為]', re.I)


def _clean(value):
    return str(value or '').strip()


def _utc(value):
    if isinstance(value, datetime):
        obj = value
    elif _clean(value):
        raw = _clean(value)
        try:
            obj = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            try:
                obj = parsedate_to_datetime(raw)
            except (ValueError, TypeError, OverflowError):
                return None
    else:
        return None
    if obj is None:
        return None
    return obj.replace(tzinfo=HKT) if obj.tzinfo is None else obj


def _norm(value):
    return ' '.join(unicodedata.normalize('NFKC', _clean(value)).casefold().split())


def _qid(value):
    return _norm(value)


def _strip_history(text):
    # Keep notices pasted or forwarded on their own; exclude quoted history after
    # the author has already written a meaningful status or schedule.
    lines = []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        if line.lstrip().startswith('>'):
            continue
        if re.match(r'\s*(?:-{2,}\s*(?:original message|forwarded message|转发邮件|轉寄郵件|原始邮件)|On .{8,} wrote:|在.+写道[:：])', line, re.I):
            previous = '\n'.join(lines)
            if _DEADLINE.search(previous) or _EVENT.search(previous):
                break
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def _completed(text):
    # Do not treat "not completed the assessment" or "if you completed
    # the assessment" as a completed round.
    for sentence in re.split(r'[。!\n]|\.(?:\s|$)', text):
        # A job named Test/Assessment is not the object of an application receipt.
        if re.search(r'\b(?:application|resume|cv)\b.{0,120}\b(?:submitted|received|completed)\b|(?:申请|申請|投递|投遞|简历|簡歷).{0,60}(?:已提交|已收到|已完成|提交成功)',sentence,re.I):
            continue
        if re.search(r'\b(?:not|never|if|once|yet to|must|should)\b|未.{0,10}(?:完成|提交)|如已|若已|请完成|請完成', sentence, re.I):
            continue
        if re.search(r'\b(?:assessment|test|hackerrank|codility)\s+(?:(?:has been|was|is)\s+)?(?:successfully\s+)?(?:submitted|completed)\b|(?:completed|submitted)\s+(?:the|your)\s+(?:online\s+)?(?:assessment|test)\b|(?:笔试|筆試|网测|網測|测评|測評)\s*(?:已完成|已提交|提交成功)', sentence, re.I):
            return True
    return False


def _status(text):
    if re.search(r'(?:if|should you|如未|若未|如果|若通过|若通過|通过后|通過後|逾期)[^.!。\n]{0,100}', text, re.I):
        # Conditional warnings (e.g. noncompletion *will* result in withdrawal)
        # are not confirmed rejection evidence.
        text = re.sub(r'(?:\bif\b|should you|如未|若未|如果|若通过|若通過|通过后|通過後|逾期)[^.!。\n]{0,180}', '', text, flags=re.I)
    if re.search(r'not (?:be |been )?(?:shortlisted|selected|progress(?:ed|ing)?)|will not (?:be moving|move|proceed|progress)|unsuccessful|regret to inform.{0,100}application|application (?:has been |was |is )?(?:rejected|closed|withdrawn)|position (?:has been |was )?filled|未(?:能)?通过|未(?:能)?通過|未入围|未入圍|不再推进|不再推進|流程终止|流程終止|已拒绝|已拒絕|已撤回|很遗憾[^。]{0,70}(?:未|无法)|很遺憾[^。]{0,70}(?:未|無法)', text, re.I):
        return 'closed', True, 'high'
    if re.search(r'offer (?:letter|of employment)|pleased to offer|(?:would like to|delighted to) offer you (?:the|a) (?:role|position|internship)|formal offer|录用通知|錄用通知|正式\s*offer|实习录用|實習錄用', text, re.I):
        return 'offer', True, 'high'
    if _CANCELLED.search(text):
        return 'interview', True, 'medium'
    if re.search(r'interview (?:invitation|confirm(?:ation|ed)|reschedul\w+|(?:has been|was|is)\s+(?:rescheduled|scheduled|confirmed))|(?:reschedul\w+|confirm\w+|invit\w+|join|attend|schedule\w*)[^.!。\n]{0,95}\binterview\b|(?:Date\s*/\s*Time|interviewer)\s*[:：]|面[试試](?:通[知告]|邀请|邀請|安排|改期|确认|確認|时间|時間)|邀[请請][^。]{0,30}面[试試]|面談通知', text, re.I):
        return 'interview', True, 'high'
    if _completed(text):
        return 'waiting', True, 'high'
    if re.search(r'online assessment|online test|coding (?:challenge|assessment|test)|assessment (?:invitation|reopened|deadline|extension)|hackerrank|codility|网测|網測|笔试|筆試|在线测评|在線測評', text, re.I):
        return 'assessment', True, 'high'
    if re.search(r'(?:application|resume|cv)\b[^.\n]{0,30}\b(?:received|submitted|under review)|(?:received|reviewing)\b[^.\n]{0,25}\b(?:application|resume|cv)|thank you for applying|已收到.{0,15}(?:申请|申請|投递|投遞|简历|簡歷)|感谢.{0,8}投递|感謝.{0,8}投遞|投[递遞]成功|审核中|審核中', text, re.I):
        return 'waiting', True, 'high'
    return 'waiting', False, 'low'


def _identity(text, company, title, requisition):
    fields = {}
    labels = {
        'company': r'company|employer|organization|organisation|公司名称|公司名稱|公司|雇主',
        'title': r'job title|job|position|role|申请岗位|申請崗位|岗位名称|崗位名稱|岗位|崗位|职位|職位',
        'requisition': r'requisition(?:\s*(?:id|number|no\.?))?|job\s*(?:id|reference|no\.?)|vacancy\s*(?:id|number)|岗位编号|崗位編號|职位编号|職位編號|招聘编号|招聘編號',
    }
    for key, provided in [('company', company), ('title', title), ('requisition', requisition)]:
        found = re.search(r'^\s*(?:' + labels[key] + r')\s*[:：#]\s*([^\n]{1,150})', text, re.I | re.M)
        fields[key] = _clean(provided or (found[1] if found else ''))
    if not fields['company']:
        # Prefer explicit body signatures over guessing by an email domain,
        # which often belongs to a portal or recruiting agency.
        found = re.search(r'^\s*([^\n:：]{2,60}?)\s+(?:campus recruiting|talent acquisition|graduate recruitment|early careers|recruiting|recruitment|careers|HR)(?:\s+team)?\s*$', text, re.I | re.M)
        if not found:
            found = re.search(r'^\s*([^\n:：]{2,40}?)(?:人才招聘部|校招团队|校招團隊|招聘团队|招聘團隊|人力资源部|人力資源部)\s*$', text, re.M)
        inferred = _clean(found[1] if found else '')
        if re.search(r'[.。!?？]|^(?:dear|thanks?|best|the|campus|talent|grad(?:uate)?|early|hr|人力|招聘)\b', inferred, re.I):
            inferred = ''
        fields['company'] = inferred
    if not fields['requisition']:
        found = re.search(r'\b(?:requisition(?:\s+(?:id|number|no\.?))?|job id|vacancy id)\s*[:#：]?\s*((?:[A-Z]{1,8}[-_])?\d{3,}(?:[-_]\w+)?)\b', text, re.I)
        if not found:
            found = re.search(r'\b(JR[-_]\d{4,})\b', text, re.I)
        fields['requisition'] = _clean(found[1] if found else '')
    if not fields['title']:
        found = re.search(r'\b(?:position of|role of|your application for (?:the )?(?:position|role) of|applied for(?: the position of)?)\s*[:：]?\s*([^\n.!。]{3,100})', text, re.I)
        # Companies sometimes prefix this text with the job ID.
        inferred = re.sub(r'^JR[-_]\d{4,}\s*[-:：]?\s*', '', _clean(found[1] if found else ''), flags=re.I)
        fields['title'] = re.split(r'\s*(?:[,;；，]|\s+at\s+|\s+has\s+been\s+|\s+was\s+|\s+in\s+Hong Kong)', inferred, maxsplit=1, flags=re.I)[0].strip()
    return fields


def _date_hits(line, received):
    hits = []
    for exp in _DATES:
        for m in exp.finditer(line):
            if any(start <= m.start() < end or start < m.end() <= end for start, end, *_ in hits):
                continue
            parts = m.groupdict()
            explicit = parts.get('y') or parts.get('y2')
            if not explicit and not received:
                hits.append((m.start(), m.end(), '', 'unknown', '日期缺少年份，且未提供收件日期。'))
                continue
            y = int(explicit) if explicit else received.astimezone(HKT).year
            english = parts.get('english')
            mo = int(parts['m']) if not english else next(i for name, i in _MONTHS.items() if name.startswith(english[:3].lower()))
            try:
                day = date(y, mo, int(parts['d']))
                if not explicit and received and day < received.astimezone(HKT).date() - timedelta(days=31):
                    day = day.replace(year=y + 1)
            except ValueError:
                continue
            after = line[m.end():]
            clock = _CLOCK.search(after)
            note = '' if explicit else '年份根据收件日期推算，请核对。'
            if not clock:
                hits.append((m.start(), m.end(), day.isoformat(), 'date', note))
                continue
            hour = int(clock['h'])
            minute = int(clock['minute'] or clock['zhminute'] or 0)
            meridiem = (clock['meridiem'] or '').lower().replace('.', '')
            half = clock['half']
            if meridiem or half:
                if not 1 <= hour <= 12:
                    continue
                if meridiem == 'pm' or half in ('下午', '晚上', '中午'):
                    hour = hour % 12 + 12
                elif meridiem == 'am' or half == '上午':
                    hour %= 12
            if hour > 23 or minute > 59:
                continue
            remainder = after[clock.end():]
            # Look after the first clock and optional displayed range; the
            # shared offset is usually at the end of a conference invitation.
            candidate = re.split(r'[;；。]|\.\s|\s,\s', remainder, maxsplit=1)[0][:44]
            offset = re.search(r'(?:GMT|UTC)\s*([+-])(\d{1,2})(?::?(\d{2}))?', candidate, re.I)
            trailing_offset = re.match(r'\s*([+-])(\d{2}):?(\d{2})\b', candidate)
            zone = HKT
            # A range such as 14:00-15:00 is not a UTC offset; only
            # recognise a bare signed offset on an ISO-style timestamp.
            raw = offset or (trailing_offset if after.startswith('T') and not meridiem else None)
            if raw:
                hh, mm = int(raw[2]), int(raw[3] or 0)
                if hh < 24 and mm < 60:
                    zone = timezone(timedelta(hours=hh, minutes=mm) * (1 if raw[1] == '+' else -1))
            elif re.search(r'\b(?:UTC|GMT)\b', candidate, re.I) or (after.startswith('T') and candidate.startswith('Z')):
                zone = timezone.utc
            elif re.search(r'\b(?:EST|EDT|PST|PDT|BST|CST|IST|CEST|CET)\b', candidate):
                hits.append((m.start(), m.end() + clock.end(), '', 'unknown', '时区缩写不明确，请手动核对。'))
                continue
            elif not re.search(r'HKT|香港|北京|北京时间|北京時間|GMT\+8|UTC\+8|SGT', candidate, re.I):
                note = ' '.join(filter(None, (note, '未写明时区，暂按香港时间。')))
            stamp = datetime.combine(day, time(hour, minute), zone).astimezone(HKT)
            precision = 'estimated' if note else 'exact'
            hits.append((m.start(), m.end() + clock.end(), stamp.isoformat(timespec='minutes'), precision, note))
    return sorted(hits)


def _date_candidates(text, status, received):
    warnings = []
    by_field = {'deadline': [], 'interview_at': []}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        # In a multi-line template the heading may carry the context.
        prev = lines[i - 1].strip() if i else ''
        context = line if _DEADLINE.search(line) or _EVENT.search(line) or len(prev) > 65 else prev + ' ' + line
        deadline = bool(_DEADLINE.search(context))
        event = bool(_EVENT.search(context)) or (status == 'interview' and bool(re.search(r'(?:new |updated )?(?:date|time|日期|时间|時間)\s*[:：]', context, re.I)))
        hits = _date_hits(line, received)
        for start, _, value, precision, note in hits:
            prefix = line[:start]
            nearest_new = list(_NEW.finditer(prefix))
            nearest_old = list(_NOT_OLD.finditer(prefix))
            old = nearest_old and (not nearest_new or nearest_old[-1].end() > nearest_new[-1].end())
            if old:
                continue
            priority = 2 if nearest_new or _NEW.search(context) and len(hits) == 1 else 1
            if not value:
                if (deadline or event) and note:
                    warnings.append(note)
                continue
            before = prefix if context == line else prev + ' ' + prefix
            previous_deadline = list(_DEADLINE.finditer(before))
            previous_event = list(_EVENT.finditer(before))
            if previous_deadline and previous_event and status == 'interview':
                field = 'deadline' if previous_deadline[-1].end() > previous_event[-1].end() else 'interview_at'
            elif previous_event and event and status == 'interview':
                field = 'interview_at'
            else:
                field = 'deadline' if deadline else 'interview_at' if event and status == 'interview' else None
            if field:
                by_field[field].append((priority, value, precision, note))
    for m in _RELATIVE.finditer(text):
        if not _DEADLINE.search(text) and status not in ('assessment', 'offer'):
            continue
        number = _norm(m['n1'] or m['n2'])
        count = int(number) if number.isdigit() else ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven'].index(number)
        unit = _norm(m['u1'] or m['u2'])
        if not received:
            warnings.append('相对期限需要已核实的通知时间，未自动填入截止日期。')
            continue
        if re.search(r'business|working|工作', unit):
            warnings.append('工作日期限依赖招聘方工作日历，未自动推算。')
            continue
        if not count or count > 366:
            continue
        priority = 2 if re.search(r'another|extend|延[长長]|[额額]外', m[0], re.I) else 1
        if 'hour' in unit or re.search('小[时時]', unit):
            guessed = (received.astimezone(HKT) + timedelta(hours=count)).isoformat(timespec='minutes')
        else:
            guessed = (received.astimezone(HKT).date() + timedelta(days=count)).isoformat()
        by_field['deadline'].append((priority, guessed, 'estimated', '按通知时间推算；属于估算，以原邮件或招聘系统为准。'))
    result, precisions = {}, {}
    for field, vals in by_field.items():
        # A concrete deadline outweighs a relative estimate of the same priority.
        best = max(((row[0], row[2] != 'estimated') for row in vals), default=(0, False))
        shortlist = [row for row in vals if (row[0], row[2] != 'estimated') == best]
        unique = {row[1]: row for row in shortlist}
        if len(unique) == 1:
            _, value, precision, note = next(iter(unique.values()))
            result[field], precisions[field] = value, precision
            if note:
                warnings.append(note)
        else:
            result[field], precisions[field] = '', 'unknown'
            if len(unique) > 1:
                warnings.append('检测到多个可能的截止时间，请手动确认。' if field == 'deadline' else '检测到多个可能的面试时间，请手动确认。')
    return result, precisions, list(dict.fromkeys(warnings))


def parse_notice(text, received_at=None, source_url='', company='', title='', requisition=''):
    """Return an editable notice preview with no side effects."""
    notice = _parse_text(text, received_at, source_url, company, title, requisition)
    if not notice['completion'] and notice['status'] != 'assessment':
        return notice
    parts = [{'source': '粘贴通知当前正文', 'text': _mail_scope(text)}]
    parsed = _parse_notice_parts(parts, received_at, source_url, company, title, requisition,
                                 legacy_fingerprint=notice['fingerprint'])
    if notice['completion'] or (parsed['assessment_id'] and parsed['status'] == 'assessment'):
        return parsed
    return notice


def _parse_text(text, received_at=None, source_url='', company='', title='', requisition=''):
    original = _clean(text)
    active = _strip_history(unicodedata.normalize('NFKC', original))
    received = _utc(received_at)
    warnings = []
    if _clean(received_at) and not received:
        warnings.append('无法识别收件时间，请使用带时区的 ISO 日期时间。')
    status, explicit, confidence = _status(active)
    identity = _identity(active, company, title, requisition)
    # Completion acknowledgments clear the test due date only when confirmed.
    completion = explicit and status == 'waiting' and _completed(active)
    dates, precisions, date_warnings = _date_candidates(active, status, received)
    warnings.extend(date_warnings)
    if not identity['company'] or not (identity['title'] or identity['requisition']):
        warnings.append('公司或岗位标识不完整；请选择已有投递或手动补充，避免误合并。')
    if not explicit:
        warnings.append('未识别到明确的流程状态，请人工确认。')
    cancelled = status == 'interview' and bool(_CANCELLED.search(active)) and not dates['interview_at']
    if cancelled:
        warnings.append('面试取消不等于流程终止；请联系招聘方核对是否另行安排。')
    # Identical notices pasted twice remain idempotent. Detect a resend of an
    # equal relative-date template as distinct only if the resolved date differs.
    relative_key = dates.get('deadline') if _RELATIVE.search(active) else ''
    fp = sha256(json.dumps([_norm(active), _norm(identity['company']), _norm(identity['title']),
                            _qid(identity['requisition']), relative_key], ensure_ascii=False).encode('utf-8')).hexdigest()
    return {**identity, **dates, 'status': status, 'next_action': ('确认是否还有下一轮安排' if completion else '向招聘方确认是否重新安排面试' if cancelled else STATUS_ACTION[status]) if explicit else '',
            'evidence':[{'source':'粘贴通知当前正文','field':'text','value':'','quote':_mail_scope(original)[:800]}] if original else [],
            'confidence': confidence, 'has_explicit_status': explicit, 'completion': completion,
            'interview_cancelled': cancelled,
            'rescheduled': bool(re.search(r'reschedul|改期|重新安排',active,re.I)),
            'sent_precision': 'date' if len(_clean(received_at))==10 else 'exact' if received else 'unknown',
            'date_precision': precisions, 'notes': '\n'.join(warnings), 'warnings': warnings,
            'received_at': received.astimezone(HKT).isoformat(timespec='seconds') if received else '',
            'source_url': _clean(source_url), 'fingerprint': fp}


class _EmailHTML(HTMLParser):
    """Text only: attributes/URLs are never fetched, rendered, or used as IDs."""
    BLOCK = {'br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'section', 'article'}
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    IGNORE = {'script', 'style', 'head', 'template', 'noscript', 'iframe', 'svg', 'object', 'blockquote', 'a'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        hidden = ('hidden' in attr or str(attr.get('aria-hidden', '')).lower() == 'true'
                  or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attr.get('style') or '', re.I)
                  or re.search(r'gmail_quote|yahoo_quoted', attr.get('class') or '', re.I))
        skip = bool(self.stack and self.stack[-1][1]) or tag in self.IGNORE or bool(hidden)
        if not skip and tag in self.BLOCK:
            self.parts.append('\n')
        if not skip and tag in {'td', 'th'}:
            self.parts.append(' ')
        if tag not in self.VOID:
            self.stack.append((tag, skip))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        # Recover from malformed HTML conservatively, without executing anything.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if not (self.stack and self.stack[-1][1]) and tag in self.BLOCK:
            self.parts.append('\n')
        if tag in {'td', 'th'}:
            self.parts.append(' ')

    def handle_data(self, data):
        if not (self.stack and self.stack[-1][1]):
            self.parts.append(re.sub(r'[\t\r\n ]+', ' ', data))


def _mail_scope(text):
    """Only the current decision body; drop links, recommendations and history."""
    text = unicodedata.normalize('NFKC', str(text))
    lines = []
    for line in text.splitlines():
        if re.search(r'(?i)(?:recommended|suggested) (?:jobs|roles|positions|opportunities|vacancies)|other (?:jobs|roles|opportunities)|'
                     r'you (?:may|might) (?:also )?(?:like|be interested|consider)|similar (?:jobs|roles)|'
                     r'推荐职位|推荐岗位|推薦職位|其他职位|其他岗位|其他職位|unsubscribe|取消订阅|取消訂閱|'
                     r'--+\s*(?:original message|forwarded message|转发邮件|轉寄郵件|原始邮件|原始郵件)|^On .+ wrote:|^在.+写道', line):
            break
        if line.lstrip().startswith('>'):
            continue
        # URL text and tracking parameters cannot supply identity or evidence.
        line = re.sub(r'(?:https?://|www\.)[^\s<>]+', ' [链接已省略] ', line, flags=re.I)
        line = re.sub(r'(?i)\b(?:utm_[a-z_]+|gclid|fbclid|gh_src|tracking_id|token)=[^\s<>]+', '[跟踪参数已省略]', line)
        lines.append(line.strip())
    return '\n'.join(line for line in lines if line)


_MAIL_LABELS = {
    'company': r'company|employer|organization|organisation|公司名称|公司名稱|公司|雇主',
    'title': r'job title|position|role|申请岗位|申請崗位|岗位名称|崗位名稱|岗位|崗位|职位|職位',
    'requisition': r'requisition(?:\s*(?:id|number|no\.?))?|job\s*(?:id|reference|no\.?)|vacancy\s*(?:id|number)|岗位编号|崗位編號|职位编号|職位編號|招聘编号|招聘編號',
}


def _mail_identity(text):
    fields, evidence, conflicts = {}, [], []
    for field, label in _MAIL_LABELS.items():
        hits = [(m[1].strip(), m[0].strip()) for m in re.finditer(
            r'^\s*(?:' + label + r')\s*[:：#]\s*([^\n]{1,150})$', text, re.I | re.M)]
        # A narrative title must explicitly describe this application, not a bare ID.
        if not hits and field == 'title':
            for m in re.finditer(r'(?:your application for (?:the )?(?:(?:position|role) of )?|'
                                 r'position of |role of |applied for (?:the position of )?)'
                                 r'([^\n.!。;；]{3,100})', text, re.I):
                value = re.split(r'\s+(?:at|has been|was|is)\s+|[,，]', m[1], maxsplit=1, flags=re.I)[0].strip()
                hits.append((value, m[0]))
        if not hits and field == 'company':
            inferred = _identity(text, '', '', '')['company']
            if inferred:
                hits.append((inferred, next((line for line in text.splitlines() if inferred in line), inferred)))
        # ID must be an explicit field in the current body, never bare JR-... text.
        hits = [(v, q) for v, q in hits if '[链接已省略]' not in v]
        unique = {_norm(v): v for v, _ in hits}
        fields[field] = next(iter(unique.values())) if len(unique) == 1 else ''
        if len(unique) > 1:
            conflicts.append('正文包含多个不同的' + {'company': '公司', 'title': '岗位', 'requisition': '岗位编号'}[field])
        evidence.extend({'field': field, 'value': v, 'quote': q[:250]} for v, q in hits)
    return fields, evidence, conflicts


def parse_eml(raw: bytes):
    """Decode BOTH plain/HTML alternatives locally; attachments are not evidence."""
    if not isinstance(raw, bytes) or not raw:
        raise ValueError('请选择一个非空的 .eml 文件。')
    if len(raw) > 5_000_000:
        raise ValueError('.eml 文件不能超过 5 MB。')
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = _mail_scope(_clean(msg.get('Subject', '')))
    sender = _clean(msg.get('From', ''))
    if not any((subject, sender, msg.get('Date'), msg.get('MIME-Version'))):
        raise ValueError('文件不含可识别的邮件头；可以改用粘贴文本。')
    date_header = msg.get('Date', '')
    header_time = getattr(date_header, 'datetime', None)
    anchor = header_time if header_time and header_time.tzinfo is not None else None
    bodies = []
    for kind in ('plain', 'html'):
        body = msg.get_body(preferencelist=(kind,))
        if body is None or body.get_content_disposition() == 'attachment':
            continue
        try:
            contents = body.get_content()
        except (LookupError, UnicodeError):
            contents = (body.get_payload(decode=True) or b'').decode('utf-8', errors='replace')
        if kind == 'html':
            parser = _EmailHTML()
            parser.feed(contents)
            parser.close()
            contents = ''.join(parser.parts)
        contents = _mail_scope(contents)
        if len(contents) > 150000:
            raise ValueError('邮件正文过长，请截取当前通知正文后粘贴。')
        if contents:
            bodies.append({'source': 'HTML 正文' if kind == 'html' else '纯文本正文', 'text': contents})
    # Compatibility text is only for display/legacy callers; reconciliation uses bodies.
    richest = max(bodies, key=lambda b: (sum(bool(v) for v in _mail_identity(b['text'])[0].values()),
                                        _status(b['text'])[1], len(b['text'])), default={'text': ''})
    text = '\n'.join(filter(None, [subject, richest['text']]))
    return {'text': text, 'bodies': bodies,
            'received_at': anchor.astimezone(HKT).isoformat(timespec='seconds') if anchor else '',
            'subject': subject, 'sender': sender, 'message_id': _clean(msg.get('Message-ID', ''))}


def parse_eml_notice(mail, received_at=None, source_url='', company='', title='', requisition=''):
    """Conservative MIME reconciliation with quoted, inert, scoped evidence."""
    parts = ([{'source': '邮件主题', 'text': mail['subject']}] if mail.get('subject') else []) + mail.get('bodies', [])
    notice = _parse_notice_parts(parts, received_at or mail.get('received_at'), source_url, company, title, requisition)
    notice['is_eml'] = True
    return notice


def _parse_notice_parts(parts, received_at, source_url, company, title, requisition, legacy_fingerprint=None):
    evidence, reasons, candidates = [], [], []
    identities = {k: {} for k in _MAIL_LABELS}
    states = set()
    for part in parts:
        text = part['text']
        identity, quotes, conflicts = _mail_identity(text)
        reasons.extend(conflicts)
        evidence.extend({**q, 'source': part['source']} for q in quotes)
        for key, value in identity.items():
            if value:
                identities[key][_norm(value)] = value
        parsed = _parse_text(text, received_at=received_at)
        candidates.append(parsed)
        # Check sentences independently so one MIME representation cannot silently
        # win by the parser's status precedence. Generic footer has no status.
        for line in re.split(r'\n|(?<=[.!。])\s+', text):
            if re.match(r'^\s*(?:' + '|'.join(_MAIL_LABELS.values()) + r')\s*[:：#]', line, re.I):
                continue
            status, explicit, _ = _status(line)
            if explicit:
                states.add(status)
                evidence.append({'source': part['source'], 'field': 'status', 'value': status, 'quote': line[:250]})
    identity = {}
    for key, values in identities.items():
        if len(values) > 1:
            reasons.append('邮件各部分的' + {'company': '公司', 'title': '岗位', 'requisition': '岗位编号'}[key] + '不一致')
        identity[key] = next(iter(values.values())) if len(values) == 1 else ''
    for key, value in [('company', company), ('title', title), ('requisition', requisition)]:
        if _clean(value):
            # User-supplied context is visible evidence, never an implicit sender guess.
            value = _mail_scope(value).replace('\n', ' ')[:150]
            evidence.append({'source': '手动提供', 'field': key, 'value': value, 'quote': value})
            if identities[key] and _norm(value) not in identities[key]:
                reasons.append('手动提供的身份与邮件正文不一致')
            identity[key] = value
    if any(p.get('interview_cancelled') for p in candidates) and any(p['has_explicit_status'] and p['status']=='interview' and not p.get('interview_cancelled') for p in candidates):
        reasons.append('邮件各部分对面试取消或确认的描述冲突')
    if len(states) > 1:
        reasons.append('邮件主题或 MIME 正文状态冲突，请逐项核对原通知')
    if not identity['company'] or not (identity['title'] or identity['requisition']):
        reasons.append('仅有雇主或岗位身份不完整，不能建议关联')
    title_value = identity['title']
    if not identity['requisition'] and (re.fullmatch(r'[A-Z]{2,8}(?:\s+(?i:intern|graduate|trainee))?', title_value)
            or _norm(title_value) in {'intern', 'trainee', 'graduate', '实习生', '校招生'}
            or re.search(r'\sor\s|[/／]|或', title_value, re.I)):
        reasons.append('岗位名称为缩写、泛称或多个可能岗位，请人工确认')
    if not states:
        reasons.append('未识别到明确状态，请人工确认')
    status = next(iter(states)) if len(states) == 1 else 'waiting'
    chosen = next((p for p in candidates if p['has_explicit_status'] and p['status'] == status), None)
    notice = dict(chosen or _parse_text('', received_at=received_at))
    # Never borrow a date from the alternative silently when it disagrees.
    for field in ('deadline', 'interview_at'):
        vals = {p[field] for p in candidates if p[field]}
        if len(vals) > 1:
            reasons.append('邮件各部分的日期不一致，请人工核对')
        elif len(vals) == 1:
            value = next(iter(vals)); notice[field] = value
            notice['date_precision'][field] = next(p['date_precision'][field] for p in candidates if p[field] == value)
    assessment_relative = 'assessment' in states and any(_RELATIVE.search(p['text']) for p in parts)
    assessment_ids = {}
    for part in parts:
        for line in part['text'].splitlines():
            hit=re.fullmatch(r'\s*(?:Assessment ID|Test ID|测评编号|測評編號|测试编号)\s*[:：]\s*([A-Za-z0-9_-]{2,80})\s*',line,re.I)
            if hit:
                assessment_ids[_norm(hit[1])]=hit[1]
                evidence.append({'source':part['source'],'field':'assessment_id','value':hit[1],'quote':line[:180]})
    assessment_id=next(iter(assessment_ids.values())) if len(assessment_ids)==1 else ''
    if assessment_relative and (not assessment_id or not notice.get('received_at') or notice.get('sent_precision')!='exact'):
        reasons.append('测评相对期限缺少唯一测评编号或可信发送时间，须复核；不自动更新截止估计')
    notice.update(assessment_relative=assessment_relative,assessment_id=assessment_id,
        assessment_completion=any(p.get('completion') for p in candidates))
    if assessment_relative:
        evidence.append({'source':'发送时间与正文相对期限','field':'deadline','value':notice.get('deadline',''),
            'quote':'发送 '+str(notice.get('received_at') or '未知')+'；推算截止 '+str(notice.get('deadline') or '未知')+'（估算，非精确截止）'})
    reasons = list(dict.fromkeys(reasons))
    notice.update(identity)
    unique_evidence={}
    for item in evidence:
        unique_evidence.setdefault((item['source'],item['field'],_norm(item['value'])),item)
    evidence=sorted(unique_evidence.values(),key=lambda e:e['field']!='status')
    notice.update(requires_review=bool(reasons), evidence=evidence[:40], source_url=_clean(source_url))
    notice['status'] = status
    notice['has_explicit_status'] = len(states) == 1 and not reasons
    notice['confidence'] = 'low' if reasons else 'high'
    notice['warnings'] = list(dict.fromkeys(reasons + [w for p in candidates for w in p['warnings'] if '岗位标识不完整' not in w and '未识别到明确的流程状态' not in w]))
    notice['notes'] = '\n'.join(notice['warnings'])
    if reasons:
        notice.update(status='waiting', deadline='', interview_at='', next_action='', completion=False, interview_cancelled=False)
        notice['date_precision'] = {}
    notice['legacy_fingerprint'] = legacy_fingerprint or sha256(json.dumps([parts, identity, notice.get('deadline')], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    notice['fingerprint'] = sha256(json.dumps([notice['legacy_fingerprint'],notice.get('received_at','')]).encode()).hexdigest()
    return notice


def application_chronology(notice, application):
    """Compare sent time to user-entered submission only; never creation/event time."""
    raw=application.get('submitted_at','')
    sent=_utc(notice.get('received_at'))
    submitted=_utc(raw)
    if not sent or not submitted or notice.get('sent_precision') in ('date','unknown'):
        return 'unknown'
    if len(str(raw))==10:
        # A day denotes an interval in Hong Kong, not midnight precision.
        end=submitted+timedelta(days=1)
        return 'conflict' if sent<submitted else 'unknown' if sent<end else 'ok'
    return 'conflict' if sent<submitted else 'ok'


def match_application(notice, applications):
    """Exact company plus exact requisition preferred; never match on sender."""
    if notice.get('requires_review'):
        return {'match_id': None, 'matches': [], 'ambiguous': True, 'reason': '邮件证据需复核，不预选投递记录'}
    company, title, req = (_norm(notice.get('company')), _norm(notice.get('title')), _qid(notice.get('requisition')))
    if not company or not (title or req):
        return {'match_id': None, 'matches': [], 'ambiguous': False, 'reason': '缺少公司或岗位标识'}
    same_company = [a for a in applications if _norm(a.get('company')) == company]
    exact = [a for a in same_company if req and _qid(a.get('requisition')) == req]
    verify_history = notice.get('is_eml') or notice.get('assessment_completion')
    if verify_history and exact and title and any(_norm(a.get('title')) != title for a in exact):
        return {'match_id': None, 'matches': [], 'ambiguous': True, 'reason': '邮件编号与台账岗位名称冲突，必须人工复核'}
    reason = '公司与岗位编号一致'
    if not exact and title:
        titled = [a for a in same_company if _norm(a.get('title')) == title]
        can_backfill = len(titled) == 1 and not _qid(titled[0].get('requisition'))
        exact = titled if not req or can_backfill else []
        reason = '公司与岗位名称唯一一致'
    if verify_history and exact:
        checks=[application_chronology(notice,a) for a in exact]
        eligible=[a for a,check in zip(exact,checks) if check=='ok']
        if len(eligible)!=len(exact):
            return {'match_id':None,'matches':[a.get('id') for a in exact], 'ambiguous':True,
                    'reason':'邮件发送早于实际投递，或发送/投递时间缺失及精度不足；保留候选供人工复核，不预选'}
    matches = [a.get('id') for a in exact]
    return {'match_id': matches[0] if len(matches) == 1 else None,
            'matches': matches, 'ambiguous': len(matches) > 1,
            'reason': reason if len(matches) == 1 else '找到多条历史记录，必须人工选择' if matches else '无足够一致的已有记录'}


def apply_notice(notice, application_or_none):
    """Reconcile a confirmed notice without losing history or regressing state."""
    out = dict(application_or_none or {})
    if notice.get('review_only'):
        return {**out, 'update_applied': False, 'warnings': ['已复核但未选择新状态，仅记录历史，不变更投递。']}
    warnings = []
    if notice.get('fingerprint') and out.get('last_notice_fingerprint') == notice['fingerprint']:
        return {**out, 'update_applied': False, 'warnings': ['这条通知已处理。']}
    prev_time, new_time = _utc(out.get('last_notice_at')), _utc(notice.get('received_at'))
    if prev_time and new_time and new_time < prev_time:
        return {**out, 'update_applied': False, 'warnings': ['这条通知早于已处理的通知，只记录历史。']}
    prior_slot, incoming_slot = _utc(out.get('interview_at')), _utc(notice.get('interview_at'))
    if prior_slot and incoming_slot and incoming_slot<prior_slot and not notice.get('rescheduled'):
        return {**out,'update_applied':False,'warnings':['通知提到更早的面试安排且没有明确改期证据，仅记录历史，请人工核对。']}
    old_status = out.get('status') or 'saved'
    new_status = notice.get('status') if notice.get('has_explicit_status', True) else ''
    if not out:
        out['status'] = 'waiting'
    if prev_time and not new_time and old_status in ('assessment', 'interview', 'offer', 'closed'):
        return {**out, 'update_applied': False, 'warnings': ['缺少收件时间，不能覆盖较新的流程记录；请核对后在投递台账手动修改。']}
    # A test-completion receipt may transition the test to waiting, but must
    # not erase a later interview/offer. Closed is terminal; use manual edit
    # to explicitly reopen a confirmed closed application.
    completion_after_assessment = notice.get('completion') and old_status == 'assessment'
    if new_status and not completion_after_assessment and PHASE.get(new_status, -1) < PHASE.get(old_status, 0):
        return {**out, 'update_applied': False, 'warnings': ['通知状态早于当前流程，只记录历史。']}
    # Do not interpret a newer but date-less notification as confirmation of
    # any previously unknown schedule. Do not erase manually entered identity.
    for key in ('company', 'title', 'requisition'):
        if notice.get(key) and not out.get(key):
            out[key] = notice[key]
    precision = dict(out.get('date_precision') or {})
    if new_status in PHASE:
        if new_status != old_status:
            if old_status == 'assessment' or new_status == 'closed':
                out['deadline'] = ''
                precision.pop('deadline', None)
            if new_status in ('offer', 'closed'):
                out['interview_at'] = ''
                precision.pop('interview_at', None)
        out['status'] = new_status
        if notice.get('next_action') or new_status == 'closed':
            out['next_action'] = notice.get('next_action', '')
    if new_status not in ('closed',) and not completion_after_assessment:
        for key in ('deadline', 'interview_at'):
            if notice.get(key):
                out[key] = notice[key]
                precision[key] = (notice.get('date_precision') or {}).get(key, 'unknown')
    elif completion_after_assessment:
        out['deadline'] = ''
        precision.pop('deadline', None)
    if new_status == 'interview' and notice.get('interview_cancelled'):
        out['interview_at'] = ''
        precision.pop('interview_at', None)
    out['date_precision'] = precision
    if notice.get('source_url'):
        out['source_url'] = notice['source_url']
    if new_time and (new_status or any(notice.get(k) for k in ('deadline','interview_at'))):
        out['last_notice_at'] = new_time.astimezone(HKT).isoformat(timespec='seconds')
    if notice.get('fingerprint'):
        out['last_notice_fingerprint'] = notice['fingerprint']
    return {**out, 'update_applied': True, 'warnings': warnings}
