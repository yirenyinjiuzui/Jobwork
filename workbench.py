"""Local SQLite storage and workflow logic for 求职工作台."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import re
import secrets
import sqlite3
import unicodedata
from urllib.parse import urlsplit
from pathlib import Path

HK = timezone(timedelta(hours=8), 'HKT')
STATUS = ('saved', 'submitted', 'waiting', 'assessment', 'interview', 'offer', 'closed')
TYPES = ('intern', 'graduate', 'other')
PROFILE = ('full_name','preferred_name','email','phone','city','school','degree','major',
           'graduation','available_from','linkedin','github','portfolio','project_summary','resume_zh','resume_en','answers')
RESUME_SCHEMA = json.loads((Path(__file__).resolve().parent / 'web' / 'resume-fields.json').read_text(encoding='utf-8'))
RESUME_EXTRA_TEXT = [field for _, fields in RESUME_SCHEMA['sections'] for field in fields]
RESUME_TEXT = [[key] for key in ('political_status', 'student_origin', 'candidate_status', 'target_position',
                                'target_industry', 'target_city', 'transfer_preference')]
RESUME_TEXT += [['skills', '', 'textarea'], ['self_evaluation', '', 'textarea'], *RESUME_EXTRA_TEXT]
RESUME_RECORDS = {key: primary + extra for key, _, _, primary, extra in RESUME_SCHEMA['records']}
NEW_RESUME_GROUPS = ('family_relations', 'patents', 'publications')
APP_FIELDS = ('company','title','requisition','location','career_type','status','deadline',
              'interview_at','interview_reply_by','next_action','source_url','resume_label','submitted_at','last_notice_at','last_notice_fingerprint')

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def normalized(v):
    return ' '.join(unicodedata.normalize('NFKC',str(v or '')).casefold().split())

def _matches_legacy_job(job, app):
    from discovery import _canonical_manual_url
    if (not job['url'] or not app['source_url'] or
        normalized(app['company'])!=normalized(job['company']) or
        normalized(app['requisition'])!=normalized(job['requisition']) or
        _canonical_manual_url(app['source_url'])!=_canonical_manual_url(job['url'])):
        return False
    if job['requisition']:
        return True
    return normalized(app['title'])==normalized(job['title']) and normalized(app['location'])==normalized(job['location'])

def date_value(v):
    s = str(v or '').strip()
    if not s:
        return ''
    if len(s)==10:
        return datetime.strptime(s,'%Y-%m-%d').date().isoformat()
    d = datetime.fromisoformat(s.replace('Z','+00:00'))
    return (d if d.tzinfo else d.replace(tzinfo=HK)).isoformat(timespec='minutes')

def safe_url(v):
    s = str(v or '').strip()
    if not s:
        return ''
    u = urlsplit(s)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or any(ord(c)<=32 for c in s) or '\\' in s:
        raise ValueError('链接必须是有效的 HTTP(S) 地址')
    return s[:2200]

def short(v,n=255):
    return str(v or '').strip()[:n]

def clean_resume_details(details):
    if not isinstance(details, dict):
        raise ValueError('简历资料须为对象')

    def clean_fields(record, fields):
        return {key: short(record[key], 2800 if spec[-1:] == ['textarea'] else 400)
                for key, *spec in fields if isinstance(record.get(key), str) and record[key].strip()}

    result = clean_fields(details, RESUME_TEXT)
    for key, fields in RESUME_RECORDS.items():
        records = details.get(key, [])
        if not isinstance(records, list) or len(records) > 20 or not all(isinstance(row, dict) for row in records):
            raise ValueError('每类简历经历最多保存 20 条有效记录')
        result[key] = [row for record in records if (row := clean_fields(record, fields))]
    return result

def has_expanded_resume(details):
    if any(key in details for key, *_ in RESUME_EXTRA_TEXT) or any(details.get(key) for key in NEW_RESUME_GROUPS):
        return True
    return any(key in row for group, _, _, _, extra in RESUME_SCHEMA['records']
               for row in details.get(group, []) for key, *_ in extra)

def at(v):
    if not v:
        return None
    try:
        v = str(v)
        if len(v)==10:
            return datetime.fromisoformat(v).replace(tzinfo=HK,hour=23,minute=59)
        d = datetime.fromisoformat(v.replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=HK)
    except ValueError:
        return None

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
 id INTEGER PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, requisition TEXT NOT NULL,
 identity TEXT UNIQUE NOT NULL, location TEXT NOT NULL, career_type TEXT NOT NULL, status TEXT NOT NULL,
 deadline TEXT NOT NULL, interview_at TEXT NOT NULL, interview_reply_by TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL, source_url TEXT NOT NULL, resume_label TEXT NOT NULL DEFAULT '', submitted_at TEXT NOT NULL DEFAULT '',
 last_notice_at TEXT NOT NULL, last_notice_fingerprint TEXT NOT NULL, date_precision TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (
 id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES applications(id),
 fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, received_at TEXT NOT NULL, status TEXT NOT NULL,
 source_url TEXT NOT NULL, notes TEXT NOT NULL, applied INTEGER NOT NULL, UNIQUE(application_id,fingerprint));
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL, website TEXT NOT NULL, career_url TEXT NOT NULL, notes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, board TEXT NOT NULL, company TEXT NOT NULL,
 last_checked TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '', initialized INTEGER NOT NULL DEFAULT 0,
 enabled INTEGER NOT NULL DEFAULT 1, UNIQUE(provider,board));
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, board_id INTEGER REFERENCES sources(id) ON DELETE CASCADE, source_id TEXT NOT NULL,
 company TEXT NOT NULL, title TEXT NOT NULL, requisition TEXT NOT NULL, location TEXT NOT NULL, career_type TEXT NOT NULL,
 url TEXT NOT NULL, deadline TEXT NOT NULL, eligibility TEXT NOT NULL DEFAULT '', start TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, UNIQUE(board_id,source_id));
CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, url TEXT NOT NULL, created_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

class ProfileConflict(ValueError):
    pass


class Store:
    def __init__(self, filename):
        self.file = str(Path(filename).resolve())
        Path(self.file).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            db.execute('BEGIN IMMEDIATE')
            if not any(row[1]=='resume_label' for row in db.execute('PRAGMA table_info(applications)')):
                db.execute("ALTER TABLE applications ADD COLUMN resume_label TEXT NOT NULL DEFAULT ''")
            if not any(row[1]=='submitted_at' for row in db.execute('PRAGMA table_info(applications)')):
                db.execute("ALTER TABLE applications ADD COLUMN submitted_at TEXT NOT NULL DEFAULT ''")
            if not any(row[1]=='interview_reply_by' for row in db.execute('PRAGMA table_info(applications)')):
                db.execute("ALTER TABLE applications ADD COLUMN interview_reply_by TEXT NOT NULL DEFAULT ''")
                self._recover_interview_replies(db)
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('calendar_id',?)",(secrets.token_hex(16),))
            self._migrate_job_links(db)

    @staticmethod
    def _recover_interview_replies(db):
        from tracker import _date_candidates, _mail_scope, _utc
        rows=db.execute("""SELECT a.id,a.deadline,a.date_precision,h.notes,h.received_at
            FROM applications a JOIN history h ON h.application_id=a.id AND h.fingerprint=a.last_notice_fingerprint
            WHERE a.status='interview' AND a.deadline!='' AND h.status='interview' AND h.applied=1""").fetchall()
        for row in rows:
            summary,*evidence=row['notes'].split('；证据 ')
            if '截止 '+row['deadline'] not in summary.split('；'):
                continue
            # Old history contains bounded quotations. Restore only a reply date
            # corroborated by the recorded deadline and the original wording.
            replies={}
            for item in evidence:
                label,_,quote=item.partition('：')
                if not label.endswith((' / text',' / status')):
                    continue
                dates,precision,_=_date_candidates(_mail_scope(quote),'interview',_utc(row['received_at']))
                if dates['interview_reply_by']:
                    replies[dates['interview_reply_by']]=precision['interview_reply_by']
            if set(replies)=={row['deadline']}:
                precision=json.loads(row['date_precision'])
                precision['interview_reply_by']=replies[row['deadline']]
                db.execute('UPDATE applications SET interview_reply_by=?,date_precision=? WHERE id=?',
                           (row['deadline'],json.dumps(precision,ensure_ascii=False),row['id']))

    @staticmethod
    def _migrate_job_links(db):
        # Row numbers in old links may already refer to a different board's job.
        links=db.execute("SELECT key,value FROM settings WHERE key GLOB 'job_application:[0-9]*'").fetchall()
        for key, app_id in links:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(key.split(':')[1],)).fetchone()
            app=db.execute('SELECT * FROM applications WHERE id=?',(app_id,)).fetchone()
            new_key='legacy:'+key
            if job and app and _matches_legacy_job(job,app):
                new_key='job_application:'+job['source_id']
            db.execute('UPDATE settings SET key=? WHERE key=?',(new_key,key))

    @contextmanager
    def connect(self, write=False):
        con = sqlite3.connect(self.file, timeout=12)
        con.row_factory = sqlite3.Row
        try:
            con.execute('PRAGMA foreign_keys=ON')
            if write:
                con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def rows(db, sql, args=()):
        return [Store.unpack(r) for r in db.execute(sql,args)]

    @staticmethod
    def unpack(row):
        r=dict(row)
        if 'region' in r and 'description' in r:
            from location_review import assess_location
            r['location_review']=assess_location(r)
        if 'date_precision' in r:
            r['date_precision']=json.loads(r['date_precision'])
        return r

    @staticmethod
    def record(db, table, id):
        if table not in ('applications','companies','sources','jobs'):
            raise ValueError('无效的数据类型')
        res=db.execute(f'SELECT * FROM {table} WHERE id=?',(int(id),)).fetchone()
        if not res:
            raise ValueError('找不到该记录')
        return Store.unpack(res)

    def applications(self):
        with self.connect() as db:
            return self.rows(db,'SELECT * FROM applications ORDER BY updated_at DESC,id DESC')

    @staticmethod
    def _save_application(db, data):
        id=data.get('id')
        old=Store.record(db,'applications',id) if id else {}
        vals={f:short(data.get(f,old.get(f,'')),2200 if f=='source_url' else (1500 if f=='next_action' else 255)) for f in APP_FIELDS}
        if not vals['company'] or not vals['title']:
            raise ValueError('公司和岗位名称必填')
        vals['status']=vals['status'] or 'saved'
        vals['career_type']=vals['career_type'] or 'other'
        if vals['status'] not in STATUS or vals['career_type'] not in TYPES:
            raise ValueError('无效的投递状态或岗位类型')
        for f in ('deadline','interview_at','interview_reply_by','submitted_at','last_notice_at'):
            vals[f]=((at(vals[f]).isoformat(timespec='seconds') if at(vals[f]) else '') if f=='last_notice_at' else date_value(vals[f]))
        precision=data.get('date_precision',old.get('date_precision',{}))
        if data.get('_manual'):
            precision=dict(precision)
            for f in ('deadline','interview_at','interview_reply_by'):
                if f in data and vals[f]!=old.get(f,''):
                    if vals[f]:
                        precision[f]='date' if len(vals[f])==10 else 'exact'
                    else:
                        precision.pop(f,None)
        if old.get('status')=='interview' and vals['status']!='interview':
            vals['interview_reply_by']=''
            precision=dict(precision)
            precision.pop('interview_reply_by',None)
        vals['date_precision']=json.dumps(precision,ensure_ascii=False)
        vals['source_url']=safe_url(vals['source_url'])
        discriminator=('req:'+normalized(vals['requisition'])) if vals['requisition'] else ('title:'+normalized(vals['title'])+'|'+normalized(vals['location']))
        vals['identity']=(old['identity'] if old.get('identity','').startswith('job:') else
                          data.get('_job_identity') or normalized(vals['company'])+'|'+discriminator)
        vals['updated_at']=now()
        fields=list(vals)
        if not id:
            conflict=db.execute('SELECT id FROM applications WHERE identity=?',(vals['identity'],)).fetchone()
            if conflict:
                raise ValueError('此岗位已经在台账里，请更新原记录')
            vals['created_at']=now()
            fields=list(vals)
            id=db.execute(f"INSERT INTO applications ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",tuple(vals.values())).lastrowid
        else:
            db.execute(f"UPDATE applications SET {','.join(f+'=?' for f in fields)} WHERE id=?",(*vals.values(),int(id)))
        return Store.record(db,'applications',id)

    def save_application(self,data):
        # Notice ordering metadata is reserved for the importer.
        clean={k:v for k,v in data.items() if k in (*APP_FIELDS[:-2],'id')}
        with self.connect(True) as db:
            return self._save_application(db,{**clean,'_manual':True})

    def save_company(self,data):
        vals=[short(data.get('name')),safe_url(data.get('website')),safe_url(data.get('career_url')),short(data.get('notes'),1500)]
        if not vals[0]:
            raise ValueError('公司名称必填')
        with self.connect(True) as db:
            if data.get('id'):
                id=self.record(db,'companies',data['id'])['id']
                db.execute('UPDATE companies SET name=?,website=?,career_url=?,notes=?,name_key=? WHERE id=?',(*vals,normalized(vals[0]),id))
            else:
                db.execute('INSERT INTO companies(name,website,career_url,notes,name_key) VALUES (?,?,?,?,?) ON CONFLICT(name_key) DO UPDATE SET name=excluded.name,website=excluded.website,career_url=excluded.career_url,notes=excluded.notes',(*vals,normalized(vals[0])))
                id=db.execute('SELECT id FROM companies WHERE name_key=?',(normalized(vals[0]),)).fetchone()[0]
            return self.record(db,'companies',id)

    def save_source(self,data):
        from discovery import validate_source
        vals=validate_source(data)
        with self.connect(True) as db:
            if data.get('id'):
                old=self.record(db,'sources',data['id'])
                id=old['id']
                if (old['provider'],old['board']) != (vals['provider'],vals['board']):
                    raise ValueError('更换招聘源地址时请先添加新源，再删除旧源')
                db.execute('UPDATE sources SET company=? WHERE id=?',(vals['company'],id))
            else:
                id=db.execute('INSERT INTO sources(provider,board,company) VALUES (?,?,?)',
                    (vals['provider'],vals['board'],vals['company'])).lastrowid
            return self.record(db,'sources',id)

    def delete_source(self,id):
        with self.connect(True) as db:
            self.record(db,'sources',id)
            db.execute('DELETE FROM sources WHERE id=?',(int(id),))
            db.execute('DELETE FROM settings WHERE key=?',(f'demo_phase_{id}',))

    @staticmethod
    def put_job(db, item, board_id=None):
        fields=('source_id','company','title','requisition','location','career_type','url','deadline','eligibility','start','description','region','active')
        vals=[short(item.get(f),2200 if f=='url' else 5000 if f=='description' else 1000 if f in ('eligibility','start') else 255) for f in fields[:-1]]
        vals[6]=safe_url(vals[6]); vals[7]=date_value(vals[7])
        vals.append(int(bool(item.get('active',True))))
        if board_id is None:
            exists=db.execute('SELECT id FROM jobs WHERE board_id IS NULL AND source_id=?',(vals[0],)).fetchone()
        else:
            exists=db.execute('SELECT id FROM jobs WHERE board_id=? AND source_id=?',(int(board_id),vals[0])).fetchone()
        if exists:
            id=exists[0]
            db.execute('UPDATE jobs SET '+','.join(f+'=?' for f in fields)+' WHERE id=?',(*vals,id))
        else:
            id=db.execute('INSERT INTO jobs(board_id,'+','.join(fields)+') VALUES ('+','.join('?' for _ in range(len(fields)+1))+')',(board_id,*vals)).lastrowid
        return Store.record(db,'jobs',id)

    def save_job(self,data):
        from discovery import manual_job
        job=manual_job({**data,'deadline':date_value(data.get('deadline'))})
        with self.connect(True) as db:
            # Reuse a v1.0 row whose ID still includes an old marketing URL.
            # Do not delete or guess between historical duplicates.
            exists=db.execute('SELECT 1 FROM jobs WHERE board_id IS NULL AND source_id=?',(job['source_id'],)).fetchone()
            if not exists:
                matches=[]
                for row in self.rows(db,'SELECT * FROM jobs WHERE board_id IS NULL'):
                    if normalized(row['company'])!=normalized(job['company']):
                        continue
                    if manual_job(row)['source_id']==job['source_id']:
                        matches.append(row)
                if len(matches)==1:
                    old=matches[0]
                    db.execute('UPDATE jobs SET source_id=? WHERE id=?',(job['source_id'],old['id']))
                    db.execute('UPDATE settings SET key=? WHERE key=?',('job_application:'+job['source_id'],'job_application:'+old['source_id']))
                elif len(matches)>1:
                    raise ValueError('找到多条旧版收藏，请在列表检查原记录；未创建重复岗位')
            return self.put_job(db,job)

    def save_job_as_application(self,id):
        with self.connect(True) as db:
            job=self.record(db,'jobs',id)
            key='job_application:'+job['source_id']
            linked=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            if linked:
                return self.record(db,'applications',linked[0])
            # Only reuse an unambiguously identical legacy page + company + ID.
            # Similar titles or a requisition alone are never a linkage.
            matches=[]
            if job['url']:
                for row in self.rows(db,'SELECT * FROM applications'):
                    if (not row['identity'].startswith('job:') and _matches_legacy_job(job,row) and
                        not db.execute("SELECT 1 FROM settings WHERE key LIKE 'job_application:%' AND value=?",(str(row['id']),)).fetchone()):
                        matches.append(row)
            if len(matches)>1:
                raise ValueError('同一页面对应多条旧投递记录，请先复核；未关联或覆盖')
            if matches:
                app=matches[0]
            else:
                d={k:job[k] for k in ('company','title','requisition','location','career_type','deadline')}
                d.update(source_url=job['url'],status='saved',_job_identity='job:'+job['source_id'])
                app=self._save_application(db,d)
            db.execute('INSERT INTO settings(key,value) VALUES (?,?)',(key,str(app['id'])))
            return app

    def check_sources(self, id=None):
        from discovery import fetch_jobs, detect_changes, DiscoveryError
        with self.connect() as db:
            sources=[self.record(db,'sources',id)] if id is not None else self.rows(db,'SELECT * FROM sources WHERE enabled=1 ORDER BY id')
        results=[]
        for src in sources:
            request_token=secrets.token_hex(16)
            with self.connect(True) as db:
                db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    ('source_check:'+str(src['id']),request_token))
            try:
                if src['provider']=='demo':
                    from discovery import demo_jobs
                    with self.connect() as db:
                        flag=db.execute('SELECT value FROM settings WHERE key=?',(f"demo_phase_{src['id']}",)).fetchone()
                    phase=int(flag[0]) if flag else 0
                    jobs=demo_jobs(src, phase=min(phase,2))
                else:
                    jobs=fetch_jobs(src)
            except (DiscoveryError,OSError,ValueError) as e:
                error=short(e,400)
                with self.connect(True) as db:
                    current=db.execute('SELECT value FROM settings WHERE key=?',('source_check:'+str(src['id']),)).fetchone()
                    if current and current[0]==request_token:
                        db.execute('UPDATE sources SET last_checked=?,last_error=? WHERE id=?',(now(),error,src['id']))
                results.append({'id':src['id'],'error':error})
                continue
            with self.connect(True) as db:
                stale=db.execute('SELECT * FROM sources WHERE id=?',(src['id'],)).fetchone()
                if not stale:
                    continue
                current=db.execute('SELECT value FROM settings WHERE key=?',('source_check:'+str(src['id']),)).fetchone()
                if not current or current[0]!=request_token:
                    results.append({'id':src['id'],'error':'较旧请求结果已丢弃，未覆盖较新的来源状态'})
                    continue
                old=self.rows(db,'SELECT * FROM jobs WHERE board_id=?',(src['id'],))
                changes=detect_changes(old,jobs,initialized=bool(stale['initialized']))
                missing=[]
                warning=''
                if src['provider']!='demo':
                    missing=[j['id'] for j in changes['closed']]
                    # Absence (including empty/old snapshots) is not closure evidence.
                    absent={j['source_id'] for j in changes['closed']}
                    changes['jobs']=[j for j in changes['jobs'] if j['source_id'] not in absent]
                    changes['closed']=[]
                    if missing or not jobs:
                        warning='本次暂不可核实：接口未返回部分岗位或返回空列表；保留最后状态，未判定关闭或未开招。'
                    info_row=db.execute('SELECT value FROM settings WHERE key=?',('source_review:'+str(src['id']),)).fetchone()
                    info=json.loads(info_row[0]) if info_row else {}
                    seen=info.get('seen_at',{})
                    for j in jobs:seen[j['source_id']]=now()
                    info.update(token=request_token,missing=missing,seen_at=seen,observed_at=now())
                    db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        ('source_review:'+str(src['id']),json.dumps(info,ensure_ascii=False)))
                for item in changes['jobs']:
                    self.put_job(db,item,src['id'])
                for kind,label in (('new','新岗位'),('reopened','岗位重新开放')):
                    for item in changes[kind]:
                        db.execute('INSERT INTO notifications(title,body,url,created_at) VALUES (?,?,?,?)',
                             (f'{label} · {item["company"]}', f'{item["title"]} · {item.get("location") or "地点未标注"}',
                              safe_url(item.get('url')),now()))
                db.execute('UPDATE sources SET initialized=?,last_checked=?,last_error=? WHERE id=?',(int(bool(stale['initialized'] or jobs or src['provider']=='demo')),now(),warning,src['id']))
                if src['provider']=='demo':
                    db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(f"demo_phase_{src['id']}",str(min(phase+1,2))))
            results.append({'id':src['id'],'jobs':len(jobs),'new':len(changes['new']),'reopened':len(changes['reopened']),
                            'closed':len(changes['closed']),'unverified':len(missing) or int(bool(warning)),'baseline':changes['baseline'] and bool(jobs)})
        return results

    def confirm_job_closed(self,data):
        if data.get('reviewed') is not True:
            raise ValueError('请先核对原职位页的明确关闭证据')
        with self.connect(True) as db:
            job=self.record(db,'jobs',data['id'])
            board=job['board_id']
            current=db.execute('SELECT value FROM settings WHERE key=?',('source_check:'+str(board),)).fetchone()
            pending=db.execute('SELECT value FROM settings WHERE key=?',('source_review:'+str(board),)).fetchone()
            info=json.loads(pending[0]) if pending else {}
            if not current or current[0]!=data.get('token') or info.get('token')!=data.get('token') or job['id'] not in info.get('missing',[]):
                raise ValueError('来源已变化或复核已过期，请重新检查，未关闭岗位')
            evidence=safe_url(data.get('evidence_url'))
            reason=short(data.get('reason'),500)
            if not evidence or evidence!=job['url'] or not reason:
                raise ValueError('需原职位页链接及明确关闭原因，不能以接口缺席代替证据')
            db.execute('UPDATE jobs SET active=0 WHERE id=?',(job['id'],))
            info['missing'].remove(job['id'])
            info.setdefault('closed_at',{})[job['source_id']]=now()
            proof={'job_id':job['id'],'source_id':job['source_id'],'url':evidence,'reason':reason,'confirmed_at':now()}
            info.setdefault('closure_evidence',{})[str(job['id'])]=proof
            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(info,ensure_ascii=False),'source_review:'+str(board)))
            db.execute('INSERT INTO settings(key,value) VALUES (?,?)',('source_evidence:'+secrets.token_hex(16),json.dumps(proof,ensure_ascii=False)))
            return {'job':self.record(db,'jobs',job['id']),'evidence':proof}

    @staticmethod
    def profile_snapshot(db):
        values=dict(db.execute("SELECT key,value FROM settings WHERE key IN ('profile','profile_revision')"))
        return {'profile':json.loads(values.get('profile','{}')),
                'profile_revision':int(values.get('profile_revision',0))}

    def set_profile(self,data):
        profile={k:short(data.get(k),5000 if k=='project_summary' else 500) for k in PROFILE if k!='answers'}
        answers=data.get('answers') or {}
        if not isinstance(answers,dict):
            raise ValueError('常见问题答案必须是对象')
        profile['answers']={short(k,180):short(v,3500) for k,v in list(answers.items())[:40] if short(k,180)}
        with self.connect(True) as db:
            snapshot=self.profile_snapshot(db)
            revision=snapshot['profile_revision']
            if type(data.get('profile_revision')) is not int or data['profile_revision']!=revision:
                raise ProfileConflict('当前页未读取最新资料。请保留本页草稿，另开资料页核对后保存。')
            previous=snapshot['profile']
            if 'resume_details' in data:
                if data.get('resume_fields_version') != 1 and has_expanded_resume(previous.get('resume_details', {})):
                    raise ValueError('资料页已更新，请刷新页面后再保存。')
                profile['resume_details'] = clean_resume_details(data['resume_details'])
            elif 'resume_details' in previous:
                profile['resume_details'] = previous['resume_details']
            db.execute("INSERT INTO settings(key,value) VALUES ('profile',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(profile,ensure_ascii=False),))
            db.execute("INSERT INTO settings(key,value) VALUES ('profile_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(revision+1),))
        return {'profile':profile,'profile_revision':revision+1}

    def mark_read(self,id=None):
        with self.connect(True) as db:
            if id is None:
                db.execute('UPDATE notifications SET read=1')
            else:
                db.execute('UPDATE notifications SET read=1 WHERE id=?',(int(id),))

    def calendar_row(self,id):
        with self.connect() as db:
            return self.record(db,'applications',id), db.execute("SELECT value FROM settings WHERE key='calendar_id'").fetchone()[0]

    def history(self,id):
        with self.connect() as db:
            return self.rows(db,'SELECT * FROM history WHERE application_id=? ORDER BY created_at DESC,id DESC',(int(id),))

    def import_notice(self, notice, id=None, create=False, overrides=None):
        from tracker import apply_notice, match_application, application_chronology, _utc
        import assessment_tasks as tasks_api
        overrides=overrides or {}
        if notice.get('requires_review') and overrides.get('review_confirmed') is not True:
            raise ValueError('邮件证据不明确或冲突，请先勾选已复核并选择对应岗位；不会默认覆盖。')
        with self.connect(True) as db:
            if '_preview_apps' in notice:
                current={str(a['id']):a for a in self.rows(db,'SELECT * FROM applications')}
                if current!=notice['_preview_apps']:
                    raise ValueError('预览后投递记录已变化，请重新预览并确认；未写入。')
            if id is None and not create:
                match=match_application(notice,self.rows(db,'SELECT * FROM applications'))
                id=match.get('match_id')
            old=self.record(db,'applications',id) if id is not None else None
            if old is None and not create:
                raise ValueError('请先选定要更新的投递记录，或明确选择新建')
            if notice.get('is_eml') and old:
                suggested=match_application(notice,self.rows(db,'SELECT * FROM applications'))
                if (suggested.get('ambiguous') or suggested.get('match_id') not in (None,old['id'])) and overrides.get('review_confirmed') is not True:
                    raise ValueError('所选岗位与邮件建议关联不一致，请明确复核后再写入。')
            if notice.get('is_eml') and old and application_chronology(notice,old)!='ok' and overrides.get('review_confirmed') is not True:
                raise ValueError('邮件发送时间与实际投递时间冲突或不明确，请重新预览并明确复核。')
            assessment_key='assessment:'+str(old['id']) if old else ''
            prior_assessment=db.execute('SELECT value FROM settings WHERE key=?',(assessment_key,)).fetchone() if old else None
            tasks=tasks_api.load(db,old)
            task_key=tasks_api.key(notice.get('assessment_id'))
            task=tasks.get(task_key)
            receipt=notice.get('assessment_completion')
            task_event=bool(task_key and (receipt or notice.get('status')=='assessment'))
            relative=notice.get('assessment_relative')
            assessment_ok=bool(notice.get('assessment_id') and notice.get('received_at') and notice.get('sent_precision')=='exact' and
                (task or not tasks and not prior_assessment and (not old or old['status'] in ('saved','submitted','waiting'))))
            if relative and assessment_ok and overrides.get('same_assessment_confirmed') is not True:
                raise ValueError('请明确确认邮件来源、发送时间及同一测评编号后，再更新相对截止估计。')
            base=dict(notice)
            if receipt:
                if not old:
                    raise ValueError('请为测评完成回执选择已有投递记录。')
                if not task or not _utc(task.get('notice_at')) or not notice.get('received_at') or notice.get('sent_precision')!='exact' or notice.get('requires_review') or match_application(notice,self.rows(db,'SELECT * FROM applications')).get('match_id')!=old['id']:
                    if overrides.get('review_confirmed') is not True:
                        raise ValueError('完成回执无法唯一确认原测评，请复核；不会清除其他待办。')
                    base['review_only']=True
                elif overrides.get('assessment_completion_confirmed') is not True:
                    raise ValueError('请明确确认此回执只完成测评 '+notice['assessment_id']+'。')
            if receipt and task and _utc(task.get('notice_at')) and _utc(notice.get('received_at')) and _utc(notice['received_at'])<=_utc(task['notice_at']):
                base['review_only']=True
            if task_event and task and task.get('completed'):
                base['review_only']=True
            if task_event and task and _utc(task.get('notice_at')) and (not _utc(notice.get('received_at')) or _utc(notice['received_at'])<_utc(task['notice_at'])):
                base['review_only']=True

            if relative and not assessment_ok:
                if overrides.get('review_confirmed') is not True:
                    raise ValueError('无法确认同一测评或发送时间，请复核；不能自动更新截止估计。')
                if not old:
                    raise ValueError('缺少测评身份，先手动建立待核实记录；不从本通知创建截止估计。')
                base['review_only']=True
                base['warnings']=list(base.get('warnings',[]))+['测评身份/发送时间未确认，仅记录历史，不改截止时间。']

            safe={k:v for k,v in overrides.items() if k in APP_FIELDS[:-2] and k not in ('resume_label','submitted_at')}
            if 'status' in safe and safe['status'] not in STATUS:
                raise ValueError('请选择有效的流程状态。')
            base.update(safe)
            if notice.get('requires_review') and 'status' not in safe:
                if not old:
                    raise ValueError('需复核的邮件新建记录时必须明确选择状态。')
                base['review_only']=True
            if 'status' in safe:
                base['has_explicit_status']=True
            prior=None
            if old:
                prior=db.execute('SELECT id FROM history WHERE application_id=? AND fingerprint=?',(id,notice['fingerprint'])).fetchone()
                if not prior and notice.get('legacy_fingerprint'):
                    prior=db.execute('SELECT id FROM history WHERE application_id=? AND fingerprint=? AND received_at=?',
                        (id,notice['legacy_fingerprint'],notice.get('received_at',''))).fetchone()
            if prior:
                return {'application':old,'duplicate':True,'applied':False,'warnings':['同一通知已记录']}
            compare_old=old
            if task_event and old and not base.get('review_only'):
                compare_old={**old,'last_notice_at':task.get('notice_at','') if task else ''}
                if receipt and old['status'] in ('interview','offer','closed'):
                    compare_old['status']='assessment'
            merged=apply_notice(base,compare_old)
            applied=bool(merged.get('update_applied',True))
            if not old:
                merged={**merged,**safe}
                applied=True
            elif applied:
                # The user can explicitly correct rank-independent fields.
                merged.update(safe)
            if applied and task_event and not base.get('review_only'):
                task={'id':notice['assessment_id'],'completed':bool(receipt),
                    'deadline':task.get('deadline','') if receipt and task else base.get('deadline',''),
                    'precision':task.get('precision','unknown') if receipt and task else base.get('date_precision',{}).get('deadline','unknown'),
                    'notice_at':notice.get('received_at','')}
                tasks[task_key]=task
                if not old or old['status'] in ('saved','submitted','waiting','assessment'):
                    pending=[t for t in tasks.values() if not t['completed']]
                    # Compare deadlines using the same end-of-day convention as the
                    # dashboard; date-only notices must not hide an exact cutoff
                    # on that date. Preserve the original raw value and precision.
                    dated=sorted((t for t in pending if at(t['deadline'])),
                                 key=lambda t:(at(t['deadline']),len(t['deadline'])==10))
                    merged['status']='assessment' if pending else 'waiting'
                    merged['deadline']=dated[0]['deadline'] if dated else ''
                    merged.setdefault('date_precision',{}).pop('deadline',None)
                    if dated:merged['date_precision']['deadline']=dated[0]['precision']
                    merged['next_action']='待完成测评：'+', '.join(t['id'] for t in pending) if pending else '测评已完成，等待招聘方结果'
                if receipt and old and old['status'] in ('interview','offer','closed'):
                    for field in ('status','deadline','interview_at','interview_reply_by','next_action','date_precision'):
                        merged[field]=old[field]
                if old and _utc(old.get('last_notice_at')) and (not _utc(merged.get('last_notice_at')) or _utc(merged['last_notice_at'])<_utc(old['last_notice_at'])):
                    merged['last_notice_at']=old['last_notice_at']
            if applied:
                for f in ('deadline','interview_at','interview_reply_by'):
                    if f in safe and safe[f]!=notice.get(f):
                        if safe[f]:
                            merged.setdefault('date_precision',{})[f]='date' if len(str(safe[f]))==10 else 'exact'
                        else:
                            merged.setdefault('date_precision',{}).pop(f,None)
                row=self._save_application(db,merged)
                if task_event and not base.get('review_only'):
                    tasks_api.save(db,row['id'],tasks)
                if notice.get('assessment_id') and base.get('status')=='assessment' and (not relative or assessment_ok):
                    db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        ('assessment:'+str(row['id']),notice['assessment_id']))
            else:
                row=old
            warnings=list(dict.fromkeys((notice.get('warnings') or [])+(merged.get('warnings') or [])))
            history_status=base.get('status') if base.get('has_explicit_status') and not base.get('review_only') else ''
            label='识别状态：'+str(history_status or '待核实')
            times='；'.join(f'{name} {base[k]}' for k,name in (('deadline','截止'),('interview_at','面试'),('interview_reply_by','面试回复期限')) if base.get(k))
            evidence=['证据 '+e['source']+' / '+e['field']+'：'+e['quote'] for e in notice.get('evidence',[])][:12]
            msg=('；'.join(x for x in (label,times,*warnings,*evidence) if x))[:6000]
            db.execute('INSERT INTO history(application_id,fingerprint,created_at,received_at,status,source_url,notes,applied) VALUES (?,?,?,?,?,?,?,?)',
                (row['id'],notice['fingerprint'],now(),short(base.get('received_at')),short(history_status),safe_url(base.get('source_url')),msg,int(applied)))
            return {'application':row,'duplicate':False,'applied':applied,'warnings':warnings}

    def state(self):
        with self.connect() as db:
            apps=self.rows(db,'SELECT * FROM applications ORDER BY updated_at DESC,id DESC')
            import assessment_tasks
            for app in apps:
                tracked=list(assessment_tasks.load(db,app).values())
                if tracked:app['assessment_tasks']=tracked
            profile=self.profile_snapshot(db)
            jobs=self.rows(db,'SELECT * FROM jobs ORDER BY active DESC,id DESC')
            source_map={r['id']:r for r in self.rows(db,'SELECT * FROM sources')}
            reviews={int(r['key'].split(':')[1]):json.loads(r['value']) for r in db.execute("SELECT key,value FROM settings WHERE key LIKE 'source_review:%'")}
            polls={int(r['key'].split(':')[1]):r['value'] for r in db.execute("SELECT key,value FROM settings WHERE key LIKE 'source_check:%'")}
            for job in jobs:
                src=source_map.get(job['board_id'])
                if src and src['provider']!='demo':
                    info=reviews.get(src['id'],{})
                    last=info.get('seen_at',{}).get(job['source_id'],'')
                    closed=info.get('closed_at',{}).get(job['source_id'],'')
                    expired=not last or (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()>86400
                    pending=job['id'] in info.get('missing',[])
                    uncertain=bool(src['last_error'] or expired or pending)
                    job['source_verification']={'uncertain':uncertain,'last_seen':last,'closed_confirmed_at':closed,
                        'message':('本次暂不可核实；保留最后记录状态。' if uncertain else '本次接口返回了此岗位。')+' 最后记录：'+('开放' if job['active'] else '关闭')+'；上次接口见到：'+(last or '旧记录未记录时间'),
                        'closure_evidence':info.get('closure_evidence',{}).get(str(job['id'])),
                        'close_token':info.get('token') if pending and polls.get(src['id'])==info.get('token') else ''}
                similar=[other['id'] for other in jobs if other['id']!=job['id'] and
                    normalized(other['company'])==normalized(job['company']) and
                    ((normalized(other['title'])==normalized(job['title']) and normalized(other['location'])==normalized(job['location'])) or
                     (job['requisition'] and normalized(other['requisition'])==normalized(job['requisition'])))]
                job['identity_review']=('相似岗位或编号重复，已分别保留；请核对来源和职责后分别记录。相关条目：'+', '.join(map(str,similar[:8]))) if similar else ''
            return dict(applications=apps,today=prioritize(apps),**profile,
                companies=self.rows(db,'SELECT * FROM companies ORDER BY name'),
                sources=self.rows(db,'SELECT * FROM sources ORDER BY id'),
                jobs=jobs,
                notifications=self.rows(db,'SELECT * FROM notifications ORDER BY id DESC LIMIT 250'))

def prioritize(apps, clock=None):
    now_hk=clock or datetime.now(HK)
    ranked=[]
    for row in apps:
        status=row['status']
        if status not in ('assessment','interview','offer','saved'):
            continue
        due_field='interview_reply_by' if status=='interview' else 'deadline'
        due=at(row.get(due_field))
        if status=='interview':
            slot=at(row.get('interview_at'))
            # Prefer a future action over an expired one, then the earlier date.
            if slot and (not due or (slot<now_hk,slot)<=(due<now_hk,due)):
                due, due_field=slot, 'interview_at'
        if status=='saved' and not due:
            continue
        if due and due<now_hk and status=='saved':
            continue
        label={'saved':'申请截止','assessment':'待完成网测','interview':'面试回复截止' if due_field=='interview_reply_by' and due else '待参加面试','offer':'待处理 Offer'}[status]
        days=((due.astimezone(HK).date()-now_hk.astimezone(HK).date()).days if due else None)
        precision=(row.get('date_precision') or {}).get(due_field)
        suffix=('日期待确认' if days is None else '时间已过，请确认结果' if due<now_hk else
                '今天（香港时间）' if days==0 else '明天（香港时间）' if days==1 else f'{days} 天后')
        if precision=='estimated':
            suffix+='（推算，请核对通知）'
        epoch=due.timestamp() if due else float('inf')
        # Keep still-actionable items ahead of expired items.
        group=2 if due and due<now_hk else 1 if due is None else 0
        ranked.append((group,epoch,row['id'],{**row,'reason':f'{label} · {suffix}'}))
    return [v[-1] for v in sorted(ranked)[:3]]
