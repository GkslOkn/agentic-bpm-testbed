import json
import os
import sqlite3
from pathlib import Path
import pytest
import pm4py
from testbed.client import Camunda
from testbed.models import ROOT,build
from testbed.runner import Runner,RunConfig,compare

pytestmark=pytest.mark.integration


@pytest.fixture(scope='module',autouse=True)
def require_live_camunda():
    c=Camunda()
    try: topology=c.topology()
    except Exception as exc: pytest.fail(f'Real Camunda required: {exc}')
    finally: c.close()
    assert topology['gatewayVersion']=='8.10.3-SNAPSHOT'


@pytest.mark.parametrize('dataset',['bpic2019','bpic2017','synthetic'])
def test_clean_execution_deployment_dmn_and_exports(dataset):
    r=Runner(RunConfig(dataset=dataset,scenario='clean',instances=3,timeout_seconds=60))
    m=r.execute()
    assert m['metrics']['completed']==3
    assert m['metrics']['compliance_violations']==0
    assert not m['cleanup']
    assert any(d.get('decisionDefinition') for d in m['deployment']['deployments'])
    log=pm4py.read_xes(str(r.folder/'events.xes'),return_legacy_log_object=True,show_progress_bar=False)
    assert len(log)==3
    assert any(e['resource']=='python-worker' and e['job_key'] for t in log for e in t)
    ocel=pm4py.read_ocel2_json(str(r.folder/'events.ocel.json'))
    assert len(ocel.events)>0 and len(ocel.relations)>=len(ocel.events)
    assert (r.folder/'inputs.json').exists() and len(m['workload_hash'])==64


@pytest.mark.parametrize('scenario,action',[
    ('service_outage','fallback'),('timeout','retry'),('missing_data','lookup'),
    ('resource_shortage','reassign'),('sla_risk','prioritise'),('rule_change','update_rule')])
def test_all_l0_disruptions_change_real_execution(scenario,action):
    cfg=RunConfig(dataset='synthetic',scenario=scenario,instances=4,timeout_seconds=60)
    # Missing-data scenario's fixed probability can select no case for some seeds.
    cfg.seed=42
    r=Runner(cfg); m=r.execute()
    with sqlite3.connect(r.folder/'state.sqlite') as db:
        actions=[json.loads(x[0])['action'] for x in db.execute('SELECT response FROM adaptations')]
        assert action in actions
        if action=='fallback': assert db.execute("SELECT COUNT(*) FROM transactions WHERE provider='backup'").fetchone()[0]>0
        if action=='reassign':
            assert db.execute("SELECT COUNT(*) FROM events WHERE resource='backup-reviewers'").fetchone()[0]>0
        if action=='prioritise': assert db.execute('SELECT COUNT(*) FROM resources WHERE priority=100').fetchone()[0]>0
        if action=='update_rule': assert db.execute('SELECT COUNT(*) FROM cases WHERE compliance=1').fetchone()[0]==4
    assert m['metrics']['completed']==4
    assert not m['cleanup']


def test_human_escalation_uses_boundary_error_and_native_user_task():
    r=Runner(RunConfig(dataset='bpic2019',scenario='service_outage',strategy='escalate',instances=2,timeout_seconds=60))
    m=r.execute(); assert m['metrics']['completed']==2
    assert m['metrics']['human_escalations']==2
    with sqlite3.connect(r.folder/'state.sqlite') as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE activity='Boundary error caught'").fetchone()[0]==2
        assert db.execute("SELECT COUNT(*) FROM events WHERE activity='Purchasing operations escalation' AND lifecycle='complete' AND job_key<>''").fetchone()[0]==2


def test_no_adaptation_creates_incidents_then_cancels_only_owned_cases():
    r=Runner(RunConfig(scenario='service_outage',strategy='none',instances=2,timeout_seconds=45))
    m=r.execute(); assert m['metrics']['completed']==0 and m['metrics']['stuck_cases']==2
    assert len(m['cleanup'])==2
    c=Camunda()
    try:
        for item in m['cleanup']: assert c.instance(item['key'])['state'] in ('CANCELED','TERMINATED')
    finally: c.close()


