"""Frozen sources, independent research stages and the original deterministic claim/plan gates."""
from . import claims
from .evidence_core import Snapshot, absence_check
from urllib.parse import urlparse
from .plan_gate import plan_gate
from .common import ServiceError, atomic, fingerprint, json_bytes, safe

class Sources:
    def __init__(self,rows):
        self.items={s['id']:Snapshot(s['id'],s['text'],s.get('class','internal_record'),url=s.get('url',''),host=(urlparse(s.get('url','')).hostname or s['id']),observed_at=s.get('as_of','')) for s in rows}
    def get(self,key): return self.items.get(key)
    def all(self): return list(self.items.values())

def prepare(root,job):
    payload=job['payload']; sources=payload.get('sources',[])
    if not sources: raise ServiceError('Supply saved sources or an approved evidence adapter output')
    frozen=[]
    for source in sources:
        if 'text' in source: text=source['text']
        else: text=safe(root,source['path']).read_text()
        if len(text)>200000: raise ServiceError('Source exceeds snapshot limit')
        row=dict(source,text=text); row.pop('path',None); row['sha256']=fingerprint({'text':text})
        frozen.append(row)
    if len({s['id'] for s in frozen})!=len(frozen): raise ServiceError('Duplicate source id')
    job['sources']=frozen; job['claims']=[]; job['gaps']=[]; job['round']=0
    atomic(safe(root,'state/research/'+job['id']+'/sources.json'),json_bytes(frozen))

def check_findings(job,findings,seat):
    store=Sources(job['sources']); existing={claims.dedupe_key(c) for c in job['claims']}
    for block in findings:
        cid='CLM-%04d'%(len(job['claims'])+1)
        block=dict(block,source=block.get('source',block.get('source_id','')))
        row=claims.gate_finding(block,cid,seat,'round-'+str(job['round']),store,job['payload']['card'],{'max_finding_chars':500,'max_quote_chars':2000})
        if claims.dedupe_key(row) in existing:
            row['status']='duplicate'; row['reasons'].append('Duplicate saved evidence')
        existing.add(claims.dedupe_key(row)); job['claims'].append(row)
    claims.apply_same_host_rule(job['claims'])

def verified(job): return [c for c in job['claims'] if c['status']=='supported']

def check_plan(job,text):
    result=plan_gate(text,job['payload']['card'],{c['claim_id']:c for c in job['claims']},[g['question_id'] for g in job.get('gaps',[]) if g.get('question_id')])
    if not result['pass']: raise ServiceError('Deterministic plan gate: '+'; '.join(result['rejects']))
    return result


def check_gaps(job,gaps):
    store=Sources(job['sources'])
    for raw in gaps:
        record=claims.gap_record(raw,'GAP-%04d'%(len(job['gaps'])+1),store.all())
        job['gaps'].append(record)
