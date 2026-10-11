/* Evidence-only presentation helpers. No BPMN execution or experiment policy. */
(function (root) {
  'use strict';
  const failureKinds = new Set(['service_outage', 'timeout', 'missing_data', 'resource_shortage']);
  function object(value) {
    if (value && typeof value === 'object') return value;
    try { return JSON.parse(value || '{}'); } catch (_) { return {}; }
  }
  function parseCSV(text) {
    text = text.replace(/^\uFEFF/, '');
    const rows = []; let row = [], cell = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') {
        if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
        else if (quoted || cell === '') quoted = !quoted;
        else cell += c;
      } else if (c === ',' && !quoted) { row.push(cell); cell = ''; }
      else if ((c === '\n' || c === '\r') && !quoted) {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cell); if (row.some(v => v !== '')) rows.push(row);
        row = []; cell = '';
      } else cell += c;
    }
    if (quoted) throw Error('Incomplete CSV export; using available API history.');
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    if (!rows.length) return [];
    const headers = rows.shift();
    if (!headers.includes('case_id') || !headers.includes('activity') || !headers.includes('id')) {
      throw Error('CSV event schema is not recognised.');
    }
    return rows.map(values => Object.fromEntries(headers.map((key, i) => [key, values[i] ?? ''])));
  }
  function ordered(events) {
    return [...events].sort((a, b) => Number(a.id) - Number(b.id) || String(a.timestamp).localeCompare(String(b.timestamp)));
  }
  function mergeHistory(previous, incoming) {
    const map = new Map(previous.map(e => [String(e.id), e]));
    for (const e of incoming) map.set(String(e.id), e);
    return ordered([...map.values()]);
  }
  function contiguous(events) {
    return events.length === 0 || (Number(events[0].id) === 1 &&
      events.every((e, i) => Number(e.id) === i + 1));
  }
  function analyse(record, events) {
    const cases = new Map((record.cases || []).map(c => [c.case_id, c]));
    const adaptations = new Map();
    for (const a of record.adaptations || []) {
      adaptations.set(a.request_id, { ...a, request: object(a.request), response: object(a.response) });
    }
    const chronological = ordered(events);
    let activeFloor = chronological.length ? Number(chronological[0].id) : Infinity;
    for (let i = 1; i < chronological.length; i++) {
      if (Number(chronological[i].id) !== Number(chronological[i-1].id) + 1) activeFloor = Number(chronological[i].id);
    }
    const byCase = new Map(), groups = new Map();
    const groupKey = (cid, activity) => JSON.stringify([cid, activity]);
    for (const e of chronological) {
      if (!byCase.has(e.case_id)) byCase.set(e.case_id, []);
      byCase.get(e.case_id).push(e);
      const key = groupKey(e.case_id, e.activity);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
      if (e.lifecycle === 'adaptation' && e.request_id) {
        const old = adaptations.get(e.request_id) || {};
        adaptations.set(e.request_id, { ...old, request_id: e.request_id, case_id: e.case_id,
          activity: e.activity, timestamp: e.timestamp, event: e,
          outcome: old.outcome || e.outcome || 'pending',
          request: { ...old.request, disruption_label: old.request?.disruption_label || e.disruption },
          response: { ...old.response, action: old.response?.action || e.intervention } });
      }
    }
    const incidents = [];
    const dedupe = new Set();
    for (const e of chronological) {
      const a = adaptations.get(e.request_id);
      const kind = e.disruption || a?.request.disruption_label || '';
      const isError = e.lifecycle === 'error';
      const isCondition = e.lifecycle === 'adaptation';
      if (!isError && !isCondition) continue;
      const key = e.request_id ? e.request_id : 'event-' + e.id;
      if (dedupe.has(key)) {
        const existing = incidents.find(i => i.key === key);
        if (isError && existing) { existing.explicitError = true; existing.category = 'Failure / blocking incident'; existing.event = e; existing.timestamp = e.timestamp; }
        continue;
      }
      dedupe.add(key);
      const sameTask = groups.get(groupKey(e.case_id, e.activity)) || [];
      const completedAfter = sameTask.find(next => Number(next.id) > Number(e.id) && next.lifecycle === 'complete');
      const c = cases.get(e.case_id);
      const blocking = failureKinds.has(kind);
      let recovery = completedAfter ? (blocking || isError ? 'Task completion recorded afterward' : 'Activity completed afterward') :
        c?.status === 'completed' ? 'Instance completed; later task completion not recorded' :
        c?.status === 'stuck' ? 'Instance stuck; task recovery not recorded' :
        'Recovery not yet recorded in available history';
      incidents.push({ key, event: e, case_id: e.case_id, instance_key: c?.instance_key || '',
        activity: e.activity, element: a?.request.element || '', type: kind || a?.request.trigger || 'Not recorded',
        category: isError || blocking ? 'Failure / blocking incident' : 'Process condition',
        explicitError: isError, blocking, action: a?.response.action || e.intervention || 'Not recorded',
        message: e.error_message || a?.request.error_message || 'Not recorded',
        reason: kind || a?.request.trigger || 'Not recorded', timestamp: e.timestamp,
        recovered: !!completedAfter && (blocking || isError), recovery,
        instanceStatus: c?.status || 'Not recorded', oracle: a?.outcome || e.outcome || 'Not recorded' });
    }
    const stats = new Map();
    for (const list of groups.values()) {
      const activity = list[0].activity;
      if (!stats.has(activity)) stats.set(activity, { activity, completed: 0, errors: 0, incidents: 0,
        adapted: 0, active: 0, recovered: 0, unresolved: 0, events: [] });
      const stat = stats.get(activity); stat.events.push(...list);
      stat.completed += list.filter(e => e.lifecycle === 'complete').length;
      stat.errors += list.filter(e => e.lifecycle === 'error').length;
      stat.adapted += list.filter(e => e.lifecycle === 'adaptation' && e.intervention && e.intervention !== 'none').length;
      const cid = list[0].case_id;
      let phase = '', phaseId = 0;
      for (const e of list) {
        if (['start', 'complete', 'error'].includes(e.lifecycle)) { phase = e.lifecycle; phaseId = Number(e.id); }
        if (e.lifecycle === 'adaptation' && failureKinds.has(e.disruption) &&
          ['retry', 'escalate', 'none'].includes(e.intervention)) phase = 'blocked';
      }
      // A last observed start is evidence of observed activity, not exact engine token state.
      if (record.status === 'running' && cases.get(cid)?.status === 'running' && phase === 'start' && phaseId >= activeFloor) stat.active++;
    }
    for (const incident of incidents) {
      const stat = stats.get(incident.activity);
      if (!stat) continue;
      if (incident.blocking || incident.explicitError) {
        stat.incidents++; if (incident.recovered) stat.recovered++; else stat.unresolved++;
      }
    }
    const requests = [...adaptations.values()];
    const m = record.metrics || {};
    const completed = (record.cases || []).filter(c => c.status === 'completed').length;
    return { cases, byCase, stats, incidents, adaptations, requests,
      summary: { total: record.config?.instances ?? m.instances_requested ?? null,
        started: record.cases?.length ?? m.cases_started ?? 0,
        completed: m.completed ?? completed,
        running: (record.cases || []).filter(c => c.status === 'running').length,
        stuck: (record.cases || []).filter(c => c.status === 'stuck').length,
        unstarted: m.unstarted_cases ?? Math.max(0, (record.config?.instances || 0) - (record.cases?.length || 0)),
        requests: m.adaptation_requests ?? requests.length,
        accepted: requests.filter(a => a.outcome === 'success').length,
        rejected: requests.filter(a => a.outcome === 'failure').length,
        pending: requests.filter(a => !a.outcome || a.outcome === 'pending').length,
        recoveredCases: new Set(incidents.filter(i => i.recovered).map(i => i.case_id)).size } };
  }
  root.ExecutionEvidence = { parseCSV, object, ordered, mergeHistory, contiguous, analyse };
})(window);
