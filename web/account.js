/* Sign-up, mock OTP login, profile and document checks (stretch screens).
 * Uses helpers from app.js: $, S, show, say, notice, esc, startSession.
 * The OTP is a MOCK shown in a "demo SMS" box: the farmer types it in. We never auto-fill it. */
const A = { token: null, profile: null, fromSignup: false, samples: [], uploadFor: null, timer: null };
const TOKEN_KEY = 'kcm_token';
const FIELD_IDS = { name: 'f-name', mobile: 'f-mobile', village: 'f-village', district: 'f-district', land_acres: 'f-land', main_crop: 'f-crop' };
const FIELD_NAMES = { name: ['पूरा नाम', 'full name'], mobile: ['मोबाइल नंबर', 'mobile number'], village: ['गाँव', 'village'],
  district: ['जिला', 'district'], land_acres: ['ज़मीन (एकड़)', 'land in acres'], main_crop: ['मुख्य फसल', 'main crop'] };
const STATUS_LABEL = { PASSED: 'ठीक · Looks good', REVIEW: 'जाँच जारी · Checking', MISSING: 'गायब · Missing', NEEDS_FIX: 'सुधारें · Needs fix' };
const THUMB = { aadhaar_card: 'aadhaar_card_sample.png', pan_card: null, land_record: 'land_record_sample.png',
  bank_passbook: 'bank_passbook_sample.png', insurance_papers: 'insurance_papers_sample.png' };
const tr = (hi, en) => (S.lang === 'hi' ? hi : en);

function saveToken(t) {
  A.token = t;
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* storage blocked: stay in memory */ }
}
function loadToken() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }

async function req(method, path, body, isForm) {
  const headers = {};
  if (A.token) headers.Authorization = 'Bearer ' + A.token;
  if (body && !isForm) headers['Content-Type'] = 'application/json';
  const r = await fetch(path, { method, headers, body: body && !isForm ? JSON.stringify(body) : body });
  return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
}
const digitsOf = (t) => String(t || '').replace(/[०-९]/g, d => '०१२३४५६७८९'.indexOf(d)).replace(/\D/g, '');
function showError(id, html) { $(id).innerHTML = html; $(id).hidden = !html; }

// ---------------- sign-up (step 1) ----------------
$('go-signup').onclick = () => {
  A.fromSignup = true; show('signup');
  say(tr('अपना नाम, मोबाइल नंबर और खेती की जानकारी बताइए। किसी भी डिब्बे के पास माइक दबाकर बोल सकते हैं।',
    'Tell me your name, mobile number and farm details. You can tap the mic beside a box to speak.'));
};
$('go-login').onclick = () => { A.fromSignup = false; openOtp(''); };
document.querySelectorAll('.to-welcome').forEach(b => b.onclick = () => { clearInterval(A.timer); show('lang'); });

document.querySelectorAll('[data-mic-for]').forEach(btn => btn.onclick = async () => {
  const input = $(btn.dataset.micFor);
  try {
    input.value = await Voice.listen(S.lang);
    if (input.id === 'f-mobile') {          // read the number back so the farmer can confirm it
      const d = digitsOf(input.value);
      input.value = d || input.value;
      say(tr('मैंने सुना: ', 'I heard: ') + d.split('').join(' ') + tr('। सही है?', '. Is that right?'));
    }
  } catch (e) { notice(tr('आवाज़ समझ नहीं आई, कृपया लिखें', 'Could not hear you, please type') + ' (' + e.message + ')'); }
});

