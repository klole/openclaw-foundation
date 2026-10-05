"""Read-only adapter collection, current fact reconciliation, frozen goal packets."""
import datetime as dt
import json
from pathlib import Path
import re
from .common import ServiceError, atomic, fingerprint, json_bytes, now, read, safe

AREAS=('company','numbers','offers','marketing','tools','people','gaps')
def stamp(value):
    try:
        parsed=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError,TypeError): raise ServiceError('Fact needs an ISO date/time')

def validate(fact):
    for key in ('id','area','label','value','as_of','source','fresh_hours'):
        if key not in fact: raise ServiceError('Fact missing '+key)
    if not re.fullmatch(r'[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+',fact['id']) or fact['area'] not in AREAS: raise ServiceError('Invalid fact id or area')
    if not isinstance(fact['fresh_hours'],(int,float)) or fact['fresh_hours']<=0: raise ServiceError('Invalid freshness')
    stamp(fact['as_of']); return dict(fact)

def collect(root):
    root=Path(root); prior=read(safe(root,'company/context/current.json'),{'facts':{},'sources':{},'conflicts':[]})
    recorded=read(safe(root,'company/context/facts.json'),{'facts':[]}).get('facts',[])
    config=read(safe(root,'company/context/sources.json'),{'sources':[]})
    facts={}; conflicts=[]; gaps=[]; health={}
    def add(raw,kind):
        fact=validate(raw); fid=fact['id']; fact['kind']=kind
        old=facts.get(fid)
        if old and old['value']!=fact['value']:
            conflicts.append({'id':fid,'versions':[old,fact]})
        if old and old['kind']=='collected' and kind=='recorded': return
        if old and old['kind']==kind and stamp(old['as_of'])>stamp(fact['as_of']): return
        facts[fid]=fact
    for fact in recorded: add(fact,'recorded')
    for source in config['sources']:
        ident=source['id']
        try:
            if source.get('type')!='json-file': raise ServiceError('Unsupported adapter; publish read-only JSON via the approved connector')
            source_path=safe(root,source['path'])
            data=read(source_path); rows=data.get('facts')
            if not isinstance(rows,list): raise ServiceError('Source must contain facts array')
            checked=[validate(r) for r in rows]
            for fact in checked: add(fact,'collected')
            health[ident]={'status':'ok','as_of':now(),'path':source['path']}
        except (ServiceError,OSError,KeyError,TypeError) as e:
            health[ident]={'status':'unreadable','reason':str(e),'as_of':now()}
            gaps.append({'source':ident,'owner':source.get('owner','librarian'),'reason':str(e)})
            for fid,old in prior['facts'].items():
                if old.get('adapter')==ident and fid not in facts:
                    facts[fid]=dict(old,status='stale',carried=True)
            continue
        for fact in checked: facts[fact['id']]['adapter']=ident
    for fid,old in prior['facts'].items():
        if fid not in facts:
            facts[fid]=dict(old,status='stale',carried=True)
            gaps.append({'fact':fid,'owner':'librarian','reason':'Previously collected fact is no longer present in a configured source'})
    current=dt.datetime.now(dt.timezone.utc)
    changes=[]
    for fid,fact in facts.items():
        age=(current-stamp(fact['as_of'])).total_seconds()/3600
        fact['status']='stale' if fact.get('carried') or age>fact['fresh_hours'] else 'current'
        old=prior['facts'].get(fid)
        if not fact.get('carried') and (old is None or old['value']!=fact['value']): changes.append({'id':fid,'old':old,'new':fact})
    result={'as_of':now(),'facts':facts,'sources':health,'conflicts':conflicts,'gaps':gaps,'changes':changes}
    atomic(safe(root,'company/context/current.json'),json_bytes(result))
    atomic(safe(root,'company/context/CHANGES.json'),json_bytes({'at':now(),'changes':changes}))
    if changes:
        history=safe(root,'bible/history.md'); text=history.read_text() if history.exists() else '# History\n'
        lines=['\n## '+result['as_of']]+['- %s: %s → %s. Source: %s; as of %s.'%(c['id'],json.dumps(c['old']['value']) if c['old'] else 'baseline',json.dumps(c['new']['value']),c['new']['source'],c['new']['as_of']) for c in changes]
        atomic(history,(text+'\n'.join(lines)+'\n').encode())
    conflict_path=safe(root,'company/context/conflicts.md')
    atomic(conflict_path,('# Current conflicts\n\n'+json.dumps(conflicts,indent=2)+'\n').encode())
    if conflicts:
        atomic(safe(root,'bible/inbox/context-conflicts-'+fingerprint(conflicts)[:16]+'.json'),json_bytes({'at':now(),'conflicts':conflicts}))
    lines=['# Current company context','As of: '+result['as_of']]+['- %s: %s (%s; %s; %s)'%(f['id'],json.dumps(f['value']),f['status'],f['as_of'],f['source']) for f in facts.values()]
    lines+=['## Gaps',json.dumps(gaps),'## Conflicts',json.dumps(conflicts)]
    text=('\n'.join(lines)+'\n').encode(); atomic(safe(root,'company/context/INDEX.md'),text)
    roster=read(safe(root,'generated/roster.json'))
    for seat in roster['agents']: atomic(safe(root,'workspaces/'+seat['id']+'/work/context/company-now.md'),text)
    return result

def packet(root,goal):
    data=read(safe(root,'company/context/current.json'),{'facts':{},'sources':{},'conflicts':[],'gaps':[]})
    terms=set(re.findall(r'[a-z0-9]{3,}',goal.lower()))
    facts=list(data['facts'].values())
    ranked=sorted(facts,key=lambda f:(f['area']=='company',len(terms & set(re.findall(r'[a-z0-9]{3,}',json.dumps(f).lower())))),reverse=True)
    out={'goal':goal,'as_of':now(),'facts':ranked[:25],'conflicts':data.get('conflicts',[]),'gaps':data.get('gaps',[]),
         'rules':safe(root,'company/RULES.md').read_text(),'snapshot':safe(root,'bible/SNAPSHOT.md').read_text()}
    out['sha256']=fingerprint(out); return out
