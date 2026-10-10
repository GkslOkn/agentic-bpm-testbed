import hashlib
import heapq
import importlib.metadata
import json
import math
import platform
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import httpx
import yaml
from .adaptation import AdaptationRequest, L0, PRESETS
from .client import Camunda
from .datasets import workload, digest
from .models import ROOT, STEPS, mapping, build
from .storage import Store, now


@dataclass
class RunConfig:
    dataset: str = 'synthetic'
    scenario: str = 'X'
    seed: int = 42
    instances: int = 200
    strategy: str = 'full'
    acceleration: float = 10000000
    timeout_seconds: float = 300
    sample_limit: int = 1000
    retry_max: int = 2
    retry_backoff_seconds: float = 600
    task_mean_seconds: float = 60
    failure_probability: float = 0
    human_delay_seconds: float = 3600
    sla_seconds: float = 172800
    sla_warn_ratio: float = .75
    resource_capacity: int = 2
    human_mode: str = 'batch'

    def validate(self):
        if self.dataset not in ('synthetic','bpic2019','bpic2017'): raise ValueError('Unknown dataset')
        if self.strategy not in PRESETS: raise ValueError('Unknown strategy')
        if not 1<=self.instances<=10000: raise ValueError('instances must be 1..10000')
        for x in (self.acceleration,self.timeout_seconds,self.task_mean_seconds,self.sla_seconds,self.resource_capacity):
            if not math.isfinite(x) or x<=0: raise ValueError('Timing and capacity must be finite and positive')
        if not 0<=self.failure_probability<=1: raise ValueError('Invalid failure probability')
        if not 0<self.sla_warn_ratio<1: raise ValueError('Invalid SLA warning ratio')
        if self.human_mode not in ('batch','manual'): raise ValueError('Invalid human mode')
        for x in (self.human_delay_seconds,self.retry_backoff_seconds):
            if not math.isfinite(x) or x<0: raise ValueError('Delays must be finite and nonnegative')
        if self.retry_max<0: raise ValueError('retry_max must be nonnegative')


def stable_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


