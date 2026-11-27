"""Verified SQLite snapshots. Never instantiate Store or migrate the source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from contextlib import closing


def readonly(path):
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)


def validate_schema(db):
    # Reconstructed from visible v1.1.12 work record; never migrate the source.
    from workbench import SCHEMA
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(SCHEMA)
        tables=[r[0] for r in reference.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        optional={'applications':{'resume_label','submitted_at','interview_reply_by'}}
        def unique_columns(con,table):
            return {tuple(r[2] for r in con.execute('PRAGMA index_info("'+idx[1].replace('"','""')+'")'))
                    for idx in con.execute('PRAGMA index_list("'+table+'")') if idx[2]}
        def foreign_keys(con,table):
            return sorted(tuple(r[2:]) for r in con.execute('PRAGMA foreign_key_list("'+table+'")'))
        for table in tables:
            row=db.execute('SELECT type,sql FROM sqlite_master WHERE name=?',(table,)).fetchone()
            if not row or row[0]!='table' or not row[1] or 'VIRTUAL TABLE' in row[1].upper():
                raise ValueError('Not a supported workbench backup: missing ordinary table '+table)
            expected={r[1]:r for r in reference.execute('PRAGMA table_info("'+table+'")')}
            actual={r[1]:r for r in db.execute('PRAGMA table_info("'+table+'")')}
            missing=set(expected)-set(actual)-optional.get(table,set())
            extra=set(actual)-set(expected)
            if missing or extra:
                raise ValueError('Incompatible table '+table+'; missing columns: '+','.join(sorted(missing))+'; unsupported columns: '+','.join(sorted(extra)))
            for name,col in actual.items():
                if tuple(col[2:])!=tuple(expected[name][2:]):
                    raise ValueError('Incompatible column definition: '+table+'.'+name)
            if unique_columns(db,table)!=unique_columns(reference,table):
                raise ValueError('Incompatible uniqueness/primary-key indexes: '+table)
            if foreign_keys(db,table)!=foreign_keys(reference,table):
                raise ValueError('Incompatible foreign-key structure: '+table)
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,)).fetchone():
                raise ValueError('Unsupported trigger on workbench table: '+table)
        for (raw,) in db.execute('SELECT date_precision FROM applications'):
            try:valid=isinstance(json.loads(raw),dict)
            except (TypeError,ValueError):valid=False
            if not valid:raise ValueError('Unreadable applications.date_precision JSON; keep backup for repair')
        return tables


def validate(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('Database integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise ValueError('Database foreign key check failed')
    tables=validate_schema(db)
    counts = {}
    for table in tables:
        counts[table] = db.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
    return counts


def snapshot(source, destination):
    source = Path(source).expanduser().resolve(strict=True)
    destination = Path(destination).expanduser().absolute()
    if not source.is_file():
        raise ValueError('Source must be an existing database file')
    if not destination.parent.is_dir():
        raise ValueError('Destination parent folder must already exist')
    for name in (destination, Path(str(destination)+'-wal'), Path(str(destination)+'-shm'), Path(str(destination)+'-journal')):
        if os.path.lexists(name):
            raise FileExistsError('Destination or its SQLite sidecar already exists: ' + str(name))
    # Exclusive creation also guards against another backup selecting this name.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        deadline = time.monotonic() + 30
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('Snapshot timed out; retry when database is less busy')
        with closing(readonly(source)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst, pages=128, progress=progress, sleep=0.05)
            # Standalone artifact: no dependency on WAL/SHM files after close.
            dst.execute('PRAGMA journal_mode=DELETE')
            dst.commit()
        with closing(readonly(destination)) as check:
            counts = validate(check)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        return {'path': str(destination.resolve()), 'sha256': digest, 'counts': counts}
    except BaseException:
        # Only files owned by this failed, exclusively created destination.
        for path in (destination, Path(str(destination)+'-wal'), Path(str(destination)+'-shm'), Path(str(destination)+'-journal')):
            path.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verified data backup/restore into a NEW SQLite file; never overwrite.')
    parser.add_argument('action', nargs='?', choices=('backup', 'restore'))
    parser.add_argument('source', nargs='?')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args(argv)
    try:
        if args.action is None:
            print('Database backup / restore (NOT program ZIP/TXT recovery).')
            print('1 = backup; 2 = restore to NEW database. Existing files are never replaced.')
            action = input('Choice [1/2]: ').strip()
            if action not in ('1','2'):
                raise ValueError('Choose 1 or 2')
            source = input('Existing source database full path: ').strip().strip('"')
            destination = input('NEW destination database full path (parent folder must exist): ').strip().strip('"')
            if not source or not destination:
                raise ValueError('Both paths are required')
        else:
            if not args.source or not args.destination:
                raise ValueError('Both source and destination paths are required')
            source, destination = args.source, args.destination
        result = snapshot(source, destination)
        print('SUCCESS: independent snapshot reopened; integrity_check=ok; foreign_key_check=ok; workbench_schema=ok')
        print('File:', result['path'])
        print('Applications:', result['counts']['applications'], '; Jobs:', result['counts']['jobs'], '; History:', result['counts']['history'])
        print('SHA256:', result['sha256'])
        print('Keep the original installation and backup. Verify records before using the new installation.')
        return 0
    except (OSError, ValueError, sqlite3.Error, EOFError) as exc:
        print('FAILED: ' + str(exc) + '. Original database and source backup were not replaced. Keep them; choose a known workbench backup or request repair. Start the new installation only after SUCCESS; do not delete the current data.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
