"""Private application backups, bounded workspace hygiene and an escaped local HQ."""
import datetime as dt
import html
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import zipfile
from .common import ServiceError, Store, atomic, hash_bytes, json_bytes, now, read, safe

EXCLUDED = {'secrets', 'auth', 'credentials', '__pycache__', '.git', 'backups', 'native-backups'}
def eligible(name):
    parts = name.split('/')
    return not any(p in EXCLUDED or p.endswith('.lock') or p in ('auth-profiles.json', 'auth.json', '.env') for p in parts)

def backup(root, output, native=None):
    """Quiescent snapshot; caller must stop workers. SQLite uses its snapshot API."""
    root=Path(root).absolute(); output=Path(output).absolute()
    if output.exists(): raise ServiceError('Backup output already exists')
    try: output.relative_to(root)
    except ValueError: pass
    else: raise ServiceError('Store full backups outside the installation')
    with Store(root).transaction() as state:
        if any(j.get('lease') for j in state['jobs'].values()): raise ServiceError('Stop workers and resolve active leases before backup')
        payload={}
        with tempfile.TemporaryDirectory() as temp:
            for p in sorted(root.rglob('*')):
                name=p.relative_to(root).as_posix()
                if not eligible(name): continue
                safe(root,name)
                if not p.is_file(): continue
                if p.suffix in ('.sqlite','.sqlite3','.db'):
                    dest=Path(temp)/'snapshot.db'
                    with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as src, sqlite3.connect(str(dest)) as dst: src.backup(dst)
                    payload[name]=dest.read_bytes(); dest.unlink()
                elif p.name.endswith(('-wal','-shm')): continue
                else: payload[name]=p.read_bytes()
            payload['state/runtime.json']=json_bytes(state)
        native_meta=None
        if native:
            config_path=Path(native.get('config_path','')).expanduser()
            state_path=Path(native.get('state_dir','')).expanduser()
            if not config_path.is_absolute() or not config_path.is_file() or config_path.is_symlink() or not state_path.is_absolute() or not state_path.is_dir() or state_path.is_symlink(): raise ServiceError('Native recovery needs an existing absolute dedicated config and state directory')
            payload['native/config.json']=config_path.read_bytes()
            with tempfile.TemporaryDirectory() as temp:
                for p in sorted(state_path.rglob('*')):
                    name=p.relative_to(state_path).as_posix()
                    safe(state_path,name)
                    if any(part in ('.git','__pycache__') or part.endswith('.lock') for part in p.relative_to(state_path).parts) or not p.is_file(): continue
                    if p.suffix in ('.db','.sqlite','.sqlite3'):
                        dest=Path(temp)/'snapshot.db'
                        with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as src, sqlite3.connect(str(dest)) as dst: src.backup(dst)
                        payload['native/state/'+name]=dest.read_bytes(); dest.unlink()
                    elif not p.name.endswith(('-wal','-shm')): payload['native/state/'+name]=p.read_bytes()
            native_meta={'config_path':str(config_path),'state_dir':str(state_path),'credentials_included':True,'requires':'dedicated gateway stopped for a consistent profile snapshot'}
        if sum(len(b) for b in payload.values())>2*1024**3: raise ServiceError('Backup exceeds two GiB; archive heavy media separately')
        meta={'schema':1,'created':now(),'files':{n:hash_bytes(b) for n,b in payload.items()},'excluded':sorted(EXCLUDED),'native':native_meta,'scope':'installation plus dedicated native profile' if native else 'installation only; native auth and external gateway state require separate host backup'}
        output.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(dir=str(output.parent)); os.close(fd)
        try:
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
                for name,data in payload.items(): z.writestr('files/'+name,data)
                z.writestr('backup.json',json_bytes(meta))
            os.chmod(temp,0o600); os.replace(temp,output)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return {'backup':str(output),'sha256':hash_bytes(output.read_bytes()),'files':len(payload),'scope':meta['scope']}

def load_backup(archive,destination):
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>50000 or sum(i.file_size for i in infos)>2*1024**3: raise ServiceError('Oversized backup')
        if len({i.filename for i in infos})!=len(infos): raise ServiceError('Duplicate backup entry')
        for i in infos:
            safe(destination,i.filename)
            if i.is_dir() or (i.external_attr>>16)&0o170000==0o120000: raise ServiceError('Invalid backup entry')
        meta=json.loads(z.read('backup.json'))
        if meta.get('schema')!=1 or set(meta['files'])!={i.filename[6:] for i in infos if i.filename.startswith('files/')} or len(infos)!=len(meta['files'])+1: raise ServiceError('Invalid backup manifest')
        payload={name:z.read('files/'+name) for name in meta['files']}
        for name,data in payload.items():
            safe(destination,name)
            if (not eligible(name) and not (meta.get('native') and name.startswith('native/'))) or hash_bytes(data)!=meta['files'][name]: raise ServiceError('Invalid backup checksum/path')
    return meta,payload

