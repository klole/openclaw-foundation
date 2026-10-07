"""Scoped durable messaging admission and replies. No administrative tools are exposed."""
import fcntl
import json
from pathlib import Path
import re
import subprocess
import time
from .common import ServiceError
from .dot_auth import canonical, digest, random

TERMINAL={'done','completed','failed','cancelled','denied','admission_unknown'}

def schema(properties,required): return {'type':'object','properties':properties,'required':required,'additionalProperties':False}
def tools():
    definitions=[('foundation_agents','Discover the allowed OpenClaw agents for this owner. No model call.',{},[],True,'agents:read'),
                 ('foundation_send','Send an explicitly owner-authorized request to an agent. Returns a durable receipt, not completion. Reuse exactly the same idempotency key after uncertain delivery. Agent actions can affect external systems and retain their approval rules.',
                  {'agent':{'type':'string'},'message':{'type':'string','maxLength':8000},'conversation':{'type':'string','maxLength':128},'idempotency_key':{'type':'string','pattern':'^[A-Za-z0-9_-]{1,80}$'}},['message','conversation','idempotency_key'],False,'messages:send'),
                 ('foundation_task_status','Read this owner’s task receipt and real reply. Pending or unknown outcomes never authorize resubmission with a fresh key.',{'task_id':{'type':'string'}},['task_id'],True,'messages:read'),
                 ('foundation_conversation','Read this owner’s recent task receipts for a conversation, including missed event updates.',{'conversation':{'type':'string','maxLength':128}},['conversation'],True,'messages:read')]
    return [{'name':n,'description':d,'inputSchema':schema(p,r),'annotations':{'readOnlyHint':read,'destructiveHint':not read,'openWorldHint':True,'idempotentHint':True},'securitySchemes':[{'type':'oauth2','scopes':[scope]}],'_meta':{'securitySchemes':[{'type':'oauth2','scopes':[scope]}]}} for n,d,p,r,read,scope in definitions]

class Adapter:
    def __init__(self,config): self.config=config
    def call(self,owner,name,args):
        command=owner.get('command') or self.config.get('adapter_command')
        if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command): raise ServiceError('Messaging adapter is not configured')
        # The executable and argv prefix are operator-defined; no message becomes shell code.
        try:
            result=subprocess.run(command+[name],input=canonical(args),text=True,capture_output=True,timeout=80)
            if result.returncode or len(result.stdout)>1000000: raise ServiceError('Adapter failed; inspect private adapter logs')
            reply=json.loads(result.stdout)
            if not isinstance(reply,dict): raise ValueError()
            if 'task_id' not in reply and 'id' in reply: reply['task_id']=reply['id']
            if 'status' not in reply and 'state' in reply: reply['status']=reply['state']
            return reply
        except (OSError,ValueError,subprocess.TimeoutExpired): raise ServiceError('Adapter outcome is uncertain; the original key remains reserved')

