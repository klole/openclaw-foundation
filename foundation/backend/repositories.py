"""Configured repository checks and exact-head operator merge; never self-merge."""
from pathlib import Path
import re
import subprocess
from .common import ServiceError, atomic, json_bytes, now, safe

def run(args,cwd,timeout=120):
    try: p=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired): raise ServiceError('Repository command failed or timed out')
    if p.returncode: raise ServiceError('Repository check failed: '+args[0])
    return p.stdout

def checks(root,cfg,payload,before_check=None):
    repo=cfg['repositories'].get(payload.get('repository'))
    if not repo: raise ServiceError('Repository is not configured')
    checkout=Path(repo['path']).expanduser().absolute()
    if checkout.is_symlink() or not checkout.is_dir(): raise ServiceError('Invalid checkout')
    sha=payload.get('head','')
    if not re.fullmatch('[a-f0-9]{40}',sha) or run(['git','rev-parse','HEAD'],checkout).strip()!=sha: raise ServiceError('Checkout must be the exact proposed head')
    if run(['git','status','--porcelain'],checkout).strip(): raise ServiceError('Repository checks need a clean checkout')
    if not repo.get('checks'): raise ServiceError('Configure meaningful check commands')
    receipts=[]
    for args in repo['checks']:
        if not isinstance(args,list) or not args or not all(isinstance(a,str) for a in args): raise ServiceError('Check must be a literal argument array; shell expressions are not evaluated')
        timeout=repo.get('timeout',300)
        if not isinstance(timeout,int) or not 1<=timeout<=900: raise ServiceError('Check timeout must be 1..900 seconds')
        if before_check: before_check(timeout)
        out=run(args,checkout,timeout); receipts.append({'command':args,'passed':True,'output_tail':out[-4000:]})
    if run(['git','rev-parse','HEAD'],checkout).strip()!=sha or run(['git','status','--porcelain'],checkout).strip(): raise ServiceError('Checks changed tracked checkout; review before release')
    return {'head':sha,'repository':payload['repository'],'checks':receipts,'at':now()}

def merge(runtime,jid):
    import json
    state=runtime.store.snapshot(); job=state['jobs'][jid]; p=job['payload']
    if job['kind']!='gate' or job['status']!='release-ready' or not runtime.authorized(state,job): raise ServiceError('Exact change needs independent review and current owner approval')
    repo=runtime.cfg['repositories'].get(p.get('repository'),{})
    if not repo.get('github') or not repo.get('merger_login'): raise ServiceError('Configure github repository and independent merger_login')
    pr=str(p.get('pr',''))
    if not pr.isdigit(): raise ServiceError('PR number required')
    cwd=repo['path']; gh=repo.get('gh_binary','gh')
    login=run([gh,'api','user','--jq','.login'],cwd).strip()
    info=json.loads(run([gh,'pr','view',pr,'--repo',repo['github'],'--json','headRefOid,author,state'],cwd))
    if info['state']!='OPEN' or info['headRefOid']!=p['head'] or login!=repo['merger_login'] or info['author']['login']==login: raise ServiceError('PR head/independent merge identity does not match approval')
    proof=checks(runtime.root,runtime.cfg,p)
    run([gh,'pr','merge',pr,'--repo',repo['github'],'--squash','--match-head-commit',p['head']],cwd)
    receipt={'at':now(),'head':p['head'],'pr':pr,'repository':repo['github'],'merger':login,'proof':proof}
    atomic(safe(runtime.root,'state/merge-receipts/'+jid+'.json'),json_bytes(receipt))
    with runtime.store.transaction() as current:
        current['jobs'][jid]['status']='done'; current['jobs'][jid]['results']['merge']=receipt
    return receipt
