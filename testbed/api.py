import json
import sqlite3
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from .runner import RunConfig, Runner, compare
from .client import Camunda
from .models import ROOT, build, mapping
from .datasets import load
from .storage import Store
import yaml

app=FastAPI(title='Agentic BPM Testbed — Work Package 1')
lock=threading.Lock()
errors={}


class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset: str='bpic2019'
    scenario: str='X'
    seed: int=42
    instances: int=200
    strategy: str='full'
    acceleration: float=10000000
    timeout_seconds: float=300
    sample_limit: int=1000
    task_mean_seconds: float=60
    failure_probability: float=0
    human_mode: str='batch'
    human_delay_seconds: float=3600
    resource_capacity: int=2
    sla_seconds: float=172800
    sla_warn_ratio: float=.75


def run_folder(run_id):
    if len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id): raise HTTPException(400,'Invalid run ID')
    folder=ROOT/'artifacts/runs'/run_id
    if not folder.exists(): raise HTTPException(404,'Run not found')
    return folder


@app.get('/api/environment')
def environment():
    client=Camunda()
    try: return {'topology':client.topology(),'operate':'http://localhost:8080/operate','tasklist':'http://localhost:8080/tasklist'}
    except Exception as exc: raise HTTPException(503,str(exc))
    finally: client.close()


@app.get('/api/config')
def configuration():
    return {'defaults':asdict(RunConfig()),'scenarios':yaml.safe_load((ROOT/'config/scenarios.yaml').read_text()),
            'oracle':yaml.safe_load((ROOT/'config/oracle.yaml').read_text()),
            'mappings':{d:mapping(d) for d in ['bpic2019','bpic2017','synthetic']}}


@app.get('/api/models/{dataset}')
def model(dataset:str):
    if dataset not in ['bpic2019','bpic2017','synthetic']: raise HTTPException(404)
    folder=ROOT/'models'/dataset
    if not (folder/f'{dataset}.bpmn').exists(): build(dataset,f'reference_{dataset}',folder)
    return FileResponse(folder/f'{dataset}.bpmn',media_type='application/xml')


@app.get('/api/profiles/{dataset}')
def profile(dataset:str,limit:int=1000):
    if dataset not in ['bpic2019','bpic2017']: raise HTTPException(400,'No historical profile for synthetic mode')
    if not 1<=limit<=10000: raise HTTPException(400,'limit must be 1..10000')
    _,data,_=load(dataset,limit)
    return data


@app.post('/api/runs',status_code=202)
def start(request:RunRequest):
    config=RunConfig(**request.model_dump())
    try:
        config.validate()
        if config.scenario not in yaml.safe_load((ROOT/'config/scenarios.yaml').read_text()): raise ValueError('Unknown scenario')
    except ValueError as exc: raise HTTPException(400,str(exc))
    if not lock.acquire(blocking=False): raise HTTPException(409,'An experiment is already running in this server')
    run_id=uuid.uuid4().hex
    def work():
        try: Runner(config,run_id).execute()
        except Exception as exc: errors[run_id]=str(exc)
        finally: lock.release()
    threading.Thread(target=work,daemon=False).start()
    return {'run_id':run_id}


@app.get('/api/runs')
def runs():
    folder=ROOT/'artifacts/runs'
    results=[]
    for path in sorted(folder.glob('*/metadata.json'),key=lambda p:p.stat().st_mtime,reverse=True) if folder.exists() else []:
        results.append(json.loads(path.read_text(encoding='utf-8')))
    return results


@app.get('/api/runs/{run_id}')
def run(run_id:str):
    folder=run_folder(run_id); path=folder/'metadata.json'
    if not path.exists(): return {'run_id':run_id,'status':'failed' if run_id in errors else 'preparing','error':errors.get(run_id)}
    meta=json.loads(path.read_text(encoding='utf-8'))
    if run_id in errors: meta['error']=errors[run_id]
    with sqlite3.connect(folder/'state.sqlite') as db:
        db.row_factory=sqlite3.Row
        meta['cases']=[dict(r) for r in db.execute('SELECT case_id,instance_key,status,business_seconds,compliance FROM cases')]
        meta['events']=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 300')]
        meta['adaptations']=[dict(r) for r in db.execute('SELECT * FROM adaptations ORDER BY rowid DESC LIMIT 300')]
    return meta


