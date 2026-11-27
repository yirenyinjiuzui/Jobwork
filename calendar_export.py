"""Generate local RFC 5545 iCalendar files without calendar account access."""
from datetime import date, datetime, timezone
from hashlib import sha256
import re

from workbench import HK

_DEADLINE = {
    'saved': '申请截止', 'assessment': '笔试／网测截止',
    'offer': 'Offer 回复截止'
}

def _clean(value):
    value=str(value or '').replace('\r\n','\n').replace('\r','\n')
    return ''.join(c for c in value if c in ('\n','\t') or (ord(c)>=32 and ord(c)!=127))

def _escape(value):
    return (_clean(value).replace('\\','\\\\').replace('\n','\\n')
            .replace(';','\\;').replace(',','\\,'))

def _fold(line):
    chunks=[]
    body=''
    size=0
    for char in line:
        n=len(char.encode('utf-8'))
        if size+n>75:
            chunks.append(body)
            body=' '
            size=1
        body+=char
        size+=n
    chunks.append(body)
    return '\r\n'.join(chunks)

def _timestamp(dt):
    if not dt.tzinfo:
        dt=dt.replace(tzinfo=HK)
    d=dt.astimezone(timezone.utc)
    return d.strftime('%Y%m%dT%H%M%SZ')

def _start(value):
    source=str(value or '')
    try:
        if re.fullmatch(r'\d{4}-\d\d-\d\d',source):
            day=date.fromisoformat(source)
            return 'DTSTART;VALUE=DATE:'+day.strftime('%Y%m%d'), True
        if source:
            start=datetime.fromisoformat(source.replace('Z','+00:00'))
            return 'DTSTART:'+_timestamp(start), False
    except ValueError:
        pass
    return None,False

def export_application(application, namespace='', clock=None):
    kind=application.get('status')
    scheduled=[]
    if kind in _DEADLINE:
        scheduled.append(('deadline',_DEADLINE[kind]))
    if kind=='interview':
        scheduled.append(('interview_reply_by','面试回复截止'))
        scheduled.append(('interview_at','面试'))
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Job Workbench//Application Dates//ZH-CN','CALSCALE:GREGORIAN','METHOD:PUBLISH']
    company=application.get('company','')
    title=application.get('title','')
    precision=application.get('date_precision') or {}
    dtstamp=_timestamp(clock or datetime.now(timezone.utc))
    count=0
    for field, event_name in scheduled:
        start, whole_day=_start(application.get(field))
        if not start:
            continue
        count+=1
        estimate=precision.get(field)=='estimated'
        summary=f'{event_name}：{company} · {title}'
        if estimate:
            summary+='（推算，请核对）'
        if whole_day:
            summary+='（未注明时刻）'
        details=[]
        if application.get('requisition'):
            details.append('岗位编号：'+str(application['requisition']))
        if application.get('next_action'):
            details.append('下一步：'+str(application['next_action']))
        if estimate:
            details.append('这个时间由通知推算，不是招聘方确认的精确时间。')
        if whole_day:
            details.append('原记录未注明时刻；仅占位，请核对原通知。')
        details.append('手动导出，不会自动接收改期。')
        identity=sha256(f'{namespace}|{application.get("id")}|{field}'.encode()).hexdigest()[:32]
        lines+=['BEGIN:VEVENT',f'UID:{identity}@job-workbench.local',f'DTSTAMP:{dtstamp}',start,
                'CLASS:PRIVATE',f'SUMMARY:{_escape(summary)}',f'DESCRIPTION:{_escape(chr(10).join(details))}']
        if field=='interview_at' and application.get('location'):
            lines.append(f'LOCATION:{_escape(application["location"])}')
        lines.append('END:VEVENT')
    if not count:
        raise ValueError('这条记录没有可导出的日期。')
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(_fold(line) for line in lines)+'\r\n').encode('utf-8')
