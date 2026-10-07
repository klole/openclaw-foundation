#!/usr/bin/env python3
"""Optional fixed-command SSH messaging adapter; keys and host pinning remain private."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

def call(command,method,args):
    if method not in ('foundation_agents','foundation_send','foundation_task_status'): raise ValueError('Unsupported method')
    if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command): raise ValueError('Invalid SSH command')
    req={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':method,'arguments':args}}
    result=subprocess.run(command,input=json.dumps(req)+'\n',text=True,capture_output=True,timeout=75)
    if result.returncode or len(result.stdout)>1000000: raise ValueError('SSH messaging failed')
    response=json.loads(result.stdout)
    if response.get('error') or response.get('result',{}).get('isError'): raise ValueError('Messaging request rejected or uncertain; inspect the original receipt')
    return json.loads(response['result']['content'][0]['text'])

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--command-file',required=True); p.add_argument('method'); args=p.parse_args()
    try: print(json.dumps(call(json.loads(Path(args.command_file).read_text()),args.method,json.load(sys.stdin))))
    except (ValueError,OSError,KeyError,subprocess.TimeoutExpired): raise SystemExit('Private SSH messaging adapter failed; retain the original request key')
