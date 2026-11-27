"""Rebuilt compatibility acceptance from the visible v1.1.12 record."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import sqlite3,subprocess,sys,unittest,json,threading
from urllib.request import Request,urlopen
from data_snapshot import snapshot
from workbench import Store,SCHEMA
from server import WorkbenchServer
class CompatibilityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory(prefix='恢复 [重建] ');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.src=self.root/'source.sqlite3';self.dst=self.root/'restored.sqlite3'
 def make(self,sql=SCHEMA):
  with closing(sqlite3.connect(self.src)) as c:c.executescript(sql);c.commit()
 def reject(self,pattern):
  original=self.src.read_bytes()
  with self.assertRaisesRegex(ValueError,pattern):snapshot(self.src,self.dst)
  self.assertFalse(self.dst.exists());self.assertEqual(original,self.src.read_bytes());self.assertFalse(list(self.root.glob('restored.sqlite3-*')))
 def test_impostor(self):
  self.make(';'.join('CREATE TABLE '+t+' (unrelated TEXT)' for t in ('applications','jobs','companies','sources','notifications','settings')));self.reject('missing columns')
 def test_history_required(self):
  self.make()
  with closing(sqlite3.connect(self.src)) as c, c:c.execute('DROP TABLE history')
  self.reject('history')
 def test_columns_and_unique(self):
  self.make(SCHEMA.replace('identity TEXT UNIQUE NOT NULL','identity TEXT NOT NULL'));self.reject('uniqueness')
  self.src.unlink();self.make(SCHEMA.replace('active INTEGER NOT NULL DEFAULT 1','active TEXT NOT NULL DEFAULT 1'));self.reject('jobs.active')
 def test_view_and_trigger(self):
  self.make()
  with closing(sqlite3.connect(self.src)) as c, c:c.execute('DROP TABLE notifications');c.execute('CREATE VIEW notifications AS SELECT 1 AS id')
  self.reject('notifications');self.src.unlink();self.make()
  with closing(sqlite3.connect(self.src)) as c, c:c.execute('CREATE TRIGGER unexpected AFTER INSERT ON applications BEGIN DELETE FROM jobs; END')
  self.reject('trigger')
 def test_json(self):
  Store(self.src).save_application(dict(company='Fictional Restore',title='Intern'))
  with closing(sqlite3.connect(self.src)) as c, c:c.execute("UPDATE applications SET date_precision='[]'")
  self.reject('date_precision')
 def test_legacy_optional_columns(self):
  Store(self.src).save_application(dict(company='Fictional Legacy',title='Intern',status='submitted'))
  with closing(sqlite3.connect(self.src)) as c, c:c.execute('ALTER TABLE applications DROP COLUMN resume_label');c.execute('ALTER TABLE applications DROP COLUMN submitted_at')
  original=self.src.read_bytes();snapshot(self.src,self.dst);self.assertEqual(original,self.src.read_bytes());s=Store(self.dst);a=s.applications()[0];self.assertEqual(a['submitted_at'],'');self.assertEqual(s.save_application({'id':a['id'],'status':'interview'})['status'],'interview')
 def test_cli_reject_preserves_current_and_source(self):
  self.make(';'.join('CREATE TABLE '+t+' (unrelated TEXT)' for t in ('applications','jobs','companies','sources','notifications','settings')))
  current=self.root/'current.sqlite3';Store(current).save_application(dict(company='Fictional Current',title='Intern'));before=[p.read_bytes() for p in (self.src,current)]
  for target in (self.dst,current):
   r=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'data_snapshot.py'),'restore',str(self.src),str(target)],capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertNotIn('SUCCESS',r.stdout);self.assertIn('Keep them',r.stderr)
  self.assertEqual(before,[p.read_bytes() for p in (self.src,current)]);self.assertFalse(self.dst.exists())
 def test_restored_http_read_write_survives_rejected_overwrite(self):
  Store(self.src).save_application(dict(company='Fictional HTTP',title='Intern'));snapshot(self.src,self.dst)
  s=WorkbenchServer(('127.0.0.1',0),Store(self.dst));thread=threading.Thread(target=s.serve_forever,daemon=True);thread.start();host='http://127.0.0.1:'+str(s.server_port)
  try:
   with urlopen(host+'/api/state') as r:a=json.load(r)['applications'][0]
   with self.assertRaises(FileExistsError):snapshot(self.src,self.dst)
   request=Request(host+'/api/application',json.dumps({**a,'status':'interview'}).encode(),headers={'Content-Type':'application/json'})
   with urlopen(request) as r:self.assertEqual(json.load(r)['application']['status'],'interview')
  finally:s.shutdown();s.server_close();thread.join(3)
