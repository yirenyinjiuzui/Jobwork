from contextlib import closing
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from queue import Queue
from unittest.mock import patch,Mock
from urllib.request import Request,urlopen
import hashlib,json,re,socket,sqlite3,subprocess,sys,tempfile,threading,unittest
import server
from workbench import Store

ROOT=Path(__file__).resolve().parents[1]
class StartupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='启动 [隔离] ');self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
 def run_conflict(self,port,path):
  with patch.object(sys,'argv',['launch.py','--port',str(port),'--data',str(path),'--interval','0']),patch('server.webbrowser.open') as browser,patch('server.Store',side_effect=AssertionError('must not open Store')):
   self.assertEqual(server.run(),1);browser.assert_not_called()
 def test_arbitrary_http_200_is_not_probed_or_used_as_ready(self):
  class Always200(BaseHTTPRequestHandler):
   hits=0
   def do_GET(self):
    type(self).hits+=1;self.send_response(200);self.end_headers();self.wfile.write(b'OTHER SERVICE')
   def log_message(self,*args):pass
  listener=HTTPServer(('127.0.0.1',0),Always200);thread=threading.Thread(target=listener.serve_forever,daemon=True);thread.start()
  try:
   target=self.path/'new [data]'/'app.sqlite3';self.run_conflict(listener.server_port,target)
   self.assertFalse(target.parent.exists());self.assertEqual(Always200.hits,0)
   with urlopen(f'http://127.0.0.1:{listener.server_port}/') as response:self.assertEqual(response.read(),b'OTHER SERVICE')
  finally:listener.shutdown();listener.server_close();thread.join(3)
 def test_existing_old_workbench_same_and_other_database_untouched(self):
  old=self.path/'old.sqlite3';store=Store(old);store.save_application(dict(company='Fictional Existing',title='Intern'))
  listener=server.WorkbenchServer(('127.0.0.1',0),store);thread=threading.Thread(target=listener.serve_forever,daemon=True);thread.start()
  try:
   before=old.read_bytes();self.run_conflict(listener.server_port,old);self.assertEqual(old.read_bytes(),before)
   other=self.path/'other.sqlite3';Store(other)
   with closing(sqlite3.connect(other)) as db, db:db.execute('ALTER TABLE applications DROP COLUMN submitted_at')
   before=other.read_bytes();self.run_conflict(listener.server_port,other);self.assertEqual(other.read_bytes(),before)
   with urlopen(f'http://127.0.0.1:{listener.server_port}/api/state') as response:self.assertEqual(json.load(response)['applications'][0]['company'],'Fictional Existing')
  finally:listener.shutdown();listener.server_close();thread.join(3)
 def test_database_initialization_failure_releases_owned_listener(self):
  captured=[];original=server.WorkbenchServer
  def create(*args):
   result=original(*args);captured.append(result.server_port);return result
  with patch.object(sys,'argv',['launch.py','--port','0','--data',str(self.path/'bad.sqlite3'),'--interval','0']),patch('server.WorkbenchServer',side_effect=create),patch('server.Store',side_effect=sqlite3.DatabaseError('synthetic invalid database')),patch('server.webbrowser.open') as browser:
   self.assertEqual(server.run(),1);browser.assert_not_called()
  with closing(socket.socket()) as sock:sock.bind(('127.0.0.1',captured[0]))
 def start(self,db,port):
  proc=subprocess.Popen([sys.executable,'-B','launch.py','--data',str(db),'--port',str(port),'--interval','0','--no-browser'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  q=Queue();reader=threading.Thread(target=lambda:[q.put(line) for line in proc.stdout],daemon=True);reader.start()
  try:
   line=q.get(timeout=5);match=re.search(r'http://127\.0\.0\.1:\d+/',line);self.assertIsNotNone(match,line);return proc,match[0].rstrip('/')
  except BaseException:proc.terminate();proc.communicate(timeout=5);raise
 def test_first_start_restart_and_explicit_other_port_database(self):
  db=self.path/'正常 [库].sqlite3';proc,host=self.start(db,0)
  try:
   req=Request(host+'/api/application',json.dumps({'company':'Fictional Restart','title':'Intern'}).encode(),headers={'Content-Type':'application/json'})
   with urlopen(req) as r:self.assertEqual(json.load(r)['application']['company'],'Fictional Restart')
   second,other=self.start(self.path/'other.sqlite3',0)
   try:
    self.assertNotEqual(host,other)
    with urlopen(other+'/api/state') as r:self.assertEqual(json.load(r)['applications'],[])
   finally:second.terminate();second.communicate(timeout=5)
  finally:proc.terminate();proc.communicate(timeout=5)
  proc,restarted=self.start(db,int(host.rsplit(':',1)[1]))
  try:
   with urlopen(restarted+'/api/state') as r:self.assertEqual(json.load(r)['applications'][0]['company'],'Fictional Restart')
  finally:proc.terminate();proc.communicate(timeout=5)
 def test_windows_exclusive_branch_is_only_simulated(self):
  instance=server.WorkbenchServer.__new__(server.WorkbenchServer);instance.socket=Mock()
  with patch('server.os.name','nt'),patch.object(socket,'SO_EXCLUSIVEADDRUSE',12345,create=True),patch.object(server.ThreadingHTTPServer,'server_bind'):
   instance.server_bind()
  self.assertFalse(instance.allow_reuse_address);instance.socket.setsockopt.assert_called_once_with(socket.SOL_SOCKET,12345,1)
