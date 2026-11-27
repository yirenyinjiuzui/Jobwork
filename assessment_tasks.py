"""Small per-application assessment ledger in the existing settings table."""
import json

def key(value):
    return str(value or '').strip().casefold()

def load(db, application):
    if not application:
        return {}
    saved=db.execute('SELECT value FROM settings WHERE key=?',('assessment_tasks:'+str(application['id']),)).fetchone()
    if saved:
        return json.loads(saved[0])
    legacy=db.execute('SELECT value FROM settings WHERE key=?',('assessment:'+str(application['id']),)).fetchone()
    # Old completed/unknown history is never guessed into a pending task.
    if legacy and application['status']=='assessment':
        return {key(legacy[0]):{'id':legacy[0],'completed':False,'deadline':application['deadline'],
            'precision':application.get('date_precision',{}).get('deadline','unknown'),
            'notice_at':application.get('last_notice_at','')}}
    return {}

def save(db, app_id, tasks):
    db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        ('assessment_tasks:'+str(app_id),json.dumps(tasks,ensure_ascii=False)))
