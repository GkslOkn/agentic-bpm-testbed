import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, folder, run_id):
        self.folder=Path(folder); self.run_id=run_id
        self.db=sqlite3.connect(self.folder/'state.sqlite', timeout=20)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY, instance_key TEXT, status TEXT, input TEXT, started TEXT, ended TEXT, business_seconds REAL DEFAULT 0, compliance INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run_id TEXT, case_id TEXT, activity TEXT, lifecycle TEXT, timestamp TEXT, resource TEXT, disruption TEXT, request_id TEXT, intervention TEXT, outcome TEXT, job_key TEXT, business_seconds REAL);
        CREATE TABLE IF NOT EXISTS adaptations(request_id TEXT PRIMARY KEY, case_id TEXT, request TEXT, response TEXT, accepted INTEGER, outcome TEXT);
        CREATE TABLE IF NOT EXISTS effects(case_id TEXT, step TEXT, result TEXT, PRIMARY KEY(case_id,step));
        CREATE TABLE IF NOT EXISTS attempts(case_id TEXT, step TEXT, number INTEGER, PRIMARY KEY(case_id,step));
        CREATE TABLE IF NOT EXISTS customers(case_id TEXT PRIMARY KEY, data_present INTEGER, attributes TEXT);
        CREATE TABLE IF NOT EXISTS inventory(case_id TEXT PRIMARY KEY, quantity INTEGER, reserved INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS transactions(case_id TEXT PRIMARY KEY, amount REAL, provider TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS shipments(case_id TEXT PRIMARY KEY, message_id TEXT UNIQUE, confirmed INTEGER);
        CREATE TABLE IF NOT EXISTS resources(case_id TEXT PRIMARY KEY, team TEXT, priority INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS compliance_audits(case_id TEXT PRIMARY KEY, rule_version TEXT, checked_at TEXT, evidence TEXT);
        ''')
        self.db.commit()

    def event(self, case_id, activity, lifecycle, resource='python-worker', disruption='', request_id='', intervention='', outcome='', job_key='', business_seconds=0):
        self.db.execute('INSERT INTO events(run_id,case_id,activity,lifecycle,timestamp,resource,disruption,request_id,intervention,outcome,job_key,business_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (self.run_id,case_id,activity,lifecycle,now(),resource,disruption,request_id,intervention,outcome,str(job_key),business_seconds))
        self.db.commit()

    def attempt(self,cid,step):
        row=self.db.execute('SELECT number FROM attempts WHERE case_id=? AND step=?',(cid,step)).fetchone()
        n=row['number'] if row else 0
        self.db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(cid,step,n+1)); self.db.commit()
        return n

    def effect(self,cid,step,amount,variables):
        """Local mock effect and result commit atomically before engine acknowledgement.

        Redelivery reads the result. This is an outbox/idempotency pattern for SQLite
        mocks, not an exactly-once guarantee for arbitrary remote systems.
        """
        row=self.db.execute('SELECT result FROM effects WHERE case_id=? AND step=?',(cid,step)).fetchone()
        if row: return json.loads(row['result'])
        with self.db:
            if step=='reserve':
                self.db.execute('UPDATE inventory SET reserved=1 WHERE case_id=?',(cid,))
            if step=='payment':
                self.db.execute('INSERT OR IGNORE INTO transactions VALUES(?,?,?,?)',(cid,amount,variables.get('provider','primary'),'paid'))
            if step=='validate': self.db.execute('UPDATE customers SET data_present=1 WHERE case_id=?',(cid,))
            if step=='compliance' and variables.get('complianceChecked'):
                self.db.execute('UPDATE cases SET compliance=1 WHERE case_id=?',(cid,))
                if variables.get('ruleUpdated'):
                    evidence={row['step']:json.loads(row['result']) for row in self.db.execute('SELECT step,result FROM effects WHERE case_id=?',(cid,))}
                    if not evidence.get('validate',{}).get('dataPresent') or not evidence.get('match',{}).get('matchingChecked'):
                        raise RuntimeError('Updated compliance policy requires verified data and document matching')
                    self.db.execute('INSERT OR IGNORE INTO compliance_audits VALUES(?,?,?,?)',(cid,'tactical-v2',now(),json.dumps(evidence)))
            self.db.execute('INSERT INTO effects VALUES(?,?,?)',(cid,step,json.dumps(variables)))
        return variables

    def finish(self,cid,status):
        self.db.execute('UPDATE cases SET status=?,ended=? WHERE case_id=?',(status,now(),cid)); self.db.commit()

    def rows(self,table):
        if table not in {'cases','events','adaptations','effects','transactions','resources'}: raise ValueError(table)
        return [dict(r) for r in self.db.execute(f'SELECT * FROM {table}')]

    def export(self):
        import pandas as pd
        import pm4py
        events=self.rows('events')
        df=pd.DataFrame(events)
        df.to_csv(self.folder/'events.csv',index=False)
        if df.empty: return
        df['case:concept:name']=df['case_id']; df['concept:name']=df['activity']
        df['time:timestamp']=pd.to_datetime(df['timestamp'],utc=True)
        df['org:resource']=df['resource']; df['lifecycle:transition']=df['lifecycle']
        pm4py.write_xes(df,str(self.folder/'events.xes'))
        # Valid OCEL with the case object and, for purchasing, the observed purchase
        # document object. Do not fabricate invoice/customer object identities.
        obj=[]; relations=[]; seen=set()
        inputs={c['case_id']:json.loads(c['input']) for c in self.rows('cases')}
        for e in events:
            cid=e['case_id']; objects=[(cid,'case')]
            doc=inputs.get(cid,{}).get('attributes',{}).get('Purchasing Document')
            if doc: objects.append((f'purchase-document:{doc}','purchase_document'))
            for oid,typ in objects:
                if oid not in seen: obj.append({'ocel:oid':oid,'ocel:type':typ}); seen.add(oid)
                relations.append({'ocel:eid':str(e['id']),'ocel:activity':e['activity'], 'ocel:timestamp':pd.Timestamp(e['timestamp']), 'ocel:oid':oid,'ocel:type':typ,'ocel:qualifier':'case_context'})
        from pm4py.objects.ocel.obj import OCEL
        oevents=pd.DataFrame([{'ocel:eid':str(e['id']),'ocel:activity':e['activity'],'ocel:timestamp':pd.Timestamp(e['timestamp'])} for e in events])
        ocel=OCEL(events=oevents,objects=pd.DataFrame(obj),relations=pd.DataFrame(relations))
        pm4py.write_ocel2_json(ocel,str(self.folder/'events.ocel.json'))