$('signup-form').onsubmit = async (e) => {
  e.preventDefault();
  document.querySelectorAll('.field').forEach(f => f.classList.remove('field-error'));
  showError('signup-error', '');
  const body = {};
  Object.entries(FIELD_IDS).forEach(([k, id]) => { body[k] = $(id).value; });
  const r = await req('POST', '/api/auth/signup', body);
  if (r.ok) { openOtp(digitsOf(body.mobile), true); return; }
  const d = r.data;
  if (d.error === 'missing_fields' || d.error === 'invalid_fields') {
    const keys = Array.isArray(d.fields) ? d.fields : Object.keys(d.fields);
    keys.forEach(k => $(FIELD_IDS[k]).closest('.field').classList.add('field-error'));
    const names = keys.map(k => tr(FIELD_NAMES[k][0], FIELD_NAMES[k][1])).join(', ');
    const msg = d.error === 'missing_fields' ? tr('कृपया यह जानकारी भी दीजिए: ', 'Please also tell me: ') + names
      : tr('कृपया इन्हें ठीक कीजिए: ', 'Please correct: ') + names;
    showError('signup-error', esc(msg) + (d.error === 'invalid_fields'
      ? '<br><span class="small">' + Object.entries(d.fields).map(([k, v]) => esc(k + ': ' + v)).join('<br>') + '</span>' : ''));
    say(msg);
  } else if (r.status === 409) {
    showError('signup-error', esc(tr('यह नंबर पहले से पंजीकृत है। कृपया लॉगिन करें।', 'This number is already registered. Please log in.')));
    setTimeout(() => { A.fromSignup = false; openOtp(digitsOf(body.mobile)); }, 1500);
  } else showError('signup-error', esc(d.message || 'Error'));
};

// ---------------- mock OTP (step 2 / login) ----------------
function buildBoxes() {
  const fs = $('otp-boxes');
  fs.querySelectorAll('input').forEach(i => i.remove());
  for (let i = 0; i < 6; i++) {
    const inp = document.createElement('input');
    Object.assign(inp, { type: 'text', inputMode: 'numeric', autocomplete: 'one-time-code' });
    inp.setAttribute('aria-label', 'OTP digit ' + (i + 1));
    inp.oninput = () => {      // one digit per box; several digits at once (fast keyboards) spread forward
      const boxes = [...fs.querySelectorAll('input')];
      const d = digitsOf(inp.value).split('');
      let j = boxes.indexOf(inp);
      inp.value = '';
      d.forEach(ch => { if (j < 6) boxes[j++].value = ch; });
      (boxes[Math.min(j, 5)] || inp).focus();
      checkBoxes();
    };
    inp.onkeydown = (e) => { if (e.key === 'Backspace' && !inp.value && inp.previousElementSibling?.tagName === 'INPUT') inp.previousElementSibling.focus(); };
    inp.onpaste = (e) => {     // the farmer may paste the code they typed/copied themselves
      e.preventDefault();
      const d = digitsOf(e.clipboardData.getData('text')).slice(0, 6).split('');
      fs.querySelectorAll('input').forEach((b, j) => { b.value = d[j] || ''; });
      checkBoxes();
    };
    fs.appendChild(inp);
  }
}
const otpCode = () => [...$('otp-boxes').querySelectorAll('input')].map(i => i.value).join('');
function checkBoxes() { $('otp-verify').disabled = otpCode().length !== 6; }

function openOtp(mobile, autoSend) {
  show('otp');
  $('otp-title').textContent = A.fromSignup ? 'चरण 2 / 3 · Step 2 of 3' : 'लॉगिन · Log in';
  $('otp-mobile').value = mobile || '';
  $('otp-sms').hidden = true; $('otp-boxes').disabled = true; showError('otp-error', '');
  buildBoxes(); checkBoxes();
  if (autoSend) sendOtp();
  else say(tr('अपना मोबाइल नंबर डालिए और OTP भेजें दबाइए।', 'Enter your mobile number and press Send OTP.'));
}

function startTimer(seconds) {
  clearInterval(A.timer);
  let left = seconds;
  $('otp-send').disabled = true;
  const tick = () => {
    $('otp-timer').textContent = left > 0 ? `दोबारा भेजें ${left}s में · Resend in ${left}s` : '';
    if (left-- <= 0) { clearInterval(A.timer); $('otp-send').disabled = false; }
  };
  tick(); A.timer = setInterval(tick, 1000);
}

