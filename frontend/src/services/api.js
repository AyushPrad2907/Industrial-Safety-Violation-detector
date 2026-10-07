export async function fetchHealth() {
  const res = await fetch('/api/health');
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}

export async function fetchSystemStatus() {
  const res = await fetch('/api/status');
  if (!res.ok) throw new Error('Status fetch failed');
  return res.json();
}

export async function fetchStats() {
  const res = await fetch('/api/stats');
  if (!res.ok) throw new Error('Stats fetch failed');
  return res.json();
}

export async function fetchWorkers() {
  const res = await fetch('/api/workers');
  if (!res.ok) throw new Error('Workers fetch failed');
  return res.json();
}

export async function fetchViolations(params = {}) {
  const query = new URLSearchParams();
  if (params.severity && params.severity !== 'All') query.set('severity', params.severity);
  if (params.violation_type && params.violation_type !== 'All') query.set('violation_type', params.violation_type);
  if (params.worker_id && params.worker_id !== 'All') query.set('worker_id', params.worker_id);

  const res = await fetch(`/api/violations?${query.toString()}`);
  if (!res.ok) throw new Error('Violations fetch failed');
  return res.json();
}

export async function fetchViolationById(eventId) {
  const res = await fetch(`/api/violations/${encodeURIComponent(eventId)}`);
  if (!res.ok) throw new Error('Violation record not found');
  return res.json();
}

export async function startMonitoring(payload = {}) {
  const res = await fetch('/api/monitoring/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error('Failed to start monitoring');
  return res.json();
}

export async function stopMonitoring() {
  const res = await fetch('/api/monitoring/stop', {
    method: 'POST'
  });
  if (!res.ok) throw new Error('Failed to stop monitoring');
  return res.json();
}

export async function resetSession() {
  const res = await fetch('/api/session/reset', {
    method: 'POST'
  });
  if (!res.ok) throw new Error('Failed to reset session');
  return res.json();
}

export function getCsvExportUrl(params = {}) {
  const query = new URLSearchParams();
  if (params.severity && params.severity !== 'All') query.set('severity', params.severity);
  if (params.violation_type && params.violation_type !== 'All') query.set('violation_type', params.violation_type);
  if (params.worker_id && params.worker_id !== 'All') query.set('worker_id', params.worker_id);
  return `/api/violations/export/csv?${query.toString()}`;
}

export function getEvidenceUrl(eventId) {
  return `/api/evidence/${encodeURIComponent(eventId)}`;
}
