#!/usr/bin/env python3
"""JSON-stdin adapter for an installed Foundation runtime; no gateway configuration writes."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.common import ServiceError
from backend.core import Runtime, roster

def call(root,name,args):
    runtime=Runtime(root)
    if name=='foundation_agents':
        return {'default':'cos','agents':[{'id':k,'name':v['title'],'role':v['type']} for k,v in roster(root).items()]}
    if name=='foundation_send':
        job=runtime.submit('work',{'goal':args['message'],'maker':args['agent'],'checker':'push-queue' if args['agent']!='push-queue' else 'release-gate','dot_conversation':args['conversation']},key=args['idempotency_key'])
        return {'task_id':job['id'],'status':job['status']}
    if name=='foundation_task_status':
        job=runtime.store.snapshot()['jobs'][args['task_id']]
        return {'task_id':job['id'],'status':job['status'],'reply':job['results'].get('summary',job['results'].get('artifact'))}
    raise ServiceError('Unsupported messaging method')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True); parser.add_argument('method'); args=parser.parse_args()
    try: print(json.dumps(call(args.root,args.method,json.load(sys.stdin))))
    except (ServiceError,OSError,ValueError,KeyError): raise SystemExit('Foundation messaging adapter failed; inspect private runtime state')