def restore(archive, destination, apply=False):
    """Restore into a fresh directory, so a recovery never destroys current evidence."""
    destination=Path(destination).absolute()
    if destination.exists(): raise ServiceError('Restore requires a fresh destination')
    meta,payload=load_backup(archive,destination)
    payload={n:b for n,b in payload.items() if not n.startswith('native/')}
    if not apply: return {'applied':False,'files':len(payload),'destination':str(destination),'created':meta['created']}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=str(destination.parent)) as temp:
        stage=Path(temp)/'installation'; stage.mkdir(mode=0o700)
        for name,data in payload.items(): atomic(safe(stage,name),data)
        if (stage/'foundation').exists(): os.chmod(stage/'foundation',0o700)
        # Workspaces are still bound to their old host path. Require explicit render/provision.
        atomic(stage/'state/RESTORED.json',json_bytes({'at':now(),'requires':'render and provision; transport disabled until operator verifies target paths'}))
        cfg=read(stage/'config/backend.json',{})
        cfg.setdefault('native',{})['enabled']=False; cfg.setdefault('wake',{})['enabled']=False
        atomic(stage/'config/backend.json',json_bytes(cfg)); os.rename(stage,destination)
    return {'applied':True,'destination':str(destination),'native_enabled':False}

def restore_native(archive,destination,apply=False):
    destination=Path(destination).absolute()
    if destination.exists(): raise ServiceError('Native restore requires a fresh destination')
    meta,payload=load_backup(archive,destination)
    if not meta.get('native'): raise ServiceError('This backup has no native profile')
    payload={n[7:]:b for n,b in payload.items() if n.startswith('native/')}
    if not apply: return {'applied':False,'destination':str(destination),'files':len(payload),'credentials_included':True}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-restore-',dir=str(destination.parent)) as temp:
        stage=Path(temp)/'profile'; stage.mkdir(mode=0o700)
        for name,data in payload.items(): atomic(safe(stage,name),data)
        os.rename(stage,destination)
    return {'applied':True,'config_path':str(destination/'config.json'),'state_dir':str(destination/'state'),'next':'Review paths, set backend native profile, render/provision and prove seats before starting the dedicated gateway.'}

def hygiene(root, cfg):
    root=Path(root); changes=[]; cutoff=time.time()-cfg['notes_days']*86400
    for seat in read(safe(root,'generated/roster.json'))['agents']:
        prefix='workspaces/'+seat['id']+'/'
        for folder,age in [('memory',cfg['memory_days']),('work/notes',cfg['notes_days'])]:
            base=safe(root,prefix+folder)
            for p in sorted(base.glob('*.md')):
                name=p.relative_to(root).as_posix(); safe(root,name)
                if p.name in ('GOALS.md','OPEN.md') or p.stat().st_mtime>time.time()-age*86400: continue
                dest='archive/'+name
                if safe(root,dest).exists() and safe(root,dest).read_bytes()!=p.read_bytes(): dest='archive/'+str(time.time_ns())+'/'+name
                atomic(safe(root,dest),p.read_bytes()); p.unlink(); changes.append({'path':name,'archived':dest})
        for name,limit,words in [('GOALS.md',cfg['goals_chars'],False),('OPEN.md',cfg['open_words'],True)]:
            p=safe(root,prefix+'work/notes/'+name)
            if not p.exists(): continue
            text=p.read_text(); size=len(text.split()) if words else len(text)
            if size<=limit: continue
            # Keep the entire live sheet. A model must reconcile it; never silently truncate goals.
            with Store(root).transaction() as state:
                from .common import incident
                incident(state,'hygiene-'+seat['id']+'-'+name,'librarian','Goal/open sheet exceeds budget; reconcile against archived original',[name])
            dest='archive/oversized/'+seat['id']+'/'+str(time.time_ns())+'-'+name
            atomic(safe(root,dest),text.encode()); changes.append({'path':str(p),'action':'needs-reconciliation','archived':dest})
    return {'changes':changes}

def hq(root):
    state=Store(root).snapshot(); cfg=read(safe(root,'config/company.json'))
    rows=[]
    for j in sorted(state['jobs'].values(),key=lambda j:j['created'],reverse=True):
        rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in (j['id'],j['kind'],j['payload']['goal'],j['status'],j['stage'],j.get('error','')) )+'</tr>')
    incidents=''.join('<li>'+html.escape(i['owner']+': '+i['reason'])+'</li>' for i in state['incidents'].values() if i['status']=='open')
    context=read(safe(root,'company/context/current.json'),{'facts':{},'gaps':[],'conflicts':[]})
    body='<!doctype html><html lang="en"><meta charset="utf-8"><title>Company HQ</title><style>body{font:16px system-ui;margin:2rem;background:#f5f6f8;color:#17202a}table{border-collapse:collapse;width:100%;background:white}td,th{padding:.8rem;border:1px solid #ddd;text-align:left}code{white-space:pre-wrap}h1{font-size:2rem}</style><h1>'+html.escape(cfg['company_name'])+' HQ</h1><p>Local snapshot: '+html.escape(now())+'. Refresh with foundation hq. Operator commands handle approvals.</p><p>Context: '+str(len(context['facts']))+' facts; '+str(len(context.get('gaps',[])))+' gaps; '+str(len(context.get('conflicts',[])))+' conflicts.</p><h2>Jobs</h2><table><tr><th>ID<th>Kind<th>Goal<th>Status<th>Stage<th>Issue</tr>'+''.join(rows)+'</table><h2>Open incidents</h2><ul>'+incidents+'</ul><h2>Usage reservations</h2><code>'+html.escape(json.dumps(state['usage'],indent=2))+'</code></html>'
    p=safe(root,'generated/hq.html'); atomic(p,body.encode()); return {'hq':str(p),'jobs':len(rows)}
