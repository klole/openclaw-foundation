"""Explicit native provisioning preserving unrelated gateway fields, with CAS rollback."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
from .common import ServiceError, Store, atomic, fingerprint, hash_bytes, json_bytes, now, read, safe, uid

def native_path(cfg):
    value=cfg['native'].get('config_path','')
    if not value or not Path(value).expanduser().is_absolute(): raise ServiceError('Set an absolute native.config_path')
    p=Path(value).expanduser()
    if p.is_symlink(): raise ServiceError('Native config cannot be a symlink')
    return p

def candidate(root,cfg):
    path=native_path(cfg); original=path.read_bytes(); current=json.loads(original)
    result=json.loads(original); fragment=read(safe(root,'generated/openclaw.fragment.json'))
    agents=result.setdefault('agents',{})
    if agents.get('ownership') not in (None,'explicit') or agents.get('list'): raise ServiceError('Target gateway must use explicit agents.entries; convert separately before provisioning')
    entries=agents.setdefault('entries',{}); tracked=read(safe(root,'state/provision.json'),{'entries':{}})
    changes=[]
    for seat,entry in fragment['agents']['entries'].items():
        existing=entries.get(seat)
        if existing is not None:
            if seat not in tracked['entries']: raise ServiceError('Agent id collision on this gateway: '+seat+'. Use a dedicated gateway/profile for each company.')
            if fingerprint(existing)!=tracked['entries'][seat]: raise ServiceError('Provisioned entry edited outside foundation: '+seat)
        if existing!=entry: changes.append(seat)
        entries[seat]=entry
    removed=set(tracked['entries'])-set(fragment['agents']['entries'])
    for seat in removed:
        if fingerprint(entries.get(seat))!=tracked['entries'][seat]: raise ServiceError('Retired entry changed externally: '+seat)
        del entries[seat]; changes.append(seat)
    agents['ownership']='explicit'
    # Only seed defaults on a fresh explicit gateway; never repoint another company's COS.
    if not current.get('agents',{}).get('entries'):
        agents.setdefault('defaults',{}).update(fragment['agents']['defaults'])
    # File request bridge doesn't need native peer messaging; preserve existing global policy.
    data=json_bytes(result)
    return path,original,data,changes,fragment['agents']['entries']

def provision(root,cfg,apply=False):
    path,before,after,changes,entries=candidate(root,cfg)
    result={'applied':False,'config_path':str(path),'changed_seats':changes,'before_sha256':hash_bytes(before),'after_sha256':hash_bytes(after),'gateway_restart_required':bool(changes)}
    if not apply: return result
    if not changes: return result
    with Store(root).transaction() as state:
        if any(j.get('lease') for j in state['jobs'].values()): raise ServiceError('Stop workers before native provisioning')
        fd,temp=tempfile.mkstemp(prefix='.foundation-native-',suffix='.json',dir=str(path.parent)); os.close(fd)
        try:
            atomic(temp,after); env=dict(os.environ,OPENCLAW_CONFIG_PATH=temp)
            if cfg['native'].get('env_path'): env['PATH']=cfg['native']['env_path']
            if cfg['native'].get('state_dir'): env['OPENCLAW_STATE_DIR']=cfg['native']['state_dir']
            proc=subprocess.run([cfg['native']['binary'],'config','validate','--json'],capture_output=True,text=True,timeout=60,env=env)
            if proc.returncode: raise ServiceError('Native candidate schema validation failed; live config untouched')
            if path.read_bytes()!=before: raise ServiceError('Gateway config changed during validation; preview again')
            receipt=uid('provision'); prior=read(safe(root,'state/provision.json'),{'entries':{}})
            atomic(safe(root,'state/native-backups/'+receipt+'.json'),json_bytes({'path':str(path),'before':json.loads(before),'before_bytes':before.decode(),'after_sha256':hash_bytes(after),'prior':prior}))
            atomic(path,after)
            atomic(safe(root,'state/provision.json'),json_bytes({'at':now(),'entries':{k:fingerprint(v) for k,v in entries.items()},'config_path':str(path),'receipt':receipt,'gateway_restart_verified':False}))
        finally: Path(temp).unlink(missing_ok=True)
    result.update(applied=True,receipt=receipt); return result

def provision_rollback(root,cfg,receipt,apply=False):
    if not receipt.startswith('provision-') or '/' in receipt: raise ServiceError('Invalid provision receipt')
    saved=read(safe(root,'state/native-backups/'+receipt+'.json')); path=native_path(cfg)
    if str(path)!=saved['path'] or hash_bytes(path.read_bytes())!=saved['after_sha256']: raise ServiceError('Gateway changed since provisioning; rollback requires reconciliation')
    if not apply: return {'applied':False,'receipt':receipt,'config_path':str(path)}
    with Store(root).transaction() as state:
        if any(j.get('lease') for j in state['jobs'].values()): raise ServiceError('Stop workers before rollback')
        if hash_bytes(path.read_bytes())!=saved['after_sha256']: raise ServiceError('Gateway changed during rollback')
        atomic(path,saved['before_bytes'].encode()); atomic(safe(root,'state/provision.json'),json_bytes(saved['prior']))
    return {'applied':True,'receipt':receipt,'gateway_restart_required':True}

def service_files(root,python):
    root=Path(root).absolute(); python=Path(python).absolute()
    if not python.is_file(): raise ServiceError('Choose an existing Python 3.9+ executable')
    cid=read(safe(root,'config/company.json'))['company_id']; label='local.openclaw.foundation.'+cid
    safe(root,'state').mkdir(parents=True,exist_ok=True,mode=0o700)
    args=[str(python),str(root/'foundation'),'serve','--root',str(root)]
    plist={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':True,'StandardOutPath':str(root/'state/service.stdout.log'),'StandardErrorPath':str(root/'state/service.stderr.log'),'ThrottleInterval':30}
    atomic(safe(root,'generated/service.launchd.plist'),plistlib.dumps(plist))
    # systemd quoting follows systemd.syntax, not shell quoting.
    def quote(v): return '"'+str(v).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    unit='[Unit]\nDescription=OpenClaw foundation '+cid+'\nAfter=network-online.target\n[Service]\nType=simple\nWorkingDirectory='+quote(root)+'\nExecStart='+' '.join(quote(a) for a in args)+'\nRestart=on-failure\nRestartSec=30\nUMask=0077\n[Install]\nWantedBy=default.target\n'
    atomic(safe(root,'generated/service.systemd.unit'),unit.encode())
    return {'launchd':str(root/'generated/service.launchd.plist'),'systemd':str(root/'generated/service.systemd.unit'),'activated':False}
