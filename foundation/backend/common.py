import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

SCHEMA = 2
class ServiceError(Exception): pass

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def hash_bytes(data): return hashlib.sha256(data).hexdigest()
def json_bytes(obj): return (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()
def fingerprint(obj): return hash_bytes(json_bytes(obj))
def uid(prefix): return prefix + '-' + uuid.uuid4().hex[:16]
def read(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError:
        if default is not None: return default
        raise ServiceError('Missing file: ' + str(path))
    except ValueError: raise ServiceError('Malformed JSON: ' + str(path))
def safe(root, relative):
    if not isinstance(relative,str) or not relative or '\\' in relative or relative.startswith('/') or any(p in ('','..','.') for p in relative.split('/')):
        raise ServiceError('Unsafe relative path')
    root=Path(root).absolute(); p=root
    if root.is_symlink(): raise ServiceError('Root cannot be a symlink')
    for part in relative.split('/'):
        p=p/part
        if p.is_symlink(): raise ServiceError('Symlink refused: '+relative)
    try: p.resolve().relative_to(root.resolve())
    except ValueError: raise ServiceError('Path escapes root')
    return p

def atomic(path, data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.write-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp,0o600); os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def initial():
    return {'schema':SCHEMA,'jobs':{},'incidents':{},'approvals':{},'usage':{},'wakes':{},'receipts':{},'events':[]}

def migrate(state):
    """Explicit additive migration. Unknown newer schemas fail closed."""
    if not isinstance(state,dict): raise ServiceError('Runtime state must be an object')
    version=state.get('schema',1)
    if version>SCHEMA or version<1: raise ServiceError('Unsupported runtime schema')
    out=json.loads(json.dumps(state))
    if version==1:
        out.setdefault('receipts',{})
        for job in out.get('jobs',{}).values(): job.setdefault('attempts',0)
        out['schema']=2
    for key,value in initial().items(): out.setdefault(key,value)
    return out

class Store:
    def __init__(self,root): self.root=Path(root).absolute(); self.path=safe(self.root,'state/runtime.json')
    @contextlib.contextmanager
    def transaction(self):
        lock=safe(self.root,'state/runtime.lock'); lock.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:
                original=read(self.path,initial()); state=migrate(original)
                yield state
                if state!=original:
                    state['events']=state['events'][-2000:]
                    atomic(self.path,json_bytes(state))
            finally: fcntl.flock(f,fcntl.LOCK_UN)
    def snapshot(self): return migrate(read(self.path,initial()))

def event(state,kind,**fields):
    state['events'].append(dict(at=now(),kind=kind,**fields))

def incident(state,key,owner,reason,evidence=None):
    old=state['incidents'].get(key)
    item={'key':key,'owner':owner,'reason':reason,'status':'open','evidence':evidence or [],'updated':now()}
    if old and old['status']=='open' and old['reason']==reason: return old
    item['since']=old.get('since',now()) if old else now()
    state['incidents'][key]=item; event(state,'incident',key=key,owner=owner,reason=reason)
    return item

def inbox(root,seat,message):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',seat): raise ServiceError('Invalid seat')
    name='workspaces/%s/work/inbox/%s.json'%(seat,uid('event'))
    atomic(safe(root,name),json_bytes(message)); return name
