"""Conservative internship-location evidence, derived without changing stored text."""
import re

HK = re.compile(r'\bhong\s*kong\b|\bhk\b|香港|九龙|九龍|新界', re.I)
AWAY = re.compile(r'\bsingapore\b|\bshenzhen\b|\bshanghai\b|\bbeijing\b|\blondon\b|\bnew york\b|\btokyo\b|\bmainland\b|\boverseas\b|outside (?:of )?hong kong|新加坡|深圳|上海|北京|伦敦|倫敦|东京|東京|内地|內地|外地|海外',re.I)
PLACEMENT = re.compile(
    r'(?:internships?|interns?)\s+(?:(?:will|must|are|is|be|work|working|primarily|physically|onsite|on-site|based|located|take|takes|place|entirely)\s+){0,8}(?:in|at)\s+([^.;。；\n]+)|'
    r'(?:internship location|work location|location of (?:the )?internship)\s*[:：]\s*([^.;。；\n]+)|'
    r'(?:实习|實習)(?:工作)?(?:地点|地點|期间|期間)?\s*(?:需|须|須)?\s*(?:[:：]|在|位于|位於|设在|設在|安排在|将在|將在|为|為)\s*([^。；;\n]+)', re.I)
TRAIN = re.compile(r'training|rotation|rotate|培训|培訓|轮岗|輪崗',re.I)
REQUIRED = re.compile(r'mandatory|required|must|compulsory|必须|必須|须|須|需参加|需參加|需赴|需在',re.I)
FUTURE = re.compile(r'after graduation|permanent|full.time|conversion|graduate role|招聘办公室|招聘辦公室|recruiting office|毕业后|畢業後|转正|轉正',re.I)


def excerpts(description):
    raw = re.sub(r'(?:https?://|www\.)\S+', '[链接省略]', str(description or '')[:5000], flags=re.I)
    raw = re.sub(r'\b(?:utm_\w+|token|gclid|fbclid)=\S+', '[跟踪参数省略]', raw, flags=re.I)
    marked = list(re.finditer(r'\[正文:(元数据|可见)\]\s*(.*?)(?=\[正文:|$)',raw,re.S))
    chunks = [('JobPosting.description' if m[1]=='元数据' else '可见岗位正文',m[2]) for m in marked] if marked else [('已存岗位正文/手动摘录',raw)]
    return [(source, line.strip()) for source,chunk in chunks for line in re.split(r'(?<=[。；;.!])\s*|\n',chunk) if line.strip()][:16]


def assess_location(job):
    location, title = str(job.get('location') or ''), str(job.get('title') or '')
    evidence = [{'source':'页面地点标注','quote':location[:160]}, {'source':'岗位标题','quote':title[:160]}]
    rows=excerpts(job.get('description'))
    relevant=[(src,line) for src,line in rows if HK.search(line) or AWAY.search(line) or TRAIN.search(line) or PLACEMENT.search(line)]
    evidence.extend({'source':src,'quote':line[:180]} for src,line in relevant[:4])
    hk=False; away=False; rotation=False; mandatory=False; future=False; unknown_placement=False; training_missing=False
    for _,line in rows:
        future |= bool(HK.search(line) and FUTURE.search(line))
        if TRAIN.search(line) and AWAY.search(line):
            rotation=True; mandatory |= bool(REQUIRED.search(line)) and not bool(re.search(r'not required|not mandatory|optional|无需|無需|不必',line,re.I))
        if TRAIN.search(line) and REQUIRED.search(line) and not HK.search(line) and not AWAY.search(line):
            training_missing=True
        for found in PLACEMENT.finditer(line):
            if FUTURE.search(line[:found.start()]):
                continue
            dest=next(v for v in found.groups() if v)
            dest=re.split(r'[,，]|\bbut\b|\band (?=after|must|required|mandatory|the permanent|full.time)|after graduation|毕业后|畢業後|转正|轉正',dest,maxsplit=1,flags=re.I)[0]
            unknown_placement |= not bool(HK.search(dest) or AWAY.search(dest))
            hk |= bool(HK.search(dest))
            away |= bool(AWAY.search(dest))
    incomplete = len(str(job.get('description') or '')) >= 590 or '…' in str(job.get('description') or '') or '[摘录不完整]' in str(job.get('description') or '')
    uncertain = unknown_placement or training_missing or bool(re.search(r'\b(?:may|might|either|tbd|to be confirmed|subject to)\b|待定|可能|待确认|待確認|(?:internship|interns?).{0,35}\bnot\b|(?:实习|實習).{0,15}(?:不在|不是|并非|並非)',str(job.get('description') or ''),re.I))
    remote = bool(re.search(r'remote|hybrid|远程|遠程|混合办公',str(job.get('description') or '')+' '+location,re.I))
    if job.get('career_type')!='intern':
        status,reason='not_intern','非实习岗位，本轮不判断实习地点'
    elif (away and (HK.search(location+' '+title) or hk)) or (hk and AWAY.search(location)):
        status,reason='conflict','香港标注与实习正文地点冲突，请核对实际实习地点'
    elif rotation:
        status='rotation'
        reason='正文含必须异地培训/轮岗，不能视为全程香港实地实习' if mandatory else '正文含异地培训/轮岗，是否必须及安排需复核'
    elif incomplete or remote or uncertain:
        status,reason='unclear','摘录不完整、表述含糊或包含远程/混合安排，实际实习地点需复核'
    elif hk and not away and not AWAY.search(location):
        status,reason='hk_onsite','正文明确实习在香港；仍须核对原职位'
    elif away and not hk:
        status,reason='other','正文明确实习在其他地点'
    elif AWAY.search(location) and not HK.search(location+' '+title):
        status,reason='other','地点标注在其他地区；未作为香港实地实习'
    else:
        status='missing'
        reason='香港仅出现在转正/招聘办公室安排中，实习地点需复核' if future else '缺少明确的实习地点正文，不能只凭标题或地点标注判断'
    return {'status':status,'hk_onsite':status=='hk_onsite','requires_review':status in {'conflict','rotation','unclear','missing'},'reason':reason,'evidence':[e for e in evidence if e['quote']]}