def test_equivalent_strategy_inputs_and_isolation():
    result=compare(RunConfig(dataset='synthetic',scenario='service_outage',instances=2,timeout_seconds=45))
    runs=result['runs']; assert len({r['workload_hash'] for r in runs})==1
    assert len({r['run_id'] for r in runs})==5
    assert runs[0]['metrics']['completed']==0
    assert runs[3]['metrics']['completed']==2
    assert runs[4]['metrics']['human_escalations']==2


def test_purchasing_matching_variants_with_explicit_synthetic_fixtures(monkeypatch):
    # Two-way is absent from the initial bounded source sample. Exercise the
    # executable branch with labelled test fixtures, never claim observed data.
    fixtures=[]
    for mode in ['3way-before','3way-after','2way','consignment']:
        fixtures.append({'case_id':'SYNTHETIC-TEST-'+mode,'amount':100,'variant':'synthetic-fixture',
                         'matchingMode':mode,'needsGoodsReceipt':mode!='2way',
                         'attributes':{'fixture':True},'events':[],'arrival_seconds':0})
    monkeypatch.setattr('testbed.runner.workload',lambda *args: (fixtures,None))
    r=Runner(RunConfig(dataset='bpic2019',scenario='clean',instances=4,timeout_seconds=60))
    m=r.execute()
    assert m['metrics']['completed']==4 and m['validation']['valid']
    with sqlite3.connect(r.folder/'state.sqlite') as db:
        steps={c['case_id']:[x[0] for x in db.execute('SELECT step FROM effects WHERE case_id=? ORDER BY rowid',(c['case_id'],))] for c in fixtures}
        assert 'reserve' not in steps['SYNTHETIC-TEST-2way']
        assert 'invoice' not in steps['SYNTHETIC-TEST-consignment']
        before=steps['SYNTHETIC-TEST-3way-before']; after=steps['SYNTHETIC-TEST-3way-after']
        assert before.index('invoice')<before.index('reserve')
        assert after.index('reserve')<after.index('invoice')


def test_dashboard_manual_approval_completes_native_tasks_and_logs():
    import time
    from fastapi.testclient import TestClient
    from testbed.api import app
    with TestClient(app) as web:
        response=web.post('/api/runs',json={'dataset':'synthetic','scenario':'service_outage','strategy':'escalate',
                                           'instances':1,'human_mode':'manual','timeout_seconds':60})
        assert response.status_code==202
        rid=response.json()['run_id']; deadline=time.monotonic()+55; approvals=0; final=None
        while time.monotonic()<deadline:
            result=web.get('/api/runs/'+rid)
            if result.status_code!=200: time.sleep(.1); continue
            record=result.json()
            if record['status'] in ('finished','failed'): final=record; break
            tasks=web.get('/api/runs/'+rid+'/tasks')
            if tasks.status_code==200:
                for task in tasks.json():
                    assert web.post('/api/runs/'+rid+'/tasks/'+str(task['userTaskKey'])+'/complete').status_code==200
                    assert web.post('/api/runs/'+rid+'/tasks/'+str(task['userTaskKey'])+'/complete').json()['already_completed']
                    approvals+=1
            time.sleep(.2)
        assert final and final['status']=='finished' and final['metrics']['completed']==1
        assert approvals>0 and final['metrics']['human_escalations']==1
        assert any(e['resource']=='manual-human' and e['lifecycle']=='complete' for e in final['events'])


@pytest.mark.acceptance
@pytest.mark.skipif(os.getenv('TESTBED_ACCEPTANCE')!='1',reason='Set TESTBED_ACCEPTANCE=1 for 200-case acceptance runs')
@pytest.mark.parametrize('dataset',['bpic2019','bpic2017','synthetic'])
@pytest.mark.parametrize('scenario',['clean','X'])
def test_200_case_acceptance(dataset,scenario):
    r=Runner(RunConfig(dataset=dataset,scenario=scenario,seed=42,instances=200,timeout_seconds=300))
    m=r.execute(); assert m['metrics']['completed']==200 and not m['cleanup']
    assert m['metrics']['compliance_violations']==0
    if scenario=='X': assert m['metrics']['adaptation_requests']>0
    assert len(pm4py.read_xes(str(r.folder/'events.xes'),return_legacy_log_object=True,show_progress_bar=False))==200
