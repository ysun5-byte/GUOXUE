# -*- coding: utf-8 -*-
"""Read-only full project inventory, exact hashes, and content deduplication."""
from pathlib import Path
from datetime import datetime, timezone
import collections
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import time

ROOT = Path('/Users/yuanfeisun/Desktop/八字手环')
OLD = Path('/Users/yuanfeisun/Documents/Codex/2026-11-01/00-01-part-1-23')
PREP = ROOT / 'work/上传准备'
SNAPSHOT = PREP / 'source_snapshot/desktop'
DB = PREP / 'inventory.sqlite'
SMALL_LIMIT = 48 * 1024 * 1024
assert not DB.exists(), 'Do not overwrite an existing source inventory.'
PREP.mkdir(parents=True, exist_ok=True)
SNAPSHOT.mkdir(parents=True, exist_ok=False)
conn = sqlite3.connect(DB)
conn.execute('PRAGMA journal_mode=WAL')
conn.executescript('''
CREATE TABLE paths(path TEXT PRIMARY KEY, scope TEXT NOT NULL, relative_path TEXT NOT NULL,
 source_path TEXT NOT NULL, kind TEXT NOT NULL, bytes INTEGER NOT NULL, mode INTEGER NOT NULL,
 dev INTEGER NOT NULL, ino INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 sha256 TEXT NOT NULL, git_blob TEXT NOT NULL, link_target TEXT);
CREATE TABLE objects(sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL, source_path TEXT NOT NULL,
 git_blob TEXT NOT NULL, kind TEXT NOT NULL, references_count INTEGER NOT NULL DEFAULT 1);
CREATE TABLE findings(path TEXT, category TEXT, byte_offset INTEGER);
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
''')
started = time.time()
stats = collections.Counter()
inode_cache = {}
last_progress = started
patterns = [
 ('github_classic_token', re.compile(rb'gh[pousr]_[A-Za-z0-9]{36,255}\b')),
 ('github_fine_grained_token', re.compile(rb'github_pat_[A-Za-z0-9_]{70,255}\b')),
 ('private_key', re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----')),
 ('aws_access_key', re.compile(rb'\bAKIA[0-9A-Z]{16}\b')),
 ('openai_project_key', re.compile(rb'\bsk-proj-[A-Za-z0-9_-]{48,255}\b')),
]
binary_suffixes = {'.zip','.gz','.png','.jpg','.jpeg','.webp','.gif','.pdf','.pptx','.mp4',
                   '.sqlite','.db','.woff','.woff2','.ttf','.ico','.heic','.mp3'}

def enumerate_files(base, exclude_prep=False):
    stack = [base]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda x:x.name)
        for e in entries:
            p = Path(e.path)
            if exclude_prep and (p == PREP or p == ROOT/'.git'):
                continue
            if e.is_symlink():
                yield p, 'symlink'
            elif e.is_dir(follow_symlinks=False):
                stack.append(p)
            elif e.is_file(follow_symlinks=False):
                yield p, 'file'
            else:
                raise RuntimeError('Unsupported source filesystem object: '+str(p))

