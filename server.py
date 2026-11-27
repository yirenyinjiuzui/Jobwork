"""Launch the local job workbench (Python 3.11+, no Python dependencies)."""
from argparse import ArgumentParser
from base64 import b64decode
from binascii import Error as Base64Error
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import csv
import io
import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from workbench import Store, HK, ProfileConflict, safe_url, normalized

ROOT = Path(__file__).resolve().parent
ASSETS = {
    '/': ROOT/'web/index.html', '/index.html': ROOT/'web/index.html',
    '/style.css': ROOT/'web/style.css', '/app.js': ROOT/'web/app.js', '/resume-fields.json': ROOT/'web/resume-fields.json',
    '/demo-form.html': ROOT/'extension/demo-form.html',
    '/demo-form.js': ROOT/'extension/demo-form.js', '/demo-form.css': ROOT/'extension/demo-form.css',
    '/demo-preview.mjs': ROOT/'extension/demo-preview.mjs', '/demo-profile.json': ROOT/'extension/demo-profile.json',
    '/review-cards.mjs': ROOT/'extension/review-cards.mjs', '/review-cards.css': ROOT/'extension/review-cards.css',
    '/page.mjs': ROOT/'extension/page.mjs', '/matcher.mjs': ROOT/'extension/matcher.mjs',
}
MAX_BODY = 8 * 1024 * 1024

class InputError(ValueError):
    pass

def data_blob(raw, maximum):
    if not isinstance(raw,str) or len(raw)>maximum*4//3+8:
        raise InputError('文件太大或格式无效')
    try:
        result=b64decode(raw,validate=True)
    except (ValueError,Base64Error) as e:
        raise InputError('文件无法读取') from e
    if not result or len(result)>maximum:
        raise InputError('文件为空或超出大小限制')
    return result

def recognize_image(data):
    result=data_blob(data.get('image_base64'),5*1024*1024)
    if result.startswith(b'\x89PNG\r\n\x1a\n'):
        suffix='.png'
    elif result.startswith(b'\xff\xd8\xff'):
        suffix='.jpg'
    else:
        raise InputError('只接受 PNG 或 JPEG 截图')
    lang=data.get('language','eng')
    if lang not in ('eng','chi_sim+eng','chi_tra+eng'):
        raise InputError('无效的 OCR 语言')
    executable=os.getenv('TESSERACT_CMD') or shutil.which('tesseract')
    if not executable:
        raise InputError('未找到本机 Tesseract，可先使用网页字段识别或粘贴截图内的文字')
    try:
        with tempfile.TemporaryDirectory(prefix='job-ocr-') as folder:
            f=Path(folder)/('image'+suffix)
            f.write_bytes(result)
            proc=subprocess.run([executable,str(f),'stdout','-l',lang,'--psm','6'],
                capture_output=True,timeout=20,check=False)
    except (subprocess.TimeoutExpired,OSError) as e:
        raise InputError('本机 OCR 未能完成，请缩小或裁剪截图后重试') from e
    if proc.returncode:
        raise InputError('OCR 无法识别该图片，或未安装所选语言包')
    text=proc.stdout.decode('utf-8','replace').strip()[:24000]
    if not text:
        raise InputError('未识别出清晰文字，可裁剪对应表单区域后重试')
    return text

class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self, address, store):
        self.store=store
        self.previews={}
        self.preview_lock=threading.Lock()
        self.check_lock=threading.Lock()
        self.ocr_lock=threading.Lock()
        super().__init__(address,Handler)

    def server_bind(self):
        # Windows SO_REUSEADDR can permit competing listeners; own this endpoint.
        if os.name=='nt' and hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.allow_reuse_address=False
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()

    def check(self,id=None):
        if not self.check_lock.acquire(blocking=False):
            raise InputError('已在检查招聘源，请稍后刷新')
        try:
            return self.store.check_sources(id)
        finally:
            self.check_lock.release()

    def make_preview(self, notice):
        with self.preview_lock:
            epoch=time.monotonic()
            self.previews={k:v for k,v in self.previews.items() if epoch-v[0]<1800}
            if len(self.previews)>=100:
                self.previews.pop(next(iter(self.previews)))
            token=secrets.token_urlsafe(24)
            self.previews[token]=epoch,notice
            return token

    def get_preview(self,token):
        with self.preview_lock:
            result=self.previews.get(token)
            if not result or time.monotonic()-result[0]>=1800:
                raise InputError('预览已过期，请重新识别')
            return result[1]

    def drop_preview(self,token):
        with self.preview_lock:
            self.previews.pop(token,None)

