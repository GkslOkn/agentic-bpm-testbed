'use strict';
const pages = ['Camunda environment','BPMN process','Mock systems & workers','Workload configuration','Disruption injector','L0 adaptation interface','Run & monitoring','Event logs','Strategy comparisons'];
const labels = ['No adaptation','Retry only','Retry + fallback','Full L0 rule set','Escalate everything'];
const query = new URLSearchParams(location.search);
const Evidence = window.ExecutionEvidence;
let page = Math.max(0,Math.min(8,Number(query.get('page')) || 0));
let config = null, selected = query.get('run'), record = null, viewer = null;
let viewerPath = '', viewerReady = null, renderToken = 0, refreshing = false, shellKey = '';
let inspection = null, caseSelection = '', activitySelection = '', incidentFilter = 'all';
let eventFilter = 'all', casePage = 0, eventPage = 0, incidentPage = 0, requestPage = 0, newestFirst = true;
let histories = new Map(), taskRecords = [], tasksRun = '', exportWarning = '';
let advanced = {acceleration:10000000,task_mean_seconds:60,failure_probability:0,human_delay_seconds:3600,resource_capacity:2,sla_seconds:172800,human_mode:'batch'};
const $ = id => document.getElementById(id);
const escape = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finalRun = r => r && !['preparing','running'].includes(r.status);
const show = value => value === undefined || value === null || value === '' ? 'Not recorded' : String(value);
const time = value => value ? String(value).replace('T',' ').replace('+00:00',' UTC') : 'Not recorded';
async function api(path, body) {
  const response = await fetch('/api/' + path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || response.statusText));
  return data;
}
function settings() { return {dataset:$('dataset').value,scenario:$('scenario').value,strategy:$('strategy').value,seed:+$('seed').value,instances:+$('instances').value,...advanced}; }
function card(title, body) { return '<section class="card"><h3>' + escape(title) + '</h3>' + body + '</section>'; }
function table(rows, keys) {
  return '<div class="scroll"><table><thead><tr>' + keys.map(k=>'<th>'+escape(k)+'</th>').join('') +
    '</tr></thead><tbody>' + rows.map(r=>'<tr>'+keys.map(k=>'<td>'+escape(typeof r[k]==='object'?JSON.stringify(r[k]):r[k])+'</td>').join('')+'</tr>').join('') + '</tbody></table></div>';
}
function badge(value, tone='neutral') { return '<span class="badge '+tone+'">'+escape(value)+'</span>'; }
function linkCase(cid) { return '<button class="text-button" data-case="'+escape(cid)+'">'+escape(cid)+'</button>'; }
function linkActivity(name) { return '<button class="text-button" data-activity="'+escape(name)+'">'+escape(name)+'</button>'; }
function navigation() {
  $('nav').innerHTML = pages.map((p,i)=>'<button class="'+(i===page?'on':'')+'" data-page="'+i+'">'+(i+1)+'. '+p+'</button>').join('');
  $('nav').querySelectorAll('button').forEach(b=>b.onclick=()=>{ page=+b.dataset.page; shellKey=''; render(); });
}
function field(key,label,values) {
  return '<div><label>'+escape(label)+'</label>'+(values?'<select data-setting="'+key+'">'+values.map(v=>'<option '+(advanced[key]===v?'selected':'')+'>'+escape(v)+'</option>').join('')+'</select>':'<input data-setting="'+key+'" type="number" value="'+escape(advanced[key])+'">')+'</div>';
}
function downloads() {
  if (!record) return '';
  return '<div class="exports">'+['events.csv','events.xes','events.ocel.json','metadata.json','inputs.json','configuration.json','validation.json'].map(n=>
    '<a href="/api/runs/'+encodeURIComponent(selected)+'/files/'+n+'">'+escape(n)+'</a>').join(' ')+'</div>';
}
function history() { return histories.get(selected) || {events:[],full:false}; }
async function receiveHistory(next) {
  let h = histories.get(next.run_id);
  if (!h) {
    if (histories.size >= 3) histories.delete(histories.keys().next().value);
    h = {events:[],full:false,retryAt:0,loading:false};
    histories.set(next.run_id,h);
  }
  h.events = Evidence.mergeHistory(h.events, next.events || []);
  if (finalRun(next) && !h.full && !h.loading && Date.now() >= h.retryAt) {
    h.loading = true;
    try {
      const response = await fetch('/api/runs/'+encodeURIComponent(next.run_id)+'/files/events.csv');
      if (!response.ok) throw Error('CSV export unavailable ('+response.status+').');
      const events = Evidence.parseCSV(await response.text());
      if (events.some(e=>e.run_id!==next.run_id)) throw Error('CSV run identity does not match selected run.');
      h.events = Evidence.mergeHistory(events,next.events || []); h.full = true; h.warning = '';
    } catch (e) { h.warning = e.message; h.retryAt = Date.now()+15000; }
    finally { h.loading = false; }
  }
}
function coverage() {
  const h=history(), contiguous=Evidence.contiguous(h.events);
  const source=h.full?'Exported history loaded: '+h.events.length+' events.':
    contiguous?'Live observed history: '+h.events.length+' events through ID '+(h.events.at(-1)?.id || 0)+'.':
    'Partial live history: '+h.events.length+' observed events; earlier records or polling gaps are missing.';
  return '<div class="evidence-note">'+escape(source)+(h.warning?' '+escape(h.warning):'')+
    ' The API supplies at most 300 recent events/requests. Completed runs load their CSV automatically. Unobserved states and exact error messages remain unknown.</div>';
}
function pager(name, count, index, size) {
  const max=Math.max(0,Math.ceil(count/size)-1), current=Math.min(index,max);
  return '<div class="pager"><span>'+count+' records'+(count?' | '+(current*size+1)+'-'+Math.min(count,(current+1)*size):'')+
    '</span><button data-pager="'+name+'" data-delta="-1" '+(current===0?'disabled':'')+'>Previous</button>'+
    '<button data-pager="'+name+'" data-delta="1" '+(current>=max?'disabled':'')+'>Next</button></div>';
}
function kpis() {
  const s=inspection.summary, m=record.metrics || {};
  const count=(label,value,note,tone='')=>'<div class="'+tone+'"><b>'+escape(value)+'</b><span>'+escape(label)+'</span><small>'+escape(note)+'</small></div>';
  return '<div class="kpi research-kpi">'+
    count('Total instances',s.total ?? 'Unknown','Requested by recorded run')+
    count('Started',s.started,'Recorded process instances')+
    count('Completed',s.completed,'Backend completion count','good')+
    count('Successful executions',s.completed,'Success here means completed execution; not SLA/compliance correctness','good')+
    count('Failed / stuck instances',s.stuck,'Recorded stuck cases; run errors and unstarted cases shown separately',s.stuck?'bad':'')+
    count('Running',s.running,'Last recorded case status')+
    count('Adaptation requests',s.requests,m.adaptation_requests===undefined?'Observed requests; may be partial':'Backend total')+
    '</div><div class="run-progress"><progress max="'+Math.max(1,s.total || 1)+'" value="'+s.completed+'" aria-label="Completed instances"></progress>'+
    '<span>'+s.completed+' / '+escape(s.total ?? '?')+' completed; '+s.unstarted+' not started</span></div>'+
    '<p class="muted">Recorded oracle outcomes: '+s.accepted+' success, '+s.rejected+' failure, '+s.pending+
    ' pending in available request history. A failed retry can precede successful recovery. SLA violations: '+
    escape(m.sla_violations ?? 'not finalised')+'; compliance violations: '+escape(m.compliance_violations ?? 'not finalised')+
    '. Cases with recorded task recovery: '+s.recoveredCases+'.</p>'+
    (record.error?'<div class="evidence-note error">Run-level error: '+escape(record.error)+
      '. A run error does not identify a BPMN failure location.</div>':'');
}
function diagramCard() {
  return card('Executable BPMN and recorded activity evidence',
    '<div class="row viewer-tools"><button data-zoom="1.25" aria-label="Zoom in">Zoom +</button><button data-zoom="0.8" aria-label="Zoom out">Zoom -</button><button data-fit>Fit diagram</button><button data-clear-activity>Clear activity selection</button>'+
    '<span class="muted">Click an activity to inspect its records. Pan and zoom stay unchanged during polling.</span></div>'+
    '<div class="legend">'+badge('Completed','success')+badge('Last observed active','active')+
    badge('Error / blocking incident','failure')+badge('Adaptation recorded','adapted')+badge('No event evidence','neutral')+'</div>'+
    '<div id="viewer" aria-label="Executable BPMN viewer"></div>'+
    '<p class="muted">Markers may coexist: an activity can have historical errors and later completion. Gateways, DMN decisions and message catches stay unmarked unless directly supported by records.</p>');
}
function inspectorShell() {
  return '<div id="run-context"></div><div id="run-kpis"></div>'+
    '<div class="card"><div class="row"><div class="instance-control"><label for="case-select">Inspect instance</label><select id="case-select"></select></div>'+
    '<button data-clear-case>All instances</button><span id="case-summary"></span></div></div>'+
    diagramCard()+'<div id="activity-detail"></div>'+
    '<div class="inspection-grid"><section class="card"><h3>Recorded failures, blocking incidents and conditions</h3>'+
    '<label for="incident-filter">Show</label><select id="incident-filter">'+
    [['all','All incidents and conditions'],['failures','Task errors / blocking incidents'],['recovered','Later task completion recorded'],['stuck','Instances recorded stuck'],['conditions','SLA / rule-change conditions']].map(([v,l])=>'<option value="'+v+'">'+l+'</option>').join('')+
    '</select><div id="incident-table"></div></section><section class="card"><h3>Adaptation actions and oracle outcomes</h3><div id="adaptation-table"></div></section></div>'+
    '<section class="card"><h3>Process instances</h3><div id="case-table"></div></section>'+
    '<section class="card"><h3 id="history-heading">Actual event history</h3><div class="row"><div><label for="event-filter">Events</label><select id="event-filter">'+
    [['all','All recorded events'],['error','Explicit task errors'],['adaptation','Adaptation requests'],['complete','Completions'],['start','Task starts']].map(([v,l])=>'<option value="'+v+'">'+l+'</option>').join('')+
    '</select></div><button data-order>Toggle chronological / newest first</button></div><div id="event-table"></div></section>'+
    card('Native human tasks','<div id="tasks"></div>');
}
function selectedEvents() {
  let events=history().events;
  if (caseSelection) events=events.filter(e=>e.case_id===caseSelection);
  if (activitySelection && viewer) events=events.filter(e=>elementForEvent(e)?.id===activitySelection);
  return events;
}
function elementForEvent(e) {
  if (!viewer) return null;
  const registry=viewer.get('elementRegistry'), exact=registry.getAll().filter(el=>!el.labelTarget && !el.waypoints && el.businessObject?.name===e.activity);
  if (exact.length===1) return exact[0];
  // Request.element is an explicit recorded BPMN identifier. Scope it to the source activity;
  // escalation records themselves must not be mapped onto the failing service task.
  const a=inspection?.adaptations.get(e.request_id);
  if (e.lifecycle==='adaptation' && a?.request.element) return registry.get(a.request.element) || null;
  if (e.activity==='Boundary error caught' && a) {
    const task=registry.get(a.request.element) || registry.getAll().find(el=>!el.labelTarget && el.businessObject?.name===a.activity);
    const boundary=task && registry.get(task.id+'_error');
    return boundary?.businessObject?.attachedToRef?.id===task.id?boundary:null;
  }
  return null;
}
function activityRows() {
  if (!viewer || !activitySelection) return [];
  return selectedEvents();
}
function updateActivity() {
  if (!$('activity-detail')) return;
  if (!activitySelection || !viewer) {
    $('activity-detail').innerHTML=card('Activity inspection','<p class="muted">Select a BPMN activity or click an activity name in a table. Records will be scoped to the selected instance, if any.</p>');
    return;
  }
  const element=viewer.get('elementRegistry').get(activitySelection);
  const rows=activityRows(), name=element?.businessObject?.name || activitySelection;
  $('activity-detail').innerHTML=card(name+' ['+activitySelection+']',
    '<p>'+badge(rows.filter(e=>e.lifecycle==='complete').length+' completions','success')+' '+
    badge(rows.filter(e=>e.lifecycle==='error').length+' explicit errors','failure')+' '+
    badge(rows.filter(e=>e.lifecycle==='adaptation').length+' adaptation requests','adapted')+'</p>'+
    '<p class="muted">'+(rows.length?'Counts describe the available recorded history.':'No direct execution event is available for this element; its state is unknown.')+'</p>'+
    (rows.length?eventTable(rows.slice(-20).reverse()):''));
}
function eventTable(events) {
  return '<div class="scroll"><table><thead><tr><th>Time (UTC)</th><th>Case</th><th>Activity</th><th>Lifecycle</th><th>Resource</th><th>Disruption</th><th>Action</th><th>Outcome</th><th>Job/task key</th></tr></thead><tbody>'+
    events.map(e=>'<tr class="'+(e.lifecycle==='error'?'event-error':e.lifecycle==='adaptation'?'event-adaptation':'')+'"><td>'+escape(time(e.timestamp))+
      '</td><td>'+linkCase(e.case_id)+'</td><td>'+linkActivity(e.activity)+'</td><td>'+escape(e.lifecycle)+'</td><td>'+escape(show(e.resource))+'</td><td>'+escape(show(e.disruption))+
      '</td><td>'+escape(show(e.intervention))+'</td><td>'+escape(show(e.outcome))+'</td><td>'+escape(show(e.job_key))+'</td></tr>').join('')+'</tbody></table></div>';
}
function updateInspection() {
  if (!record || !$('run-context')) return;
  const h=history(); inspection=Evidence.analyse(record,h.events);
  $('run-context').innerHTML='<p class="run-caption">Viewing run <strong>'+escape(record.run_id)+'</strong> | '+escape(record.config?.dataset || 'Unknown dataset')+
    ' | '+escape(record.config?.strategy || 'Unknown strategy')+' | '+badge(record.status)+'</p><p class="muted">Controls above configure the next experiment; this view uses the selected run\'s recorded configuration.</p>'+coverage();
  $('run-kpis').innerHTML=kpis();
  const caseSelect=$('case-select'), cases=record.cases || [];
  caseSelect.innerHTML='<option value="">All instances</option>'+cases.map(c=>'<option value="'+escape(c.case_id)+'" '+(caseSelection===c.case_id?'selected':'')+'>'+
    escape(c.case_id+' | '+c.status+' | '+c.instance_key)+'</option>').join('');
  const chosen=inspection.cases.get(caseSelection);
  $('case-summary').innerHTML=chosen?badge(chosen.status,chosen.status==='stuck'?'failure':chosen.status==='completed'?'success':'active')+
    ' Camunda instance: <code>'+escape(chosen.instance_key)+'</code>':'Aggregate view of recorded instances';
  let incidents=inspection.incidents.filter(i=>!caseSelection || i.case_id===caseSelection);
  if (incidentFilter==='failures') incidents=incidents.filter(i=>i.blocking || i.explicitError);
  if (incidentFilter==='recovered') incidents=incidents.filter(i=>i.recovered);
  if (incidentFilter==='stuck') incidents=incidents.filter(i=>i.instanceStatus==='stuck');
  if (incidentFilter==='conditions') incidents=incidents.filter(i=>!i.blocking && !i.explicitError);
  incidents.reverse(); incidentPage=Math.min(incidentPage,Math.max(0,Math.ceil(incidents.length/20)-1));
  $('incident-filter').value=incidentFilter;
  $('incident-table').innerHTML=incidents.length?'<div class="scroll"><table><thead><tr><th>Case / instance</th><th>BPMN activity</th><th>Recorded type / reason</th><th>Exact error message</th><th>Timestamp (UTC)</th><th>Action</th><th>What happened afterward</th></tr></thead><tbody>'+
    incidents.slice(incidentPage*20,(incidentPage+1)*20).map(i=>'<tr><td>'+linkCase(i.case_id)+'<small>'+escape(show(i.instance_key))+'</small></td><td>'+linkActivity(i.activity)+
      '<small>'+escape(i.explicitError?'Explicit error event':i.category)+'</small></td><td>'+escape(i.type)+'</td><td>'+escape(i.message)+'</td><td>'+escape(time(i.timestamp))+
      '</td><td>'+escape(i.action)+'</td><td>'+badge(!i.blocking && !i.explicitError?'Process condition':i.recovered?'Later completion':'No task recovery record',i.recovered?'success':'neutral')+
      '<small>'+escape(i.recovery)+'; instance: '+escape(i.instanceStatus)+'</small></td></tr>').join('')+'</tbody></table></div>'+pager('incidents',incidents.length,incidentPage,20):
      '<p class="muted">No matching incident is present in the available history.</p>';
  let requests=inspection.requests.filter(a=>!caseSelection || a.case_id===caseSelection).sort((a,b)=>String(b.timestamp || b.request.timestamp).localeCompare(String(a.timestamp || a.request.timestamp)));
  requestPage=Math.min(requestPage,Math.max(0,Math.ceil(requests.length/20)-1));
  $('adaptation-table').innerHTML=requests.length?'<div class="scroll"><table><thead><tr><th>Case</th><th>Activity / element</th><th>Action</th><th>Recorded oracle outcome</th></tr></thead><tbody>'+
    requests.slice(requestPage*20,(requestPage+1)*20).map(a=>'<tr><td>'+linkCase(a.case_id)+'</td><td>'+linkActivity(a.activity || a.request.element || 'Not recorded')+'</td><td>'+escape(show(a.response.action))+
    '</td><td>'+badge(show(a.outcome),a.outcome==='success'?'success':a.outcome==='failure'?'failure':'neutral')+'</td></tr>').join('')+'</tbody></table></div>'+
    pager('requests',requests.length,requestPage,20)+'<p class="muted">Oracle failure is separate from task recovery and instance completion.</p>':
    '<p class="muted">No adaptation request recorded in available history.</p>';
  casePage=Math.min(casePage,Math.max(0,Math.ceil(cases.length/20)-1));
  $('case-table').innerHTML='<div class="scroll"><table><thead><tr><th>Case</th><th>Camunda instance</th><th>Recorded status</th><th>Observed incidents</th><th>Recovery evidence</th><th>Compliance check flag</th></tr></thead><tbody>'+
    cases.slice(casePage*20,(casePage+1)*20).map(c=>{
      const related=inspection.incidents.filter(i=>i.case_id===c.case_id && (i.blocking || i.explicitError));
      return '<tr class="'+(c.case_id===caseSelection?'selected-row':'')+'"><td>'+linkCase(c.case_id)+'</td><td>'+escape(c.instance_key)+'</td><td>'+badge(c.status,c.status==='completed'?'success':c.status==='stuck'?'failure':'active')+
        '</td><td>'+related.length+'</td><td>'+escape(related.some(i=>i.recovered)?'Later task completion recorded':'No recovery evidence / not applicable')+
        '</td><td>'+escape(c.compliance===1?'Checked':c.compliance===0?'Not checked':'Not recorded')+'</td></tr>';
    }).join('')+'</tbody></table></div>'+pager('cases',cases.length,casePage,20);
  let events=selectedEvents().filter(e=>eventFilter==='all' || e.lifecycle===eventFilter);
  if (newestFirst) events=[...events].reverse();
  eventPage=Math.min(eventPage,Math.max(0,Math.ceil(events.length/50)-1));
  $('event-filter').value=eventFilter;
  $('history-heading').textContent=caseSelection?'Execution history: '+caseSelection:'Actual event history';
  $('event-table').innerHTML=eventTable(events.slice(eventPage*50,(eventPage+1)*50))+pager('events',events.length,eventPage,50)+
    '<p class="muted">'+(newestFirst?'Newest first.':'Chronological order.')+' Activity and instance filters apply. Missing records are not inferred.</p>';
  updateTasks(); updateMarkers(); updateActivity();
}
function updateTasks() {
  if (!$('tasks')) return;
  $('tasks').innerHTML=tasksRun!==selected?'<p class="muted">Native task status is unavailable.</p>':
    taskRecords.length?taskRecords.map(t=>'<p>'+escape(t.name || t.elementId)+' <code>'+escape(t.userTaskKey)+'</code> '+
    '<button data-task="'+escape(t.userTaskKey)+'">Approve</button></p>').join(''):'No active native user tasks.';
}
async function ensureViewer(path) {
  if (viewer && viewerPath===path) return viewerReady;
  if (viewer) viewer.destroy();
  if (typeof BpmnJS==='undefined') throw Error('Local bpmn-js asset missing');
  const diagram=new BpmnJS({container:'#viewer'}); viewer=diagram; viewerPath=path;
  viewerReady=(async()=>{
    const response=await fetch(path); if (!response.ok) throw Error('Executable BPMN unavailable ('+response.status+').');
    await diagram.importXML(await response.text());
    if (viewer!==diagram) return;
    diagram.get('canvas').zoom('fit-viewport');
    diagram.get('eventBus').on('element.click',event=>{
      if (event.element.labelTarget) activitySelection=event.element.labelTarget.id;
      else if (!event.element.waypoints) activitySelection=event.element.id;
      eventPage=0; updateInspection();
    });
  })();
  return viewerReady;
}
function updateMarkers() {
  if (!viewer || !inspection) return;
  const canvas=viewer.get('canvas'), overlays=viewer.get('overlays'), registry=viewer.get('elementRegistry');
  overlays.clear();
  for (const el of registry.getAll()) {
    if (el.labelTarget || el.waypoints) continue;
    for (const name of ['evidence-complete','evidence-active','evidence-failed','evidence-adapted','evidence-selected']) canvas.removeMarker(el.id,name);
  }
  const filtered=caseSelection?history().events.filter(e=>e.case_id===caseSelection):history().events;
  const scoped=Evidence.analyse({...record,cases:record.cases,adaptations:record.adaptations},filtered);
  const counts=new Map();
  for (const e of filtered) {
    const el=elementForEvent(e); if (!el) continue;
    if (!counts.has(el.id)) counts.set(el.id,{completed:0,errors:0,adapted:0,active:0,unresolved:0,recovered:0});
    const c=counts.get(el.id);
    if (e.lifecycle==='complete') c.completed++;
    if (e.lifecycle==='error') c.errors++;
    if (e.lifecycle==='adaptation' && e.intervention && e.intervention!=='none') c.adapted++;
  }
  for (const [name,s] of scoped.stats) {
    const el=registry.getAll().find(e=>!e.labelTarget && !e.waypoints && e.businessObject?.name===name);
    if (!el) continue;
    if (!counts.has(el.id)) counts.set(el.id,{completed:0,errors:0,adapted:0});
    Object.assign(counts.get(el.id),{active:s.active,unresolved:s.unresolved,recovered:s.recovered,incidents:s.incidents});
  }
  const nativeCounts=new Map();
  for (const task of tasksRun===selected?taskRecords:[]) {
    if (caseSelection && inspection.cases.get(caseSelection)?.instance_key!==String(task.processInstanceKey)) continue;
    const id=task.elementId || task.flowNodeId;
    if (!registry.get(id)) continue;
    if (!nativeCounts.has(id)) nativeCounts.set(id,new Set());
    nativeCounts.get(id).add(String(task.userTaskKey));
  }
  for (const [id,keys] of nativeCounts) {
    if (!counts.has(id)) counts.set(id,{completed:0,errors:0,adapted:0});
    counts.get(id).active=Math.max(keys.size,counts.get(id).active || 0);
  }
  for (const [id,c] of counts) {
    if (c.completed) canvas.addMarker(id,'evidence-complete');
    if (c.adapted) canvas.addMarker(id,'evidence-adapted');
    if (c.errors || c.incidents) canvas.addMarker(id,'evidence-failed');
    if (c.active) canvas.addMarker(id,'evidence-active');
    const badgeNode=document.createElement('button'); badgeNode.className='activity-count';
    const text=[c.completed?'C:'+c.completed:'',c.errors?'E:'+c.errors:'',c.incidents?'I:'+c.incidents:'',c.adapted?'A:'+c.adapted:'',c.active?'Live:'+c.active:''].filter(Boolean).join(' ');
    badgeNode.textContent=text; badgeNode.title='C=completion events; E=explicit errors; I=blocking incidents; A=adaptation actions; Live=last observed active/waiting. Historical errors remain visible after recovery.';
    badgeNode.onclick=()=>{activitySelection=id;eventPage=0;updateInspection();};
    overlays.add(id,{position:{bottom:-8,left:0},html:badgeNode});
  }
  if (activitySelection && registry.get(activitySelection)) canvas.addMarker(activitySelection,'evidence-selected');
}
function chooseActivity(name) {
  if (!viewer) return;
  const el=viewer.get('elementRegistry').get(name) || viewer.get('elementRegistry').getAll().find(e=>!e.labelTarget && !e.waypoints && e.businessObject?.name===name);
  if (!el) { $('notice').textContent='No unique recorded BPMN element is available for "'+name+'".'; return; }
  activitySelection=el.id; eventPage=0; updateInspection();
}
function preserveUpdate(update) {
  const active=document.activeElement, id=active?.id, selectionStart=active?.selectionStart;
  const scrolls=[...document.querySelectorAll('#content .scroll')].map(el=>el.scrollTop);
  update();
  document.querySelectorAll('#content .scroll').forEach((el,i)=>{el.scrollTop=scrolls[i] || 0;});
  if (id && $(id)) { $(id).focus({preventScroll:true}); if (selectionStart!=null && $(id).setSelectionRange) $(id).setSelectionRange(selectionStart,selectionStart); }
}
async function render() {
  navigation(); const token=++renderToken, content=$('content');
  const hasRun=!!record?.config, key=page+'|'+selected+'|'+hasRun;
  const inspector=hasRun && (page===1 || page===6);
  if (inspector && shellKey===key && $('viewer')) {
    preserveUpdate(updateInspection); return;
  }
  if (viewer) { viewer.destroy(); viewer=null; viewerPath=''; viewerReady=null; }
  shellKey=key; content.innerHTML='<h2>'+escape(pages[page])+'</h2>';
  try {
    if (inspector) {
      content.insertAdjacentHTML('beforeend',inspectorShell());
      updateInspection();
      const model=record.config.dataset;
      await ensureViewer('/api/runs/'+encodeURIComponent(selected)+'/files/'+encodeURIComponent(model)+'.bpmn');
      if (token===renderToken) updateInspection();
    } else if (page===0) {
      const env=await api('environment'); if (token!==renderToken) return;
      content.innerHTML+=card('Running engine','<p><a target="_blank" rel="noopener" href="'+escape(env.operate)+'">Operate</a> | <a target="_blank" rel="noopener" href="'+escape(env.tasklist)+'">Tasklist</a> | demo / demo</p><pre>'+escape(JSON.stringify(env.topology,null,2))+'</pre><p>Installed images are pinned by digest in the existing Compose override.</p>');
    } else if (page===1) {
      content.innerHTML+=diagramCard()+card('Execution evidence','Select a recorded run to inspect activity state. This is the configured model preview.');
      await ensureViewer('/api/models/'+encodeURIComponent($('dataset').value));
    } else if (page===2) {
      content.innerHTML+=card('Per-run mock systems','<p>SQLite inventory, customer records, primary and backup payment transactions, carrier confirmation outbox and resource assignments. Effects use case/task idempotency keys.</p><div class="row">'+field('task_mean_seconds','Synthetic task mean (seconds)')+field('failure_probability','Seeded service failure probability')+field('human_delay_seconds','Batch human delay (model seconds)')+field('resource_capacity','Worker pool capacity')+'</div>');
    } else if (page===3) {
      content.innerHTML+=card('Workload and timing','<div class="row">'+field('acceleration','Model seconds per wall second')+field('sla_seconds','SLA (model seconds)')+field('human_mode','Human mode',['batch','manual'])+'</div><p>BPIC 2019 preserves source attributes, observed arrivals and inter-event timing proxies. BPIC 2017 CSV lacks timestamps: seeded synthetic arrivals and durations. Synthetic mode uses Poisson arrivals. No historical decision is treated as an oracle.</p><button id="profile">Load dataset profile</button><pre id="profiledata"></pre>');
      $('profile').onclick=async()=>{try{$('profiledata').textContent=JSON.stringify(await api('profiles/'+$('dataset').value),null,2);}catch(e){if($('profiledata'))$('profiledata').textContent=e.message;}};
    } else if (page===4) {
      content.innerHTML+=card('YAML scenarios and independent oracle','<pre>'+escape(JSON.stringify({scenario:config.scenarios[$('scenario').value],targets:config.mappings[$('dataset').value].disruption_targets,oracle:config.oracle},null,2))+'</pre>');
    } else if (page===5) {
      content.innerHTML+=card('Handler contract','<p>Monitor requests include case state, trigger, element, allowed actions and retry attempt. L0 returns a structured action and parameters. The existing handler executes real retries, fallback, human escalation, reassignment, prioritisation and rule updates.</p><pre>'+escape(JSON.stringify(record?.adaptations?.slice(0,3) || {request:{request_id:'...',case_id:'...',trigger:'incident',element:'payment',allowed_actions:['retry','fallback','escalate']},response:{request_id:'...',action:'fallback',handler:'L0-rules'}},null,2))+'</pre>');
    } else if (page===6) {
      content.innerHTML+=card('Monitoring',selected?'Run preparation is in progress; execution records will appear when available.':'Start an experiment or select a recorded run.');
    } else if (page===7) {
      if (record) {
        const info={...record,events:undefined,adaptations:undefined,cases:undefined};
        content.innerHTML+=card('Exports and reproducibility',downloads()+'<pre>'+escape(JSON.stringify(info,null,2))+'</pre>')+coverage()+card('Independent events',eventTable(history().events.slice(-300).reverse())+'<p class="muted">Latest 300 of '+history().events.length+' loaded events. Use monitoring to filter or inspect an instance.</p>');
      } else content.innerHTML+=card('Event logs','No run selected.');
    } else if (page===8) {
      const comparisons=await api('comparisons'); if (token!==renderToken) return;
      if (!comparisons.length) content.innerHTML+=card('Comparable experiments','Run the five strategies with the same dataset, seed and scenario. Results will appear here.');
      for (const cmp of comparisons) {
        const rows=cmp.runs.map((r,i)=>({strategy:labels[i],...r.metrics,run_id:r.run_id}));
        content.innerHTML+=card('Comparison '+cmp.comparison_id,table(rows,['strategy','completed','stuck_cases','sla_violations','compliance_violations','adaptation_success_rate','additional_intervention_cost'])+
          rows.map(r=>'<p>'+escape(r.strategy)+' <progress max="1" value="'+escape(r.completion_rate)+'"></progress> '+(100*r.completion_rate).toFixed(1)+'% <button data-open-run="'+escape(r.run_id)+'">Inspect run</button></p>').join(''));
      }
    }
  } catch (e) {
    if (token===renderToken) { content.insertAdjacentHTML('beforeend',card('Error','<p class="error">'+escape(e.message)+'</p>')); shellKey=''; }
  }
}
async function refresh() {
  if (refreshing) return false;
  refreshing=true;
  const captured=selected;
  try {
    const runs=await api('runs');
    const html='<option value="">Select run</option>'+runs.map(r=>'<option value="'+escape(r.run_id)+'" '+(r.run_id===selected?'selected':'')+'>'+
      escape((r.config?.dataset || 'preparing')+' | '+(r.config?.strategy || '')+' | '+r.status+' | '+r.run_id.slice(0,8))+'</option>').join('');
    if ($('runs').innerHTML!==html) $('runs').innerHTML=html;
    if (captured) {
      const next=await api('runs/'+encodeURIComponent(captured));
      await receiveHistory(next);
      if (captured!==selected) return false;
      record=next; inspection=Evidence.analyse(record,history().events);
      $('summary').textContent=JSON.stringify({run_id:selected,status:record.status,metrics:record.metrics,error:record.error},null,2);
      $('status').textContent=record.status;
      try {
        const tasks=await api('runs/'+encodeURIComponent(captured)+'/tasks');
        if (captured===selected) { taskRecords=tasks; tasksRun=captured; }
      } catch (_) { if (captured===selected) tasksRun=''; }
    } else { record=null;inspection=null;taskRecords=[];tasksRun='';$('summary').textContent='';$('status').textContent='No run selected'; }
    return true;
  } catch (e) { $('notice').textContent=e.message; return false; }
  finally { refreshing=false; }
}
function selectRun(id) {
  selected=id || null; record=null; inspection=null; caseSelection=''; activitySelection='';
  casePage=eventPage=incidentPage=requestPage=0; tasksRun=''; shellKey='';
  const url=new URL(location.href); if (selected) url.searchParams.set('run',selected); else url.searchParams.delete('run');
  url.searchParams.set('page',String(page)); window.history.replaceState(null,'',url);
  refresh().then(render);
}
$('content').addEventListener('click',async event=>{
  const button=event.target.closest('button'); if (!button) return;
  try {
    if (button.hasAttribute('data-case')) {caseSelection=button.dataset.case;eventPage=incidentPage=requestPage=0;updateInspection();}
    if (button.hasAttribute('data-activity')) {
      if (!viewer) {page=6;shellKey='';await render();}
      chooseActivity(button.dataset.activity);
    }
    if (button.hasAttribute('data-clear-case')) {caseSelection='';eventPage=incidentPage=requestPage=0;updateInspection();}
    if (button.hasAttribute('data-clear-activity')) {activitySelection='';eventPage=0;updateInspection();}
    if (button.hasAttribute('data-fit') && viewer) viewer.get('canvas').zoom('fit-viewport');
    if (button.dataset.zoom && viewer) {const canvas=viewer.get('canvas');canvas.zoom(Math.max(.1,Math.min(3,canvas.zoom()*Number(button.dataset.zoom))));}
    if (button.hasAttribute('data-order')) {newestFirst=!newestFirst;eventPage=0;updateInspection();}
    if (button.dataset.pager) {
      const delta=Number(button.dataset.delta);
      if (button.dataset.pager==='cases') casePage+=delta;
      if (button.dataset.pager==='events') eventPage+=delta;
      if (button.dataset.pager==='incidents') incidentPage+=delta;
      if (button.dataset.pager==='requests') requestPage+=delta;
      updateInspection();
    }
    if (button.dataset.openRun) {page=6;selectRun(button.dataset.openRun);}
    if (button.dataset.task) {
      button.disabled=true;
      await api('runs/'+encodeURIComponent(selected)+'/tasks/'+encodeURIComponent(button.dataset.task)+'/complete',{});
      await refresh(); if ($('run-context')) updateInspection();
    }
  } catch (e) { $('notice').textContent=e.message; button.disabled=false; }
});
$('content').addEventListener('change',event=>{
  const el=event.target;
  if (el.dataset.setting) {advanced[el.dataset.setting]=el.tagName==='SELECT'?el.value:+el.value;$('config').textContent=JSON.stringify(settings(),null,2);}
  if (el.id==='case-select') {caseSelection=el.value;eventPage=incidentPage=requestPage=0;updateInspection();}
  if (el.id==='incident-filter') {incidentFilter=el.value;incidentPage=0;updateInspection();}
  if (el.id==='event-filter') {eventFilter=el.value;eventPage=0;updateInspection();}
});
$('execute').onclick=async()=>{
  const button=$('execute'); button.disabled=true;
  try {const result=await api('runs',settings());page=6;$('notice').textContent='Experiment started: '+result.run_id;selectRun(result.run_id);}
  catch(e){$('notice').textContent=e.message;} finally {button.disabled=false;}
};
$('compare').onclick=async()=>{
  const button=$('compare');button.disabled=true;
  try {await api('comparisons',settings());page=8;shellKey='';$('notice').textContent='Five isolated strategy runs started; comparison appears when all finish.';render();}
  catch(e){$('notice').textContent=e.message;} finally {button.disabled=false;}
};
$('runs').onchange=()=>selectRun($('runs').value);
for (const id of ['dataset','scenario','strategy','seed','instances']) $(id).onchange=()=>{
  $('config').textContent=JSON.stringify(settings(),null,2);
  if (page===1 && !record) shellKey='';
  render();
};
(async()=>{
  config=await api('config');
  $('scenario').innerHTML=Object.keys(config.scenarios).map(k=>'<option '+(k==='X'?'selected':'')+'>'+escape(k)+'</option>').join('');
  $('config').textContent=JSON.stringify(settings(),null,2);
  await refresh();await render();
  setInterval(async()=>{
    if (document.hidden) return;
    const changed=await refresh();
    if (changed && [1,6,8].includes(page)) render();
  },3000);
})().catch(e=>$('notice').textContent=e.message);
