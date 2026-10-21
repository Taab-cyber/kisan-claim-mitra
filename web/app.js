/* Farmer app: screens, API calls, and the voice guide.
 * The browser never decides anything important: approval, execution and verification
 * all happen (and are enforced) on the backend. This file only shows results. */
const S = { lang: 'hi', sid: null, last: null, appNo: null, proposal: null };
const $ = (id) => document.getElementById(id);

// Phrases the quick buttons send (the same trained NLU handles them as typed text).
const QUICK = {
  status: { hi: 'मेरे क्लेम का स्टेटस बताओ', en: 'what is my claim status' },
  season: { hi: 'मेरा सीज़न गलत है', en: 'the season in my record is wrong' },
  upload: { hi: 'मुझे दस्तावेज़ अपलोड करना है', en: 'i want to upload a document' },
  apply: { hi: 'फसल बीमा के लिए आवेदन करना है', en: 'i want to apply for crop insurance' },
  help: { hi: 'मुझे मदद चाहिए', en: 'i need help' },
};
const CLAIM = {
  under_review: 'जाँच जारी · Under review', documents_pending: 'कागज़ बाकी · Documents pending',
  approved: 'मंज़ूर · Approved', rejected: 'अस्वीकार · Rejected',
};
const PAY = {
  PAID: ['ok', 'जमा · Credited'], NOT_PAID: ['warn', 'बाकी · Not credited'], UNCERTAIN: ['unsure', 'अस्पष्ट · Unclear'],
};

// ---------------- helpers ----------------
async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.message || data.detail || ('HTTP ' + r.status));
  return data;
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function istTime(iso) {
  if (!iso) return 'unknown';
  return new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' IST';
}
function notice(text, ms = 6000) {
  const n = $('notice'); n.textContent = text; n.hidden = false;
  clearTimeout(notice.t); notice.t = setTimeout(() => { n.hidden = true; }, ms);
}
function show(name) {
  document.querySelectorAll('.screen').forEach(s => { s.hidden = s.id !== 'screen-' + name; });
  window.scrollTo(0, 0);
}
function say(text) { return Voice.speak(text, S.lang); }
function setLang(lang) {
  S.lang = lang;
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-lang]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === lang)));
}
function addLog(who, text) {
  const d = document.createElement('div'); d.className = 'msg ' + who; d.textContent = text;
  $('log').appendChild(d); $('log').scrollTop = $('log').scrollHeight;
}

// ---------------- talking to the agent ----------------
async function send(text) {
  text = (text || '').trim();
  if (!text) return;
  if (!S.sid) await startSession();
  addLog('farmer', text);
  try { handle(await api('/api/chat', { session_id: S.sid, text, lang: S.lang })); }
  catch (e) { notice('Error: ' + e.message); }
}

async function decide(approve) {
  if (!S.proposal) return;
  $('ap-approve').disabled = $('ap-reject').disabled = true;   // UX only; backend is the real guard
  try { handle(await api('/api/approve', { session_id: S.sid, proposal_id: S.proposal.id, approve })); }
  catch (e) { notice('Error: ' + e.message); $('ap-approve').disabled = $('ap-reject').disabled = false; }
}

function handle(r) {
  S.last = r;
  if (r.claim) S.appNo = r.claim.app_no;
  addLog('agent', r.reply);
  $('guide-text').textContent = r.reply;
  $('guide-sub').textContent = r.state === 'AWAIT_APPROVAL' ? 'हाँ / नहीं बोलिए · Say yes or no' : '';
  say(r.reply);
  const p = r.proposal;
  const statusFirst = r.claim && ['check_status', 'missing_docs'].includes(r.intent);
  if (p && p.status === 'PENDING' && statusFirst && p.change.action_type === 'document_upload') {
    renderApproval(r); renderStatus(r); show('status');      // "Upload it" button opens approval
  }
  else if (p && p.status === 'PENDING') { renderApproval(r); show('approval'); }
  else if (p) { renderResult(r); show('approval'); }
  else if (r.claim) { renderStatus(r); show('status'); }
  else { show('home'); }
}

