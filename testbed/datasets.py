"""Bounded ingestion: never materialize the 729 MB XES as a DOM/DataFrame."""
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
from .models import ROOT, mapping


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def attrs(element):
    result = {}
    for child in element:
        if 'key' not in child.attrib:
            continue
        value = child.get('value')
        tag = child.tag.rsplit('}', 1)[-1]
        if tag == 'boolean': value = value == 'true'
        elif tag in ('float', 'int'): value = float(value)
        result[child.get('key')] = value
    return result


def bounded_xes(path, limit, output):
    """Extract complete original traces verbatim, then use PM4Py XES ingestion."""
    with open(output, 'wb') as out:
        out.write(b'<?xml version="1.0" encoding="UTF-8"?><log xes.version="1.0">')
        count = 0
        context = ET.iterparse(path, events=('start', 'end'))
        _, root = next(context)
        for event, el in context:
            if event == 'end' and el.tag.rsplit('}', 1)[-1] == 'trace':
                out.write(ET.tostring(el, encoding='utf-8'))
                root.remove(el)
                el.clear()
                count += 1
                if count >= limit: break
        out.write(b'</log>')
    return count


def load(dataset, limit=1000, refresh=False):
    if dataset == 'synthetic':
        raise ValueError('Synthetic mode has no historical dataset')
    if not 1 <= limit <= 10000:
        raise ValueError('Sample limit must be 1..10000 to bound memory')
    cfg = mapping(dataset); source = ROOT / cfg['file']
    folder = ROOT / 'artifacts' / 'profiles' / f'{dataset}-{limit}'
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / 'cases.json'
    identity = {'file': cfg['file'], 'bytes': source.stat().st_size, 'mtime_ns': source.stat().st_mtime_ns}
    if cache.exists() and not refresh:
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved['identity'] == identity:
            return saved['cases'], json.loads((folder / 'profile.json').read_text()), folder
    import pm4py
    cases = []
    if dataset == 'bpic2019':
        bounded_xes(source, limit, folder / 'sample.xes')
        log = pm4py.read_xes(str(folder / 'sample.xes'), return_legacy_log_object=True, show_progress_bar=False)
        for trace in log:
            events = [dict(e) for e in trace]
            for e in events:
                e['time:timestamp'] = e['time:timestamp'].isoformat()
            cases.append({'case_id': str(trace.attributes['concept:name']), 'attributes': dict(trace.attributes), 'events': events})
        schema = sorted({k for c in cases for e in c['events'] for k in e})
    else:
        # CSV has no timestamps in the supplied derivative. Preserve original row
        # order and lifecycle; no invented historical dates.
        by_case = {}
        with source.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f); schema = reader.fieldnames
            for row in reader:
                cid = row['case:concept:name']
                if cid not in by_case:
                    if len(by_case) >= limit: continue
                    by_case[cid] = {'case_id': cid, 'attributes': {k: v for k,v in row.items() if k.startswith('case:')}, 'events': []}
                by_case[cid]['events'].append({k:v for k,v in row.items() if not k.startswith('case:') and v != ''})
        cases = list(by_case.values())
    activities = Counter(); resources = Counter(); transitions = Counter(); gaps = defaultdict(list); calendars = Counter()
    starts = []; variants = Counter(); lifecycle = Counter()
    for c in cases:
        variants[c['attributes'].get('Item Category', c['attributes'].get('case:ApplicationType', 'unknown'))] += 1
        events = c['events']
        if events and events[0].get('time:timestamp'): starts.append(events[0]['time:timestamp'])
        for i,e in enumerate(events):
            name = e.get('concept:name', 'unknown'); activities[name] += 1
            resources[e.get('org:resource', 'unknown')] += 1
            lifecycle[e.get('lifecycle:transition', 'not supplied')] += 1
            if e.get('time:timestamp'):
                t = datetime.fromisoformat(e['time:timestamp'])
                calendars[f'{t.weekday()}:{t.hour}'] += 1
            if i:
                prev = events[i-1]; transitions[(prev['concept:name'], name)] += 1
                if e.get('time:timestamp') and prev.get('time:timestamp'):
                    gap = (datetime.fromisoformat(e['time:timestamp'])-datetime.fromisoformat(prev['time:timestamp'])).total_seconds()
                    if gap >= 0: gaps[name].append(gap)
    profile = {'dataset': dataset, 'identity': {**identity, 'sha256': digest(source)}, 'sampling': 'first N distinct cases; not representative random sampling',
               'cases': len(cases), 'events': sum(activities.values()), 'event_schema': schema,
               'case_schema': sorted({k for c in cases for k in c['attributes']}), 'activities': dict(activities),
               'resources': dict(resources), 'variants': dict(variants), 'lifecycle': dict(lifecycle),
               'timestamps_available': bool(starts), 'observed_activity_calendar': dict(calendars),
               'inter_event_seconds_mean': {k:sum(v)/len(v) for k,v in gaps.items()},
               'timing_warning': 'Inter-event gaps include waiting; not service durations or contractual calendars.',
               'transitions': [{'from':a, 'to':b, 'count':n} for (a,b),n in transitions.items()],
               'arrival_timestamps': sorted(starts)}
    mapped=set(cfg['activities'].values())
    profile['mapping_coverage']={'mapped_historical_activities':sorted(mapped.intersection(activities)),
                                'unmapped_historical_activities':sorted(set(activities)-mapped),
                                'synthetic_operational_activities':sorted(mapped-set(activities)),
                                'warning':'Operational abstraction omits historical loops and administrative changes. Full trace equivalence is not claimed.'}
    totals = Counter()
    for (a,b),n in transitions.items(): totals[a]+=n
    for x in profile['transitions']: x['probability'] = x['count']/totals[x['from']]
    cache.write_text(json.dumps({'identity':identity,'cases':cases}, ensure_ascii=False), encoding='utf-8')
    (folder/'profile.json').write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding='utf-8')
    return cases, profile, folder


