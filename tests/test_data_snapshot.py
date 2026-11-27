from contextlib import closing
from pathlib import Path
import hashlib,shutil,sqlite3,subprocess,sys,tempfile,unittest
from data_snapshot import snapshot
from workbench import Store

class SnapshotTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='备份 [测试] ');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.src=self.root/'原始 [数据].sqlite3';self.dst=self.root/'备份 [新].sqlite3';self.store=Store(self.src)
 def test_active_wal_committed_and_uncommitted_restore(self):
  with closing(sqlite3.connect(self.src)) as writer:
   writer.execute('PRAGMA wal_autocheckpoint=0');writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
   saved=self.store.save_application(dict(company='Fictional Harbor',title='Intern',status='submitted'))
   shutil.copyfile(self.src,self.root/'main-only.sqlite3')
   with closing(sqlite3.connect(self.root/'main-only.sqlite3')) as copy:self.assertEqual(copy.execute('SELECT count(*) FROM applications').fetchone()[0],0)
   writer.execute("INSERT INTO settings VALUES ('uncommitted','synthetic')")
   schema=writer.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
   result=snapshot(self.src,self.dst);self.assertEqual(result['counts']['applications'],1)
   restored=self.root/'还原 [新].sqlite3';snapshot(self.dst,restored)
   with closing(sqlite3.connect(restored)) as db:
    self.assertEqual(db.execute("SELECT count(*) FROM settings WHERE key='uncommitted'").fetchone()[0],0)
    self.assertEqual(schema,db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall())
    self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
   self.assertEqual(Store(restored).applications()[0]['id'],saved['id']);writer.rollback()
  self.assertEqual(result['sha256'],hashlib.sha256(self.dst.read_bytes()).hexdigest());self.assertFalse(Path(str(self.dst)+'-wal').exists())
 def test_source_missing_never_creates_source_or_target(self):
  missing=self.root/'missing.sqlite3'
  with self.assertRaises(FileNotFoundError):snapshot(missing,self.dst)
  self.assertFalse(missing.exists());self.assertFalse(self.dst.exists())
 def test_existing_destination_and_source_refused(self):
  self.dst.write_bytes(b'KEEP')
  with self.assertRaises(FileExistsError):snapshot(self.src,self.dst)
  self.assertEqual(self.dst.read_bytes(),b'KEEP')
  with self.assertRaises(FileExistsError):snapshot(self.src,self.src)
 def test_existing_sidecar_refused(self):
  side=Path(str(self.dst)+'-wal');side.write_bytes(b'KEEP')
  with self.assertRaises(FileExistsError):snapshot(self.src,self.dst)
  self.assertEqual(side.read_bytes(),b'KEEP');self.assertFalse(self.dst.exists())
 def test_invalid_or_unrelated_source_cleans_only_new_destination(self):
  for content in (b'not a database',b''):
   bad=self.root/'bad';bad.write_bytes(content)
   with self.assertRaises((sqlite3.Error,ValueError)):snapshot(bad,self.dst)
   self.assertFalse(self.dst.exists());self.assertEqual(bad.read_bytes(),content)
 def test_parent_missing_fails(self):
  with self.assertRaises(ValueError):snapshot(self.src,self.root/'missing'/'new.db')
  self.assertFalse((self.root/'missing').exists())
 def test_cli_success_failure_and_interactive(self):
  script=Path(__file__).resolve().parents[1]/'launch.py'
  def run(*args,input=None):return subprocess.run([sys.executable,'-B',str(script),'--data-tools',*args],input=input,text=True,capture_output=True)
  result=run('backup',str(self.src),str(self.dst));self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('integrity_check=ok',result.stdout);self.assertIn('SHA256:',result.stdout)
  self.assertNotEqual(run('restore',str(self.src),str(self.dst)).returncode,0)
  new=self.root/'interactive.sqlite3';result=run(input=f'2\n{self.dst}\n{new}\n');self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(new.exists())
 def test_existing_backup_unchanged_after_restore(self):
  snapshot(self.src,self.dst);before=self.dst.read_bytes();snapshot(self.dst,self.root/'restore.sqlite3');self.assertEqual(before,self.dst.read_bytes())

if __name__=='__main__':unittest.main()