// ---------------- screen renderers ----------------
function renderStatus(r) {
  const c = r.claim, a = r.assessment || {};
  $('st-meta').innerHTML = [['आवेदन नं. · App no.', c.app_no], ['मौसम · Season', c.season], ['फसल · Crop', c.crop]]
    .map(([k, v]) => `<div><div class="small">${esc(k)}</div><div style="font-weight:700;font-size:13px">${esc(v ?? '—')}</div></div>`).join('');
  $('st-summary').textContent = r.reply;
  const dec = $('st-decision');
  dec.className = 'card ' + (c.claim_status === 'approved' ? 'ok' : c.claim_status === 'rejected' ? 'bad' : 'warn');
  dec.innerHTML = `<div class="label">Claim decision</div><div class="big">${esc(CLAIM[c.claim_status] || c.claim_status || '—')}</div>
    <div class="mono">claim_status = ${esc(c.claim_status)}</div>`;
  const [cls, label] = PAY[a.payment] || PAY.UNCERTAIN;
  $('st-payment').className = 'card ' + cls;
  $('st-payment').innerHTML = `<div class="label">Payment</div><div class="big">${esc(label)}</div>
    <div class="mono">payment_status = ${esc(c.payment_status ?? 'missing')}</div>`;
  const unsure = a.verdict === 'UNCERTAIN';
  $('st-uncertain').hidden = !unsure;
  if (unsure) $('st-uncertain').innerHTML = `<div class="label">UNCERTAIN · पक्का नहीं</div>
    <div style="font-size:13px">${(a.problems || []).map(esc).join('<br>')}</div>`;
  const docs = a.missing_documents || [];
  $('st-missing').hidden = !docs.length;
  $('st-doc').textContent = docs.join(', ');
  $('st-evidence').innerHTML = `Source: mock-portal ${esc(c.source)}<br>Fetched: ${esc(istTime(c.fetched_at))}<br>
    Record version: ${esc(c.record_version)} · Check: <span class="chip ${unsure ? 'UNCERTAIN' : 'OK'}">${unsure ? 'UNCERTAIN' : 'FRESH READ'}</span>`;
}

function renderApproval(r) {
  const p = r.proposal, ch = p.change;
  S.proposal = p;
  $('ap-summary').textContent = r.reply;
  $('ap-compare').innerHTML = ch.action_type === 'season_change'
    ? `<div class="card"><div class="label">You asked</div><div class="big">${esc(ch.to)}</div></div>
       <div class="card bad"><div class="label">Portal shows</div><div class="big">${esc(ch.from)}</div></div>`
    : `<div class="card bad" style="grid-column:span 2"><div class="label">Portal asks for (exact)</div><div class="big">${esc(ch.document_name)}</div></div>`;
  const rows = ch.action_type === 'season_change'
    ? [['Operation', 'Correct season'], ['Target record', ch.app_no], ['Change', `${ch.from} → ${ch.to}`], ['Why', "Farmer's season differs from the portal record"]]
    : [['Operation', 'Upload document'], ['Target record', ch.app_no], ['Document', ch.document_name], ['File', ch.file_ref + ' (synthetic sample)']];
  rows.push(['Action ID', `${p.id} · record v${p.base_version}`]);
  $('ap-details').innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  $('ap-state').textContent = 'Proposed change · not done yet';
  $('ap-result').hidden = true; $('ap-after').hidden = false;
  $('ap-buttons').hidden = false; $('ap-done').hidden = true;
  $('ap-approve').disabled = $('ap-reject').disabled = false;
}

