"""Validate the declared operational abstraction, not historical human correctness."""
import json
import sqlite3
from pathlib import Path


def validate_run(folder):
    folder=Path(folder)
    metadata=json.loads((folder/'metadata.json').read_text())
    inputs={c['case_id']:c for c in json.loads((folder/'inputs.json').read_text())}
    errors=[]; checked=0
    with sqlite3.connect(folder/'state.sqlite') as db:
        db.row_factory=sqlite3.Row
        for c in db.execute('SELECT * FROM cases WHERE status="completed"'):
            checked+=1; cid=c['case_id']; source=inputs[cid]
            effects={row['step']:json.loads(row['result']) for row in db.execute('SELECT step,result FROM effects WHERE case_id=?',(cid,))}
            if not effects.get('validate',{}).get('dataPresent'): errors.append(f'{cid}: data validation absent')
            if not effects.get('match',{}).get('matchingChecked'): errors.append(f'{cid}: document/application assessment absent')
            if metadata['config']['dataset']=='bpic2019':
                mode=source['matchingMode']
                if mode!='2way' and not effects.get('reserve',{}).get('goodsReceiptRecorded'): errors.append(f'{cid}: missing goods receipt')
                if mode!='consignment' and not effects.get('invoice',{}).get('invoiceRecorded'): errors.append(f'{cid}: missing invoice')
                steps=[row['step'] for row in db.execute('SELECT step FROM effects WHERE case_id=? ORDER BY rowid',(cid,))]
                if mode=='3way-before' and steps.index('invoice')>steps.index('reserve'): errors.append(f'{cid}: wrong invoice-before-GR order')
                if mode=='3way-after' and steps.index('invoice')<steps.index('reserve'): errors.append(f'{cid}: wrong invoice-after-GR order')
            terminal=source.get('loanOutcome') in ('denied','cancelled') and metadata['config']['dataset']=='bpic2017'
            if not terminal and 'payment' not in effects: errors.append(f'{cid}: payment/loan settlement absent')
            if not terminal and not db.execute('SELECT 1 FROM shipments WHERE case_id=? AND confirmed=1',(cid,)).fetchone(): errors.append(f'{cid}: external message absent')
            if not db.execute('SELECT 1 FROM events WHERE case_id=? AND activity="Process instance completed"',(cid,)).fetchone(): errors.append(f'{cid}: engine completion unobserved')
    result={'checked_completed_cases':checked,'errors':errors,'valid':not errors,
            'scope':'Operational mapping invariants; not historical trace equivalence, calibrated simulation accuracy, or an adaptation oracle.'}
    (folder/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
