/* WealthView v1.20 - Setup: the places your data comes from (banks, investments, crypto), the things you type in (house, loan, fund, other
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
    property: [['name', 'Name', 'Flat Berlin'], ['country', 'Country (2 letters)', 'DE'], ['purchase_price', 'Purchase price, EUR', '250.000'], ['purchase_date', 'Purchase date', '15.03.2019'], ['current_estimate', 'Your own value today, EUR (optional)', '']],
    loan: [['name', 'Name', 'Mortgage'], ['amount', 'Amount borrowed, EUR', '180.000'], ['start_date', 'Start date', '15.03.2019'], ['rate_pct', 'Interest rate, % per year', '2,1'], ['monthly', 'Monthly payment, EUR (or the end date)', '850'], ['end_date', 'End date (optional if you gave the payment)', ''], ['property', 'Belongs to', '@property']],
    fund: [['name', 'Name', 'World ETF'], ['invested', 'Paid in so far, EUR', '5.000'], ['since', 'Paid in on', '01.02.2024'], ['current_value', 'Value today, EUR (optional)', ''], ['isin', 'ISIN (optional)', '']],
    other: [['name', 'Name', 'Gold coins'], ['value', 'Value today, EUR', '1.500'], ['date', 'As of (optional)', '']],
  };
  let D = null, tab = 'bank', note = '', pending = 0, form = null, pick = null, onKey = null;

  async function get(path) { const r = await W().api(path); if (!r.ok) throw new Error(r.error || 'could not load'); return r; }
  async function post(path, body) { const r = await W().api(path, { method: 'POST', headers: JSONH, body: JSON.stringify(body) }); if (!r.ok) throw new Error(r.error || 'could not save'); return r; }
  const root = () => document.getElementById('setupPop');
  const err = e => { const el = root(); if (el) el.insertAdjacentHTML('afterbegin', `<div class="or" style="padding:.4rem 0" id="setupErr">${e && e.locked ? 'Locked - unlock your real numbers again.' : esc(e && e.message || 'Something went wrong.')}</div>`); };
  async function reload() { D = await get('/api/setup/state'); return D; }
  async function change(path, body, msg) {
    const old = document.getElementById('setupErr'); if (old) old.remove();
    try { await post(path, body); pending++; note = msg || ''; form = null; pick = null; await reload(); draw(); } catch (e) { err(e); }
  }

  function open() {
    const w = W(); if (!w || w.S.mode !== 'real') return;
    css(); pending = 0; tab = 'bank'; note = ''; form = null; pick = null;
    w.modalShell('Setup · where your data comes from', w.badge('static', 'Your setup'), 'fit');
    const m = document.getElementById('modal'), done = () => { document.removeEventListener('keydown', onKey, true); const n = pending; pending = 0; w.closeModal(); if (n > 0) w.reloadData(); };
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
    const status = `<span class="dim" style="margin-left:auto">${pending ? pending + ' change' + (pending > 1 ? 's' : '') + ' saved - the dashboard updates when you close' : 'Changes are saved at once'}${note ? ' · ' + esc(note) : ''}</span>${pending ? '<button id="spApply" style="margin-left:.6rem">Update dashboard now</button>' : ''}`;
    el.innerHTML = `<div class="spb">${tabs}${status}</div><div class="spbody" id="spbody"></div>`;
    el.querySelectorAll('.sptab').forEach(b => b.onclick = () => { tab = b.dataset.t; form = null; pick = null; note = ''; draw(); });
    const ap = el.querySelector('#spApply'); if (ap) ap.onclick = async () => { ap.disabled = true; ap.textContent = 'Updating…'; const n = pending; const ok = await W().reloadData(); if (ok) pending = Math.max(0, pending - n); draw(); };
    const c = el.querySelector('#spbody');
    if (tab === 'questions') drawQuestions(c); else { drawSources(c, tab); if (tab === 'investment') drawAssets(c); if (tab === 'bank') drawBalances(c); }
  }

  const HELP = {
    bank: 'Add each bank, card or payment account you want to see. Choose the folder where you save its exports (CSV files). Sub-folders are read too. WealthView works out by itself what each file is.',
    investment: 'Add a depot or broker folder, and type in what has no export: a house or apartment, a loan, a fund, or anything else you own.',
    crypto: 'Add a folder with your crypto CSV exports, or connect an exchange through its API.',
  };

  function drawSources(c, section) {
    const list = D.sources.filter(s => s.section === section);
    const rows = list.map(s => `<div class="spr" data-id="${s.id}"><div class="spn"><input class="spi" data-a="rename" value="${esc(s.name)}" maxlength="80" aria-label="Name"><span class="dim xs">${s.source_type === 'api' ? 'connected through ' + esc(s.connector) : esc(s.folder)}</span></div>
      <div class="spo">${s.source_type === 'folder' ? `<label><input type="checkbox" data-a="subfolders" ${s.subfolders ? 'checked' : ''}> sub-folders</label>` : ''}<label><input type="checkbox" data-a="active" ${s.active ? 'checked' : ''}> on</label>
      <span class="dim xs">${s.accounts} account${s.accounts === 1 ? '' : 's'}</span>${s.source_type === 'folder' ? '<button data-a="folder">Change folder…</button>' : ''}<button data-a="delete">Remove</button></div></div>`).join('');
    const adding = form && form.add === section ? addForm(section) : `<button id="spAdd" class="spadd">+ Add ${section === 'bank' ? 'a bank or card' : section === 'investment' ? 'a depot or broker' : 'crypto'}</button>`;
    c.insertAdjacentHTML('beforeend', `<div class="cph">${esc(HELP[section])}</div>${rows || '<div class="dim" style="padding:.8rem 0">Nothing added yet.</div>'}${adding}`);
    c.querySelectorAll('.spr').forEach(r => {
      const id = +r.dataset.id;
      r.querySelectorAll('[data-a]').forEach(x => {
        const a = x.dataset.a;
        if (a === 'rename') x.onchange = () => change('/api/setup/source', { action: 'rename', id, name: x.value }, 'renamed');
        else if (a === 'subfolders' || a === 'active') x.onchange = () => change('/api/setup/source', { action: a, id, on: x.checked }, a === 'active' ? (x.checked ? 'switched on' : 'switched off') : '');
        else if (a === 'folder') x.onclick = () => { form = { pickFor: id }; pick = null; browse(''); };
        else if (a === 'delete') x.onclick = () => { if (confirm('Remove "' + (list.find(s => s.id === id) || {}).name + '"? Data already brought in stays; the place is only switched off.')) change('/api/setup/source', { action: 'delete', id }, 'removed'); };
      });
    });
    const add = c.querySelector('#spAdd'); if (add) add.onclick = () => { form = { add: section, name: '', folder: '', api: false }; draw(); };
    wireAdd(c, section);
    if (form && form.pickFor && pick) drawPicker(c);
  }

  function addForm(section) {
    const f = form;
    const where = section === 'crypto' ? `<label><input type="radio" name="spw" value="folder" ${f.api ? '' : 'checked'}> a folder of CSV files</label> <label><input type="radio" name="spw" value="api" ${f.api ? 'checked' : ''}> an exchange API</label><br>` : '';
    const tgt = f.api ? `<select id="spCon"><option value="coinbase">Coinbase</option></select> <span class="dim xs">The API key goes in your config file, never into this window.</span>` :
      `<input id="spFolder" class="spf" placeholder="Folder with the exports, e.g. C:\\Users\\you\\Documents\\Bank" value="${esc(f.folder)}"> <button id="spBrowse">Browse…</button>`;
    return `<div class="spform"><div class="cph">NEW</div>${where}<input id="spName" placeholder="Name, e.g. ${section === 'crypto' ? 'My exchange' : section === 'bank' ? 'My bank' : 'My broker'}" value="${esc(f.name)}" maxlength="80"><br>${tgt}
      <div style="margin-top:.5rem"><button id="spSave">Add</button> <button id="spCancel">Cancel</button></div><div id="spPick"></div></div>`;
  }

  function wireAdd(c, section) {
    if (!form || form.add !== section) return;
    const nm = c.querySelector('#spName'), fo = c.querySelector('#spFolder');
    const sync = () => { form.name = nm.value; if (fo) form.folder = fo.value; };
    nm.oninput = sync; if (fo) fo.oninput = sync;
    c.querySelectorAll('input[name=spw]').forEach(r => r.onchange = () => { sync(); form.api = r.value === 'api'; draw(); });
    const br = c.querySelector('#spBrowse'); if (br) br.onclick = () => { sync(); browse(fo.value.trim()); };
    c.querySelector('#spCancel').onclick = () => { form = null; pick = null; draw(); };
    c.querySelector('#spSave').onclick = () => {
      sync();
      const body = form.api ? { action: 'add', section, name: nm.value, source_type: 'api', connector: c.querySelector('#spCon').value } : { action: 'add', section, name: nm.value, folder: form.folder };
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
    if (a.kind === 'property') return `bought ${f.purchase_date} for ${fmt(f.purchase_price)}${f.current_estimate ? ' · your value ' + fmt(f.current_estimate) : ' · value follows the house price index (estimate)'}`;
    if (a.kind === 'loan') return `${fmt(f.amount)} at ${String(f.rate_pct).replace('.', ',')} % from ${f.start_date}${f.monthly ? ' · ' + fmt(f.monthly) + ' a month' : ''}${f.property ? ' · ' + esc(f.property) : ''}`;
    if (a.kind === 'fund') return `${fmt((f.payments || []).reduce((s, p) => s + p.amount, 0))} paid in${f.current_value ? ' · worth ' + fmt(f.current_value) : ' · shown at cost'}`;
    return `worth ${fmt(f.value)}`;
  }

  function assetForm() {
    const f = form, props = D.assets.filter(a => a.kind === 'property').map(a => a.name);
    const inputs = FIELDS[f.kind].map(([k, label, ph]) => ph === '@property'
      ? `<label class="spl">${esc(label)}<select data-f="${k}"><option value="">(none)</option>${props.map(p => `<option ${f.vals[k] === p ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select></label>`
      : `<label class="spl">${esc(label)}<input data-f="${k}" placeholder="${esc(ph)}" value="${esc(f.vals[k] == null ? '' : f.vals[k])}"></label>`).join('');
    const hint = f.kind === 'property' ? '<div class="dim xs" style="margin-top:.3rem">Without your own value, WealthView follows the official house price index of your country (Eurostat) and labels the number "estimate". Only the country code is sent for that, nothing else.</div>' : '';
    return `<div class="spform"><div class="cph">${f.id ? 'EDIT' : 'NEW'} · ${esc(KINDS[f.kind]).toUpperCase()}</div><div class="spg">${inputs}</div>${hint}<div style="margin-top:.5rem"><button id="spSaveA">Save</button> <button id="spCancel">Cancel</button></div></div>`;
  }

  function wireAsset(c) {
    c.querySelectorAll('[data-f]').forEach(x => x.oninput = x.onchange = () => { form.vals[x.dataset.f] = x.value; });
    c.querySelector('#spCancel').onclick = () => { form = null; draw(); };
    c.querySelector('#spSaveA').onclick = () => {
      const fields = Object.assign({}, form.vals); if (form.id && form.kind === 'fund') delete fields.payments;
      change('/api/setup/asset', form.id ? { action: 'update', id: form.id, fields } : { action: 'add', kind: form.kind, fields }, 'saved');
    };
  }

  function drawBalances(c) {
    const acc = D.accounts.filter(a => a.kind === 'bank' || a.kind === 'card');
    if (!acc.length) return;
    const today = new Date().toISOString().slice(0, 10);
    c.insertAdjacentHTML('beforeend', `<div class="cph" style="margin-top:1.2rem">ACCOUNT BALANCES · only needed when an account's files do not show a balance</div>${acc.map(a => `<div class="spr" data-aid="${a.id}"><div class="spn"><b>${esc(a.name)}</b> ${a.balance != null ? `<span class="dim xs">typed: ${fmt(a.balance)} on ${esc(a.balance_date)}</span>` : ''}</div>
      <div class="spo"><input class="spi" style="width:8rem" data-b placeholder="Balance, EUR"><button data-a="bal">Save balance</button></div></div>`).join('')}`);
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
    s.textContent = `.setupbox{width:min(92vw,76rem);height:min(76vh,50rem);min-height:24rem;display:flex;flex-direction:column}.spb{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;border-bottom:1px solid rgba(60,190,235,.25);padding-bottom:.5rem}
.sptab{padding:.35rem .9rem}.sptab.on{border-color:var(--or);color:var(--or);background:rgba(255,154,61,.1)}.spq{background:var(--or);color:#000;padding:0 .4rem;font-size:.68rem}.spbody{flex:1;overflow:auto;padding:.7rem .2rem}
.spr{display:flex;justify-content:space-between;gap:1rem;align-items:center;padding:.5rem .3rem;border-bottom:1px solid rgba(60,190,235,.12);flex-wrap:wrap}.spn{min-width:0;flex:1 1 18rem}.spo{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.spo label{font-size:.74rem;color:var(--dim)}.spi,.spform input,.spform select,.spl input,.spl select{background:rgba(0,16,26,.85);color:#fff;border:1px solid rgba(60,190,235,.35);padding:.3rem .5rem;font:inherit;font-size:.8rem}
.spn .spi{width:min(100%,22rem);font-size:.9rem}.spform{margin-top:.8rem;padding:.8rem;border:1px solid rgba(60,190,235,.3);background:rgba(60,190,235,.04)}.spform input#spName{width:min(100%,22rem);margin-bottom:.4rem}
.spf{width:min(100%,34rem)}.spg{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:.6rem}.spl{display:flex;flex-direction:column;gap:.2rem;font-size:.7rem;color:var(--dim)}.spadd{margin:.5rem .4rem 0 0}
.sppick{margin-top:.6rem;max-height:14rem;overflow:auto;border:1px solid rgba(60,190,235,.25);padding:.4rem}.spd{padding:.25rem .4rem;cursor:pointer}.spd:hover{background:rgba(60,190,235,.1)}.spo button.on{border-color:var(--or);color:var(--or)}`;
    document.head.appendChild(s);
  }
  window.WVS = { open };
})();