@app.get('/api/runs/{run_id}/files/{name}')
def download(run_id:str,name:str):
    if name not in ['events.csv','events.xes','events.ocel.json','metadata.json','inputs.json','configuration.json','validation.json','bpic2019.bpmn','bpic2017.bpmn','synthetic.bpmn','review.dmn']: raise HTTPException(404)
    path=run_folder(run_id)/name
    if not path.exists(): raise HTTPException(404,'Artifact not generated yet')
    return FileResponse(path,filename=name)


@app.get('/api/runs/{run_id}/tasks')
def tasks(run_id:str):
    path=run_folder(run_id)/'metadata.json'
    if not path.exists(): return []
    meta=json.loads(path.read_text())
    deployment=meta.get('deployment',{})
    definition=next((d['processDefinition']['processDefinitionKey'] for d in deployment.get('deployments',[]) if d.get('processDefinition')),None)
    if not definition: return []
    client=Camunda()
    try: return client.user_tasks(definition)
    finally: client.close()


@app.post('/api/runs/{run_id}/tasks/{task_key}/complete')
def complete_task(run_id:str,task_key:str):
    folder=run_folder(run_id)
    with sqlite3.connect(folder/'state.sqlite') as db:
        completed=db.execute("SELECT 1 FROM events WHERE job_key=? AND lifecycle='complete' AND resource='manual-human'",(task_key,)).fetchone()
    if completed: return {'completed':task_key,'already_completed':True}
    own=tasks(run_id); task=next((t for t in own if str(t['userTaskKey'])==task_key),None)
    if not task: raise HTTPException(404,'Task does not belong to this run')
    with sqlite3.connect(folder/'state.sqlite') as db:
        cid=db.execute('SELECT case_id FROM cases WHERE instance_key=?',(str(task['processInstanceKey']),)).fetchone()[0]
        pending=db.execute('SELECT request,request_id FROM adaptations WHERE case_id=? ORDER BY rowid DESC LIMIT 1',(cid,)).fetchone()
    variables={'humanReviewed':True}
    if task.get('elementId')=='escalation' and pending:
        variables.update(resumeStep=json.loads(pending[0])['element'],humanApprovedStep=json.loads(pending[0])['element'],dataPresent=True,ruleUpdated=True,complianceChecked=True)
    client=Camunda()
    try: client.complete_user(task_key,variables)
    finally: client.close()
    metadata=json.loads((folder/'metadata.json').read_text())
    step=task.get('elementId',task.get('flowNodeId','review'))
    store=Store(folder,run_id)
    try:
        store.event(cid,mapping(metadata['config']['dataset'])['activities'].get(step,step),'complete',
                    resource='manual-human',request_id=pending[1] if pending and step=='escalation' else '',
                    intervention='escalate' if step=='escalation' else '',outcome='approved',job_key=task_key)
    finally: store.db.close()
    return {'completed':task_key}


@app.get('/api/comparisons')
def comparisons():
    return [json.loads(p.read_text()) for p in (ROOT/'artifacts/comparisons').glob('*.json')]


@app.post('/api/comparisons',status_code=202)
def start_comparison(request:RunRequest):
    config=RunConfig(**request.model_dump())
    try: config.validate()
    except ValueError as exc: raise HTTPException(400,str(exc))
    if not lock.acquire(blocking=False): raise HTTPException(409,'Experiment already running')
    def work():
        try: compare(config)
        except Exception as exc: errors['comparison']=str(exc)
        finally: lock.release()
    threading.Thread(target=work,daemon=False).start()
    return {'status':'started'}


app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')


@app.get('/')
def index(): return FileResponse(ROOT/'static/index.html')