class Runner:
    def __init__(self, config, run_id=None, handler=None):
        config.validate(); self.cfg=config; self.run_id=run_id or uuid.uuid4().hex
        self.folder=ROOT/'artifacts'/'runs'/self.run_id; self.folder.mkdir(parents=True,exist_ok=False)
        self.store=Store(self.folder,self.run_id); self.client=Camunda(); self.handler=handler or L0(config.strategy,config.retry_max)
        self.mapping=mapping(config.dataset)
        scenarios=yaml.safe_load((ROOT/'config/scenarios.yaml').read_text())
        if config.scenario not in scenarios: raise ValueError('Unknown scenario')
        self.scenarios=scenarios[config.scenario]
        self.oracle=yaml.safe_load((ROOT/'config/oracle.yaml').read_text())
        self.model=build(config.dataset,self.run_id,self.folder)
        expanded={'config':asdict(config),'scenarios':self.scenarios,'oracle':self.oracle,'mapping':self.mapping}
        (self.folder/'configuration.json').write_text(json.dumps(expanded,indent=2),encoding='utf-8')
        self.meta={'run_id':self.run_id,'status':'preparing','seed':config.seed,'config':asdict(config),
                   'config_hash':stable_hash(expanded),
                   'started_at':now(),'model_sha256':digest(self.model['bpmn']), 'model_version':'wp1-operational-v1',
                   'model_semantic_sha256':stable_hash(self.model['bpmn'].read_text().replace(self.run_id,'<scope>')),
                   'dependency_lock_sha256':digest(ROOT/'requirements.lock.txt'),
                   'versions':{'python':platform.python_version(),**{p:importlib.metadata.version(p) for p in ['fastapi','httpx','pm4py','PyYAML']}},
                   'camunda_image':'camunda/camunda@sha256:cb3408f10bfbac29be4d1f3b13955d2003c9f1a1c19becab329f818ade895cb7',
                   'assumptions':['Curated executable abstraction, not historical trace conformance.', 'Batch humans are synthetic approvals, not historical decisions.',
                                  'Inter-event gaps are timing proxies; no validated service durations.', '2017 CSV lacks timestamps; arrivals and durations are synthetic.',
                                  'Recorded wall timestamps are actual; business_seconds is model time. API overhead affects accelerated wall time.']}
        self.inputs={}; self.keys={}; self.pending=[]; self.seq=0; self.handled_users=set(); self.cost=0
        self.resource_due=[]; self.reserve_queue=[]; self.persist()

    def persist(self):
        # Atomic replacement lets the dashboard poll during a run.
        temp=self.folder/'metadata.tmp'; temp.write_text(json.dumps(self.meta,indent=2,default=str),encoding='utf-8'); temp.replace(self.folder/'metadata.json')

    def rng(self,cid,step,kind='duration'):
        return random.Random(int(stable_hash([self.cfg.seed,cid,step,kind])[:16],16))

    def schedule(self,due,kind,data):
        self.seq+=1; heapq.heappush(self.pending,(due,self.seq,kind,data))

    def incident(self,cid,step,kind,attempt=0,job_key=''):
        request=AdaptationRequest(request_id=uuid.uuid4().hex,run_id=self.run_id,case_id=cid,timestamp=datetime.now(timezone.utc),
            trigger={'timeout':'timeout','missing_data':'data_error','resource_shortage':'queue','sla_risk':'sla_warning','rule_change':'rule_change'}.get(kind,'incident'),
            element=step,disruption_label=kind,case_state=self.inputs[cid],allowed_actions=['none',*self.oracle[kind]],attempt=attempt)
        response=self.handler.respond(request); accepted=response.action in self.oracle[kind]
        self.store.db.execute('INSERT INTO adaptations VALUES(?,?,?,?,?,?)',(request.request_id,cid,request.model_dump_json(),response.model_dump_json(),int(accepted),'pending'))
        self.store.db.commit()
        self.store.event(cid,self.mapping['activities'].get(step,step),'adaptation',resource='L0-rules',disruption=kind,
                         request_id=request.request_id,intervention=response.action,outcome='pending',job_key=job_key)
        return response.action,request.request_id

    def disruptions(self,cid,step):
        c=self.inputs[cid]
        row=self.store.db.execute('SELECT business_seconds FROM cases WHERE case_id=?',(cid,)).fetchone()
        logical=c['arrival_seconds']+row[0]
        result=[]
        for s in self.scenarios:
            target=self.mapping['disruption_targets'][s['type']]
            if target!=step: continue
            lo,hi=s['window_hours']
            if not lo*3600<=logical<hi*3600: continue
            if self.rng(cid,step,s['type']).random()>=s['probability']: continue
            if s['type']=='rule_change' and c['amount']<=s.get('amount_gt',0): continue
            result.append(s)
        return result

    def task_duration(self,cid,step):
        c=self.inputs[cid]
        labels={step,self.mapping['activities'].get(step,step)}
        events=c['events']; matching=[]
        for i,e in enumerate(events):
            if i and e.get('concept:name') in labels and e.get('time:timestamp') and events[i-1].get('time:timestamp'):
                gap=(datetime.fromisoformat(e['time:timestamp'])-datetime.fromisoformat(events[i-1]['time:timestamp'])).total_seconds()
                if gap>=0: matching.append(gap)
        return sum(matching)/len(matching) if matching else self.rng(cid,step).expovariate(1/self.cfg.task_mean_seconds)

    def activate_job(self,job,step):
        v=job['variables']; cid=v['caseId']; key=job['jobKey']
        if cid not in self.inputs: raise RuntimeError('Foreign job activated; run isolation failed')
        if step=='sla':
            self.store.event(cid,'SLA boundary timer','complete',resource='Camunda-timer',job_key=key)
            self.client.complete(key,{})
            return
        cached=self.store.db.execute('SELECT result FROM effects WHERE case_id=? AND step=?',(cid,step)).fetchone()
        if cached:
            self.client.complete(key,json.loads(cached[0])); return
        attempt=self.store.attempt(cid,step)
        duration=self.task_duration(cid,step); updates={}; action=''; request_id=''; disruption=''
        self.store.event(cid,self.mapping['activities'][step],'start',job_key=key)
        scenarios=self.disruptions(cid,step)
        if step in ('payment','match') and self.rng(cid,step,'base_failure').random()<self.cfg.failure_probability:
            scenarios.append({'type':'service_outage','failures':1})
        if v.get('humanApprovedStep')==step:
            scenarios=[]; updates={'dataPresent':True,'complianceChecked':True,'provider':'human-resolved'}
        for s in scenarios:
            kind=s['type']; disruption=kind
            if kind in ('service_outage','timeout') and attempt>=s.get('failures',1): continue
            if kind=='missing_data' and v.get('dataPresent'): continue
            if kind=='rule_change' and v.get('ruleUpdated'): continue
            action,request_id=self.incident(cid,step,kind,attempt,key)
            if action=='retry':
                self.cost+=.1
                self.store.event(cid,self.mapping['activities'][step],'error',disruption=kind,request_id=request_id,intervention=action,job_key=key)
                self.client.fail(key,max(1,3-attempt),'Injected '+kind,max(1,int(self.cfg.retry_backoff_seconds/self.cfg.acceleration*1000)))
                self.store.db.execute('UPDATE cases SET business_seconds=business_seconds+? WHERE case_id=?',(self.cfg.retry_backoff_seconds,cid)); self.store.db.commit()
                return
            if action=='none' and kind in ('service_outage','timeout','missing_data','resource_shortage'):
                self.client.fail(key,0,'Unresolved '+kind); self.store.finish(cid,'stuck'); return
            if action=='escalate':
                self.client.error(key,'EXTERNAL_ERROR',{'resumeStep':step,'escalationRequestId':request_id})
                self.store.event(cid,'Boundary error caught','complete',resource='Camunda-boundary',disruption=kind,request_id=request_id,intervention='escalate',job_key=key)
                return
            if action=='fallback': updates['provider']='backup'; self.cost+=1
            elif action=='lookup':
                self.cost+=.2
                updates['dataPresent']=True
                self.store.db.execute('UPDATE customers SET data_present=1 WHERE case_id=?',(cid,)); self.store.db.commit()
            elif action=='reassign':
                updates['assignedTeam']='backup-operations'
                self.store.db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?)',(cid,'backup-operations',0)); self.store.db.commit(); self.cost+=1
            elif action=='prioritise':
                updates['priority']=100
                self.store.db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?)',(cid,'operations',100)); self.store.db.commit()
                # Expedited handling changes the actual job completion deadline.
                duration*=.1; self.cost+=2
            elif action=='update_rule':
                updates.update(ruleUpdated=True,complianceChecked=True); self.cost+=.25
            if kind=='sla_risk' and action=='none': duration+=s.get('delay_seconds',86400)
        if step=='validate': updates.setdefault('dataPresent',True)
        if step=='reserve': updates['goodsReceiptRecorded']=bool(v.get('needsGoodsReceipt'))
        if step=='invoice': updates['invoiceRecorded']=True
        if step=='match':
            if self.cfg.dataset=='bpic2019' and v.get('needsGoodsReceipt') and not v.get('goodsReceiptRecorded'):
                self.client.fail(key,0,'Missing goods receipt for matching'); self.store.finish(cid,'stuck'); return
            if self.cfg.dataset=='bpic2019' and v.get('matchingMode')!='consignment' and not v.get('invoiceRecorded'):
                self.client.fail(key,0,'Missing invoice for matching'); self.store.finish(cid,'stuck'); return
            updates['matchingChecked']=True
        if step=='compliance':
            changed=any(s['type']=='rule_change' for s in scenarios)
            updates.setdefault('complianceChecked',not changed or bool(v.get('ruleUpdated')))
        # Limited real worker pool for document review/handling. Reassignment
        # bypasses this pool with a distinct team; prioritisation shortens service.
        data=(job,step,updates,duration,request_id,action,disruption)
        if step=='reserve' and not updates.get('assignedTeam'):
            self.seq+=1
            heapq.heappush(self.reserve_queue,(-updates.get('priority',0),self.seq,time.monotonic(),data))
        else:
            self.schedule(time.monotonic()+duration/self.cfg.acceleration,'job',data)

    def dispatch_reserve_queue(self):
        clock=time.monotonic()
        self.resource_due=[t for t in self.resource_due if t>clock]
        while self.reserve_queue and len(self.resource_due)<self.cfg.resource_capacity:
            _,_,queued_at,data=heapq.heappop(self.reserve_queue)
            job,step,updates,duration,rid,action,disruption=data
            wait_seconds=(clock-queued_at)*self.cfg.acceleration
            cid=job['variables']['caseId']
            self.store.event(cid,self.mapping['activities'][step],'assigned',resource='priority-pool' if updates.get('priority') else 'operations-pool',request_id=rid,intervention=action,job_key=job['jobKey'])
            # Worker queue waiting is measured separately. API overhead is excluded
            # from modeled cycle-time metrics and is retained in wall time.
            due=clock+duration/self.cfg.acceleration
            self.resource_due.append(due); self.schedule(due,'job',data)

    def finish_job(self,data,acknowledged=False):
        job,step,updates,duration,request_id,action,disruption=data
        cid=job['variables']['caseId']; key=job['jobKey']
        result=self.store.effect(cid,step,self.inputs[cid]['amount'],updates)
        if not acknowledged: self.client.complete(key,result)
        self.store.db.execute('UPDATE cases SET business_seconds=business_seconds+? WHERE case_id=?',(duration,cid)); self.store.db.commit()
        self.store.event(cid,self.mapping['activities'][step],'complete',disruption=disruption,request_id=request_id,intervention=action,outcome='executed',job_key=key,business_seconds=duration)
        if step=='dispatch':
            self.client.message(self.model['message'],f'{self.run_id}:{cid}',f'{self.run_id}:{cid}:confirmation')
            self.store.db.execute('INSERT OR IGNORE INTO shipments VALUES(?,?,1)',(cid,f'{self.run_id}:{cid}:confirmation')); self.store.db.commit()
            self.store.event(cid,'External confirmation published','complete',resource='mock-carrier',outcome='published')

    def start_case(self,c):
        cid=c['case_id']; self.inputs[cid]=c
        variables={'runId':self.run_id,'caseId':cid,'amount':c['amount'],'variant':c['variant'],
                   'matchingMode':c.get('matchingMode','3way-after'),'loanOutcome':c.get('loanOutcome','pending'),
                   'needsGoodsReceipt':c['needsGoodsReceipt'],'correlationKey':f'{self.run_id}:{cid}',
                   'forceReview':self.cfg.scenario=='resource_shortage','dataPresent':False,
                   'ruleUpdated':False,'complianceChecked':False,
                   'slaTimer':f'PT{max(.1,self.cfg.sla_seconds*self.cfg.sla_warn_ratio/self.cfg.acceleration):.3f}S'}
        result=self.client.create(self.definition_key,variables); key=str(result['processInstanceKey']); self.keys[key]=cid
        with self.store.db:
            self.store.db.execute('INSERT INTO cases(case_id,instance_key,status,input,started) VALUES(?,?,?,?,?)',(cid,key,'running',json.dumps(c),now()))
            self.store.db.execute('INSERT INTO customers VALUES(?,?,?)',(cid,0,json.dumps(c['attributes'])))
            self.store.db.execute('INSERT INTO inventory VALUES(?,?,0)',(cid,1))
        self.store.event(cid,'Process instance started','complete',resource='Camunda',outcome=key)

    def poll_humans(self):
        for task in self.client.user_tasks(self.definition_key):
            key=str(task['userTaskKey'])
            if key in self.handled_users: continue
            self.handled_users.add(key)
            cid=self.keys.get(str(task['processInstanceKey']))
            if not cid: continue
            step=task.get('elementId',task.get('flowNodeId','review'))
            if self.cfg.human_mode=='manual':
                self.store.event(cid,self.mapping['activities'].get(step,step),'start',resource='manual-human',job_key=key)
                continue
            updates={}; action=''; rid=''; delay=self.cfg.human_delay_seconds
            if step=='escalation':
                pending=self.store.db.execute('SELECT request_id,request FROM adaptations WHERE case_id=? ORDER BY rowid DESC LIMIT 1',(cid,)).fetchone()
                req=json.loads(pending['request']); updates={'resumeStep':req['element'],'humanApprovedStep':req['element'],'dataPresent':True,'ruleUpdated':True,'complianceChecked':True}
                rid=pending['request_id']; action='escalate'; self.cost+=3
            else:
                for s in self.disruptions(cid,'review'):
                    action,rid=self.incident(cid,'review',s['type'])
                    if action=='none':
                        self.store.finish(cid,'stuck'); return
                    if action=='reassign':
                        updates['assignedTeam']='backup-reviewers'; delay*=.5; self.cost+=1
                        self.client.assign_user(key,'backup-reviewer')
                    if action=='escalate':
                        updates['assignedTeam']='operations-supervisor'; self.cost+=3
                        self.client.assign_user(key,'operations-supervisor')
                updates['humanReviewed']=True
            self.store.event(cid,self.mapping['activities'].get(step,step),'start',resource='synthetic-human',request_id=rid,intervention=action,job_key=key)
            self.schedule(time.monotonic()+delay/self.cfg.acceleration,'human',(key,cid,step,updates,delay,rid,action))

    def finish_human(self,data):
        key,cid,step,updates,delay,rid,action=data
        self.client.complete_user(key,updates)
        self.store.db.execute('UPDATE cases SET business_seconds=business_seconds+? WHERE case_id=?',(delay,cid)); self.store.db.commit()
        self.store.event(cid,self.mapping['activities'].get(step,step),'complete',resource=updates.get('assignedTeam','synthetic-human'),request_id=rid,intervention=action,outcome='approved',job_key=key,business_seconds=delay)

    def execute(self):
        error=None; pool=None
        try:
            self.meta['engine_topology']=self.client.topology()
            version=self.meta['engine_topology']['gatewayVersion']
            if not version.startswith('8.10.'): raise RuntimeError(f'Unsupported engine {version}; tested pin is 8.10.3-SNAPSHOT')
            cases,profile=workload(self.cfg.dataset,self.cfg.instances,self.cfg.seed,self.cfg.sample_limit)
            self.meta['dataset_identity']=profile['identity'] if profile else {'dataset':'synthetic'}
            self.meta['workload_hash']=stable_hash(cases)
            (self.folder/'inputs.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
            self.meta['deployment']=self.client.deploy([self.model['bpmn'],self.model['dmn']])
            self.definition_key=next(d['processDefinition']['processDefinitionKey'] for d in self.meta['deployment']['deployments'] if d.get('processDefinition'))
            self.meta['status']='running'; self.persist(); start=time.monotonic(); check_at=0; humans_at=0
            pool=ThreadPoolExecutor(max_workers=11)
            for c in cases: self.schedule(start+c['arrival_seconds']/self.cfg.acceleration,'start',c)
            while time.monotonic()-start<self.cfg.timeout_seconds:
                clock=time.monotonic()
                ready_jobs=[]
                while self.pending and self.pending[0][0]<=clock:
                    _,_,kind,data=heapq.heappop(self.pending)
                    if kind=='start': self.start_case(data)
                    elif kind=='job': ready_jobs.append(data)
                    elif kind=='human': self.finish_human(data)
                acknowledgements=[]
                for data in ready_jobs:
                    job,step,updates,_,_,_,_=data; cid=job['variables']['caseId']
                    result=self.store.effect(cid,step,self.inputs[cid]['amount'],updates)
                    acknowledgements.append(pool.submit(self.client.complete,job['jobKey'],result))
                for data,future in zip(ready_jobs,acknowledgements):
                    future.result(); self.finish_job(data,acknowledged=True)
                steps=[*STEPS,'sla']
                futures=[pool.submit(self.client.activate,f'{self.run_id}.{step}',100,int((self.cfg.timeout_seconds+60)*1000)) for step in steps]
                for step,future in zip(steps,futures):
                    for job in future.result():
                        self.activate_job(job,step)
                self.dispatch_reserve_queue()
                if clock>=humans_at:
                    self.poll_humans(); humans_at=clock+.2
                if clock>=check_at:
                    running={r['instance_key']:r for r in self.store.rows('cases') if r['status']=='running'}
                    for instance in self.client.instances(self.definition_key):
                        row=running.get(str(instance['processInstanceKey']))
                        if row and instance.get('state')=='COMPLETED':
                            self.store.finish(row['case_id'],'completed')
                            self.store.event(row['case_id'],'Process instance completed','complete',resource='Camunda',outcome='completed')
                    check_at=clock+.5; self.meta['cases_started']=len(self.keys); self.persist()
                rows=self.store.rows('cases')
                if len(rows)==self.cfg.instances and all(r['status']!='running' for r in rows) and not self.pending and not self.reserve_queue: break
                time.sleep(.01)
            for row in self.store.rows('cases'):
                if row['status']=='running': self.store.finish(row['case_id'],'stuck')
            self.meta['status']='finished'
        except Exception as exc:
            error=exc; self.meta.update(status='failed',error=f'{type(exc).__name__}: {exc}')
            if isinstance(exc,httpx.HTTPStatusError): self.meta['error_detail']=exc.response.text
        finally:
            if pool: pool.shutdown(wait=True,cancel_futures=True)
            # Cancel every owned instance still active, including incidents. Never
            # cancel instances from another experiment or the user's other work.
            cleanup=[]
            for key,cid in self.keys.items():
                try:
                    state=self.client.instance(key).get('state')
                    if state not in ('COMPLETED','CANCELED','TERMINATED'):
                        self.client.cancel(key); cleanup.append({'key':key,'action':'cancelled'})
                except Exception as exc: cleanup.append({'key':key,'error':str(exc)})
            cancelled={item['key'] for item in cleanup if item.get('action')=='cancelled'}
            deadline=time.monotonic()+15
            while cancelled and time.monotonic()<deadline:
                for instance in self.client.instances(self.definition_key):
                    if instance.get('state') in ('CANCELED','TERMINATED','COMPLETED'):
                        cancelled.discard(str(instance['processInstanceKey']))
                if cancelled: time.sleep(.2)
            if cancelled:
                self.meta['cleanup_unconfirmed']=sorted(cancelled)
                self.meta['status']='failed'
                error=error or RuntimeError('Cancellation confirmation timed out; run isolation not verified')
            self.meta['cleanup']=cleanup
            self.meta['ended_at']=now()
            try:
                self.meta['metrics']=self.metrics(); self.store.export()
                self.persist()
                if (self.folder/'inputs.json').exists():
                    from .validation import validate_run
                    self.meta['validation']=validate_run(self.folder)
                    if not self.meta['validation']['valid']: raise RuntimeError('Operational replay validation failed')
            except Exception as exc:
                self.meta['export_error']=str(exc); error=error or exc; self.meta['status']='failed'
            self.persist(); self.store.db.close(); self.client.close()
        if error: raise error
        return self.meta

    def metrics(self):
        cases=self.store.rows('cases'); adaptations=self.store.rows('adaptations'); events=self.store.rows('events')
        complete=[c for c in cases if c['status']=='completed']; ct=[c['business_seconds'] for c in complete]
        ok=0
        for a in adaptations:
            c=next(c for c in cases if c['case_id']==a['case_id'])
            request=json.loads(a['request']); response=json.loads(a['response'])
            successful=bool(a['accepted']) and c['status']=='completed'
            if request['disruption_label']=='rule_change': successful=successful and bool(c['compliance'])
            if response['action']=='retry':
                # A later fallback/escalation cannot make an exhausted retry successful.
                successful=successful and not any(b['case_id']==a['case_id'] and b['request_id']!=a['request_id'] and json.loads(b['request'])['element']==request['element'] and json.loads(b['response'])['action'] in ('fallback','escalate') for b in adaptations)
            outcome='success' if successful else 'failure'; ok+=int(successful)
            self.store.db.execute('UPDATE adaptations SET outcome=? WHERE request_id=?',(outcome,a['request_id']))
            self.store.db.execute('UPDATE events SET outcome=? WHERE request_id=? AND lifecycle=?',(outcome,a['request_id'],'adaptation'))
        self.store.db.commit()
        compliance_violations=sum(1 for c in complete if (self.cfg.dataset!='bpic2017' or self.inputs[c['case_id']].get('loanOutcome')=='pending') and not c['compliance'])
        return {'instances_requested':self.cfg.instances,'cases_started':len(cases),'completed':len(complete),
                'completion_rate':len(complete)/self.cfg.instances,'stuck_cases':self.cfg.instances-len(complete),
                'unstarted_cases':self.cfg.instances-len(cases),
                'sla_violations':sum(c['business_seconds']>self.cfg.sla_seconds for c in cases),
                'compliance_violations':compliance_violations,'mean_cycle_time_seconds':sum(ct)/len(ct) if ct else None,
                'mean_wall_cycle_seconds':sum((datetime.fromisoformat(c['ended'])-datetime.fromisoformat(c['started'])).total_seconds() for c in complete)/len(complete) if complete else None,
                'human_escalations':sum(e['activity']==self.mapping['activities']['escalation'] and e['lifecycle']=='complete' or e['intervention']=='escalate' and e['resource']=='operations-supervisor' and e['lifecycle']=='complete' for e in events),
                'adaptation_requests':len(adaptations),'adaptation_success_rate':ok/len(adaptations) if adaptations else None,
                'additional_intervention_cost':self.cost+3*sum(e['activity']==self.mapping['activities']['escalation'] and e['lifecycle']=='complete' and e['resource']=='manual-human' for e in events),'cost_unit':'synthetic experiment units',
                'loan_outcomes':{outcome:sum(self.inputs[c['case_id']].get('loanOutcome')==outcome for c in complete) for outcome in ['pending','denied','cancelled']} if self.cfg.dataset=='bpic2017' else None,
                'metric_note':'Cycle time and SLA use modeled business duration sums (waiting proxies included), not accelerated API wall time. Stuck SLA remains censored.'}


def compare(config):
    results=[]
    for strategy in PRESETS:
        cfg=RunConfig(**{**asdict(config),'strategy':strategy})
        results.append(Runner(cfg).execute())
    if len({r['workload_hash'] for r in results})!=1: raise RuntimeError('Strategy inputs differ')
    folder=ROOT/'artifacts'/'comparisons'; folder.mkdir(exist_ok=True)
    result={'comparison_id':uuid.uuid4().hex,'runs':results}
    (folder/f'{result["comparison_id"]}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
