/* Judge console: runs the real scenarios on the backend and shows evidence. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let scenarios = [];
const results = {};
let selected = null;

async function getJSON(path, body) {
  const opts = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  return r.json();
}

function keyEvidence(res) {
  // the most telling evidence lines for the table cell
  const pick = res.evidence.filter(l => /^(fetch|decision|verification|duplicate_request):/.test(l));
  return pick.map(l => l.replace(/, (tool|app_no|status_code|is_paid|season_year_assumed|reason)=[^,]*/g, '').slice(0, 150)).join('\n');
}

function renderTable() {
  const head = `<div class="trow head"><div>TC</div><div>INPUT</div><div>EXPECTED</div><div>ACTUAL</div><div>EVIDENCE</div><div>RESULT</div></div>`;
  $('results').innerHTML = head + scenarios.map(s => {
    const r = results[s.id];
    const chip = !r ? '<span class="chip NOTRUN">NOT RUN</span>' : `<span class="chip ${r.passed ? 'PASS' : 'FAIL'}">${r.passed ? 'PASS' : 'FAIL'}</span>`;
    return `<div class="trow ${selected === s.id ? 'sel' : ''}" data-id="${esc(s.id)}" tabindex="0" role="button">
      <div><b>${esc(s.id)}</b></div>
      <div>${r ? r.inputs.map(esc).join('<br>') : esc(s.title)}</div>
      <div>${esc(s.expected)}</div>
      <div>${r ? esc((r.actual[r.actual.length - 1] || '').slice(0, 220)) + (r.error ? `<br><b style="color:var(--red-ink)">${esc(r.error)}</b>` : '') : '—'}</div>
      <div class="mono" style="white-space:pre-wrap;font-size:11px">${r ? esc(keyEvidence(r)) : '—'}</div>
      <div>${chip}</div></div>`;
  }).join('');
  document.querySelectorAll('.trow[data-id]').forEach(row => {
    row.onclick = () => select(row.dataset.id);
    row.onkeydown = (e) => { if (e.key === 'Enter') select(row.dataset.id); };
  });
  const done = Object.values(results);
  const off = done.filter(r => r.official);
  $('summary').textContent = done.length
    ? `${off.filter(r => r.passed).length} / ${off.length} official · ${done.filter(r => !r.official && r.passed).length} / ${done.filter(r => !r.official).length} failure cases passed`
    : '';
}

function select(id) {
  selected = id;
  renderTable();
  const r = results[id];
  if (!r) return;
  $('tl-title').textContent = `Action timeline · ${id}`;
  const steps = r.evidence.filter(l => /^(proposal|approval|execution|verification|duplicate_request|fetch):/.test(l));
  $('timeline').innerHTML = steps.length
    ? steps.map(l => `<div><i style="background:${/FAILED|EXPIRED|REJECTED|PORTAL_DOWN|TIMEOUT|duplicate/.test(l) ? 'var(--amber)' : 'var(--green)'}"></i><span>${esc(l.slice(0, 260))}</span></div>`).join('')
    : '<span class="small">No actions in this case.</span>';
  $('checks').innerHTML = r.checks.map(c => `<div>${c.ok ? '✅' : '❌'} ${esc(c.label)}</div>`).join('') +
    (r.error ? `<div style="color:var(--red-ink)"><b>Error:</b> ${esc(r.error)}</div>` : '');
  $('evidence').textContent = ['INPUT:', ...r.inputs, '', 'REPLIES:', ...r.actual, '', 'EVIDENCE:', ...r.evidence].join('\n');
}

async function run(ids, btn) {
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Running...';
  try {
    const data = await getJSON('/api/scenarios/run', { ids });
    data.results.forEach(r => { results[r.id] = r; });
    renderTable();
    if (data.results[0]) select(data.results[0].id);
  } catch (e) { alert('Run failed: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = label; showMode(); }
}

async function showMode() {
  try { const m = await getJSON('/portal/admin/mode'); $('mode-now').textContent = `current: ${m.mode}`; $('mode').value = m.mode; } catch (e) { /* ignore */ }
}

async function refreshLive() {
  const sid = $('sid').value.trim();
  const data = await getJSON('/api/evidence' + (sid ? `?session_id=${encodeURIComponent(sid)}` : ''));
  const fmt = (ts) => new Date(ts).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' });
  $('live').textContent = data.entries.length
    ? data.entries.map(e => `${fmt(e.ts)} IST  ${e.session_id}  ${e.step.padEnd(12)} ${JSON.stringify(e.data)}`).join('\n')
    : 'No farmer activity yet. Use the farmer app, then press Refresh.';
  $('live').scrollTop = $('live').scrollHeight;
}

$('run-official').onclick = (e) => run(scenarios.filter(s => s.official).map(s => s.id), e.target);
$('run-failures').onclick = (e) => run(scenarios.filter(s => !s.official).map(s => s.id), e.target);
$('set-mode').onclick = async () => { await getJSON('/portal/admin/mode', { mode: $('mode').value }); showMode(); };
$('reset').onclick = async () => { await getJSON('/portal/admin/reset', {}); showMode(); };
$('credit').onclick = async () => {
  const r = await getJSON('/portal/simulate/credit/KRB-2026-00748', {});
  alert(r.payment_status ? `KRB-2026-00748 payment_status = ${r.payment_status}` : (r.message || 'failed'));
};
$('refresh').onclick = refreshLive;

(async () => {
  scenarios = (await getJSON('/api/scenarios')).scenarios;
  renderTable(); showMode(); refreshLive();
})();