class Bridge:
    def __init__(self,store,oauth,events,config,adapter=None):
        self.store=store; self.oauth=oauth; self.events=events; self.config=config; self.adapter=adapter or Adapter(config)
    def agents(self,auth):
        result=self.adapter.call(auth['owner_record'],'foundation_agents',{})
        allowed=auth['owner_record']['agents']
        return {'default':self.config['default_agent'],'authenticated_principal':auth['principal'],
                'agents':[{k:a[k] for k in ('id','name','role') if k in a} for a in result.get('agents',[]) if a.get('id') in allowed]}
    def send(self,auth,args):
        if set(args)-{'agent','message','conversation','idempotency_key'}: raise ServiceError('Unknown send arguments')
        for field,maximum in [('message',8000),('conversation',128)]:
            if not isinstance(args.get(field),str) or not 1<=len(args[field].strip())<=maximum: raise ServiceError('Invalid '+field)
        if not isinstance(args.get('idempotency_key'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args['idempotency_key']): raise ServiceError('Invalid idempotency key')
        agent=args.get('agent',self.config['default_agent'])
        if agent not in auth['owner_record']['agents']: raise ServiceError('Agent is outside owner scope')
        original=dict(args,agent=agent); fingerprint=digest(canonical(original))
        key=digest(canonical([auth['principal'],args['idempotency_key']]))
        with self.store.transaction() as db:
            old=self.store.get(db,'jobs',key)
            if old:
                if old['fingerprint']!=fingerprint: raise ServiceError('Idempotency key reused with different input')
                return self.public(old)
            pending=[j for _,j in self.store.items(db,'jobs') if j['owner']==auth['principal'] and j['status'] not in TERMINAL]
            if len(pending)>=self.config.get('max_pending_per_owner',20): raise ServiceError('Owner pending task limit reached')
            job={'id':'dot_'+random(),'owner':auth['principal'],'conversation':args['conversation'],'status':'queued','fingerprint':fingerprint,
                 'request':dict(original,idempotency_key='dot-'+key,conversation='dot-'+digest(canonical([auth['principal'],args['conversation']]))),
                 'attempts':0,'after':0,'revision':0,'created':time.time(),'reply':None,'upstream_task':None}
            self.store.put(db,'jobs',key,job)
        return self.public(job)
    def public(self,job): return {'task_id':job['id'],'conversation':job['conversation'],'status':job['status'],'reply':job['reply']}
    def status(self,auth,ident):
        with self.store.transaction() as db:
            for _,job in self.store.items(db,'jobs'):
                if job['id']==ident and job['owner']==auth['principal']: return self.public(job)
        raise ServiceError('Unknown owner task')
    def conversation(self,auth,conversation):
        if not isinstance(conversation,str) or not 1<=len(conversation)<=128: raise ServiceError('Invalid conversation')
        with self.store.transaction() as db:
            jobs=[self.public(j) for _,j in self.store.items(db,'jobs') if j['owner']==auth['principal'] and j['conversation']==conversation]
        return {'tasks':jobs[-100:]}
    def call(self,auth,name,args):
        definitions={x['name']:x for x in tools()}
        if name not in definitions or not isinstance(args,dict): raise ServiceError('Unknown tool or arguments')
        definition=definitions[name]; props=definition['inputSchema']['properties']
        if set(args)-set(props) or any(k not in args for k in definition['inputSchema']['required']): raise ServiceError('Invalid tool arguments')
        scope=definition['_meta']['securitySchemes'][0]['scopes'][0]
        if scope not in auth['scope'].split(): raise ServiceError('Insufficient tool scope')
        self.store.rate('tool',auth['principal'],60)
        if name=='foundation_agents': return self.agents(auth)
        if name=='foundation_send': return self.send(auth,args)
        if name=='foundation_task_status': return self.status(auth,args['task_id'])
        return self.conversation(auth,args['conversation'])
    def tick(self):
        # One worker process at a time, including across process restarts.
        lock=(self.store.root/'worker.lock').open('a')
        try:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: return {'busy':True}
            with self.store.transaction() as db: jobs=self.store.items(db,'jobs')
            for key,job in [(k,j) for k,j in jobs if j['status'] not in TERMINAL and j['after']<=time.time()][:100]:
                if job['status'] in TERMINAL or job['after']>time.time(): continue
                with self.store.transaction() as db: owner=self.store.get(db,'owners',job['owner'])
                if not owner or not owner['enabled']: continue
                try:
                    if not job['upstream_task']:
                        answer=self.adapter.call(owner,'foundation_send',job['request'])
                        job['upstream_task']=answer.get('task_id')
                        if not job['upstream_task']: raise ServiceError('No upstream receipt; original request remains uncertain')
                        job['status']=answer.get('status','pending'); job['receipt']=answer
                    else:
                        answer=self.adapter.call(owner,'foundation_task_status',{'task_id':job['upstream_task'],'wait_ms':0})
                        status=answer.get('status',answer.get('state','pending'))
                        if status not in TERMINAL and answer.get('final') is True: status='completed'
                        job['status']=status
                        if status in TERMINAL: job['reply']=answer
                    job['attempts']=0; job['after']=time.time()+10
                except ServiceError:
                    job['attempts']+=1; job['after']=time.time()+min(300,10*2**min(job['attempts'],5))
                    if not job['upstream_task'] and job['attempts']>=3: job['status']='admission_unknown'
                with self.store.transaction() as db:
                    old=self.store.get(db,'jobs',key)
                    if old['status']!=job['status']:
                        job['revision']+=1; self.events.queue(db,job)
                    self.store.put(db,'jobs',key,job)
            self.events.deliver()
            return {'processed':True}
        finally: lock.close()
