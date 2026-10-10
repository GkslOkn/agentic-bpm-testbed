import argparse
import json
from .runner import RunConfig, Runner, compare
from .datasets import load, discover
from .models import ROOT, build
from .client import Camunda


def main():
    parser=argparse.ArgumentParser(description='Work Package 1: real Camunda + Python workers')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('run','compare'):
        p=sub.add_parser(name)
        p.add_argument('--dataset',choices=['bpic2019','bpic2017','synthetic'],default='synthetic')
        p.add_argument('--scenario',default='X'); p.add_argument('--seed',type=int,default=42)
        p.add_argument('--instances',type=int,default=200)
        p.add_argument('--strategy',choices=['none','retry','retry_fallback','full','escalate'],default='full')
        p.add_argument('--acceleration',type=float,default=10000000)
        p.add_argument('--timeout-seconds',type=float,default=300)
        p.add_argument('--sample-limit',type=int,default=1000)
        p.add_argument('--task-mean-seconds',type=float,default=60)
        p.add_argument('--failure-probability',type=float,default=0)
        p.add_argument('--human-mode',choices=['batch','manual'],default='batch')
    for name in ('profile','discover'):
        p=sub.add_parser(name); p.add_argument('--dataset',choices=['bpic2019','bpic2017'],required=True)
        p.add_argument('--limit',type=int,default=1000)
    sub.add_parser('doctor'); sub.add_parser('models')
    p=sub.add_parser('serve'); p.add_argument('--port',type=int,default=8000)
    p=sub.add_parser('validate-run'); p.add_argument('--run-id',required=True)
    args=vars(parser.parse_args()); command=args.pop('command')
    if command=='run': result=Runner(RunConfig(**args)).execute()
    elif command=='compare': result=compare(RunConfig(**args))
    elif command in ('profile','discover'):
        if command=='profile': _,result,folder=load(args['dataset'],args['limit'])
        else: result,folder=discover(args['dataset'],args['limit'])
        result={'profile':result,'folder':str(folder)}
    elif command=='doctor':
        c=Camunda(); result=c.topology(); c.close()
    elif command=='models':
        result={d:{k:str(v) for k,v in build(d,'reference_'+d,ROOT/'models'/d).items()} for d in ['bpic2019','bpic2017','synthetic']}
    elif command=='validate-run':
        from .validation import validate_run
        rid=args['run_id']
        if len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid): parser.error('Invalid run ID')
        result=validate_run(ROOT/'artifacts/runs'/rid)
    else:
        import uvicorn
        uvicorn.run('testbed.api:app',host='127.0.0.1',port=args['port']); return
    print(json.dumps(result,indent=2,default=str))


if __name__=='__main__': main()
