"""Small version-tested Camunda v2 REST client. No simulated engine fallback."""
import os
import time
from pathlib import Path
import httpx


class Camunda:
    def __init__(self, url=None):
        self.http = httpx.Client(base_url=(url or os.getenv('CAMUNDA_URL', 'http://localhost:8080')) + '/v2',
                                 timeout=30, auth=('demo', 'demo'))

    def close(self):
        self.http.close()

    def call(self, method, path, **kwargs):
        # Only backpressure responses are retried automatically. Never retry an
        # ambiguous process creation, deployment, or financial mutation.
        for attempt in range(5):
            r = self.http.request(method, path, **kwargs)
            if r.status_code not in (429, 503):
                r.raise_for_status()
                return r.json() if r.content else {}
            time.sleep(.1 * 2 ** attempt)
        r.raise_for_status()

    def topology(self):
        return self.call('GET', '/topology')

    def deploy(self, paths):
        files = [('resources', (Path(p).name, Path(p).read_bytes(), 'application/xml')) for p in paths]
        return self.call('POST', '/deployments', files=files)

    def create(self, definition_key, variables):
        return self.call('POST', '/process-instances', json={
            'processDefinitionKey': str(definition_key), 'variables': variables})

    def activate(self, job_type, maximum=32,lease_ms=120000):
        return self.call('POST', '/jobs/activation', json={
            'type': job_type, 'worker': 'testbed-python', 'timeout': lease_ms,
            'maxJobsToActivate': maximum, 'requestTimeout': 1}).get('jobs', [])

    def complete(self, key, variables):
        return self.call('POST', f'/jobs/{key}/completion', json={'variables': variables})

    def fail(self, key, retries, message, backoff=100):
        return self.call('POST', f'/jobs/{key}/failure', json={
            'retries': retries, 'errorMessage': message, 'retryBackOff': backoff})

    def error(self, key, code, variables=None):
        return self.call('POST', f'/jobs/{key}/error', json={'errorCode': code, 'errorMessage': code, 'variables': variables or {}})

    def message(self, name, correlation, message_id):
        return self.call('POST', '/messages/publication', json={
            'name': name, 'correlationKey': correlation, 'messageId': message_id,
            'timeToLive': 120000, 'variables': {'messageConfirmed': True}})

    def user_tasks(self, definition_key):
        return self.call('POST', '/user-tasks/search', json={
            'filter': {'processDefinitionKey': str(definition_key), 'state': 'CREATED'},
            'page': {'limit': 100}}).get('items', [])

    def complete_user(self, key, variables):
        return self.call('POST', f'/user-tasks/{key}/completion', json={'variables': variables})

    def assign_user(self,key,assignee):
        return self.call('POST',f'/user-tasks/{key}/assignment',json={'assignee':assignee,'allowOverride':True})

    def instance(self, key):
        return self.call('GET', f'/process-instances/{key}')

    def instances(self, definition_key):
        return self.call('POST','/process-instances/search',json={
            'filter':{'processDefinitionKey':str(definition_key)},'page':{'limit':10000}}).get('items',[])

    def cancel(self, key):
        return self.call('POST', f'/process-instances/{key}/cancellation', json={})
