/* WealthView v1.21 - Setup: the places your data comes from (banks, investments, crypto), the things you type in (house, loan, fund, other
   investments), balances of accounts whose files carry none, and the plain questions about files WealthView could not place by itself.
   Nothing is typed twice: the same setup exists in the installer. Everything is saved at once; the dashboard updates when you close this window
   (or press "Update dashboard now"). Needs window.WV and a real-numbers session. */
(function () {
  'use strict';
  const W = () => window.WV;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const JSONH = { 'content-type': 'application/json' };
  const TABS = [['bank', 'Banks & cards'], ['investment', 'Investments'], ['crypto', 'Crypto'], ['questions', 'Questions']];
  const KINDS = { property: 'House / apartment', loan: 'Loan', fund: 'Fund', other: 'Other investment' };
  const FIELDS = {
    property: [['name', 'Name', 'Flat Berlin'], ['country', 'Country (2 letters)', 'DE'], ['purchase_price', 'Purchase price, EUR', '250.000'], ['purchase_date', 'Purchase date', '15.03.2019'], ['area', 'Kind of area (Germany: picks the official price index)', '@area'], ['size_m2', 'Size, m² (optional)', '75'], ['price_per_m2', 'Your own local price per m², EUR (optional, replaces the index)', '4.200'], ['current_estimate', 'Your own value today, EUR (optional, replaces everything)', '']],
    loan: [['name', 'Name', 'Mortgage'], ['amount', 'Amount borrowed, EUR', '180.000'], ['start_date', 'Start date', '15.03.2019'], ['rate_pct', 'Interest rate, % per year', '2,1'], ['monthly', 'Monthly payment, EUR (or the end date)', '850'], ['end_date', 'End date (optional if you gave the payment)', ''], ['property', 'Belongs to', '@property']],
    fund: [['name', 'Name', 'World ETF'], ['invested', 'Paid in so far, EUR', '5.000'], ['since', 'Paid in on', '01.02.2024'], ['current_value', 'Value today, EUR (optional)', ''], ['folder', 'Folder with your reports (PDF or CSV, optional)', 'C:\\Users\\you\\Documents\\MyFund'], ['isin', 'ISIN (optional, for the price)', 'IE00B4L5Y983'], ['units', 'Number of units (with the ISIN)', '120,5']],
    other: [['name', 'Name', 'Gold coins'], ['value', 'Value today, EUR', '1.500'], ['date', 'As of (optional)', '']],
  };
  /* fields that must be filled before Save (the others are optional); checked here so the missing one is marked right in the form */
  const REQUIRED = { property: ['name', 'country', 'purchase_price', 'purchase_date'], loan: ['name', 'amount', 'start_date', 'rate_pct'], fund: ['name', 'invested', 'since'], other: ['name', 'value'] };
  let D = null, tab = 'bank', note = '', pending = 0, form = null, pick = null, onKey = null;
  const TESTS = {};      /* v1.22: result of the last connection test per API place: { busy } or { works, text } */

  async function get(path) { const r = await W().api(path); if (!r.ok) throw new Error(r.error || 'could not load'); return r; }
  async function post(path, body) { const r = await W().api(path, { method: 'POST', headers: JSONH, body: JSON.stringify(body) }); if (!r.ok) throw new Error(r.error || 'could not save'); return r; }
  const root = () => document.getElementById('setupPop');
  /* a problem is shown next to the Save button of the open form (where the eye is); without a form, at the top of the window */
  const err = e => {
    const el = root(); if (!el) return;
    const old = document.getElementById('setupErr'); if (old) old.remove();
    const txt = e && e.locked ? 'Locked - unlock your real numbers again.' : (e && e.message || 'Something went wrong.');
    const html = `<div class="sperr" id="setupErr" role="alert">Not saved: ${esc(txt)}</div>`;
    const slot = el.querySelector('.spform .spmsg');
    if (slot) slot.innerHTML = html; else el.insertAdjacentHTML('afterbegin', html);
  };
  async function reload() { D = await get('/api/setup/state'); return D; }
  async function change(path, body, msg) {
    const old = document.getElementById('setupErr'); if (old) old.remove();
    let r; try { r = await post(path, body); pending++; note = msg || ''; form = null; pick = null; await reload(); draw(); } catch (e) { err(e); return; }
    /* a new API place or a new key is tried at once, so a wrong key shows here and not as a missing number on the dashboard */
    const tid = body.source_type === 'api' && r && r.id ? r.id : body.action === 'keys' ? body.id : 0; if (tid) testNow(tid);
  }

  async function testNow(id) {
    TESTS[id] = { busy: true }; draw();
    try { const r = await post('/api/setup/test', { id }); TESTS[id] = { works: !!r.works, text: r.text }; } catch (e) { TESTS[id] = { works: false, text: e && e.message || 'the test did not finish' }; }
    draw();
  }
  const testLine = s => { const t = TESTS[s.id]; return !t ? '' : t.busy ? '<span class="dim xs sppath"><span class="spinner"></span> testing the connection…</span>' : `<span class="xs sppath ${t.works ? 'pos' : 'or'}">${t.works ? '✓ ' : '✗ could not be read: '}${esc(t.text)}</span>`; };

  function open() {
    /* a valid session (token) is enough to manage sources - do NOT require S.mode === 'real', or a broken
       source that makes /api/real fail (loadReal's catch) would lock the user out of the one screen that
       can fix it */
    const w = W(); if (!w || !w.S.token) return;
    css(); pending = 0; tab = 'bank'; note = ''; form = null; pick = null;
    w.modalShell('Setup · where your data comes from', w.badge('static', 'Your setup'), 'fit');
    const box = document.getElementById('mdl'); if (box) box.classList.add('wide');      /* v1.21: wide enough for every row, so no sideways scroll bar */
    const m = document.getElementById('modal'), done = () => { document.removeEventListener('keydown', onKey, true); const n = pending; pending = 0; w.closeModal(); if (n > 0) { w.S.mode === 'real' ? w.reloadData() : w.loadReal(false); } };
    document.getElementById('mx').onclick = done; m.onclick = e => { if (e.target === m) done(); };
    onKey = e => { if (!root()) { document.removeEventListener('keydown', onKey, true); return; } if (e.key === 'Escape' && !(e.target && e.target.tagName === 'INPUT')) done(); };
    document.addEventListener('keydown', onKey, true);
    document.getElementById('mbody').innerHTML = '<div class="setupbox" id="setupPop"><div class="dim" style="padding:2rem"><span class="spinner"></span> loading…</div></div>';
    reload().then(draw).catch(err);
  }

  function draw() {
    const el = root(); if (!el || !D) return;
    const nq = D.questions.length;
    const tabs = TABS.map(([k, n]) => `<button class="sptab ${k === tab ? 'on' : ''}" data-t="${k}">${esc(n)}${k === 'questions' && nq ? ` <b class="spq">${nq}</b>` : ''}</button>`).join('');
    const status = `<span class="dim spstat">${pending ? pending + ' change' + (pending > 1 ? 's' : '') + ' saved - the dashboard updates when you close' : 'Changes are saved at once'}${note ? ' · ' + esc(note) : ''}</span>${pending ? '<button id="spApply">Update dashboard now</button>' : ''}`;
    el.innerHTML = `<div class="spb">${tabs}${status}</div><div class="spbody" id="spbody"></div>`;
    el.querySelectorAll('.sptab').forEach(b => b.onclick = () => { tab = b.dataset.t; form = null; pick = null; note = ''; draw(); });
    const ap = el.querySelector('#spApply'); if (ap) ap.onclick = async () => { ap.disabled = true; ap.textContent = 'Updating…'; const n = pending; const ok = await W().reloadData(); if (ok) pending = Math.max(0, pending - n); draw(); };
    const c = el.querySelector('#spbody');
    if (tab === 'questions') drawQuestions(c); else { drawSources(c, tab); if (tab === 'investment') drawAssets(c); if (tab === 'bank') drawBalances(c); }
  }

  const HELP = {
    bank: 'Add each bank, card or payment account you want to see. Choose the folder where you save its exports (CSV files) - sub-folders are read too and WealthView works out by itself what each file is - or connect it through an API.',
    investment: 'Add a depot or broker (a folder of exports, or an API connection), and type in what has no export: a house or apartment, a loan, a fund, or anything else you own.',
    crypto: 'Add a folder with your crypto CSV exports, or connect an exchange through its API with a read-only key: Coinbase, Binance or Kraken.',
  };

  function drawSources(c, section) {
    const list = D.sources.filter(s => s.section === section);
    const rows = list.map(s => `<div class="spr" data-id="${s.id}"><div class="spn"><input class="spi" data-a="rename" value="${esc(s.name)}" maxlength="80" aria-label="Name"><span class="dim xs sppath">${s.source_type === 'api' ? esc(apiLine(s)) : esc(s.folder)}</span>${s.source_type === 'api' ? testLine(s) : ''}</div>
      <div class="spo">${s.source_type === 'folder' ? `<label><input type="checkbox" data-a="subfolders" ${s.subfolders ? 'checked' : ''}> sub-folders</label>` : ''}<label><input type="checkbox" data-a="active" ${s.active ? 'checked' : ''}> on</label>
      ${s.source_type === 'api' && !s.accounts ? '' : `<span class="dim xs">${s.accounts} account${s.accounts === 1 ? '' : 's'}</span>`}${s.source_type === 'folder' ? '<button data-a="folder">Change folder…</button>' : ((conOf(s.connector) || {}).ready ? '<button data-a="test">Test</button>' : '') + '<button data-a="keys">' + (s.has_keys ? 'Change key…' : 'Enter key…') + '</button>'}<button data-a="delete">Remove</button></div>${form && form.keysFor === s.id ? keysForm(s) : ''}</div>`).join('');
    const adding = form && form.add === section ? addForm(section) : `<button id="spAdd" class="spadd">+ Add ${section === 'bank' ? 'a bank or card' : section === 'investment' ? 'a depot or broker' : 'crypto'}</button>`;
    c.insertAdjacentHTML('beforeend', `<div class="cph">${esc(HELP[section])}</div>${rows || '<div class="dim" style="padding:.8rem 0">Nothing added yet.</div>'}${adding}`);
    c.querySelectorAll('.spr').forEach(r => {
      const id = +r.dataset.id;
      r.querySelectorAll('[data-a]').forEach(x => {
        const a = x.dataset.a;
        if (a === 'rename') x.onchange = () => change('/api/setup/source', { action: 'rename', id, name: x.value }, 'renamed');
        else if (a === 'subfolders' || a === 'active') x.onchange = () => change('/api/setup/source', { action: a, id, on: x.checked }, a === 'active' ? (x.checked ? 'switched on' : 'switched off') : '');
        else if (a === 'folder') x.onclick = () => { form = { pickFor: id }; pick = null; browse(''); };
        else if (a === 'test') x.onclick = () => testNow(id);
        else if (a === 'keys') x.onclick = () => { form = { keysFor: id, keys: {} }; pick = null; draw(); };
        else if (a === 'delete') x.onclick = () => { if (confirm('Remove "' + (list.find(s => s.id === id) || {}).name + '"? Data already brought in stays; the place is only switched off.')) change('/api/setup/source', { action: 'delete', id }, 'removed'); };
      });
    });
    const add = c.querySelector('#spAdd'); if (add) add.onclick = () => { form = { add: section, name: '', folder: '', api: false, con: '', keys: {} }; draw(); };
    wireAdd(c, section);
    wireKeys(c);
    if (form && form.pickFor && pick) drawPicker(c);
  }

  /* ---- API connections (v1.21): every kind of place can be read from a folder of exports OR through an API.
     Keys are typed here once, sent to the WealthView program on this PC and stored in the Windows Credential Manager.
     They are never shown again, never written to a file of WealthView and never kept in this page. ---- */
  const consFor = section => (D.connectors || []).filter(k => k.sections.indexOf(section) >= 0);
  const conOf = id => (D.connectors || []).find(k => k.id === id);
  function apiLine(s) {
    const k = conOf(s.connector), name = k ? k.label : s.connector;
    if (k && !k.ready) return 'through ' + name + ' · details saved · reading not switched on yet';
    return 'connected through ' + name + ' · ' + (s.has_keys ? 'key stored in Windows' : k && k.env_ready ? 'uses the key already set up on this PC' : 'NO KEY YET - click "Enter key…"');
  }
  function keyFields(k, vals) {
    return `<div class="spg">${k.fields.map(f => `<label class="spl">${esc(f.label)}<input data-k="${esc(f.key)}" type="${f.secret ? 'password' : 'text'}" autocomplete="${f.secret ? 'new-password' : 'off'}" spellcheck="false" placeholder="${esc(f.hint ? 'e.g. ' + f.hint : '')}" value="${esc(vals[f.key] || '')}"></label>`).join('')}</div>
      <div class="dim xs sphint">${esc(k.note)}${k.env_ready ? ' This PC already has a key for ' + esc(k.label) + ': leave the fields empty to keep using it.' : ''}${D.keys_possible ? ' The key is stored in the Windows Credential Manager of your user account, not in a WealthView file.' : ' Keys can only be stored on Windows.'}</div>`;
  }
  function keysForm(s) {
    const k = conOf(s.connector); if (!k) return '';
    return `<div class="spform spkeys"><div class="cph">${s.has_keys ? 'NEW KEY' : 'KEY'} · ${esc(k.label).toUpperCase()}</div>${keyFields(k, form.keys || {})}
      <div class="spact"><button id="spSaveK">Save key</button> <button id="spCancelK">Cancel</button><span class="spmsg"></span></div></div>`;
  }
  function wireKeys(c) {
    if (!form || !form.keysFor) return;
    const box = c.querySelector('.spkeys'); if (!box) return;
    const read = () => { box.querySelectorAll('[data-k]').forEach(x => { form.keys[x.dataset.k] = x.value; }); };
    box.querySelector('#spCancelK').onclick = () => { form = null; draw(); };
    box.querySelector('#spSaveK').onclick = () => { read(); change('/api/setup/source', { action: 'keys', id: form.keysFor, keys: form.keys }, 'key saved'); };
  }

  function addForm(section) {
    const f = form, cons = consFor(section);
    if (f.api && !conOf(f.con)) f.con = cons.length ? cons[0].id : '';
    const k = f.api ? conOf(f.con) : null;
    const where = `<div class="spwhere"><label><input type="radio" name="spw" value="folder" ${f.api ? '' : 'checked'}> a folder of CSV files</label><label><input type="radio" name="spw" value="api" ${f.api ? 'checked' : ''} ${cons.length ? '' : 'disabled'}> an API connection</label></div>`;
    const tgt = f.api ? `<label class="spl spsvc">Service<select id="spCon">${cons.map(x => `<option value="${esc(x.id)}" ${x.id === f.con ? 'selected' : ''}>${esc(x.label)}${x.ready ? '' : ' (not switched on yet)'}</option>`).join('')}</select></label>${k ? keyFields(k, f.keys) : ''}` :
      `<div class="sprow"><input id="spFolder" class="spf" placeholder="Folder with the exports, e.g. C:\\Users\\you\\Documents\\Bank" value="${esc(f.folder)}"> <button id="spBrowse">Browse…</button></div>`;
    return `<div class="spform"><div class="cph">NEW</div>${where}<input id="spName" placeholder="Name, e.g. ${section === 'crypto' ? 'My exchange' : section === 'bank' ? 'My bank' : 'My broker'}" value="${esc(f.name)}" maxlength="80">${tgt}
      <div class="spact"><button id="spSave">Add</button> <button id="spCancel">Cancel</button><span class="spmsg"></span></div><div id="spPick"></div></div>`;
  }

  function wireAdd(c, section) {
    if (!form || form.add !== section) return;
    const nm = c.querySelector('#spName'), fo = c.querySelector('#spFolder'), con = c.querySelector('#spCon');
    const sync = () => { form.name = nm.value; if (fo) form.folder = fo.value; c.querySelectorAll('.spform [data-k]').forEach(x => { form.keys[x.dataset.k] = x.value; }); };
    nm.oninput = sync; if (fo) fo.oninput = sync;
    c.querySelectorAll('input[name=spw]').forEach(r => r.onchange = () => { sync(); form.api = r.value === 'api'; draw(); });
    if (con) con.onchange = () => { sync(); form.con = con.value; form.keys = {}; draw(); };
    const br = c.querySelector('#spBrowse'); if (br) br.onclick = () => { sync(); browse(fo.value.trim()); };
    c.querySelector('#spCancel').onclick = () => { form = null; pick = null; draw(); };
    c.querySelector('#spSave').onclick = () => {
      sync();
      if (!nm.value.trim()) { nm.classList.add('bad'); nm.focus(); return err({ message: 'please give it a name' }); }
      const body = form.api ? { action: 'add', section, name: nm.value, source_type: 'api', connector: form.con, keys: form.keys } : { action: 'add', section, name: nm.value, folder: form.folder };
      change('/api/setup/source', body, 'added');
    };
    if (pick) drawPicker(c);
  }

  async function browse(path) {
    try { pick = await get('/api/setup/browse?path=' + encodeURIComponent(path)); } catch (e) { pick = null; err(e); return; }
    draw();
  }

  function drawPicker(c) {
    const host = c.querySelector('#spPick') || c; if (!pick) return;
    const dirs = pick.dirs.map(d => `<div class="spd" data-p="${esc(d.path)}">📁 ${esc(d.name)}</div>`).join('');
    host.insertAdjacentHTML('beforeend', `<div class="sppick"><div class="cph">PICK A FOLDER${pick.path ? ' · ' + esc(pick.path) : ''}${pick.path ? ` · ${pick.csv_files} CSV file${pick.csv_files === 1 ? '' : 's'} here` : ''}</div>
      ${pick.parent !== null && pick.path ? `<div class="spd" data-p="${esc(pick.parent)}">⬆ one level up</div>` : pick.path ? '<div class="spd" data-p="">⬆ start places</div>' : ''}${dirs || '<div class="dim xs">No sub-folders.</div>'}
      <div style="margin-top:.4rem">${pick.path ? '<button id="spUse">Use this folder</button> ' : ''}${form && form.pickFor ? '<button id="spPickCancel">Cancel</button>' : ''}</div></div>`);
    const pc = host.querySelector('#spPickCancel'); if (pc) pc.onclick = () => { form = null; pick = null; draw(); };
    host.querySelectorAll('.spd').forEach(d => d.onclick = () => browse(d.dataset.p));
    const use = host.querySelector('#spUse'); if (use) use.onclick = () => {
      if (form && form.pickFor) return change('/api/setup/source', { action: 'folder', id: form.pickFor, folder: pick.path }, 'folder changed');
      form.folder = pick.path; pick = null; draw();
    };
  }

  function drawAssets(c) {
    const rows = D.assets.map(a => `<div class="spr" data-id="${a.id}"><div class="spn"><b>${esc(a.name)}</b> <span class="dim xs">${esc(KINDS[a.kind])}</span><br><span class="dim xs">${esc(summary(a))}</span></div>
      <div class="spo"><button data-a="edit">Edit</button><button data-a="del">Remove</button></div></div>`).join('');
    const kinds = Object.keys(KINDS).map(k => `<button class="spadd" data-k="${k}">+ ${esc(KINDS[k])}</button>`).join(' ');
    c.insertAdjacentHTML('beforeend', `<div class="cph" style="margin-top:1.2rem">THINGS YOU TYPE IN</div>${rows || '<div class="dim" style="padding:.6rem 0">Nothing typed in yet.</div>'}${form && form.kind ? assetForm() : `<div style="margin-top:.5rem">${kinds}</div>`}`);
    c.querySelectorAll('.spadd[data-k]').forEach(b => b.onclick = () => { form = { kind: b.dataset.k, vals: {} }; draw(); });
    c.querySelectorAll('.spr[data-id] [data-a=del]').forEach(b => b.onclick = () => { const id = +b.closest('.spr').dataset.id; if (confirm('Remove this entry?')) change('/api/setup/asset', { action: 'delete', id }, 'removed'); });
    c.querySelectorAll('.spr[data-id] [data-a=edit]').forEach(b => b.onclick = () => { const id = +b.closest('.spr').dataset.id, a = D.assets.find(x => x.id === id); form = { kind: a.kind, id, vals: flat(a) }; draw(); });
    if (form && form.kind) wireAsset(c);
  }

  const flat = a => { const v = Object.assign({}, a.fields); if (a.kind === 'fund' && Array.isArray(v.payments) && v.payments.length === 1) { v.invested = v.payments[0].amount; v.since = v.payments[0].date; } return v; };
  const fmt = n => new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }).format(Math.round(n)) + ' €';
  function summary(a) {
    const f = a.fields;
    if (a.kind === 'property') return `bought ${f.purchase_date} for ${fmt(f.purchase_price)}${f.current_estimate ? ' · your value ' + fmt(f.current_estimate) : f.price_per_m2 && f.size_m2 ? ' · your price ' + fmt(f.price_per_m2) + ' per m²' : ' · value follows the official house price index (estimate)'}`;
    if (a.kind === 'loan') return `${fmt(f.amount)} at ${String(f.rate_pct).replace('.', ',')} % from ${f.start_date}${f.monthly ? ' · ' + fmt(f.monthly) + ' a month' : ''}${f.property ? ' · ' + esc(f.property) : ''}`;
    if (a.kind === 'fund') return `${fmt((f.payments || []).reduce((s, p) => s + p.amount, 0))} paid in${f.current_value ? ' · worth ' + fmt(f.current_value) : ' · shown at cost'}`;
    return `worth ${fmt(f.value)}`;
  }

  function assetForm() {
    const f = form, props = D.assets.filter(a => a.kind === 'property').map(a => a.name), req = REQUIRED[f.kind] || [];
    const AREAS = [['', 'Other country'], ['city', 'City (not one of the 7 largest)'], ['big7', 'One of the 7 largest cities (Berlin, Hamburg, Munich, Cologne, Frankfurt, Stuttgart, Düsseldorf)'], ['district', 'Town or rural district'], ['germany', 'Germany average']];
    const inputs = FIELDS[f.kind].map(([k, label, ph]) => ph === '@area'
      ? `<label class="spl">${esc(label)}<select data-f="${k}">${AREAS.map(([v, n]) => `<option value="${v}" ${(f.vals[k] || ((f.vals.country || 'DE').toUpperCase() === 'DE' ? 'city' : '')) === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>`
      : ph === '@property'
      ? `<label class="spl">${esc(label)}<select data-f="${k}"><option value="">(none)</option>${props.map(p => `<option ${f.vals[k] === p ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select></label>`
      : `<label class="spl"><span>${esc(label)}${req.indexOf(k) >= 0 ? ' <b class="spreq" title="needed">*</b>' : ''}</span><input data-f="${k}" placeholder="${esc(ph ? 'e.g. ' + ph : '')}" value="${esc(f.vals[k] == null ? '' : f.vals[k])}"></label>`).join('');
    const hint = f.kind === 'property' ? '<div class="dim xs" style="margin-top:.3rem">Without your own value, WealthView follows the official price index: in Germany the Bundesbank index for your kind of area (7 largest cities, other cities, towns and rural districts, or the Germany average), elsewhere the Eurostat index of the country. The number is labelled "estimate". Only the index name is requested, never your address or price. Type your own price per m² (and the size) to override the index. Immowelt and ImmoScout have no public interface and forbid automated reading, so they are not used.</div>' : '';
    return `<div class="spform"><div class="cph">${f.id ? 'EDIT' : 'NEW'} · ${esc(KINDS[f.kind]).toUpperCase()}</div><div class="spg">${inputs}</div>${hint}<div class="dim xs sphint"><b class="spreq">*</b> needed. The grey text in an empty field is only an example.</div><div class="spact"><button id="spSaveA">Save</button> <button id="spCancel">Cancel</button><span class="spmsg"></span></div></div>`;
  }

  function wireAsset(c) {
    c.querySelectorAll('[data-f]').forEach(x => x.oninput = x.onchange = () => { form.vals[x.dataset.f] = x.value; });
    c.querySelector('#spCancel').onclick = () => { form = null; draw(); };
    c.querySelector('#spSaveA').onclick = () => {
      /* read the fields themselves (a value the browser filled in fires no input event), then name the first needed field that is still empty */
      const ins = Array.from(c.querySelectorAll('.spform [data-f]')); ins.forEach(x => { form.vals[x.dataset.f] = x.value; x.classList.remove('bad'); });
      const need = (REQUIRED[form.kind] || []).filter(k => !(k === 'invested' || k === 'since' ? form.id : false)), empty = ins.filter(x => need.indexOf(x.dataset.f) >= 0 && !String(x.value).trim());
      if (empty.length) {
        empty.forEach(x => x.classList.add('bad')); empty[0].focus();
        const names = empty.map(x => (FIELDS[form.kind].find(d => d[0] === x.dataset.f) || [0, x.dataset.f])[1].replace(/ \(.*$/, '').replace(/, EUR.*$/, ''));
        return err({ message: 'please fill in ' + names.join(', ') + ' (the grey text was only an example)' });
      }
      const fields = Object.assign({}, form.vals); if (form.id && form.kind === 'fund') delete fields.payments;
      change('/api/setup/asset', form.id ? { action: 'update', id: form.id, fields } : { action: 'add', kind: form.kind, fields }, 'saved');
    };
  }

  function drawBalances(c) {
    const acc = D.accounts.filter(a => a.kind === 'bank' || a.kind === 'card');
    if (!acc.length) return;
    const today = new Date().toISOString().slice(0, 10);
    c.insertAdjacentHTML('beforeend', `<div class="cph" style="margin-top:1.2rem">ACCOUNT BALANCES · only needed when an account's files do not show a balance</div>${acc.map(a => `<div class="spr" data-aid="${a.id}"><div class="spn"><b>${esc(a.name)}</b> ${a.balance != null ? `<span class="dim xs">typed: ${fmt(a.balance)} on ${esc(a.balance_date)}</span>` : ''}</div>
      <div class="spo"><input class="spi" style="width:9rem" data-b placeholder="Balance, EUR"><button data-a="bal">Save</button></div></div>`).join('')}`);
    c.querySelectorAll('.spr[data-aid]').forEach(r => r.querySelector('[data-a=bal]').onclick = () => change('/api/setup/balance', { account_id: +r.dataset.aid, value: r.querySelector('[data-b]').value, date: today }, 'balance saved'));
  }

  function drawQuestions(c) {
    if (!D.questions.length) { c.innerHTML = '<div class="dim" style="padding:1.5rem">No open questions. When WealthView cannot tell what a file is, it asks here, once per kind of file.</div>'; return; }
    c.innerHTML = '<div class="cph">WEALTHVIEW COULD NOT TELL WHAT THESE FILES ARE · ONE CLICK EACH, REMEMBERED FOR ALL FILES OF THE SAME KIND</div>' + D.questions.map(q => `<div class="spr" data-q="${q.id}"><div class="spn"><b>${esc(q.file)}</b><br><span class="dim xs">${'What kind of file is this?'}</span></div>
      <div class="spo">${q.options.map(o => `<button data-v="${esc(o.value)}" class="${o.value === q.guess ? 'on' : ''}">${esc(o.label)}${o.value === q.guess ? ' (my guess)' : ''}</button>`).join('')}</div></div>`).join('');
    c.querySelectorAll('.spr[data-q]').forEach(r => r.querySelectorAll('[data-v]').forEach(b => b.onclick = () => change('/api/setup/answer', { id: +r.dataset.q, value: b.dataset.v }, 'answered - the files are read at the next update')));
  }

  let cssDone = false;
  function css() {
    if (cssDone) return; cssDone = true; const s = document.createElement('style');
    s.textContent = `.modal.wide{width:min(98vw,max(64vw,86rem))}
.setupbox{width:100%;min-width:0;min-height:min(56vh,30rem);display:flex;flex-direction:column;font-size:max(var(--minfs,0px),.86rem)}
.spb{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;border-bottom:1px solid rgba(60,190,235,.25);padding-bottom:.5rem}
.spstat{flex:1 1 14rem;text-align:right;min-width:0;font-size:max(var(--minfs,0px),.78rem)}
.sptab{padding:.35rem .9rem}.sptab.on{border-color:var(--or);color:var(--or);background:rgba(255,154,61,.1)}.spq{background:var(--or);color:#000;padding:0 .4rem;font-size:max(var(--minfs,0px),.72rem)}
.spbody{flex:1;min-width:0;padding:.7rem .2rem}.spbody .cph{line-height:1.5}
.spr{display:flex;justify-content:space-between;gap:.6rem 1rem;align-items:center;padding:.55rem .3rem;border-bottom:1px solid rgba(60,190,235,.12);flex-wrap:wrap}
.spn{min-width:0;flex:1 1 18rem}.spo{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;min-width:0}.sppath{display:block;margin-top:.2rem;overflow-wrap:anywhere}
.spr .spform{flex:1 1 100%}
.setupbox .xs{font-size:max(var(--minfs,0px),.74rem)}
.spo label,.spwhere label{font-size:max(var(--minfs,0px),.8rem);color:var(--dim);display:inline-flex;align-items:center;gap:.3rem;white-space:nowrap}
.spi,.spform input:not([type=radio]):not([type=checkbox]),.spform select{background:rgba(0,16,26,.85);color:#fff;border:1px solid rgba(60,190,235,.35);padding:.35rem .5rem;font:inherit;font-size:max(var(--minfs,0px),.86rem);max-width:100%;min-width:0;box-sizing:border-box}
.spform input::placeholder,.spi::placeholder{color:rgba(127,220,255,.38);font-style:italic}
.spform input.bad{border-color:var(--or);box-shadow:0 0 0 1px var(--or)}
.spn .spi{width:min(100%,22rem);font-size:max(var(--minfs,0px),.92rem)}
.spform{margin-top:.8rem;padding:.8rem;border:1px solid rgba(60,190,235,.3);background:rgba(60,190,235,.04);min-width:0}
.spform input#spName{display:block;width:min(100%,22rem);margin:.4rem 0 .5rem}
.spwhere{display:flex;gap:.4rem 1.4rem;flex-wrap:wrap;margin:.2rem 0}.sprow{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}.spf{flex:1 1 16rem;width:auto}
.spg{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(14rem,100%),1fr));gap:.6rem}
.spl{display:flex;flex-direction:column;gap:.2rem;font-size:max(var(--minfs,0px),.76rem);color:var(--dim);min-width:0}.spl input,.spl select{width:100%}.spsvc{max-width:22rem;margin-bottom:.6rem}
.spreq{color:var(--or);font-weight:400}.sphint{margin-top:.4rem;line-height:1.5}
.spact{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin-top:.6rem}.spmsg{flex:1 1 12rem;min-width:0}
.sperr{color:var(--or);border-left:3px solid var(--or);padding:.3rem .6rem;background:rgba(255,154,61,.08);font-size:max(var(--minfs,0px),.86rem)}
.spadd{margin:.5rem .4rem 0 0}
.sppick{margin-top:.6rem;max-height:14rem;overflow-y:auto;overflow-x:hidden;border:1px solid rgba(60,190,235,.25);padding:.4rem}.spd{padding:.25rem .4rem;cursor:pointer;overflow-wrap:anywhere}.spd:hover{background:rgba(60,190,235,.1)}.spo button.on{border-color:var(--or);color:var(--or)}`;
    document.head.appendChild(s);
  }
  window.WVS = { open };
})();
