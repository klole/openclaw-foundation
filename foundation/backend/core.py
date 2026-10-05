"""Durable job queues, bounded model calls, independent gates and verified follow-through."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import time
from .common import (ServiceError, Store, atomic, event, fingerprint, inbox, incident, json_bytes, now, read, safe, uid)
from . import context, research
from .transport import OpenClaw

DEFAULT={
 'schema':1,'native':{'enabled':False,'paid':True,'binary':'openclaw','config_path':'','state_dir':'','env_path':''},
 'limits':{'daily_turns':100,'daily_reserved_tokens':10000000,'max_job_turns':40,'max_concurrent_jobs':4,'reserve_tokens_per_turn':100000,'turn_seconds':180,'max_attempts':3,'retry_seconds':60,'lease_seconds':300,'max_sources':30,'max_prompt_chars':500000},
 'paid_calls':{'enabled':False,'daily_usd':0,'max_usd_per_turn':0},
 'thresholds':{'approval_confidence':0.6,'stall_seconds':7200},
 'research':{'angles':['baseline','cases','failures','objection'],'max_rounds':3,'verifiers':3,'required_model_families':[],'verifier_models':[]},
 'wake':{'enabled':False,'cadence':{'URGENT':300,'INTENSE':900,'BUILDING':1800,'PREPARING':3600,'STEADY':10800,'QUIET':21600,'DORMANT':43200}},
 'hygiene':{'memory_days':2,'notes_days':7,'goals_chars':4000,'open_words':300},
 'context':{'auto_file_verified_bible':True,'bible_requires_owner':False},
 'repositories':{},
 'updates':{'enabled':True,'repository':'klole/openclaw-foundation','channel':'stable','interval_seconds':86400,'token_env':''}
}
def config(root):
    supplied=read(safe(root,'config/backend.json'),{})
    out=json.loads(json.dumps(DEFAULT))
    for key,value in supplied.items():
        if isinstance(value,dict) and isinstance(out.get(key),dict): out[key].update(value)
        else: out[key]=value
    for key in ('daily_turns','daily_reserved_tokens','max_job_turns','max_concurrent_jobs','reserve_tokens_per_turn','turn_seconds','max_attempts','lease_seconds'):
        if not isinstance(out['limits'][key],int) or out['limits'][key]<=0: raise ServiceError('Invalid runtime limit: '+key)
    if out['limits']['lease_seconds']<=out['limits']['turn_seconds']+15: raise ServiceError('Lease must exceed turn timeout')
    return out

def roster(root): return {a['id']:a for a in read(safe(root,'generated/roster.json'))['agents']}
def iso_seconds(value): return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
def build_hash(job):
    return fingerprint({key:job['results'].get(key) for key in ('size','draft','challenge','held_out_cases','judge','review','cos_approval')})

class Runtime:
    def __init__(self,root,transport=None):
        self.root=Path(root).absolute(); self.store=Store(self.root); self.cfg=config(self.root); self.transport=transport or OpenClaw(self.root,self.cfg)
    def submit(self,kind,payload,actor='owner',key=None):
        if kind not in ('work','hire','research','gate','proof'): raise ServiceError('Unknown job kind')
        seats=roster(self.root)
        if actor!='owner' and actor not in seats: raise ServiceError('Unknown actor')
        if not isinstance(payload,dict) or not isinstance(payload.get('goal'),str) or not payload['goal'].strip(): raise ServiceError('An exact goal is required')
        payload=json.loads(json.dumps(payload))
        if kind=='gate': payload['approval_required']=True
        digest=fingerprint({'kind':kind,'payload':payload,'actor':actor})
        key=key or uid('request')
        with self.store.transaction() as state:
            for job in state['jobs'].values():
                if job['request_key']==key:
                    if job['input_hash']!=digest: raise ServiceError('Idempotency key reused for different input')
                    return job
            if kind=='work':
                maker=payload.get('maker','plumber'); checker=payload.get('checker','push-queue')
                if maker not in seats or checker not in seats or maker==checker: raise ServiceError('Work needs distinct existing maker/checker seats')
            if kind=='hire':
                seat=payload.get('seat',{})
                if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',seat.get('id','')) or not seat.get('title') or seat.get('type') not in ('manager','specialized','control'): raise ServiceError('Hire needs a complete seat specification')
                if seat['id'] in seats: raise ServiceError('Seat already exists; use a reviewed role-change proposal')
                if safe(self.root,'custom/agents/'+seat['id']).exists() or any(j['kind']=='hire' and j['payload']['seat']['id']==seat['id'] for j in state['jobs'].values()): raise ServiceError('Seat id is already reserved by a canonical role or another build')
                if seat.get('reports_to','cos') not in seats: raise ServiceError('Unknown parent')
            if kind=='gate' and not payload.get('repository'): raise ServiceError('Gate needs a configured repository and exact head')
            if kind=='gate': payload['approval_required']=True
            if kind=='research':
                if payload.get('mode','plan') not in ('plan','answer','compare'): raise ServiceError('Use plan, answer or compare; recurring watches are scheduler jobs')
                card=payload.get('card',{})
                if card.get('goal_exact')!=payload['goal'] or not card.get('unit') or 'baseline' not in card: raise ServiceError('Research needs a locked goal card, unit and baseline')
                if len(payload.get('sources',[]))>self.cfg['limits']['max_sources']: raise ServiceError('Too many sources')
            digest=fingerprint({'kind':kind,'payload':payload,'actor':actor})
            jid=uid(kind); packet=context.packet(self.root,payload['goal'])
            job={'id':jid,'kind':kind,'payload':payload,'actor':actor,'request_key':key,'input_hash':digest,'context':packet,
                 'status':'queued','stage':'intake' if kind=='work' else 'context' if kind=='hire' else 'prepare' if kind=='research' else 'review' if kind=='gate' else 'run',
                 'created':now(),'updated':now(),'attempts':0,'turns':0,'results':{},'lease':None,'not_before':0}
            state['jobs'][jid]=job; event(state,'submitted',job=jid,actor=actor,kind_of_job=kind)
        if payload.get('wake_seat')!='cos': inbox(self.root,'cos',{'event':'submitted','job':jid,'kind':kind})
        return job
    def approve(self,jid,decision,actor='owner',expires=None):
        if actor!='owner': raise ServiceError('Only the operator owner channel records owner authorization')
        if decision not in ('approve','hold','deny'): raise ServiceError('Invalid approval')
        with self.store.transaction() as state:
            job=state['jobs'][jid]
            if job.get('lease'): raise ServiceError('Cannot change approval while a job is executing')
            receipt={'actor':actor,'decision':decision,'input_hash':job['input_hash'],'expires':expires,'at':now(),
                     'plan_hash':fingerprint(job.get('plan')) if job.get('plan') else None,
                     'build_hash':build_hash(job) if job['kind']=='hire' and job['results'].get('draft') else None}
            if expires: iso_seconds(expires)
            state['approvals'][jid]=receipt; event(state,'approval',job=jid,decision=decision)
            if job['status']=='awaiting-approval' and decision=='approve': job['status']='queued'
        return receipt
    def authorized(self,state,job):
        r=state['approvals'].get(job['id'],{})
        if r.get('decision') in ('hold','deny'): return False
        needed=(job['kind']=='hire' and job['stage'] in ('install','onboarding')) or job['payload'].get('approval_required') or job['payload'].get('public') or job['payload'].get('spend_usd',0)>0
        if not needed: return True
        approved=r.get('decision')=='approve' and r.get('input_hash')==job['input_hash'] and (not r.get('expires') or iso_seconds(r['expires'])>time.time())
        if job['kind']!='hire': return approved
        if approved and r.get('build_hash')==build_hash(job): return True
        parent=state['jobs'].get(job['payload'].get('covered_parent'),{})
        if not parent or parent['kind']!='hire' or not self.authorized(state,parent): return False
        scope={key:job['payload'].get(key) for key in ('goal','seat','requirements')}
        for helper in parent['results']['draft'].get('helpers',[]):
            if scope!={key:helper.get(key) for key in ('goal','seat','requirements')}: continue
            draft=job['results'].get('draft',{})
            if draft.get('budget_proposal',{}).get('monthly_usd',float('inf'))>helper['budget_proposal']['monthly_usd']: return False
            if 'declared_tools' in helper['seat'] and set(draft.get('tools',[]))!=set(helper['seat']['declared_tools']): return False
            return not draft.get('helpers') # Added grandchildren need their own concrete sign-off.
        return False
    def call(self,job,seat,stage,request):
        if seat not in roster(self.root): raise ServiceError('Required service seat is not provisioned: '+seat)
        text=json_bytes(request)
        if len(text)>self.cfg['limits']['max_prompt_chars']: raise ServiceError('Prompt exceeds bounded context limit')
        with self.store.transaction() as state:
            live=state['jobs'][job['id']]
            if not live.get('lease') or live['lease']['token']!=job['lease']['token']: raise ServiceError('Stage lost its lease before a model call')
            deadline=dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=self.cfg['limits']['turn_seconds']+30)
            if iso_seconds(live['lease']['until'])<deadline.timestamp(): live['lease']['until']=deadline.isoformat()
            if live['turns']>=self.cfg['limits']['max_job_turns']: raise ServiceError('Job turn budget exhausted')
            day=dt.datetime.now(dt.timezone.utc).date().isoformat(); usage=state['usage'].setdefault(day,{'turns':0,'reserved_tokens':0,'reported_tokens':0,'reserved_usd':0})
            reserve=self.cfg['limits']['reserve_tokens_per_turn']
            over=state['incidents'].get('token-bound-exceeded',{})
            if over.get('status')=='open': raise ServiceError('Token reservation was exceeded; operator must verify bounds and close the incident before more calls')
            if usage['turns']>=self.cfg['limits']['daily_turns'] or usage['reserved_tokens']+reserve>self.cfg['limits']['daily_reserved_tokens']: raise ServiceError('Daily turn/token budget exhausted')
            paid=bool(self.cfg['native'].get('paid'))
            if paid:
                policy=self.cfg['paid_calls']; cost=policy['max_usd_per_turn']
                if not policy['enabled'] or not cost or usage['reserved_usd']+cost>policy['daily_usd']: raise ServiceError('Paid-call brake is closed')
                usage['reserved_usd']+=cost
            usage['turns']+=1; usage['reserved_tokens']+=reserve; live['turns']+=1; job['turns']=live['turns']
            event(state,'turn-reserved',job=job['id'],seat=seat,stage=stage,reserved_tokens=reserve)
        response,meta=self.transport.turn(seat,stage,dict(request,context=job['context']))
        if not isinstance(response,dict): raise ServiceError('Turn result must be a JSON object')
        with self.store.transaction() as state:
            usage=state['usage'][day]; usage['reported_tokens']+=meta.get('tokens',0)
            if meta.get('tokens',0)>reserve:
                usage['reserved_tokens']+=meta['tokens']-reserve
                incident(state,'token-bound-exceeded','plumber','Turn exceeded configured reservation; verify provider output/context bounds before more turns',[{'reserved':reserve,'reported':meta['tokens']}])
            receipt={'actor':seat,'stage':stage,'job':job['id'],'input_hash':fingerprint(request),'result_hash':fingerprint(response),'at':now(),'transport':meta.get('transport','test')}
            state['receipts'][uid('receipt')]=receipt; event(state,'turn-complete',job=job['id'],seat=seat,stage=stage)
        atomic(safe(self.root,'state/artifacts/'+job['id']+'/'+stage+'.json'),json_bytes(response))
        return response
    def verdict(self,job,seat,stage,artifact):
        request={'goal':job['payload']['goal'],'artifact':artifact,'schema':{'verdict':'PASS | FIX | HUMAN REVIEW','reasons':['precise findings'],'confidence':'number 0..1'}}
        if stage=='challenge': request['schema']['held_out_cases']=[{'input':'Independent scenario absent from trainer tests','expected':'Concrete acceptance criterion'}]
        if isinstance(artifact,dict) and artifact.get('model_override'): request['model_override']=artifact['model_override']
        result=self.call(job,seat,stage,request)
        if result.get('verdict') not in ('PASS','FIX','HUMAN REVIEW'): raise ServiceError('Invalid review verdict')
        confidence=float(result.get('confidence',0))
        if not math.isfinite(confidence) or not 0<=confidence<=1: raise ServiceError('Review confidence must be a finite number 0..1')
        if result.get('verdict')=='PASS' and confidence<self.cfg['thresholds']['approval_confidence']: result['verdict']='HUMAN REVIEW'
        return result
    def work_step(self,job):
        p=job['payload']; stage=job['stage']
        if stage=='intake':
            reply=self.call(job,'cos','intake',{'goal':p['goal'],'requested_by':job['actor'],'exact_request':p,'maker':p.get('maker','plumber'),'checker':p.get('checker','push-queue'),'schema':{'accepted':True,'brief':'bounded handoff','done_when':'completion condition'}})
            if reply.get('accepted') is not True: raise ServiceError('COS did not accept handoff')
            job['results']['brief']=reply; job['stage']='execute'
            if not p.get('wake_seat'): inbox(self.root,p.get('maker','plumber'),{'job':job['id'],'brief':reply})
        elif stage=='execute':
            result=self.call(job,p.get('maker','plumber'),'execute',{'brief':job['results']['brief'],'exact_request':p,'schema':{'artifact':'deliverable','evidence':['receipts'],'done':True},'job':job['id']})
            if result.get('done') is not True or not result.get('artifact'): raise ServiceError('Maker has not submitted a completed artifact')
            job['results']['artifact']=result; job['stage']='verify'
        elif stage=='verify':
            review=self.verdict(job,p.get('checker','push-queue'),'verify',{'exact_request':p,'submitted':job['results']['artifact']}); job['results']['review']=review
            if review['verdict']=='PASS': job['stage']='close'
            elif review['verdict']=='FIX': job['stage']='execute'; job['results']['brief']['review']=review
            else: job['status']='needs-attention'
        elif stage=='close':
            job['results']['summary']=self.call(job,'cos','close',{'artifact':job['results']['artifact'],'review':job['results']['review'],'schema':{'summary':'verified result'}})
            job['status']='done'
            if p.get('wake_seat'):
                folder=safe(self.root,'workspaces/'+p['wake_seat']+'/work/inbox')
                for name in p.get('inbox_files',[]):
                    original=safe(folder,name)
                    if original.exists():
                        atomic(safe(self.root,'archive/inbox/'+p['wake_seat']+'/'+name),original.read_bytes()); original.unlink()
    def hire_step(self,job):
        p=job['payload']; stage=job['stage']
        if stage=='context':
            spec=p['seat']; needs=spec.get('needs',[]); proofs=read(safe(self.root,'state/proofs.json'),{'proofs':{}})['proofs']
            missing=[name for name in needs if not proofs.get(name,{}).get('passed') or (self.cfg['native']['enabled'] and (not proofs[name].get('native') or time.time()-iso_seconds(proofs[name]['at'])>7*86400))]
            if missing: raise ServiceError('Tool proof missing: '+', '.join(missing))
            job['results']['size']=self.call(job,'judge','size',{'brief':p,'schema':{'tier':'easy | medium | hard','reason':'why'}})
            if p.get('team') and not p.get('team_card'): raise ServiceError('Team hires require an approved design card')
            job['stage']='draft'
        elif stage=='draft':
            result=self.call(job,'trainer','draft',{'brief':p,'size':job['results']['size'],'existing_seats':list(roster(self.root)),
                'schema':{'role':'core role instructions','requirements':['exact brief requirements'],'tests':[{'input':'held-out scenario','expected':'completion criterion'}],'tools':['declared abilities'],
                          'helpers':[{'goal':'bounded helper brief','seat':{'id':'helper-id','title':'Helper','type':'control','reports_to':p['seat']['id'],'spawn':[]},'requirements':['exact helper requirements'],'cost_reason':'amount and why','budget_proposal':{'monthly_usd':'number','reason':'amount and why'}}],
                          'helpers_reason':'what improves, reuse existing seats first; none needs a reason','budget_proposal':{'monthly_usd':'number','reason':'amount and why; never invent a default budget'}}})
            if not result.get('role') or not result.get('tests'): raise ServiceError('Trainer must return a role and held-out cases')
            if p.get('requirements') and any(x not in result.get('requirements',[]) for x in p['requirements']): raise ServiceError('Trainer weakened or omitted an owner requirement')
            if not isinstance(result.get('helpers',[]),list) or len(result.get('helpers',[]))>6: raise ServiceError('Helper proposal must be bounded')
            needs_helpers=job['results']['size'].get('tier')!='easy' or bool(re.search(r'revenue|growth',p['goal'],re.I))
            if needs_helpers and not result.get('helpers_reason'): raise ServiceError('Larger/growth hires need a helper proposal or explicit reuse/none reason')
            for helper in result.get('helpers',[]):
                spec=helper.get('seat',{})
                if not helper.get('goal') or not helper.get('cost_reason') or not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',spec.get('id','')) or spec.get('type') not in ('manager','specialized','control') or spec.get('reports_to')!=p['seat']['id']: raise ServiceError('Helper proposal needs a complete exact seat, parent, brief and cost reason')
                budget=helper.get('budget_proposal',{})
                if not isinstance(budget.get('monthly_usd'),(int,float)) or not math.isfinite(budget['monthly_usd']) or budget['monthly_usd']<0 or not budget.get('reason'): raise ServiceError('Helper needs an exact proposed budget ceiling and reason')
            helper_ids=[h['seat']['id'] for h in result.get('helpers',[])]
            if len(set(helper_ids))!=len(helper_ids) or any(h in roster(self.root) or h==p['seat']['id'] for h in helper_ids): raise ServiceError('Reuse existing seats and do not duplicate helper ids')
            proposed=result.get('budget_proposal',{})
            if not isinstance(proposed.get('monthly_usd'),(int,float)) or not math.isfinite(proposed['monthly_usd']) or proposed['monthly_usd']<0 or not proposed.get('reason'): raise ServiceError('Trainer must propose a reasoned budget, not request one or invent a default')
            job['results']['draft']=result; job['stage']='challenge'
        elif stage=='challenge':
            result=self.verdict(job,'release-gate','challenge',job['results']['draft']); job['results']['challenge']=result
            if result['verdict']=='PASS':
                cases=result.get('held_out_cases')
                if not isinstance(cases,list) or not 1<=len(cases)<=8 or any(not c.get('input') or not c.get('expected') for c in cases): raise ServiceError('Independent challenger must supply bounded held-out cases')
                if any(c['input'] in [t['input'] for t in job['results']['draft']['tests']] for c in cases): raise ServiceError('Held-out case repeats a trainer case')
                job['results']['held_out_cases']=cases; job['stage']='check'
            elif result['verdict']=='FIX': job['stage']='draft'
            else: job['status']='needs-attention'
        elif stage=='check':
            result=self.verdict(job,'judge','hire-check',{'brief':p,'draft':job['results']['draft'],'challenge':job['results']['challenge']}); job['results']['judge']=result
            if result['verdict']=='PASS': job['stage']='review'
            else: job['status']='needs-attention'
        elif stage=='review':
            result=self.verdict(job,'push-queue','hire-review',job['results']['draft']); job['results']['review']=result
            if result['verdict']=='PASS': job['stage']='cos-approval'
            elif result['verdict']=='FIX': job['stage']='draft'
            else: job['status']='needs-attention'
        elif stage=='cos-approval':
            result=self.verdict(job,'cos','hire-approval',{'brief':p,'draft':job['results']['draft'],'reviews':job['results']}); job['results']['cos_approval']=result
            if result['verdict']=='PASS': job['stage']='install'
            else: job['status']='needs-attention'
        elif stage=='install':
            # Canonical custom sources only. Provision and onboarding happen through the reviewed deploy path.
            seat=dict(p['seat']); seat.setdefault('reports_to','cos'); seat.setdefault('spawn',[])
            allowed_tools={'read','write','edit','memory_search','memory_get'}
            declared=set(job['results']['draft'].get('tools',[]))
            if not declared.issubset(allowed_tools): raise ServiceError('Extra tool adapter/permission needs an explicit reviewed configuration; no implicit tool grants')
            seat['declared_tools']=sorted(declared)
            folder='custom/agents/'+seat['id']
            canonical=safe(self.root,folder)
            qualification=dict(job['results'],job_id=job['id'])
            if canonical.exists():
                if read(safe(self.root,folder+'/qualification.json')).get('job_id')!=job['id'] or safe(self.root,folder+'/role.md').read_text()!=job['results']['draft']['role']: raise ServiceError('Canonical role changed; refusing to overwrite it')
            else:
                staging=safe(self.root,'custom/staging/'+job['id']); staging.mkdir(parents=True,exist_ok=True,mode=0o700)
                atomic(safe(staging,'seat.json'),json_bytes(seat)); atomic(safe(staging,'role.md'),job['results']['draft']['role'].encode()); atomic(safe(staging,'qualification.json'),json_bytes(qualification))
                canonical.parent.mkdir(parents=True,exist_ok=True); os.rename(staging,canonical)
            parent=p['seat'].get('reports_to','cos')
            parentfile=safe(self.root,'custom/agents/'+parent+'/seat.json')
            if parentfile.exists():
                parentspec=read(parentfile); parentspec.setdefault('spawn',[])
                if seat['id'] not in parentspec['spawn']: parentspec['spawn'].append(seat['id']); atomic(parentfile,json_bytes(parentspec))
            job['status']='ready-to-provision'; job['stage']='onboarding'; inbox(self.root,'cos',{'job':job['id'],'action':'render, reviewed provision, onboarding and tool proof before reporting ready'})
        elif stage=='onboarding':
            seat=p['seat']['id']; cases=job['results']['held_out_cases']
            index=job.get('case_index',0)
            if index>=len(cases):
                job['status']='done'; job['results']['onboarded']=True
                job['results']['manager_plan_required']=p['seat']['type']=='manager'
                return
            case=cases[index]
            result=self.call(job,seat,'held-out-'+str(index),{'assignment':case['input'],'schema':{'artifact':'held-out answer','evidence':[]}})
            verdict=self.verdict(job,'release-gate','held-out-review-'+str(index),{'case':case,'actual':result})
            job['results'].setdefault('held_out',[]).append({'case':case,'actual':result,'review':verdict})
            if verdict['verdict']!='PASS': job['status']='needs-attention'
            else: job['case_index']=index+1
    def research_step(self,job):
        stage=job['stage']; p=job['payload']
        if stage=='prepare':
            research.prepare(self.root,job); job['stage']='scout'; job['angle']=0
        elif stage=='scout':
            angles=self.cfg['research']['angles']; angle=angles[job['angle']]
            result=self.call(job,'rp-researcher','scout-'+str(job['round'])+'-'+angle,{'angle':angle,'card':p['card'],'sources':job['sources'],'questions':job.get('questions',[]),'schema':{'findings':[{'finding':'one assertion','quotes':['exact quote'],'source':'snapshot id','numbers':[],'arithmetic':[],'conditions':{}}],'gaps':[]}})
            research.check_findings(job,result.get('findings',[]),angle); research.check_gaps(job,result.get('gaps',[])); job['angle']+=1
            if job['angle']>=len(angles): job['stage']='claims'; job['claim_index']=0
        elif stage=='claims':
            pending=[c for c in job['claims'] if c['status']=='pending']
            if not pending: job['stage']='director'; return
            claim=pending[0]
            result=self.verdict(job,'judge','claim-'+claim['claim_id'],claim)
            if result['verdict']!='PASS': claim['status']='disputed'; claim['reasons']+=result.get('reasons',[]); return
            result=self.call(job,'rp-breaker','break-'+claim['claim_id'],{'claim':claim,'sources':job['sources'],'schema':{'verdict':'STANDS | FAIL','reasons':[]}})
            claim['status']='supported' if result.get('verdict')=='STANDS' else 'disputed'; claim['breaker']=result
        elif stage=='director':
            job['director']=self.call(job,'rp-director','director-'+str(job['round']),{'claims':job['claims'],'gaps':job['gaps'],'schema':{'questions':[],'readiness_proposal':True}})
            job['stage']='challenger'
        elif stage=='challenger':
            job['challenger']=self.call(job,'rp-challenger','challenger-'+str(job['round']),{'claims':job['claims'],'gaps':job['gaps'],'schema':{'blocking':False,'questions':[],'reasons':[]}})
            job['stage']='readiness'
        elif stage=='readiness':
            verdict=self.verdict(job,'judge','readiness-'+str(job['round']),{'claims':job['claims'],'director':job['director'],'challenger':job['challenger'],'gaps':job['gaps']})
            ready=bool(research.verified(job)) and not job['challenger'].get('blocking',True) and verdict['verdict']=='PASS'
            if ready:
                job['results']['readiness']='READY'; job['stage']='plan' if p.get('mode','plan')=='plan' else 'finish'
            elif job['round']+1<self.cfg['research']['max_rounds']:
                job['questions']=job['director'].get('questions',[])+job['challenger'].get('questions',[])
                if not job['questions']: job['status']='needs-attention'; job['results']['readiness']='RESEARCH_NOT_READY'
                else: job['round']+=1; job['angle']=0; job['stage']='scout'
            else: job['status']='needs-attention'; job['results']['readiness']='RESEARCH_NOT_READY'
        elif stage=='plan':
            result=self.call(job,'rp-planner','plan',{'card':p['card'],'claims':research.verified(job),'gaps':job['gaps'],'schema':{'plan':'plan text with Goal/Setup/Trial/Claims/fields/Constraints'}})
            job['plan']=result.get('plan',''); job['results']['plan_gate']=research.check_plan(job,job['plan']); job['stage']='plan-verify'; job['verifier']=0
        elif stage=='plan-verify':
            result=self.verdict(job,'rp-verifier','plan-verify-'+str(job['verifier']),{'card':p['card'],'claims':research.verified(job),'plan':job['plan'],'model_override':(self.cfg['research'].get('verifier_models',[]) or [None])[job['verifier']%len(self.cfg['research'].get('verifier_models',[]) or [None])]})
            if result['verdict']!='PASS': job['status']='needs-attention'; job['results']['plan_verification']=result
            else:
                job['verifier']+=1
                if job['verifier']>=self.cfg['research']['verifiers']:
                    required=self.cfg['research']['required_model_families']
                    configured=self.cfg['research'].get('verifier_models',[])
                    families={model.split('/')[0] for model in configured[:self.cfg['research']['verifiers']]}
                    if required and not set(required).issubset(families): raise ServiceError('Required independent model families are not configured')
                    job['stage']='release'
        elif stage=='release':
            verdict=self.verdict(job,'release-gate','plan-release',{'plan':job['plan'],'card':p['card'],'claims':research.verified(job)})
            job['results']['release']=verdict
            if verdict['verdict']=='PASS': job['stage']='finish'
            else: job['status']='needs-attention'
        elif stage=='finish':
            job['results'].update(claims=job['claims'],gaps=job['gaps'],plan=job.get('plan'),context_sha256=job['context']['sha256']); job['status']='done'
            atomic(safe(self.root,'state/research/'+job['id']+'/result.json'),json_bytes(job['results']))
    def gate_step(self,job):
        p=job['payload']
        if p.get('maker')==p.get('reviewer','push-queue'): raise ServiceError('Producer cannot review its own change')
        from .repositories import checks
        def renew(seconds):
            with self.store.transaction() as state:
                live=state['jobs'][job['id']]
                if not live.get('lease') or live['lease']['token']!=job['lease']['token']: raise ServiceError('Repository stage lost its lease')
                live['lease']['until']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=seconds+30)).isoformat()
        proof=checks(self.root,self.cfg,p,before_check=renew); job['results']['checks']=proof
        review=self.verdict(job,p.get('reviewer','push-queue'),'change-review',{'artifact':p.get('artifact',{}),'checks':proof}); job['results']['review']=review
        if review['verdict']=='PASS': job['status']='release-ready'
        else: job['status']='needs-attention'
    def proof_step(self,job):
        p=job['payload']; fixture=p.get('fixture',{})
        if fixture.get('type')!='read-file': raise ServiceError('Built-in proof supports read-file; custom adapters need a deterministic verifier')
        path=safe(self.root,'workspaces/'+p['seat']+'/'+fixture['path']); expected=path.read_text()
        # Expected bytes stay out of the prompt: the native seat must actually read the file.
        response=self.call(job,p['seat'],'tool-proof',{'tool':p['tool'],'fixture':fixture,'schema':{'passed':True,'evidence':'tool read receipt','observed':'exact UTF-8 contents'}})
        if response.get('passed') is not True or not response.get('evidence') or response.get('observed')!=expected: raise ServiceError('Tool proof did not match deterministic readback')
        if path.read_text()!=expected: raise ServiceError('Proof fixture changed during turn')
        review=self.verdict(job,'push-queue' if p['seat']!='push-queue' else 'release-gate','proof-review',response)
        if review['verdict']!='PASS': raise ServiceError('Independent tool-proof review failed')
        proofs=read(safe(self.root,'state/proofs.json'),{'proofs':{}}); proofs['proofs'][p['tool']]={'passed':True,'at':now(),'seat':p['seat'],'response':response,'review':review,'native':isinstance(self.transport,OpenClaw)}
        atomic(safe(self.root,'state/proofs.json'),json_bytes(proofs)); job['results']=response; job['status']='done'
    def tick(self,only=None):
        token=uid('lease'); chosen=None
        with self.store.transaction() as state:
            active=sum(bool(j.get('lease')) and iso_seconds(j['lease']['until'])>=time.time() for j in state['jobs'].values())
            for job in sorted(state['jobs'].values(),key=lambda j:j['created']):
                if only and job['id']!=only: continue
                if job.get('lease'):
                    if iso_seconds(job['lease']['until'])<time.time():
                        job['status']='needs-attention'; job['lease']=None
                        incident(state,'uncertain-'+job['id'],'plumber','Worker disappeared during a stage; inspect receipt before explicit retry to avoid duplicate effects')
                    continue
                if job['status'] not in ('queued','retry') or job.get('not_before',0)>time.time(): continue
                if active>=self.cfg['limits']['max_concurrent_jobs']: continue
                if not self.authorized(state,job): job['status']='awaiting-approval'; continue
                job['status']='running'; job['lease']={'token':token,'until':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=self.cfg['limits']['lease_seconds'])).isoformat()}
                job['attempts']+=1; chosen=json.loads(json.dumps(job)); break
        if not chosen: return {'ran':False}
        error=None
        try:
            getattr(self,chosen['kind']+'_step')(chosen)
            if chosen['status']=='running': chosen['status']='queued'
        except (ServiceError,OSError,KeyError,ValueError,TypeError) as e: error=str(e)
        with self.store.transaction() as state:
            live=state['jobs'][chosen['id']]
            if not live.get('lease') or live['lease']['token']!=token: raise ServiceError('Job lease changed during execution')
            # call() records usage/turns in durable state; never lose those reservations.
            chosen['turns']=live['turns']; chosen['lease']=None; chosen['updated']=now()
            if error:
                chosen['error']=error; chosen['attempts_at_stage']=chosen.get('attempts_at_stage',0)+1
                chosen['status']='dead-letter' if chosen['attempts_at_stage']>=self.cfg['limits']['max_attempts'] else 'retry'
                chosen['not_before']=time.time()+self.cfg['limits']['retry_seconds']*2**(chosen['attempts_at_stage']-1)
                incident(state,'job-'+chosen['id'],'plumber',error)
            else:
                chosen['attempts_at_stage']=0; chosen.pop('error',None)
                key='job-'+chosen['id']
                if key in state['incidents'] and state['incidents'][key]['status']=='open':
                    state['incidents'][key]['status']='verified'; state['incidents'][key]['proof']={'at':now(),'stage':chosen['stage'],'successful_receipt':True}
            state['jobs'][chosen['id']]=chosen; event(state,'stage',job=chosen['id'],stage=chosen['stage'],status=chosen['status'])
        if error: inbox(self.root,'plumber',{'incident':'job-'+chosen['id'],'reason':error})
        elif chosen['status'] in ('done','ready-to-provision','release-ready') and chosen['payload'].get('wake_seat')!='cos': inbox(self.root,'cos',{'job':chosen['id'],'status':chosen['status'],'results':chosen['results']})
        return {'ran':True,'job':chosen['id'],'stage':chosen['stage'],'status':chosen['status'],'error':error}
    def retry(self,jid):
        with self.store.transaction() as state:
            job=state['jobs'][jid]
            if job.get('lease'): raise ServiceError('Job is still leased')
            if job['status'] not in ('needs-attention','dead-letter','retry'): raise ServiceError('Only interrupted/failed jobs may be retried')
            job['status']='queued'; job['not_before']=0; job['attempts_at_stage']=0; event(state,'explicit-retry',job=jid)
        return job
    def monitor(self):
        notifications=[]
        with self.store.transaction() as state:
            for job in state['jobs'].values():
                key='stalled-'+job['id']
                stalled=job['status'] in ('queued','running','retry') and time.time()-iso_seconds(job['updated'])>self.cfg['thresholds']['stall_seconds']
                if not stalled and state['incidents'].get(key,{}).get('status')=='open':
                    state['incidents'][key]['status']='verified'; state['incidents'][key]['proof']={'at':now(),'updated':job['updated'],'status':job['status']}
                if stalled:
                    old=state['incidents'].get(key)
                    item=incident(state,key,'cos','Job stalled: '+job['id'],[job['stage']])
                    if not old or old['status']!='open': notifications.append(item)
            current=read(safe(self.root,'company/context/current.json'),{'sources':{}})
            for source,health in current.get('sources',{}).items():
                key='source-'+source
                if health['status']!='ok':
                    old=state['incidents'].get(key)
                    item=incident(state,key,'librarian','Unreadable context source: '+source,[health])
                    if not old or old['status']!='open': notifications.append(item)
                elif state['incidents'].get(key,{}).get('status')=='open':
                    state['incidents'][key]['status']='verified'; state['incidents'][key]['proof']={'at':now(),'collector_health':health}
        for item in notifications: inbox(self.root,item['owner'],item)
        return {'new_incidents':len(notifications),'incidents':self.store.snapshot()['incidents']}
    def wake(self):
        if not self.cfg['wake']['enabled']: return {'woken':[],'enabled':False}
        woken=[]
        for seat,spec in roster(self.root).items():
            if spec['type']=='control': continue
            root=safe(self.root,'workspaces/'+seat+'/work')
            goals=(root/'notes/GOALS.md').read_text() if (root/'notes/GOALS.md').exists() else ''
            open_items=(root/'notes/OPEN.md').read_text() if (root/'notes/OPEN.md').exists() else ''
            has_work='- [ ]' in goals or bool(list((root/'inbox').glob('*.json')))
            if spec['type'] not in ('manager','chief-of-staff') and not has_work: continue
            if spec['type']=='manager' and not read(safe(self.root,'state/manager-plans.json'),{}).get(seat,{}).get('approved'): continue
            level='BUILDING' if has_work else 'DORMANT'
            explicit=re.search(r'(?im)^wake\s*:\s*(URGENT|INTENSE|BUILDING|PREPARING|STEADY|QUIET|DORMANT|OFF)\s*$',goals)
            if explicit:
                selected=explicit.group(1).upper()
                if selected=='OFF': continue
                if selected!='URGENT' or time.time()-(root/'notes/GOALS.md').stat().st_mtime<7200: level=selected
            period=self.cfg['wake']['cadence'][level]
            if not isinstance(period,int) or not 300<=period<=43200: raise ServiceError('Wake cadence must be between 5 minutes and 12 hours')
            state=self.store.snapshot(); last=state['wakes'].get(seat,{})
            if time.time()-last.get('last',0)<period: continue
            pending=[j for j in state['jobs'].values() if j['payload'].get('wake_seat')==seat and j['status'] in ('queued','running','retry','awaiting-approval')]
            if pending: continue
            job=self.submit('work',{'goal':'Advance the current goal sheet and report verified progress','maker':seat,'checker':'push-queue' if seat!='push-queue' else 'release-gate','wake_seat':seat,'level':level,'inbox_files':[p.name for p in (root/'inbox').glob('*.json')], 'goal_sheet':goals,'open_items':open_items},actor='cos',key='wake-'+seat+'-'+str(int(time.time()/period)))
            with self.store.transaction() as current: current['wakes'][seat]={'last':time.time(),'level':level,'job':job['id']}
            woken.append(seat)
        return {'woken':woken,'enabled':True}
    def schedule(self):
        cfg=read(safe(self.root,'config/automations.json'),{'enabled':False,'jobs':[]})
        if not cfg['enabled']: return {'scheduled':[],'enabled':False}
        queued=[]
        for spec in cfg['jobs']:
            ident=spec.get('id',''); period=spec.get('every_seconds',0)
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',ident) or not isinstance(period,int) or period<300 or spec.get('kind') not in ('work','research'): raise ServiceError('Scheduled jobs need an id, period >=300 seconds and work/research kind')
            state=self.store.snapshot(); previous=state.get('schedules',{}).get(ident,{})
            if time.time()<previous.get('next',0): continue
            if previous.get('job') and state['jobs'][previous['job']]['status'] not in ('done','denied','cancelled'): continue
            payload=dict(spec['payload'],schedule_id=ident)
            job=self.submit(spec['kind'],payload,actor='cos',key='schedule-'+ident+'-'+str(int(time.time()/period)))
            with self.store.transaction() as current: current.setdefault('schedules',{})[ident]={'job':job['id'],'next':time.time()+period,'at':now()}
            queued.append(job['id'])
        return {'scheduled':queued,'enabled':True}
