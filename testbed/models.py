"""Curated operational abstraction; discovered BPMN is an analysis artifact only."""
from pathlib import Path
from xml.sax.saxutils import escape
import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['validate', 'register', 'reserve', 'invoice', 'match', 'compliance', 'payment', 'dispatch', 'archive', 'finalize']


def mapping(dataset):
    return yaml.safe_load((ROOT / 'config' / f'{dataset}.yaml').read_text())


def build(dataset, scope, folder):
    cfg = mapping(dataset)
    pid = f'testbed_{dataset}_{scope}'
    decision = f'review_{scope}'
    message = f'confirmation_{scope}'
    parts = [f'''<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
 xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
 xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
 targetNamespace="https://testbed.local/wp1" id="Definitions_{scope}">
 <bpmn:message id="confirmation" name="{message}"><bpmn:extensionElements><zeebe:subscription correlationKey="= correlationKey"/></bpmn:extensionElements></bpmn:message>
 <bpmn:error id="external_error" errorCode="EXTERNAL_ERROR"/>
 <bpmn:process id="{pid}" name="{cfg['process']}" isExecutable="true">
 <bpmn:startEvent id="start"/><bpmn:subProcess id="work" name="Operational process">
 <bpmn:startEvent id="inner_start"/>
''']
    nodes = [('inner_start', 'startEvent')]
    flows = []
    def flow(a, b, condition=None):
        fid = f'f{len(flows)}'
        flows.append((fid, a, b))
        content = f'<bpmn:conditionExpression xsi:type="bpmn:tFormalExpression" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{escape(condition)}</bpmn:conditionExpression>' if condition else ''
        parts.append(f'<bpmn:sequenceFlow id="{fid}" sourceRef="{a}" targetRef="{b}">{content}</bpmn:sequenceFlow>')
        return fid
    def service(step):
        parts.append(f'<bpmn:serviceTask id="{step}" name="{escape(cfg["activities"][step])}"><bpmn:extensionElements><zeebe:taskDefinition type="{scope}.{step}" retries="3"/></bpmn:extensionElements></bpmn:serviceTask>')
        nodes.append((step, 'serviceTask'))
    for step in STEPS:
        service(step)
    parts.append(f'<bpmn:businessRuleTask id="decision" name="Review decision"><bpmn:extensionElements><zeebe:calledDecision decisionId="{decision}" resultVariable="reviewRequired"/></bpmn:extensionElements></bpmn:businessRuleTask>')
    nodes.append(('decision', 'businessRuleTask'))
    parts.append('<bpmn:exclusiveGateway id="choice" default="skip_review"/>')
    nodes.append(('choice', 'exclusiveGateway'))
    if dataset=='bpic2019':
        for nid in ['variant_route','receipt_route','invoice_route']:
            parts.append(f'<bpmn:exclusiveGateway id="{nid}"/>'); nodes.append((nid,'exclusiveGateway'))
    if dataset=='bpic2017':
        parts.append('<bpmn:exclusiveGateway id="loan_outcome"/>'); nodes.append(('loan_outcome','exclusiveGateway'))
    for step in ['review', 'escalation']:
        parts.append(f'<bpmn:userTask id="{step}" name="{escape(cfg["activities"][step])}"><bpmn:extensionElements><zeebe:userTask/><zeebe:assignmentDefinition candidateGroups="operations"/></bpmn:extensionElements></bpmn:userTask>')
        nodes.append((step, 'userTask'))
    for step in ['validate','match','reserve','compliance','payment']:
        parts.append(f'<bpmn:boundaryEvent id="{step}_error" attachedToRef="{step}"><bpmn:errorEventDefinition errorRef="external_error"/></bpmn:boundaryEvent>')
        nodes.append((f'{step}_error', 'boundaryEvent'))
    parts.append('<bpmn:exclusiveGateway id="resume"/>')
    nodes.append(('resume','exclusiveGateway'))
    parts.append('<bpmn:intermediateCatchEvent id="confirmation_wait" name="External confirmation"><bpmn:messageEventDefinition messageRef="confirmation"/></bpmn:intermediateCatchEvent><bpmn:endEvent id="inner_end"/>')
    nodes += [('confirmation_wait', 'intermediateCatchEvent'), ('inner_end', 'endEvent')]
    flow('inner_start', 'validate'); flow('validate', 'register'); flow('register', 'decision'); flow('decision', 'choice')
    flow('choice', 'review', '= reviewRequired');
    target='variant_route' if dataset=='bpic2019' else 'reserve'
    parts.append(f'<bpmn:sequenceFlow id="skip_review" sourceRef="choice" targetRef="{target}"/>')
    flows.append(('skip_review', 'choice', target))
    flow('review',target)
    if dataset=='bpic2019':
        flow('variant_route','invoice','= matchingMode = "3way-before" or matchingMode = "2way"')
        flow('variant_route','reserve','= matchingMode = "3way-after" or matchingMode = "consignment"')
        flow('reserve','receipt_route')
        flow('receipt_route','invoice','= matchingMode = "3way-after"')
        flow('receipt_route','match','= matchingMode != "3way-after"')
        flow('invoice','invoice_route')
        flow('invoice_route','reserve','= matchingMode = "3way-before"')
        flow('invoice_route','match','= matchingMode != "3way-before"')
    else:
        flow('reserve','invoice'); flow('invoice','match')
    if dataset=='bpic2017':
        flow('match','loan_outcome')
        flow('loan_outcome','compliance','= loanOutcome = "pending"')
        flow('loan_outcome','finalize','= loanOutcome != "pending"')
    else: flow('match','compliance')
    flow('compliance','payment'); flow('payment','dispatch')
    for step in ['validate','match','reserve','compliance','payment']:
        flow(f'{step}_error','escalation')
        flow('resume',step,f'= resumeStep = "{step}"')
    flow('escalation','resume')
    flow('dispatch', 'confirmation_wait'); flow('confirmation_wait', 'archive'); flow('archive', 'finalize'); flow('finalize', 'inner_end')
    parts.append('''</bpmn:subProcess>
<bpmn:boundaryEvent id="sla_timer" attachedToRef="work" cancelActivity="false"><bpmn:timerEventDefinition><bpmn:timeDuration>= slaTimer</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>
''')
    parts.append(f'<bpmn:serviceTask id="sla" name="SLA warning monitor"><bpmn:extensionElements><zeebe:taskDefinition type="{scope}.sla"/></bpmn:extensionElements></bpmn:serviceTask><bpmn:endEvent id="sla_end"/><bpmn:endEvent id="end"/>')
    flow('start', 'work'); flow('work', 'end'); flow('sla_timer', 'sla'); flow('sla', 'sla_end')
    parts.append('</bpmn:process>')
    # Explicit DI for bpmn-js; expanded subprocess with its actual executable elements.
    parts.append(f'<bpmndi:BPMNDiagram id="diagram"><bpmndi:BPMNPlane id="plane" bpmnElement="{pid}">')
    coords = {'start': (30, 180, 36, 36), 'work': (100, 60, 2100, 400), 'end': (2250, 180, 36, 36),
              'sla_timer': (140, 442, 36, 36), 'sla': (220, 500, 120, 60), 'sla_end': (390, 510, 36, 36)}
    for i, (nid, kind) in enumerate(nodes):
        coords[nid] = (140 + (i % 12) * 160, 120 + (i // 12) * 180, 110, 60) if kind.endswith('Task') else (140 + (i % 12) * 160, 130 + (i // 12) * 180, 36, 36)
    for nid, (x,y,w,h) in coords.items():
        expanded = ' isExpanded="true"' if nid == 'work' else ''
        parts.append(f'<bpmndi:BPMNShape id="shape_{nid}" bpmnElement="{nid}"{expanded}><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}"/></bpmndi:BPMNShape>')
    for fid,a,b in flows:
        x,y,w,h=coords[a]; xx,yy,ww,hh=coords[b]
        parts.append(f'<bpmndi:BPMNEdge id="edge_{fid}" bpmnElement="{fid}"><di:waypoint x="{x+w}" y="{y+h/2}"/><di:waypoint x="{xx}" y="{yy+hh/2}"/></bpmndi:BPMNEdge>')
    parts.append('</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    bpmn = folder / f'{dataset}.bpmn'; bpmn.write_text('\n'.join(parts), encoding='utf-8')
    dmn = folder / 'review.dmn'
    dmn.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="dmn_{scope}" name="Experiment review policy" namespace="https://testbed.local/wp1">
<decision id="{decision}" name="Review policy"><decisionTable id="table" hitPolicy="FIRST">
<input id="input"><inputExpression id="expr" typeRef="boolean"><text>forceReview or amount &gt; 8000</text></inputExpression></input>
<output id="output" name="required" typeRef="boolean"/>
<rule id="yes"><inputEntry id="i1"><text>true</text></inputEntry><outputEntry id="o1"><text>true</text></outputEntry></rule>
<rule id="no"><inputEntry id="i2"><text>-</text></inputEntry><outputEntry id="o2"><text>false</text></outputEntry></rule>
</decisionTable></decision></definitions>''', encoding='utf-8')
    return {'bpmn': bpmn, 'dmn': dmn, 'process_id': pid, 'message': message, 'scope': scope}
