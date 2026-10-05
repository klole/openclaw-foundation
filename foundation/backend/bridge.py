"""Workspace-scoped request/result bridge. No agent can record operator approvals."""
import json
from .common import ServiceError, atomic, fingerprint, json_bytes, read, safe
from .core import roster

def process(runtime):
    results=[]
    for seat,spec in roster(runtime.root).items():
        folder=safe(runtime.root,'workspaces/'+seat+'/work/requests')
        for path in sorted(folder.glob('*.json')):
            safe(runtime.root,path.relative_to(runtime.root).as_posix())
            response='workspaces/'+seat+'/work/results/'+path.name
            if safe(runtime.root,response).exists(): continue
            try:
                if path.stat().st_size>128000: raise ServiceError('Request too large')
                req=read(path); action=req['action']; payload=req.get('payload',{})
                kind=spec['type']; is_manager=kind in ('manager','chief-of-staff')
                if action in ('work','hire','research'):
                    if kind=='control': raise ServiceError('Control seats do not create downstream jobs')
                    if action=='hire' and not (is_manager or seat=='trainer'): raise ServiceError('Only managers/COS/trainer propose hires')
                    if action=='work':
                        permitted=set(spec.get('spawn',[]))|{seat}
                        if not is_manager and payload.get('maker',seat) not in permitted: raise ServiceError('Maker outside role scope')
                        payload.setdefault('maker',seat)
                        payload.setdefault('checker','push-queue' if seat!='push-queue' else 'release-gate')
                    if action=='research':
                        registry=read(safe(runtime.root,'company/context/sources.json'),{'sources':[]})
                        published={s['path']:s for s in registry.get('sources',[])}
                        published.update({s['path']:s for s in registry.get('research_sources',[])})
                        for name in ('company/context/current.json','company/context/facts.json','company/context/INDEX.md'): published.setdefault(name,{'class':'internal_record'})
                        for source in payload.get('sources',[]):
                            source_path=source.get('path')
                            if source_path in published:
                                record=published[source_path]; source['class']=record.get('class','internal_record')
                                if record.get('url'): source['url']=record['url']
                            elif source_path:
                                prefix='workspaces/'+seat+'/'
                                if source_path.startswith('workspaces/'):
                                    if not source_path.startswith(prefix): raise ServiceError('Research source is outside the requesting workspace')
                                elif source_path.startswith('work/') or source_path in ('AGENTS.md','MEMORY.md'): source['path']=prefix+source_path
                                else: raise ServiceError('Source must be in your workspace or an explicitly published context export')
                                safe(runtime.root,source['path']); source['class']='tertiary'
                            else:
                                # Agent-authored inline notes cannot declare themselves primary measurements.
                                source['class']='tertiary'
                    # Every agent-initiated hire/public/spend request must still pass owner gate.
                    result=runtime.submit(action,payload,actor=seat,key='bridge-'+seat+'-'+path.name+'-'+fingerprint(req))
                elif action=='context':
                    from .context import packet
                    result=packet(runtime.root,payload.get('goal','Company context'))
                elif action=='bible-read':
                    if seat not in ('librarian','daily-company-recorder','context-watcher','context-numbers','cos'): raise ServiceError('Bible maintenance is outside role scope')
                    result={'snapshot':safe(runtime.root,'bible/SNAPSHOT.md').read_text(),'history':safe(runtime.root,'bible/history.md').read_text()[-100000:],'decisions':safe(runtime.root,'bible/decisions.md').read_text(),'notes':[]}
                    for note in sorted(safe(runtime.root,'bible/inbox').glob('*.json'))[-50:]: result['notes'].append({'name':note.name,'content':read(safe(runtime.root,note.relative_to(runtime.root).as_posix()))})
                elif action=='bible-note':
                    from .context import stamp
                    from .common import now
                    if not payload.get('source') or not payload.get('text') or len(payload['text'])>20000: raise ServiceError('A Bible note needs a source and bounded text')
                    stamp(payload['as_of'])
                    name='bible/inbox/'+seat+'-'+fingerprint(req)[:16]+'.json'
                    atomic(safe(runtime.root,name),json_bytes(dict(payload,actor=seat,recorded=now(),status='unverified'))); result={'note':name,'status':'unverified'}
                elif action=='bible-propose':
                    if seat!='librarian': raise ServiceError('Only the keeper proposes canonical Bible changes')
                    from .context import validate
                    for fact in payload.get('facts',[]): validate(fact)
                    result=runtime.submit('work',{'goal':payload['goal'],'maker':'librarian','checker':'push-queue','approval_required':runtime.cfg['context']['bible_requires_owner'],'bible_proposal':payload},actor=seat,key='bible-'+fingerprint(req))
                elif action=='status':
                    state=runtime.store.snapshot(); jid=payload['job']; job=state['jobs'][jid]
                    if job['actor']!=seat and seat not in ('cos','plumber','ops-watcher'): raise ServiceError('Job is outside seat scope')
                    result=job
                else: raise ServiceError('Unsupported agent action; approvals, deploy, retry and recovery are operator commands')
                answer={'ok':True,'result':result}
            except (ServiceError,KeyError,ValueError,TypeError,OSError) as e: answer={'ok':False,'error':str(e)}
            atomic(safe(runtime.root,response),json_bytes(answer)); results.append({'seat':seat,'request':path.name,'ok':answer['ok']})
    return {'requests':results}