async function sendOtp() {
  showError('otp-error', '');
  const r = await req('POST', '/api/auth/otp/request', { mobile: $('otp-mobile').value });
  if (!r.ok) {
    const msg = r.status === 404 ? tr('यह नंबर पंजीकृत नहीं है। पहले खाता बनाइए।', 'This number is not registered. Please create an account first.')
      : r.status === 429 ? tr(`कृपया ${r.data.retry_after} सेकंड रुकिए।`, `Please wait ${r.data.retry_after} seconds.`) : (r.data.message || 'Error');
    showError('otp-error', esc(msg)); say(msg); return;
  }
  $('otp-sms').hidden = false;
  $('otp-sms').innerHTML = `<div class="label" style="color:var(--amber-ink)">📱 डेमो SMS (नकली) · Demo SMS (mock) to ${esc(r.data.sent_to)}</div>
    <div class="big">OTP: <span class="mono" style="font-size:22px;letter-spacing:4px">${esc(r.data.mock_otp)}</span></div>
    <div class="small" style="color:var(--ink)">इसे नीचे खुद भरिए · Type it in the boxes below yourself. Valid for 5 minutes.</div>`;
  $('otp-boxes').disabled = false;
  $('otp-boxes').querySelector('input').focus();
  startTimer(r.data.resend_in);
  say(tr('OTP भेज दिया गया है। SMS में आया 6 अंकों का कोड नीचे के डिब्बों में भरिए।', 'The OTP has been sent. Type the 6-digit code from the SMS into the boxes.'));
}

async function verifyOtp() {
  const r = await req('POST', '/api/auth/otp/verify', { mobile: $('otp-mobile').value, otp: otpCode() });
  if (!r.ok) {
    const d = r.data;
    const msg = d.error === 'wrong_otp' ? tr(`गलत OTP। ${d.attempts_left} कोशिश बाकी।`, `Wrong OTP. ${d.attempts_left} tries left.`)
      : d.error === 'expired' ? tr('OTP की समय सीमा खत्म। नया OTP मँगाइए।', 'OTP expired. Please request a new one.')
      : d.error === 'locked' ? tr('बहुत सारी गलत कोशिशें। नया OTP मँगाइए।', 'Too many wrong tries. Please request a new OTP.') : (d.message || 'Error');
    showError('otp-error', esc(msg)); say(msg); buildBoxes(); checkBoxes(); return;
  }
  clearInterval(A.timer);
  saveToken(r.data.token);
  A.profile = r.data.profile;
  if (!S.sid) await startSession();
  renderHomeAccount();
  if (A.fromSignup) openDocs();
  else { show('home'); say(tr('स्वागत है, ', 'Welcome, ') + A.profile.farmer.name); }
}

$('otp-send').onclick = sendOtp;
$('otp-verify').onclick = verifyOtp;
$('otp-hint').onclick = () => say(tr('OTP आपके मोबाइल पर SMS में आता है। इस डेमो में वह पीले डिब्बे में दिखता है। उसे खुद भरिए, किसी को न बताइए।',
  'The OTP comes by SMS to your phone. In this demo it appears in the yellow box. Type it yourself and never share it.'));

// ---------------- profile + documents (step 3) ----------------
async function loadProfile() {
  if (!A.token) return null;
  const r = await req('GET', '/api/profile');
  if (!r.ok) { saveToken(null); A.profile = null; renderHomeAccount(); return null; }
  A.profile = r.data; renderHomeAccount();
  return r.data;
}

function attentionText(p) {
  const docs = p.documents.filter(d => p.attention.includes(d.doc_type));
  return docs.map(d => tr(d.name_hi, d.name_en) + ' – ' + (d.status === 'MISSING' ? tr('गायब', 'missing') : tr('सुधारें', 'needs fix'))).join(', ');
}

function renderHomeAccount() {
  const p = A.profile;
  $('account-links').hidden = !p;
  $('home-name').textContent = p ? p.farmer.name : 'किसान साथी · Farmer';
  const n = p ? p.attention.length : 0;
  $('attention').hidden = !n;
  if (n) $('attention').innerHTML = `<b>${n} दस्तावेज़ ध्यान माँगते हैं · ${n} documents need attention</b><br>${esc(attentionText(p))}`;
}