function renderResult(r) {
  const p = r.proposal, v = r.verification;
  S.proposal = p;
  $('ap-summary').textContent = r.reply;
  $('ap-state').textContent = 'Action ' + p.status;
  const status = v ? v.status : (p.status === 'REJECTED' || p.status === 'CANCELLED' ? 'OK' : 'PENDING');
  const ex = p.execution || {};
  $('ap-result').hidden = false;
  $('ap-result').innerHTML = `<div class="label">Result · परिणाम</div>
    <div class="big"><span class="chip ${esc(status)}">${esc(v ? v.status : p.status)}</span></div>
    <dl class="kv" style="margin-top:6px">
      <dt>Proposal</dt><dd>${esc(p.status)}</dd>
      ${ex.kind ? `<dt>Execution</dt><dd>${esc(ex.kind)} · attempts ${esc(ex.attempts)}${ex.replayed ? ' · duplicate ignored' : ''}</dd>` : ''}
      ${v ? `<dt>Verified by</dt><dd>fresh read ${esc(v.source)} at ${esc(istTime(v.fetched_at))}</dd>
             <dt>Expected</dt><dd class="mono">${esc(JSON.stringify(v.expected))}</dd>
             <dt>Observed</dt><dd class="mono">${esc(JSON.stringify(v.observed || {}))}</dd>` : ''}
    </dl>`;
  $('ap-after').hidden = true;
  // Unknown outcome (timeout / portal down): keep Approve available as "try / check again".
  const retry = ['PENDING_CONFIRMATION', 'APPROVED'].includes(p.status) || (v && v.status === 'PENDING');
  $('ap-buttons').hidden = !retry; $('ap-done').hidden = retry;
  $('ap-approve').disabled = $('ap-reject').disabled = false;
  if (retry) $('ap-approve').textContent = 'दोबारा जाँचें · Check again';
}

// ---------------- session + wiring ----------------
async function startSession() {
  const r = await api('/api/session', { lang: S.lang });
  S.sid = r.session_id;
  Voice.init(r.voice, notice);
}

async function listen() {
  if (!Voice.canListen() && Voice.provider() === 'browser') {
    notice('इस ब्राउज़र में आवाज़ उपलब्ध नहीं, कृपया लिखें · Voice input not supported here - please type.');
    $('text').focus(); return;
  }
  Voice.stop();
  $('mic').classList.add('listening'); $('mic-status').textContent = 'सुन रहा हूँ... · Listening...';
  try { const text = await Voice.listen(S.lang); $('text').value = text; await send(text); $('text').value = ''; }
  catch (e) { notice('आवाज़ समझ नहीं आई, फिर कोशिश करें या लिखें · Could not hear you (' + e.message + '). Try again or type.'); }
  finally { $('mic').classList.remove('listening'); $('mic-status').textContent = 'दबाएँ और बोलें · Tap and speak'; }
}

document.querySelectorAll('.lang-btn').forEach(b => b.onclick = () => {
  setLang(b.dataset.lang);
  say(b.dataset.lang === 'hi' ? 'आपने हिन्दी चुनी है। शुरू करें दबाइए।' : 'You chose English. Press start.');
});
document.querySelectorAll('.lang-toggle').forEach(b => b.onclick = () => setLang(b.dataset.lang));
$('start').onclick = async () => {
  try { await startSession(); } catch (e) { notice('Server not reachable: ' + e.message); return; }
  show('home');
  say(S.lang === 'hi' ? 'माइक दबाकर बोलिए, जैसे: मेरे क्लेम का स्टेटस बताओ। या नीचे लिखिए।'
    : 'Press the mic and speak, for example: tell me my claim status. Or type below.');
};
$('mic').onclick = listen;
$('ask').onsubmit = (e) => { e.preventDefault(); const t = $('text').value; $('text').value = ''; send(t); };
document.querySelectorAll('[data-say]').forEach(b => b.onclick = () => { $('fix-choices').hidden = true; send(QUICK[b.dataset.say][S.lang]); });
$('fix-btn').onclick = () => { $('fix-choices').hidden = !$('fix-choices').hidden; };
$('mute').onclick = () => { const m = !Voice.isMuted(); Voice.setMuted(m); $('mute').textContent = m ? '🔇' : '🔊'; $('mute').setAttribute('aria-pressed', String(m)); };
document.querySelectorAll('.back').forEach(b => b.onclick = () => { Voice.stop(); show('home'); });
document.querySelectorAll('.hear').forEach(b => b.onclick = () => S.last && say(S.last.reply));
$('st-recheck').onclick = () => S.appNo && send(S.lang === 'hi' ? `${S.appNo} का स्टेटस बताओ` : `status of ${S.appNo}`);
$('st-upload').onclick = () => {
  if (S.proposal && S.proposal.status === 'PENDING' && S.proposal.change.action_type === 'document_upload') show('approval');
  else send(QUICK.upload[S.lang] + ' ' + (S.appNo || ''));
};
$('ap-approve').onclick = () => { $('ap-approve').textContent = 'मंज़ूर · Approve'; decide(true); };
$('ap-reject').onclick = () => decide(false);
setLang('hi');