desktop = list(enumerate_files(ROOT, exclude_prep=True))
for source, kind in desktop:
    relative = source.relative_to(ROOT)
    target = SNAPSHOT/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'symlink':
        os.symlink(os.readlink(source), target)
    else:
        result = subprocess.run(['/bin/cp','-c','-p',str(source),str(target)],
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if result.returncode:
            if target.exists(): target.unlink()
            shutil.copy2(source,target)
        assert source.stat().st_size == target.stat().st_size
print(json.dumps({'stage':'desktop_snapshot_complete','original_objects':len(desktop)},ensure_ascii=False),flush=True)

def add(repo_path, scope, relative, source, kind):
    global last_progress
    before=source.lstat()
    link_target=None
    if kind=='symlink':
        link_target=os.readlink(source)
        raw=os.fsencode(link_target)
        size=len(raw)
        content_hash=hashlib.sha256(raw).hexdigest()
        git_hash=hashlib.sha1(b'blob '+str(size).encode()+b'\0'+raw).hexdigest()
    else:
        assert stat.S_ISREG(before.st_mode)
        size=before.st_size
        cache_key=(before.st_dev,before.st_ino,size,before.st_mtime_ns)
        if cache_key in inode_cache:
            content_hash,git_hash=inode_cache[cache_key]
            stats['inode_reads_reused']+=1
        else:
            h=hashlib.sha256()
            g=hashlib.sha1(b'blob '+str(size).encode()+b'\0')
            seen_findings=set()
            offset=0
            tail=b''
            scan=source.suffix.lower() not in binary_suffixes
            with source.open('rb')as f:
                while True:
                    block=f.read(4*1024*1024)
                    if not block:break
                    h.update(block);g.update(block)
                    if scan:
                        check=tail+block
                        for category,pattern in patterns:
                            for match in pattern.finditer(check):
                                absolute=offset-len(tail)+match.start()
                                if (category,absolute)not in seen_findings:
                                    conn.execute('INSERT INTO findings VALUES(?,?,?)',(repo_path,category,absolute))
                                    seen_findings.add((category,absolute))
                        tail=check[-512:]
                    offset+=len(block)
            after=source.stat()
            if (after.st_size,after.st_mtime_ns,after.st_ino)!=(size,before.st_mtime_ns,before.st_ino):
                raise RuntimeError('Source changed while reading: '+str(source))
            assert offset==size
            content_hash,git_hash=h.hexdigest(),g.hexdigest()
            inode_cache[cache_key]=(content_hash,git_hash)
            stats['physical_hashed_bytes']+=size
            stats['physical_files_hashed']+=1
    previous=conn.execute('SELECT bytes FROM objects WHERE sha256=?',(content_hash,)).fetchone()
    if previous:
        assert previous[0]==size
        conn.execute('UPDATE objects SET references_count=references_count+1 WHERE sha256=?',(content_hash,))
    else:
        conn.execute('INSERT INTO objects VALUES(?,?,?,?,?,1)',(content_hash,size,str(source),git_hash,kind))
        stats['unique_content_bytes']+=size
        stats['unique_contents']+=1
        stats['large_unique_bytes'if size>SMALL_LIMIT else'small_unique_bytes']+=size
    conn.execute('INSERT INTO paths VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 (repo_path,scope,str(relative),str(source),kind,size,stat.S_IMODE(before.st_mode),
                  before.st_dev,before.st_ino,before.st_mtime_ns,content_hash,git_hash,link_target))
    stats['path_records']+=1
    stats['logical_bytes']+=size
    stats[scope+'_records']+=1
    if stats['path_records']%1000==0:
        conn.commit()
    if time.time()-last_progress>15:
        conn.commit()
        progress=dict(stage='hashing',elapsed_seconds=round(time.time()-started,1),**stats)
        (PREP/'inventory_progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(progress,ensure_ascii=False),flush=True)
        last_progress=time.time()

for p,kind in enumerate_files(SNAPSHOT):
    rel=p.relative_to(SNAPSHOT)
    add(str(rel),'desktop',rel,p,kind)
for p,kind in enumerate_files(OLD):
    rel=p.relative_to(OLD)
    add('research-history/part1-2026-11-01/'+str(rel),'history',rel,p,kind)

formal=OLD/'outputs/Part1_研究成果_统一可复现交付'
mf=json.loads((formal/'DELIVERY_MANIFEST_r1.json').read_text())
permanent=list(mf['files'])+['DELIVERY_MANIFEST_r1.json','DELIVERY_FREEZE_r1.json']
assert len(permanent)==285
for rel in permanent:
    p=formal/rel
    add('research/part1-final/'+rel,'final_view',rel,p,'file')

friendly={
 'research/研究成果总览.txt':'outputs/研究成果总览_先读这一份.txt',
 'research/规则运行与完整算例_rev626.txt':'outputs/整套规则怎么运行_大白话与完整算例_rev626.txt',
 'research/最终验收与使用说明_rev624.txt':'outputs/Part1_研究成果_最终验收与使用说明_rev624.txt',
 'research/最终验收与独立复核记录_rev624.zip':'outputs/Part1_最终验收与独立复核记录_rev624.zip',
 'research/当前研究与接续入口_rev625.txt':'outputs/当前研究与接续入口_rev625.txt',
}
for dest,source in friendly.items():
    add(dest,'final_docs',source,OLD/source,'file')
conn.commit()
summary=dict(schema='guoxue-full-project-content-inventory/1',status='complete',
 started_utc=datetime.fromtimestamp(started,timezone.utc).isoformat(),finished_utc=datetime.now(timezone.utc).isoformat(),
 elapsed_seconds=round(time.time()-started,1),stats=dict(stats),
 original_source_root=str(OLD),desktop_source_root=str(ROOT),desktop_snapshot=str(SNAPSHOT),
 user_scope='Desktop project plus every available file and version in the whole original research project; content dedup retains all path aliases.',
 historical_generated_prepared_runtime_included=True,
 excluded='Only this task-generated work/上传准备 and new .git; external targets of original symlinks are not traversed.',
 secret_pattern_findings=conn.execute('SELECT count(*) FROM findings').fetchone()[0],
 original_frozen_source_files_not_modified=True)
conn.execute('INSERT INTO metadata VALUES(?,?)',('summary',json.dumps(summary,ensure_ascii=False)))
conn.commit()
(PREP/'inventory_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False),flush=True)
conn.close()