function renderDocs(p) {
  const f = p.farmer;
  $('profile-card').innerHTML = `<div class="label">प्रोफ़ाइल · Profile</div><dl class="kv">
    <dt>Name</dt><dd>${esc(f.name)}</dd><dt>Mobile</dt><dd>${esc(f.mobile_masked)} ${f.mobile_verified ? '✅ OTP verified' : ''}</dd>
    <dt>Village</dt><dd>${esc(f.village)}, ${esc(f.district)}</dd><dt>Farm</dt><dd>${esc(f.land_acres)} acres · ${esc(f.main_crop)}</dd></dl>`;
  $('docs-title').textContent = A.fromSignup ? 'चरण 3 / 3 · Step 3 of 3' : 'मेरे दस्तावेज़ · My documents';
  $('docs-guide').textContent = p.attention.length
    ? tr(`${p.attention.length} दस्तावेज़ ध्यान माँगते हैं: `, `${p.attention.length} documents need attention: `) + attentionText(p)
    : tr('सभी दस्तावेज़ जमा हैं। धन्यवाद!', 'All documents are in. Thank you!');
  const options = A.samples.map(s => `<option value="${esc(s.file)}">${esc(s.label)}</option>`).join('');
  $('doc-list').innerHTML = p.documents.map(d => {
    const flag = d.status === 'MISSING' || d.status === 'NEEDS_FIX';
    const thumb = THUMB[d.doc_type] ? `<img class="thumb" src="samples/${THUMB[d.doc_type]}" alt="sample">` : '<div class="thumb" style="display:grid;place-items:center;font-weight:700">PDF</div>';
    const problems = d.status === 'MISSING' ? tr('अपलोड नहीं हुआ। दावे के लिए ज़रूरी है।', 'Not uploaded. Needed for your claim.')
      : d.problems.map(c => tr(c.hi, c.en)).join(' · ');
    return `<div class="card doc-row ${flag ? 'flag' : ''}">${thumb}<div>
      <div style="font-weight:700">${esc(d.name_hi)} · ${esc(d.name_en)}</div>
      <span class="chip ${d.status}">${esc(STATUS_LABEL[d.status])}</span>
      ${problems ? `<div style="font-size:12.5px;margin-top:4px">${esc(problems)}</div>` : ''}
      ${d.file_name ? `<div class="small mono">${esc(d.file_name)}</div>` : ''}
      <div class="doc-actions">
        <button type="button" class="btn ${flag ? 'primary' : ''}" data-upload="${d.doc_type}">${d.status === 'NEEDS_FIX' ? 'दोबारा लें · Retake' : 'अपलोड · Upload'}</button>
        ${THUMB[d.doc_type] ? `<a class="btn" href="samples/${THUMB[d.doc_type]}" target="_blank" rel="noopener" style="display:inline-flex;align-items:center">नमूना · Sample</a>` : ''}
        <select data-demo="${d.doc_type}" aria-label="Upload a synthetic demo file"><option value="">🧪 डेमो फ़ाइल · Demo file</option>${options}</select>
      </div></div></div>`;
  }).join('');
  document.querySelectorAll('[data-upload]').forEach(b => b.onclick = () => { A.uploadFor = b.dataset.upload; $('doc-file').value = ''; $('doc-file').click(); });
  document.querySelectorAll('[data-demo]').forEach(sel => sel.onchange = async () => {
    if (!sel.value) return;
    const blob = await (await fetch('samples/' + sel.value)).blob();
    upload(sel.dataset.demo, new File([blob], sel.value, { type: blob.type }));
  });
}

async function openDocs() {
  const p = await loadProfile();
  if (!p) { notice(tr('कृपया पहले लॉगिन करें', 'Please log in first')); show('lang'); return; }
  renderDocs(p); show('docs'); say($('docs-guide').textContent);
}

async function upload(docType, file) {
  const form = new FormData();
  form.append('file', file, file.name);
  const r = await req('POST', `/api/profile/documents/${docType}`, form, true);
  if (!r.ok) { notice(r.data.message || 'Upload failed'); return; }
  A.profile = r.data.profile; renderDocs(A.profile); renderHomeAccount();
  const res = r.data.result;
  const failed = res.checks.filter(c => !c.ok).map(c => tr(c.hi, c.en)).join('. ');
  say(res.status === 'PASSED' ? tr('फ़ाइल ठीक है।', 'The file looks good.')
    : res.status === 'REVIEW' ? tr('फ़ाइल मिल गई, इसकी जाँच अधिकारी करेंगे।', 'File received; an officer will review it.') : failed);
}

$('doc-file').onchange = () => { const f = $('doc-file').files[0]; if (f && A.uploadFor) upload(A.uploadFor, f); };
$('attention').onclick = openDocs;
$('my-docs').onclick = openDocs;
$('logout').onclick = async () => { await req('POST', '/api/auth/logout'); saveToken(null); A.profile = null; renderHomeAccount(); show('lang'); };

(async () => {
  try { A.samples = (await (await fetch('/api/samples')).json()).samples; } catch (e) { A.samples = []; }
  A.token = loadToken();
  if (A.token) await loadProfile();
})();