def discover(dataset, limit=1000):
    """PM4Py directly-follows discovery. BPMN is diagnostic, never deployed."""
    import pm4py
    from pm4py.objects.log.obj import EventLog, Trace, Event
    cases, profile, folder = load(dataset, limit)
    log=EventLog()
    for c in cases:
        trace=Trace(attributes={'concept:name':c['case_id']})
        for e in c['events']:
            data=dict(e)
            if data.get('time:timestamp'): data['time:timestamp']=datetime.fromisoformat(data['time:timestamp'])
            trace.append(Event(data))
        log.append(trace)
    # Inductive miner accepts a DFG without fake timestamps for the 2017 CSV.
    from pm4py.algo.discovery.inductive import algorithm as im
    from pm4py.objects.conversion.process_tree import converter
    tree=im.apply(log)
    bpmn=converter.apply(tree, variant=converter.Variants.TO_BPMN)
    # Graphviz is optional and absent on this Windows machine. Discovery and XML
    # export still work; diagnostic BPMN has no useful automatic visual layout.
    pm4py.write_bpmn(bpmn, str(folder/'discovered.bpmn'),auto_layout=False)
    net,initial,final=converter.apply(tree,variant=converter.Variants.TO_PETRI_NET)
    fitness=pm4py.fitness_token_based_replay(log,net,initial,final)
    (folder/'discovery-validation.json').write_text(json.dumps({'token_replay_fitness':fitness,
        'scope':'Discovered model against the bounded source sample; does not validate the curated Camunda model or human decision correctness.'},indent=2),encoding='utf-8')
    (folder/'simulation-parameters.json').write_text(json.dumps({
        'arrivals':profile['arrival_timestamps'], 'timing_proxies':profile['inter_event_seconds_mean'],
        'resources':profile['resources'], 'calendar_observations':profile['observed_activity_calendar'],
        'branching':profile['transitions'], 'warning':profile['timing_warning'],
        'prosimos_compatible':False, 'reason':'No validated start/end durations or contractual resource calendars; this is an empirical parameter report, not calibrated Simod output.'},indent=2),encoding='utf-8')
    return profile, folder


def workload(dataset, instances, seed, sample_limit=1000):
    rng=random.Random(seed)
    selected=[]; profile=None
    if dataset!='synthetic':
        cases, profile, _=load(dataset, max(instances, sample_limit))
        if instances>len(cases): raise ValueError('Not enough distinct cases in sample')
        selected=rng.sample(cases, instances)
    inputs=[]; arrival=0.0
    cfg=mapping(dataset)
    timestamps=[datetime.fromisoformat(c['events'][0]['time:timestamp']) for c in selected if c['events'] and c['events'][0].get('time:timestamp')]
    origin=min(timestamps) if timestamps else None
    for i in range(instances):
        if dataset=='synthetic':
            arrival+=rng.expovariate(6/3600)
            inputs.append({'case_id':f'C-{i:05}', 'amount':round(rng.lognormvariate(8.4,.7),2),
                           'attributes':{'region':rng.choice(['north','south','east','west']), 'new_customer':rng.random()<.25},
                           'events':[], 'arrival_seconds':arrival, 'variant':'synthetic', 'needsGoodsReceipt':True})
        else:
            c=selected[i]; attributes=c['attributes']; events=c['events']
            amount=attributes.get(cfg['amount_attribute'])
            if amount is None: amount=next((e.get(cfg['amount_attribute']) for e in events if e.get(cfg['amount_attribute']) is not None), 0)
            timestamp=events[0].get('time:timestamp') if events else None
            if not origin: arrival+=rng.expovariate(6/3600)
            variant=attributes.get('Item Category', attributes.get('case:ApplicationType','unknown'))
            mode={'3-way match, invoice before GR':'3way-before','3-way match, invoice after GR':'3way-after','2-way match':'2way','Consignment':'consignment'}.get(variant,'3way-after')
            names={e.get('concept:name') for e in events}
            outcome='denied' if 'A_Denied' in names else 'cancelled' if 'A_Cancelled' in names else 'pending' if 'A_Pending' in names else 'pending'
            inputs.append({**c, 'amount':float(amount or 0), 'arrival_seconds':(datetime.fromisoformat(timestamp)-origin).total_seconds() if origin and timestamp else arrival,
                           'variant':variant, 'matchingMode':mode, 'loanOutcome':outcome,
                           'outcome_assumption':'2017 observed terminal outcome used as replay input; missing terminal outcome defaults to pending' if dataset=='bpic2017' else '',
                           'needsGoodsReceipt':mode!='2way' if dataset=='bpic2019' else True})
    inputs.sort(key=lambda c:c['arrival_seconds'])
    if inputs:
        minimum=inputs[0]['arrival_seconds']
        for c in inputs: c['arrival_seconds']-=minimum
    return inputs, profile
