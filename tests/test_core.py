import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from testbed.adaptation import AdaptationRequest,L0
from testbed.datasets import workload,load
from testbed.runner import RunConfig,stable_hash
from testbed.storage import Store
from testbed.api import app


def test_seeded_inputs_stable_and_independent_of_strategy():
    a,_=workload('synthetic',20,42); b,_=workload('synthetic',20,42); c,_=workload('synthetic',20,43)
    assert stable_hash(a)==stable_hash(b)!=stable_hash(c)
    assert all(y['arrival_seconds']>=x['arrival_seconds'] for x,y in zip(a,a[1:]))


def test_retry_is_bounded_and_contract_enforces_allowed_actions():
    request=AdaptationRequest(request_id='r',run_id='run',case_id='c',timestamp=datetime.now(timezone.utc),
       trigger='incident',element='payment',disruption_label='service_outage',case_state={},allowed_actions=['retry','fallback'])
    handler=L0('full',2)
    assert handler.respond(request).action=='retry'
    request.attempt=2
    assert handler.respond(request).action=='fallback'
    request.allowed_actions=['retry']
    assert handler.respond(request).action=='none'


def test_mock_payment_is_idempotent_under_redelivery(tmp_path):
    store=Store(tmp_path,'r')
    first=store.effect('c','payment',100,{'provider':'backup'})
    second=store.effect('c','payment',999,{'provider':'primary'})
    assert first==second
    rows=store.rows('transactions')
    assert len(rows)==1 and rows[0]['amount']==100 and rows[0]['provider']=='backup'
    store.db.close()


def test_api_rejects_invalid_runs_and_path_traversal():
    with TestClient(app) as c:
        assert c.post('/api/runs',json={'instances':0}).status_code==400
        assert c.post('/api/runs',json={'dataset':'unknown'}).status_code==400
        assert c.get('/api/runs/invalid/files/metadata.json').status_code==400
        assert c.get('/').status_code==200
        assert c.get('/static/vendor/bpmn-viewer.development.js').status_code==200
        assert c.get('/api/models/bpic2019').status_code==200


def test_both_local_schemas_and_missing_timestamp_limitation():
    cases,p,_=load('bpic2019',1000)
    assert p['timestamps_available'] and p['cases']==1000
    assert 'Item Category' in p['case_schema'] and 'org:resource' in p['event_schema']
    cases,p,_=load('bpic2017',1000)
    assert not p['timestamps_available']
    assert 'Accepted' in p['event_schema']
    assert any(e.get('lifecycle:transition')=='start' for c in cases for e in c['events'])


@pytest.mark.parametrize('field,value',[('acceleration',0),('acceleration',float('nan')),('resource_capacity',0),('failure_probability',2)])
def test_invalid_timing_and_workload_rejected(field,value):
    with pytest.raises(ValueError): RunConfig(**{field:value}).validate()