class Handler(BaseHTTPRequestHandler):
    # Deliberately do not dump request bodies or private paths to logs.
    def log_message(self, format, *args):
        return

    def allowed_request(self, write=False):
        expected=self.server.server_port
        valid_hosts={f'127.0.0.1:{expected}',f'localhost:{expected}'}
        host=self.headers.get('Host','').lower()
        origin=self.headers.get('Origin')
        if host not in valid_hosts:
            self.reply({'error':'只接受本机访问'},403)
            return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site' or (origin is not None and origin!=f'http://{host}'):
            self.reply({'error':'拒绝跨站访问'},403)
            return False
        if write and self.headers.get_content_type()!='application/json':
            self.reply({'error':'仅接受 JSON 请求'},415)
            return False
        return True

    def send_content(self,raw,mime,status=200,extra=None):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for k,v in (extra or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(raw)

    def reply(self,data,status=200):
        self.send_content(json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8',status)

    def do_GET(self):
        if not self.allowed_request():
            return
        p=urlsplit(self.path)
        try:
            if p.path=='/api/state':
                self.reply(self.server.store.state())
            elif p.path=='/api/history':
                self.reply(self.server.store.history(parse_qs(p.query).get('id',[''])[0]))
            elif p.path=='/api/export':
                self.export()
            elif p.path=='/api/calendar':
                from calendar_export import export_application
                id=int(parse_qs(p.query).get('id',[''])[0])
                row,namespace=self.server.store.calendar_row(id)
                self.send_content(export_application(row,namespace),'text/calendar; charset=utf-8',
                    extra={'Content-Disposition':f'attachment; filename="job-{id}.ics"'})
            elif p.path in ASSETS and ASSETS[p.path].is_file():
                f=ASSETS[p.path]
                typ='text/javascript' if f.suffix=='.mjs' else mimetypes.guess_type(f)[0] or 'application/octet-stream'
                self.send_content(f.read_bytes(),typ+'; charset=utf-8')
            elif p.path=='/favicon.ico':
                self.send_content(b'', 'image/x-icon',204)
            else:
                self.reply({'error':'找不到页面'},404)
        except (ValueError,TypeError) as e:
            self.reply({'error':str(e)},400)

    def export(self):
        output=io.StringIO()
        writer=csv.writer(output)
        fields=('company','title','requisition','location','career_type','status','deadline','interview_at','next_action','source_url','resume_label','updated_at','interview_reply_by')
        writer.writerow(fields)
        def safe_cell(value):
            value=str(value or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value
        for row in self.server.store.applications():
            writer.writerow([safe_cell(row.get(f)) for f in fields])
        self.send_content(output.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8',extra={'Content-Disposition':'attachment; filename="applications.csv"'})

    def do_POST(self):
        if not self.allowed_request(write=True):
            return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 1<=n<=MAX_BODY:
                self.reply({'error':'请求为空或超出 8 MB'},413)
                return
            data=json.loads(self.rfile.read(n))
            if not isinstance(data,dict):
                raise InputError('请求内容必须是对象')
            result=self.mutate(urlsplit(self.path).path,data)
            if result is not None:
                self.reply({'ok':True,**result})
        except ProfileConflict as e:
            self.reply({'error':str(e)},409)
        except sqlite3.IntegrityError:
            self.reply({'error':'已有相同公司、岗位或招聘源，请更新原记录'},409)
        except (ValueError, KeyError, TypeError, UnicodeError) as e:
            self.reply({'error':str(e)[:350] or '请检查输入'},400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            print('Server error:',type(e).__name__,str(e)[:220],file=sys.stderr)
            self.reply({'error':'本机程序暂时无法处理该操作，请查看启动窗口'},500)

    def mutate(self,path,d):
        store=self.server.store
        if path=='/api/application':
            return {'application':store.save_application(d)}
        if path=='/api/company':
            return {'company':store.save_company(d)}
        if path=='/api/source':
            return {'source':store.save_source(d)}
        if path=='/api/source/check':
            return {'results':self.server.check(d.get('id'))}
        if path=='/api/job/confirm-closed':
            return store.confirm_job_closed(d)
        if path=='/api/source/delete':
            store.delete_source(d['id'])
            return {}
        if path=='/api/job':
            return {'job':store.save_job(d)}
        if path=='/api/job/save':
            return {'application':store.save_job_as_application(d['id'])}
        if path=='/api/notifications/read':
            store.mark_read(d.get('id'))
            return {}
        if path=='/api/profile/import-preview':
            from resume_import import preview_resume
            return preview_resume(d.get('filename'),data_blob(d.get('content_base64'),5*1024*1024))
        if path=='/api/profile':
            return store.set_profile(d)
        if path=='/api/notice/preview':
            from tracker import parse_eml, parse_notice, parse_eml_notice, match_application
            mail=parse_eml(data_blob(d['eml_base64'],4*1024*1024)) if d.get('eml_base64') else {}
            draft=str(mail.get('text') or d.get('text') or '').strip()
            subject=mail.get('subject','')
            if subject and subject not in draft[:400]:
                draft='Subject: '+subject+'\n\n'+draft
            if not draft or len(draft)>150000:
                raise InputError('请输入通知正文，最多 150,000 字符')
            notice=(parse_eml_notice if mail else parse_notice)(mail if mail else draft,received_at=d.get('received_at') or mail.get('received_at'),
                source_url=safe_url(d.get('source_url')),company=d.get('company',''),
                title=d.get('title',''),requisition=d.get('requisition',''))
            if mail.get('message_id'):
                notice['message_id']=mail['message_id']
            applications=store.applications()
            match=match_application(notice,applications)
            notice['timing_evidence']={'sent_at':notice.get('received_at',''),
                'event_at':notice.get('interview_at',''),
                'applications':[{'id':a['id'],'submitted_at':a.get('submitted_at','')} for a in applications
                    if normalized(a['company'])==normalized(notice['company'])]}

            if mail and (match.get('ambiguous') or not match.get('match_id')):
                notice['requires_review']=True
                notice['has_explicit_status']=False
                notice['status']='waiting'
                notice['deadline']=notice['interview_at']=notice['interview_reply_by']=notice['next_action']=''
                notice['warnings'].append(match['reason'])
                notice['confidence']='low'
                notice['completion']=notice['interview_cancelled']=False
                notice['date_precision']={}
                notice['notes']='\n'.join(notice['warnings'])
            if notice.get('assessment_relative'):
                selected=next((a for a in applications if a['id']==match.get('match_id')),None)
                with store.connect() as db:
                    import assessment_tasks
                    known=assessment_tasks.load(db,selected)
                if selected and selected['status']=='assessment' and assessment_tasks.key(notice.get('assessment_id')) not in known:
                    notice['requires_review']=True
                    notice['warnings'].append('原测评编号未知或不同，不能确认同一测评；只保留历史，截止请人工核实。')
                notice['assessment_confirmation_required']=True
            if notice.get('assessment_completion'):
                import assessment_tasks
                selected=next((a for a in applications if a['id']==match.get('match_id')),None)
                with store.connect() as db:
                    known=assessment_tasks.load(db,selected)
                task=known.get(assessment_tasks.key(notice.get('assessment_id')))
                if task and task.get('notice_at'):
                    notice['assessment_completion_confirmation_required']=True
                else:
                    notice['requires_review']=True
                    notice['has_explicit_status']=False
                    notice['warnings'].append('无法核实对应的测评编号或通知时间，仅复核留历史，不清除待办。')
            bound={**notice,'_preview_apps':{str(a['id']):a for a in applications}}
            return {'token':self.server.make_preview(bound),'notice':notice,'match':match}
        if path=='/api/notice/apply':
            token=d['token']; notice=self.server.get_preview(token)
            result=store.import_notice(notice,d.get('application_id') or None,bool(d.get('create')),d.get('overrides'))
            self.server.drop_preview(token)
            return result
        if path=='/api/ocr':
            if not self.server.ocr_lock.acquire(blocking=False):
                raise InputError('正在运行 OCR，请稍后再试')
            try:
                return {'text':recognize_image(d)}
            finally:
                self.server.ocr_lock.release()
        if path=='/api/demo':
            return {'seeded':seed_demo(store)}
        self.reply({'error':'找不到此操作'},404)

def seed_demo(store):
    today=datetime.now(HK).date()
    with store.connect(True) as db:
        if db.execute("SELECT value FROM settings WHERE key='seeded'").fetchone():
            return False
        db.execute("INSERT INTO companies(name,name_key,website,career_url,notes) VALUES ('示例科技','示例科技','','','虚构示例，不是真实招聘。') ON CONFLICT(name_key) DO NOTHING")
        db.execute("INSERT INTO sources(provider,board,company) VALUES ('demo','sample','示例招聘') ON CONFLICT(provider,board) DO NOTHING")
        for title, req, st, days, act in [
            ('AI 应用实习','DEMO-101','assessment',1,'预留 60 分钟完成网测'),
            ('测试开发实习','DEMO-102','interview',3,'准备一个项目和一道 API 测试设计题'),
            ('数据分析实习','DEMO-103','waiting',None,'等待招聘方回复')]:
            stamp=(today+timedelta(days=days)).isoformat() if days is not None else ''
            store._save_application(db,dict(company='示例科技',title=title,requisition=req,
                status=st,location='香港（示例）',career_type='intern',
                deadline=stamp if st=='assessment' else '',
                interview_at=stamp+'T14:00+08:00' if st=='interview' else '',next_action=act))
        db.execute("INSERT INTO settings(key,value) VALUES ('seeded','1')")
    return True

def run():
    parser=ArgumentParser(description='求职工作台 · 仅本机运行')
    parser.add_argument('--data',type=Path,default=ROOT/'data/workbench.sqlite3')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--check',action='store_true',help='检查招聘源一次后退出')
    parser.add_argument('--interval',type=int,default=30,help='网页服务器运行时每隔多少分钟检查；0 关闭')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if args.interval<0 or 0<args.interval<5:
        parser.error('--interval 必须为 0 或至少 5 分钟')
    if not 0<=args.port<=65535:
        parser.error('--port 必须为 0 到 65535；0 表示明确请求临时端口')
    if args.check:
        store=Store(args.data)
        results=store.check_sources()
        print(json.dumps(results,ensure_ascii=False,indent=2))
        return int(any(x.get('error') for x in results))
    try:
        # Bind/listen before opening, creating or migrating any database.
        server=WorkbenchServer(('127.0.0.1',args.port),None)
    except OSError as e:
        print(f'无法启动：端口 {args.port} 无法由本次启动占用：{e}。未打开数据库或浏览器，也未停止其他服务。请核对原启动窗口及数据库路径；如需另开，明确指定新的 --port 和 --data。',file=sys.stderr)
        return 1
    try:
        store=Store(args.data)
        server.store=store
    except (OSError,sqlite3.Error,ValueError) as e:
        server.server_close()
        print(f'数据库初始化失败：{e}。本次监听已释放，未打开浏览器。保留原数据，核对 --data 路径及备份。',file=sys.stderr)
        return 1
    stop=threading.Event()
    def poll():
        while not stop.wait(args.interval*60):
            try:
                # Demo snapshots advance only when the user explicitly checks their source.
                with store.connect() as db:
                    ids=[r[0] for r in db.execute("SELECT id FROM sources WHERE enabled=1 AND provider!='demo'")]
                for id in ids:
                    server.check(id)
            except (ValueError,sqlite3.Error,RuntimeError) as e:
                print('招聘源自动检查：',e,file=sys.stderr)
    url=f'http://127.0.0.1:{server.server_port}/'
    print(f'求职工作台：{url}\n数据库：{args.data.resolve()}\n关闭此窗口即停止网页和自动检查。', flush=True)
    if args.interval:
        threading.Thread(target=poll,daemon=True).start()
    if not args.no_browser:
        threading.Thread(target=lambda:webbrowser.open(url),daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0

if __name__=='__main__':
    sys.exit(run())
