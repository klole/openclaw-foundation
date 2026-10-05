"""Operator surface; native execution remains disabled until configured by the owner."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from .common import ServiceError, Store, atomic, event, json_bytes, now, read, safe
from .core import Runtime, config

COMMANDS=('submit','approve','tick','status','retry','collect','packet','monitor','incident-resolve','wake','schedule','bridge','backup','restore','restore-native','hygiene','hq','provision','provision-rollback','service-files','serve','activate','merge','manager-plan','bible-apply','migrate','check-updates','fetch-update','update-service-files')
def parsers(sub):
    for command in COMMANDS:
        p=sub.add_parser(command); p.add_argument('--root',required=True)
        if command=='submit': p.add_argument('--kind',choices=('work','hire','research','gate','proof'),required=True); p.add_argument('--input',required=True); p.add_argument('--key')
        if command in ('approve','retry','activate','merge','manager-plan','bible-apply'): p.add_argument('--job',required=True)
        if command=='approve': p.add_argument('--decision',choices=('approve','hold','deny'),required=True); p.add_argument('--expires')
        if command in ('tick','status'): p.add_argument('--job')
        if command=='tick': p.add_argument('--steps',type=int,default=1)
        if command=='packet': p.add_argument('--goal',required=True)
        if command=='incident-resolve': p.add_argument('--key',required=True); p.add_argument('--proof',required=True)
        if command=='backup': p.add_argument('--output',required=True); p.add_argument('--native',action='store_true')
        if command in ('restore','restore-native'): p.add_argument('--archive',required=True); p.add_argument('--destination',required=True)
        if command=='provision-rollback': p.add_argument('--receipt',required=True)
        if command in ('service-files','update-service-files'): p.add_argument('--python',default=sys.executable)
        if command=='check-updates': p.add_argument('--force',action='store_true')
        if command=='fetch-update': p.add_argument('--version')
        if command in ('provision','provision-rollback','restore','restore-native','activate','merge','manager-plan','bible-apply','migrate'): p.add_argument('--apply',action='store_true')
        if command=='serve': p.add_argument('--poll',type=int,default=30); p.add_argument('--once',action='store_true')

def activate(root,jid,apply=False):
    runtime=Runtime(root); state=runtime.store.snapshot(); job=state['jobs'][jid]
    if job['kind']!='hire' or job['status']!='ready-to-provision' or not runtime.authorized(state,job): raise ServiceError('Hire needs a reviewed role and current owner approval')
    from . import deploy
    if not apply: return {'applied':False,'job':jid,'seat':job['payload']['seat']['id'],'next':'render, validate/provision if native enabled, then held-out onboarding'}
    # Import the template updater shipped beside backend, works from source and installed runtime.
    import foundation
    from types import SimpleNamespace
    rendered=foundation.update(SimpleNamespace(root=root,command='render',apply=True))
    if runtime.cfg['native']['enabled']: deployed=deploy.provision(root,runtime.cfg,True)
    else: deployed={'applied':False,'native_enabled':False,'fixture_only':True}
    with runtime.store.transaction() as current:
        live=current['jobs'][jid]
        if live['status']!='ready-to-provision': raise ServiceError('Hire changed during activation')
        live['status']='queued'; live['results']['activation']={'render':rendered,'provision':deployed}; live['updated']=now()
    children=[]
    for helper in job['results']['draft'].get('helpers',[]):
        payload={key:helper.get(key) for key in ('goal','seat','requirements')}; payload['covered_parent']=jid
        child=runtime.submit('hire',payload,actor='trainer',key='helper-'+jid+'-'+helper['seat']['id']); children.append(child['id'])
    if children:
        with runtime.store.transaction() as current: current['jobs'][jid]['results']['helper_jobs']=children
    return {'job':jid,'status':'queued','stage':'onboarding','helper_jobs':children,'native_enabled':runtime.cfg['native']['enabled']}

def cycle(runtime):
    from . import bridge,context,maintenance,updates
    out={'bridge':bridge.process(runtime),'context':context.collect(runtime.root),'monitor':runtime.monitor(),'wake':runtime.wake(),'schedule':runtime.schedule()}
    out['tick']=runtime.tick(); out['updates']=updates.check(runtime.root,runtime.cfg); out['hq']=maintenance.hq(runtime.root)
    if runtime.cfg['context']['auto_file_verified_bible']:
        for job in runtime.store.snapshot()['jobs'].values():
            if job['status']=='done' and job['payload'].get('bible_proposal') and not safe(runtime.root,'state/bible-receipts/'+job['id']+'.json').exists():
                from types import SimpleNamespace
                out.setdefault('bible',[]).append(dispatch(SimpleNamespace(root=runtime.root,command='bible-apply',job=job['id'],apply=True)))
    return out

def serve(root,poll,once):
    if poll<5: raise ServiceError('Poll must be at least five seconds')
    path=safe(root,'state/service.lock'); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ServiceError('Service already running')
        running=[True]
        def stop(*args): running[0]=False
        signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
        next_hygiene=0
        while running[0]:
            runtime=Runtime(root) # Re-read local configuration every cycle.
            try:
                result=cycle(runtime)
                if time.time()>=next_hygiene:
                    from .maintenance import hygiene
                    result['hygiene']=hygiene(root,runtime.cfg['hygiene']); next_hygiene=time.time()+86400
                atomic(safe(root,'state/service-health.json'),json_bytes({'at':now(),'ok':True,'last':result['tick']}))
            except (ServiceError,ValueError,KeyError,OSError) as e:
                atomic(safe(root,'state/service-health.json'),json_bytes({'at':now(),'ok':False,'error':str(e)}))
                if once: raise
            if once: return result
            for second in range(poll):
                if not running[0]: break
                time.sleep(1)
    return {'stopped':True}

def dispatch(args):
    root=Path(args.root).absolute(); runtime=Runtime(root); command=args.command
    from . import bridge,context,deploy,maintenance
    if command=='submit': return runtime.submit(args.kind,read(args.input),key=args.key)
    if command=='approve': return runtime.approve(args.job,args.decision,expires=args.expires)
    if command=='tick':
        if not 1<=args.steps<=100: raise ServiceError('Steps must be 1..100')
        results=[]
        for step in range(args.steps):
            result=runtime.tick(args.job); results.append(result)
            if not result['ran']: break
        maintenance.hq(root); return {'ticks':results}
    if command=='status':
        state=runtime.store.snapshot(); return state['jobs'][args.job] if args.job else state
    if command=='retry': return runtime.retry(args.job)
    if command=='collect': return context.collect(root)
    if command=='packet': return context.packet(root,args.goal)
    if command=='monitor': return runtime.monitor()
    if command=='incident-resolve':
        from .common import fingerprint
        proof=read(safe(root,args.proof))
        if proof.get('passed') is not True or not proof.get('observed') or not proof.get('source'): raise ServiceError('Resolution proof needs passed=true, observed readback and a source')
        with runtime.store.transaction() as current:
            item=current['incidents'][args.key]; item['status']='operator-verified'; item['proof']={'path':args.proof,'sha256':fingerprint(proof),'at':now(),'actor':'owner'}
            event(current,'incident-resolved',key=args.key,proof=item['proof'])
        return item
    if command=='wake': return runtime.wake()
    if command=='schedule': return runtime.schedule()
    if command=='bridge': return bridge.process(runtime)
    if command=='backup': return maintenance.backup(root,args.output,runtime.cfg['native'] if args.native else None)
    if command=='restore': return maintenance.restore(args.archive,args.destination,args.apply)
    if command=='restore-native': return maintenance.restore_native(args.archive,args.destination,args.apply)
    if command=='hygiene': return maintenance.hygiene(root,runtime.cfg['hygiene'])
    if command=='hq': return maintenance.hq(root)
    if command=='check-updates':
        from . import updates
        result=updates.check(root,runtime.cfg,args.force); maintenance.hq(root); return result
    if command=='fetch-update':
        from . import updates
        return updates.fetch(root,runtime.cfg,args.version)
    if command=='update-service-files':
        from . import updates
        return updates.service_files(root,args.python)
    if command=='provision': return deploy.provision(root,runtime.cfg,args.apply)
    if command=='provision-rollback': return deploy.provision_rollback(root,runtime.cfg,args.receipt,args.apply)
    if command=='service-files': return deploy.service_files(root,args.python)
    if command=='serve': return serve(root,args.poll,args.once)
    if command=='activate': return activate(root,args.job,args.apply)
    if command=='merge':
        if not args.apply: return {'applied':False,'job':args.job,'next':'verify exact head, checks, owner approval and independent merge identity'}
        from .repositories import merge
        return merge(runtime,args.job)
    if command=='manager-plan':
        job=runtime.store.snapshot()['jobs'][args.job]
        if job['kind']!='research' or job['payload'].get('mode','plan')!='plan' or job['status']!='done' or not job['results'].get('plan_gate',{}).get('pass'): raise ServiceError('Manager requires a verified research plan')
        seat=job['payload'].get('manager_seat')
        from .core import roster
        if seat not in roster(root) or roster(root)[seat]['type']!='manager': raise ServiceError('Set manager_seat in the frozen research request')
        if not args.apply: return {'applied':False,'seat':seat,'plan':job['results']['plan']}
        approval=runtime.store.snapshot()['approvals'].get(args.job,{})
        from .common import fingerprint
        from .core import iso_seconds
        if approval.get('decision')!='approve' or approval.get('plan_hash')!=fingerprint(job['plan']) or (approval.get('expires') and iso_seconds(approval['expires'])<=time.time()): raise ServiceError('Approve the exact completed plan before activation')
        plans=read(safe(root,'state/manager-plans.json'),{}); plans[seat]={'approved':True,'job':args.job,'plan_sha256':__import__('hashlib').sha256(job['results']['plan'].encode()).hexdigest(),'at':now()}
        atomic(safe(root,'state/manager-plans.json'),json_bytes(plans)); return plans[seat]
    if command=='bible-apply':
        job=runtime.store.snapshot()['jobs'][args.job]; proposal=job['payload'].get('bible_proposal')
        if job['kind']!='work' or job['status']!='done' or job['payload'].get('maker')!='librarian' or job['results'].get('review',{}).get('verdict')!='PASS' or not proposal: raise ServiceError('Bible change needs a completed independently reviewed librarian proposal')
        if not runtime.authorized(runtime.store.snapshot(),job): raise ServiceError('This installation requires owner authorization for the exact Bible proposal')
        facts=[context.validate(fact) for fact in proposal.get('facts',[])]
        snapshot=proposal.get('snapshot')
        if snapshot is not None and (not isinstance(snapshot,str) or len(snapshot)>10000): raise ServiceError('Snapshot must be bounded text')
        if not args.apply: return {'applied':False,'job':args.job,'proposal':proposal}
        receipt=safe(root,'state/bible-receipts/'+args.job+'.json')
        if receipt.exists(): return read(receipt)
        # Preserve originals. Canonical changes are small, ordered and replayable.
        for name in ['bible/SNAPSHOT.md','company/context/facts.json']:
            atomic(safe(root,'archive/bible/'+args.job+'/'+name),safe(root,name).read_bytes())
        current={fact['id']:fact for fact in read(safe(root,'company/context/facts.json'))['facts']}
        current.update({fact['id']:fact for fact in facts})
        try:
            if snapshot is not None: atomic(safe(root,'bible/SNAPSHOT.md'),snapshot.encode())
            atomic(safe(root,'company/context/facts.json'),json_bytes({'facts':list(current.values())}))
        except BaseException:
            for name in ['bible/SNAPSHOT.md','company/context/facts.json']: atomic(safe(root,name),safe(root,'archive/bible/'+args.job+'/'+name).read_bytes())
            raise
        result={'applied':True,'job':args.job,'at':now(),'facts':len(facts),'snapshot_changed':snapshot is not None}
        atomic(receipt,json_bytes(result)); context.collect(root)
        result['next']='Stop service and render instructions after a snapshot change.'; return result
    if command=='migrate':
        state=runtime.store.snapshot()
        if args.apply:
            with runtime.store.transaction() as current: event(current,'schema-verified',schema=current['schema'])
        return {'applied':args.apply,'schema':state['schema']}
    raise ServiceError('Unknown command')
