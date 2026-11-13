/* WealthView v1.15 - category corrections: a pop-up to fix wrong classifications fast.
   Pick a merchant, click the right category -> saved as a rule ("always put X in Y"); single bookings can be corrected on their own.
   Rules live in the database (never in your bank files) and apply on every refresh. Needs window.WV and a real-numbers session. */
(function () {
  'use strict';
  const W = () => window.WV;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf0 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
  const eur = v => nf0.format(Math.round(v)) + ' €';
  const SONST = 'Sonstiges', JSONH = { 'content-type': 'application/json' };
  const label = c => c === SONST ? 'Unsorted' : c;
  let D = null, note = '', pending = 0, sel = null, tab = 'fix', only = 'sonstiges', q = '', onKey = null;

  const colOf = c => { const P = W().PAL; if (c === SONST) return '#6c8392'; let h = 0; for (const ch of c) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return P[h % P.length]; };
  async function get() { const r = await W().api('/api/cat/overview?only=' + only + '&q=' + encodeURIComponent(q)); if (!r.ok) throw new Error(r.error || 'could not load'); return r; }
  async function post(path, body) { const r = await W().api(path, { method: 'POST', headers: JSONH, body: JSON.stringify(body) }); if (!r.ok) throw new Error(r.error || 'could not save'); return r; }

  function open() {
    const w = W(); if (!w || w.S.mode !== 'real') return;
    css(); pending = 0; sel = null; tab = 'fix'; only = 'sonstiges'; q = '';
    w.modalShell('Fix categories · teach WealthView', w.badge('static', 'Your rules'), 'fit');
    const m = document.getElementById('modal'), done = () => { document.removeEventListener('keydown', onKey, true); const n = pending; pending = 0; w.closeModal(); if (n > 0) w.reloadData(); };
    document.getElementById('mx').onclick = done; m.onclick = e => { if (e.target === m) done(); };
    onKey = e => { if (!document.getElementById('catPop')) { document.removeEventListener('keydown', onKey, true); return; } if (e.key === 'Escape') done(); else keys(e); };
    document.addEventListener('keydown', onKey, true);
    document.getElementById('mbody').style.overflow = 'hidden';
    document.getElementById('mbody').innerHTML = '<div class="cp" id="catPop"><div class="dim" style="padding:2rem"><span class="spinner"></span> loading…</div></div>';
    reload().then(draw).catch(err);
  }
  const err = e => { const el = document.getElementById('catPop'); if (el) el.innerHTML = `<div class="or" style="padding:1.5rem">${e && e.locked ? 'Locked - unlock your real numbers again.' : esc(e && e.message || 'Something went wrong.')}</div>`; };
  async function reload() { D = await get(); if (!sel || !D.merchants.find(x => x.n === sel)) sel = D.merchants.length ? D.merchants[0].n : null; return D; }

  function draw() {
    const el = document.getElementById('catPop'); if (!el) return;
    const tools = document.getElementById('mtools');
    tools.innerHTML = `<span class="fseg"><button data-t="fix" class="${tab === 'fix' ? 'on' : ''}">Fix</button><button data-t="rules" class="${tab === 'rules' ? 'on' : ''}">My rules (${D.rules.length})</button></span>` +
      (tab === 'fix' ? `<span class="fseg" style="margin-left:.8rem"><button data-o="sonstiges" class="${only === 'sonstiges' ? 'on' : ''}">Unsorted only</button><button data-o="all" class="${only === 'all' ? 'on' : ''}">All merchants</button></span><input id="catQ" type="search" placeholder="Search merchant…" value="${esc(q)}" style="margin-left:.8rem;width:15rem">` : '') +
      `<span class="dim" id="catSt" style="margin-left:auto">${pending ? pending + ' change' + (pending > 1 ? 's' : '') + ' saved - the dashboard updates when you close' : 'Changes are saved at once'}${note ? ' · ' + note : ''}</span>${pending ? '<button id="catApply" style="margin-left:.6rem">Update dashboard now</button>' : ''}`;
    const ap = tools.querySelector('#catApply'); if (ap) ap.onclick = async () => { ap.disabled = true; ap.textContent = 'Updating…'; const n = pending; const ok = await W().reloadData(); if (ok) pending = Math.max(0, pending - n); draw(); };
    tools.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tab = b.dataset.t; draw(); });
    tools.querySelectorAll('[data-o]').forEach(b => b.onclick = async () => { only = b.dataset.o; try { await reload(); draw(); } catch (e) { err(e); } });
    const qi = tools.querySelector('#catQ'); if (qi) { qi.oninput = () => { clearTimeout(qi.t); qi.t = setTimeout(async () => { q = qi.value; try { await reload(); drawList(); drawSide(); } catch (e) { err(e); } }, 250); }; qi.onkeydown = e => e.stopPropagation(); }
    if (tab === 'rules') { el.innerHTML = '<div class="cpr" id="catRules"></div>'; drawRules(); return; }
    el.innerHTML = '<div class="cpl" id="catList"></div><div class="cps" id="catSide"></div>'; drawList(); drawSide();
  }

  function drawList() {
    const el = document.getElementById('catList'); if (!el) return;
    if (!D.merchants.length) { el.innerHTML = `<div class="dim" style="padding:1.5rem;line-height:1.6">${only === 'sonstiges' ? '🎉 Nothing unsorted' + (q ? ' matching “' + esc(q) + '”' : '') + '. Switch to “All merchants” to review or change any category.' : 'No merchants match.'}</div>`; return; }
    const mx = Math.max(...D.merchants.map(x => only === 'sonstiges' ? x.unsorted : x.total), 1);
    el.innerHTML = `<div class="dim cph">${D.total_merchants} merchant${D.total_merchants === 1 ? '' : 's'}${D.total_merchants > D.merchants.length ? ' · biggest ' + D.merchants.length + ' shown' : ''} · ↑ ↓ to move</div>` + D.merchants.map(x => {
      const v = only === 'sonstiges' ? x.unsorted : x.total;
      return `<div class="cpm ${x.n === sel ? 'on' : ''}" data-n="${esc(x.n)}"><div class="cpt"><span class="cpn">${esc(x.n)}</span><span class="amt">${eur(v)}</span></div><div class="cpb"><i style="width:${Math.max(2, v / mx * 100)}%;background:${colOf(x.cat)}"></i></div><div class="cpd"><span class="chip" style="border-color:${colOf(x.cat)}">${esc(label(x.cat))}${x.mixed ? ' +' : ''}</span><span>${x.count} booking${x.count === 1 ? '' : 's'} · last ${esc(x.last)}</span></div></div>`;
    }).join('');
    el.querySelectorAll('.cpm').forEach(r => r.onclick = () => { sel = r.dataset.n; drawList(); drawSide(); });
    const on = el.querySelector('.cpm.on'); if (on) on.scrollIntoView({ block: 'nearest' });
  }

  function drawSide() {
    const el = document.getElementById('catSide'); if (!el) return; const x = D.merchants.find(m => m.n === sel);
    if (!x) { el.innerHTML = '<div class="dim" style="padding:1.5rem">Pick a merchant on the left.</div>'; return; }
    const rule = D.rules.find(r => r.kind === 'merchant' && r.pattern.toLowerCase() === x.n.toLowerCase());
    const chips = D.categories.map(c => `<button class="cc ${c === x.cat && !x.mixed ? 'on' : ''}" data-c="${esc(c)}" style="--cc:${colOf(c)}">${esc(label(c))}</button>`).join('');
    el.innerHTML = `<h4>${esc(x.n)}</h4><div class="dim">${eur(x.total)} in ${x.count} booking${x.count === 1 ? '' : 's'}${x.mixed ? ' · categories are mixed' : ''}</div>
      <div class="cph" style="margin-top:.9rem">PUT ALL BOOKINGS OF THIS MERCHANT IN…</div><div class="ccs">${chips}</div>
      <div class="cnew"><input id="catNew" type="text" maxlength="40" placeholder="…or a new category"><button id="catNewGo">Create &amp; apply</button></div>
      ${rule ? `<div class="dim" style="margin-top:.7rem">Rule saved: always <b style="color:#fff">${esc(label(rule.category))}</b> · <a href="#" id="catRm">remove rule</a></div>` : ''}
      <div class="cph" style="margin-top:1rem">RECENT BOOKINGS · correct just one</div>
      <div class="cpbk">${x.samples.map(s => `<div class="bk"><span class="dim">${esc(s.date)}</span><span class="bkp" title="${esc(s.purpose)}">${esc(s.purpose)}</span><span class="amt">${eur(s.amount)}</span><select data-k="${esc(s.key)}">${D.categories.map(c => `<option value="${esc(c)}" ${c === s.cat ? 'selected' : ''}>${esc(label(c))}</option>`).join('')}</select>${s.fixed ? `<a href="#" class="bkx" data-k="${esc(s.key)}" title="Undo this correction">↺</a>` : '<span></span>'}</div>`).join('')}</div>`;
    el.querySelectorAll('.cc').forEach(b => b.onclick = () => setMerchant(x, b.dataset.c));
    const ng = el.querySelector('#catNewGo'), ni = el.querySelector('#catNew'); ni.onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter') ng.click(); };
    ng.onclick = () => { const v = ni.value.replace(/\s+/g, ' ').trim(); if (v) setMerchant(x, v); };
    const rm = el.querySelector('#catRm'); if (rm) rm.onclick = async e => { e.preventDefault(); try { await post('/api/cat/delete', { id: rule.id }); pending++; await reload(); draw(); } catch (er) { err(er); } };
    el.querySelectorAll('select[data-k]').forEach(s => s.onchange = async () => { try { const r = await post('/api/cat/set', { scope: 'booking', key: s.dataset.k, category: s.value, name: x.n }); pending++; note = r.applied ? 'also applied to ' + r.applied + ' other booking' + (r.applied === 1 ? '' : 's') + ' of ' + x.n + ' (undo with ↺)' : ''; await reload(); draw(); } catch (er) { err(er); } });
    el.querySelectorAll('.bkx').forEach(a => a.onclick = async e => { e.preventDefault(); try { await post('/api/cat/delete', { key: a.dataset.k }); pending++; await reload(); draw(); } catch (er) { err(er); } });
  }

  async function setMerchant(x, cat) {
    try {
      await post('/api/cat/set', { scope: 'merchant', name: x.n, category: cat }); pending++;
      const idx = D.merchants.findIndex(m => m.n === x.n), nextName = D.merchants[idx + 1] ? D.merchants[idx + 1].n : (D.merchants[idx - 1] ? D.merchants[idx - 1].n : null);
      await reload(); sel = only === 'sonstiges' ? (D.merchants.find(m => m.n === nextName) ? nextName : sel) : x.n;      // keep going: the next unsorted merchant is selected
      draw();
    } catch (e) { err(e); }
  }

  function drawRules() {
    const el = document.getElementById('catRules'); if (!el) return;
    const by = {}; D.rules.forEach(r => (by[r.category] = by[r.category] || []).push(r));
    el.innerHTML = D.rules.length || D.fixed ? `<div class="dim cph">${D.rules.length} rule${D.rules.length === 1 ? '' : 's'}${D.fixed ? ' · ' + D.fixed + ' single-booking correction' + (D.fixed === 1 ? '' : 's') + ' (undo them under “Fix” → recent bookings)' : ''}</div>` +
      Object.keys(by).sort().map(c => `<div class="cpg"><div class="chip" style="border-color:${colOf(c)}">${esc(label(c))}</div>${by[c].map(r => `<span class="rl">${esc(r.pattern)}${r.kind === 'text' ? ' <i class="dim">(keyword)</i>' : ''}<a href="#" data-id="${r.id}" title="Delete rule">×</a></span>`).join('')}</div>`).join('') :
      '<div class="dim" style="padding:1.5rem;line-height:1.6">No rules yet. On the “Fix” tab, pick a merchant and click its category: that becomes a rule here.</div>';
    el.querySelectorAll('a[data-id]').forEach(a => a.onclick = async e => { e.preventDefault(); try { await post('/api/cat/delete', { id: a.dataset.id }); pending++; await reload(); draw(); } catch (er) { err(er); } });
  }

  function keys(e) {
    if (tab !== 'fix' || !D || !D.merchants.length) return; const t = e.target && e.target.tagName; if (t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA') return;
    const i = D.merchants.findIndex(m => m.n === sel);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const j = Math.max(0, Math.min(D.merchants.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1))); sel = D.merchants[j].n; drawList(); drawSide(); }
  }

  let cssDone = false;
  function css() {
    if (cssDone) return; cssDone = true; const s = document.createElement('style');
    s.textContent = `.cp{display:flex;gap:1rem;width:min(92vw,98rem);height:min(76vh,50rem);min-height:24rem}.cpl{width:27rem;flex:none;overflow:auto;border-right:1px solid rgba(60,190,235,.25);padding-right:.6rem}
.cps{flex:1;min-width:0;overflow:auto;padding:.1rem .4rem .5rem .2rem}.cpr{flex:1;overflow:auto}.cps h4{margin:0 0 .2rem;font-weight:400;font-size:1.15rem;color:#fff;letter-spacing:.06em}
.cph{font-size:.62rem;letter-spacing:.16em;color:var(--dim);margin:.2rem 0 .4rem}.cpm{padding:.45rem .5rem;border:1px solid transparent;border-bottom-color:rgba(60,190,235,.1);cursor:pointer}.cpm:hover{background:rgba(60,190,235,.06)}
.cpm.on{border-color:var(--or);background:rgba(255,154,61,.07)}.cpt{display:flex;justify-content:space-between;gap:.6rem}.cpn{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#fff}
.cpb{height:.22rem;background:rgba(60,190,235,.1);margin:.3rem 0}.cpb i{display:block;height:100%}.cpd{display:flex;justify-content:space-between;gap:.6rem;font-size:.68rem;color:var(--dim);align-items:center}
.chip{display:inline-block;border:1px solid;padding:0 .45rem;font-size:.66rem;letter-spacing:.06em;color:#dff3fa}.ccs{display:flex;flex-wrap:wrap;gap:.4rem}
.cc{border-left:.3rem solid var(--cc);padding:.35rem .7rem;font-size:.78rem;text-transform:none;letter-spacing:.02em}.cc.on{background:rgba(255,154,61,.12);border-color:var(--or);border-left-color:var(--cc);color:var(--or)}
.cnew{display:flex;gap:.4rem;margin-top:.7rem}.cnew input{flex:1;min-width:0}.cpbk{font-size:.74rem}.bk{display:grid;grid-template-columns:5.5rem minmax(0,1fr) 5rem 11rem 1.2rem;gap:.5rem;align-items:center;padding:.25rem 0;border-bottom:1px solid rgba(60,190,235,.08)}
.bkp{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.bk select{background:rgba(0,16,26,.85);color:#fff;border:1px solid rgba(60,190,235,.35);padding:.15rem .3rem;font:inherit;font-size:.72rem}.bkx{color:var(--or);text-decoration:none}
.cpg{display:flex;flex-wrap:wrap;gap:.4rem .6rem;align-items:center;margin:.5rem 0;padding-bottom:.5rem;border-bottom:1px solid rgba(60,190,235,.1)}.cpg .chip{min-width:9rem}
.rl{border:1px solid rgba(60,190,235,.3);padding:.1rem .5rem;font-size:.76rem}.rl a{margin-left:.5rem;color:var(--rd);text-decoration:none}#catPop a{color:var(--c2)}
@media (max-width:1100px){.cp{flex-direction:column;height:auto}.cpl{width:auto;max-height:18rem;border-right:0}}`;
    document.head.appendChild(s);
  }
  window.WVC = { open };
})();
