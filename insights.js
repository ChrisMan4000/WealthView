/* WealthView v1.15 - "Over time" box, digest items for Smart suggestions, database line for System status, and the Ask box.
   Reads data.insights / data.db (built by insights.py / refresh.py). Needs window.WV (exposed by wv.js). */
(function () {
  'use strict';
  const W = () => window.WV;
  const nf0 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }), nf1 = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const sA = v => v == null || isNaN(v) ? '–' : (v >= 0 ? '+' : '–') + W().A(Math.abs(v)).replace('<span class="amt">', '<span class="amt">');
  const sP = v => v == null || isNaN(v) ? '' : (v >= 0 ? '+' : '–') + nf1.format(Math.abs(v)) + ' %';
  const cls = v => v >= 0 ? 'pos' : 'neg';
  const dmy = iso => String(iso).slice(8, 10) + '.' + String(iso).slice(5, 7) + '.';
  const blurAmts = h => h.replace(/(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?(?:\s[kM])?)(\s?(?:€|EUR))/g, '<span class="amt">$1$2</span>');

  /* ------------------------------------------------------------------ demo numbers (fictional, only so the box shows something in demo mode) */
  function demoInsights(d) {
    const base = (d.totals && d.totals.assets) || 1e6, n = 75, days = [], gross = [], t0 = new Date(); t0.setDate(t0.getDate() - n);
    for (let i = 0; i < n; i++) { const t = new Date(t0); t.setDate(t.getDate() + i); days.push(t.toISOString().slice(0, 10)); gross.push(Math.round(base * (0.93 + 0.0009 * i + 0.012 * Math.sin(i / 6)))); }
    const last = gross[n - 1];
    return { curve: { days, gross, n_days: n, first: days[0] },
      changes: [{ label: '7 days', days: 7, base: days[n - 8], partial: false, span_days: 7, gross: last - gross[n - 8], gross_pct: (last / gross[n - 8] - 1) * 100 }, { label: '30 days', days: 30, base: days[n - 31], partial: false, span_days: 30, gross: last - gross[n - 31], gross_pct: (last / gross[n - 31] - 1) * 100 }, { label: '3 months', days: 90, base: days[0], partial: true, span_days: n - 1, gross: last - gross[0], gross_pct: (last / gross[0] - 1) * 100 }],
      saved_vs_market: { ready: true, frm: days[0], to: days[n - 1], delta: last - gross[0], saved: base * 0.012, market: last - gross[0] - base * 0.012 },
      spend_vs_norm: { ready: true, month: 'last month', items: [{ cat: 'Dining & Delivery', value: 640, norm: 410, delta: 230, pct: 56 }, { cat: 'Travel', value: 120, norm: 380, delta: -260, pct: -68 }] },
      yoy: { ready: true, now: { income: 96000, expense: 61000, saved: 35000 }, prev: { income: 90000, expense: 62000, saved: 28000 }, change_pct: { income: 6.7, expense: -1.6, saved: 25 } },
      recurring: { ready: true, now: 1450, ago: 1310, n: 14, creep: [{ n: 'Streaming (demo)', was: 12.99, now: 15.99, pct: 23 }], new: [] }, digest: [] };
  }

  /* ------------------------------------------------------------------ chart: recorded gross assets */
  function chart(c) {
    const ds = c.days || [], v = c.gross || [];
    if (ds.length < 2) return `<div class="dim sm" style="padding:.6rem 0">Recording started${ds.length ? ' on ' + dmy(ds[0]) + (ds[0].slice(0, 4) ? ds[0].slice(0, 4) : '') : ''}. WealthView saves one real value per day from now on - a line appears as soon as there are two days. Nothing here is estimated.</div>`;
    const pts = ds.map((x, i) => [i, v[i]]).filter(p => p[1] != null), lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1])), pad = (hi - lo) * 0.12 || hi * 0.01 || 1, y0 = lo - pad, y1 = hi + pad;
    const X = i => 4 + (i / (ds.length - 1)) * 592, Y = val => 4 + (1 - (val - y0) / (y1 - y0)) * 72;
    const line = pts.map((p, k) => (k ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(' ');
    const area = line + ` L${X(pts[pts.length - 1][0]).toFixed(1)} 78 L${X(pts[0][0]).toFixed(1)} 78 Z`;
    const dots = pts.length <= 400 ? pts.map(p => `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="3" fill="transparent"><title>${ds[p[0]]}: ${nf0.format(Math.round(p[1]))} €</title></circle>`).join('') : '';
    return `<svg viewBox="0 0 600 82" preserveAspectRatio="none" style="width:100%;height:5.2rem;display:block" class="amtsvg"><path d="${area}" fill="rgba(25,211,255,.13)"/><path d="${line}" fill="none" stroke="#19d3ff" stroke-width="1.6" vector-effect="non-scaling-stroke"/>${dots}</svg>` +
      `<div class="xs dim" style="display:flex;justify-content:space-between"><span>${ds[0]}</span><span>${ds.length} recorded days · real values</span><span>${ds[ds.length - 1]}</span></div>`;
  }

  /* ------------------------------------------------------------------ the box */
  function card(title, body, tip) { return `<div class="otc" ${tip ? `title="${W().esc(tip)}"` : ''}><div class="otn">${title}</div>${body}</div>`; }
  function pTime(d) {
    const w = W(); w.POST.push(() => { try { place(); } catch (e) { console.error(e); } });
    const I = d.insights || (d.mode === 'demo' ? demoInsights(d) : null);
    const bd = d.mode === 'demo' ? w.badge('demo', 'Demo') : w.badge('live', 'Recorded by WealthView');
    if (!I) return w.panel('pTime', 'Over time <b>//</b> your real history', bd, '<div class="dim sm">Press <b>Refresh data</b> once: WealthView then builds its database and starts recording one value per day.</div>', { style: 'flex:1.3;min-height:9rem' });
    const chips = (I.changes || []).map(c => `<span class="otchip" title="${c.partial ? 'History is shorter than this span: counted from ' + c.base : 'Since ' + c.base}">${c.partial ? 'since ' + dmy(c.base) : c.label}: <b class="${cls(c.gross || 0)}">${sA(c.gross)} ${c.gross_pct != null ? '(' + sP(c.gross_pct) + ')' : ''}</b></span>`).join('') || '<span class="dim xs">Changes appear after the second recorded day.</span>';
    const svm = I.saved_vs_market || {}, s1 = svm.ready ? card('Saved vs market', `<div class="otv">${sA(svm.saved)} <span class="dim xs">saved</span></div><div class="otv">${sA(svm.market)} <span class="dim xs">market & other</span></div><div class="xs dim">${dmy(svm.frm)} → ${dmy(svm.to)} · estimate</div>`, 'Change of gross assets split into what you saved (income minus spending) and the rest (prices, valuations).') : card('Saved vs market', `<div class="dim xs">Needs ${svm.need_days || 28} recorded days (have ${svm.have_days || 0}). Then gross-asset growth is split into money you saved and market moves.</div>`);
    const sp = I.spend_vs_norm || {}, s2 = sp.ready ? card('Spending vs your norm · ' + sp.month, (sp.items || []).slice(0, 4).map(i => `<div class="otr"><span>${w.esc(i.cat)}</span><span class="${i.delta > 0 ? 'neg' : 'pos'}">${sA(i.delta)} ${i.pct != null ? '<span class="xs">' + sP(i.pct) + '</span>' : ''}</span></div>`).join('') || '<div class="dim xs">Nothing far from your usual.</div>', 'Last full month against the median of your previous 12 months, per category.') : card('Spending vs your norm', `<div class="dim xs">${w.esc(sp.reason || '')}</div>`);
    const rc = I.recurring || {}, s3 = rc.ready ? card('Recurring costs', `<div class="otv">${w.A(rc.now)} <span class="dim xs">a month · ${rc.n} payments</span></div>${rc.ago != null ? `<div class="xs dim">a year ago: ${w.A(rc.ago)}</div>` : ''}${(rc.creep || []).slice(0, 2).map(c => `<div class="otr"><span>${w.esc(c.n)}</span><span class="neg xs">${nf1.format(c.was)} → ${nf1.format(c.now)} € (${sP(c.pct)})</span></div>`).join('')}`, 'Payments that appear nearly every month, and those that got more expensive.') : card('Recurring costs', `<div class="dim xs">${w.esc(rc.reason || '')}</div>`);
    const y = I.yoy || {}, s4 = y.ready ? card('Year over year · to ' + y.to, ['income', 'expense', 'saved'].map(k => `<div class="otr"><span>${k}</span><span>${w.A(y.now[k])} <span class="${(k === 'expense' ? -1 : 1) * (y.change_pct[k] || 0) >= 0 ? 'pos' : 'neg'} xs">${sP(y.change_pct[k])}</span></span></div>`).join(''), 'Last 12 full months against the 12 months before.') : card('Year over year', `<div class="dim xs">${w.esc(y.reason || '')}</div>`);
    return w.panel('pTime', 'Over time <b>//</b> your real history', bd, `<div style="overflow:auto;flex:1;min-height:0"><div class="otchips">${chips}</div>${chart(I.curve || {})}<div class="otg">${s1}${s2}${s3}${s4}</div></div>`, { style: 'flex:1.9;min-height:12rem' });
  }

  /* ------------------------------------------------------------------ Smart suggestions + System status */
  function tipItems(d) { const I = d.insights; return I && I.digest ? I.digest.map(x => ({ l: x.l, t: x.t, x: x.x })) : []; }
  function dbLine(d) {
    const b = d.db; if (!b || !b.counts) return '';
    const c = b.counts, li = b.last_import, w = W();
    return `<div class="xs dim" style="margin-top:.4rem;border-top:1px solid rgba(60,190,235,.2);padding-top:.35rem">Database <b class="wh">${w.esc(b.file)}</b>${b.size_kb ? ' · ' + nf0.format(b.size_kb) + ' KB' : ''}: <b class="wh">${nf0.format(c.bookings)}</b> bookings${c.bookings_from ? ' (' + w.esc(c.bookings_from) + ' → ' + w.esc(c.bookings_to) + ')' : ''}, <b class="wh">${nf0.format(c.paypal_tx)}</b> PayPal, <b class="wh">${c.snap_days || 0}</b> recorded day${c.snap_days === 1 ? '' : 's'}.` +
      (li ? `<br>Last import: <b class="wh">${(li.new_files || []).length}</b> file(s), ${nf0.format(li.new_bookings || 0)} bookings, ${nf0.format(li.new_paypal || 0)} PayPal · ${w.esc(String(li.at || '').replace('T', ' ').slice(0, 16))}` : '') +
      `<br>${c.sources ? '<b class="wh">' + nf0.format(c.sources) + '</b> source(s), <b class="wh">' + nf0.format(c.accounts || 0) + '</b> account(s). ' : ''}New downloads in your source folders (and their sub-folders) are imported automatically.</div>`;
  }

  /* ------------------------------------------------------------------ Ask box (v1.15: fixed bar under the grid, auto-growing box, voice input, sources) */
  const A = { hist: [], busy: false, st: null, stAt: 0, box: null, rec: null };
  function esc(s) { return W().esc(s); }
  /* v1.17: the model writes **bold**; show it bold (input is already HTML-escaped, so this only adds <b>) */
  const mdBold = s => String(s).replace(/\*\*([^*\n]+?)\*\*/g, '<b class="wh">$1</b>');
  const safeHref = u => /^https?:\/\//i.test(String(u || '').trim()) ? String(u).trim() : '';
  function askUI() {
    if (document.getElementById('chat')) return;
    const st = document.createElement('style');
    st.textContent = `#chat{position:relative;flex:none;box-sizing:border-box;min-width:0;z-index:30;display:flex;flex-direction:column;gap:.25rem}
@media (max-aspect-ratio:22/10){#chat{width:auto;margin:0 .9rem .8rem}}
#chatInfo{display:flex;justify-content:space-between;font-size:0.648rem;letter-spacing:.06em;color:var(--dim);text-transform:uppercase;gap:.6rem;min-width:0}#chatInfo span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#chatInfo span:last-child{flex:0 1 auto}#chatInfo b{color:var(--c2);font-weight:400}
#log{display:none;position:absolute;left:0;right:0;bottom:100%;margin-bottom:.35rem;max-height:62vh;overflow:auto;box-sizing:border-box;border:1px solid rgba(25,211,255,.35);background:rgba(0,16,26,.96);padding:.5rem .8rem;font-size:0.864rem;line-height:1.45}#log.on{display:block}
#log .q{color:#fff;margin:.35rem 0 .1rem}#log .q::before{content:"YOU > ";opacity:.5}#log .a{margin:.1rem 0 .3rem;white-space:pre-wrap}#log .a::before{content:"WEALTHVIEW > ";opacity:.6;color:var(--or)}#log .e{color:var(--rd)}
#log details{font-size:0.72rem;color:var(--dim);margin:0 0 .4rem}#log pre{margin:.2rem 0;white-space:pre-wrap;color:#9fb4c4}#logx{position:absolute;right:.4rem;top:.3rem;padding:0 .4rem}
#log .srcs{font-size:0.72rem;color:var(--dim);margin:0 0 .5rem}#log .srcs a{color:var(--c2);text-decoration:none;margin-right:.8rem;white-space:nowrap}#log .srcs a:hover{color:var(--or)}
#chatBar{display:flex;gap:.5rem;align-items:stretch}#chatBtns{display:flex;flex-direction:column;gap:.3rem;flex:none;width:4.6rem}
#chatIn{flex:1;min-width:0;box-sizing:border-box;font:inherit;font-size:0.936rem;line-height:1.4;height:3.4rem;max-height:11rem;resize:none;overflow-y:auto;background:rgba(0,16,26,.85);border:1px solid rgba(60,190,235,.45);color:#fff;padding:.4rem .6rem;outline:none;transition:min-height .15s}
#chatIn:focus{border-color:var(--or)}#chat.act #chatIn{min-height:5.6rem}
#chatBtns button{flex:1;min-height:1.55rem;padding:.1rem .5rem;width:100%}#chatMic{font-size:1rem;padding:.1rem .4rem !important}#chatMic.on{border-color:var(--rd);color:var(--rd);animation:pl 1s infinite}
.otchips{display:flex;flex-wrap:wrap;gap:.3rem .8rem;margin-bottom:.3rem;font-size:0.72rem}.otchip b{font-weight:400}
.otg{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.4rem;margin-top:.4rem}.otc{border:1px solid rgba(60,190,235,.22);padding:.3rem .45rem;background:rgba(0,20,32,.4)}
.otn{font-size:0.62rem;letter-spacing:.12em;text-transform:uppercase;color:var(--or);margin-bottom:.2rem}.otv{font-size:0.95rem;color:#fff}.otr{display:flex;justify-content:space-between;gap:.5rem;font-size:0.74rem;padding:.05rem 0}`;
    document.head.appendChild(st);
    const box = document.createElement('div'); box.id = 'chat';
    box.innerHTML = '<div id="log"><button id="logx" title="Close">✕</button><div id="logb"></div></div><div id="chatInfo"><span id="chatSt">Ask anything</span><span>your data stays on this PC · web look-ups send only search words</span></div><div id="chatBar"><textarea id="chatIn" rows="1" autocomplete="off" spellcheck="false" maxlength="1500"></textarea><div id="chatBtns"><button id="chatMic" title="Speak your question">🎤</button><button id="chatGo">Ask</button></div></div>';
    A.box = box; document.body.appendChild(box);
    const inp = document.getElementById('chatIn'), go = document.getElementById('chatGo'), mic = document.getElementById('chatMic');
    const grow = () => { inp.style.height = 'auto'; inp.style.height = Math.max(Math.min(inp.scrollHeight + 2, 176), 54) + 'px'; act(); };
    const act = () => box.classList.toggle('act', document.activeElement === inp || !!inp.value || A.hist.length > 0 || document.getElementById('log').classList.contains('on'));
    A.grow = grow; A.act = act;
    inp.addEventListener('input', grow); inp.addEventListener('focus', act); inp.addEventListener('blur', act);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } e.stopPropagation(); });
    go.onclick = send; document.getElementById('logx').onclick = () => { document.getElementById('log').classList.remove('on'); A.hist = []; document.getElementById('logb').innerHTML = ''; act(); };
    /* voice input: the browser's speech recognition (Chrome / Edge / Safari). Firefox has none - the button then says so. */
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) mic.title = 'Voice input is not available in this browser (Chrome or Edge have it)';
    else mic.title = 'Speak your question (the browser may send the audio to its speech service)';
    mic.onclick = () => {
      if (!SR) { addLog('<div class="a e">Voice input is not supported by this browser (Firefox has no speech recognition). Open WealthView in Chrome or Edge to dictate.</div>'); return; }
      if (A.rec) { A.rec.stop(); return; }
      const r = new SR(), base = inp.value.trim(); r.lang = navigator.language || 'en-US'; r.interimResults = true; r.continuous = false;
      r.onresult = ev => { let t = ''; for (const x of ev.results) t += x[0].transcript; inp.value = (base ? base + ' ' : '') + t; grow(); };
      r.onerror = ev => { addLog('<div class="a e">Voice input stopped: ' + esc(ev.error || 'error') + (ev.error === 'not-allowed' ? ' - allow the microphone for this page.' : '') + '</div>'); };
      r.onend = () => { A.rec = null; mic.classList.remove('on'); inp.focus(); };
      try { r.start(); A.rec = r; mic.classList.add('on'); } catch (e) { A.rec = null; }
    };
    window.addEventListener('resize', place); setInterval(sync, 1000); sync(); place();
  }
  /* wide screen: the bar is the LAST ITEM of the centre column, so the boxes above it give up space instead of running underneath it;
     stacked screens: it sits in the flow after the grid. (Before v1.17 it was position:fixed over the bottom of the centre column.) */
  function place() {
    const c = A.box, ctr = document.getElementById('center'), grid = document.getElementById('grid'); if (!c || !ctr || !grid) return;
    const wide = getComputedStyle(grid).position === "fixed";
    if (wide) { if (c.parentNode !== ctr) ctr.appendChild(c); }
    else if (c.parentNode !== document.body) document.body.appendChild(c);
    c.style.left = ''; c.style.width = '';
  }
  function sync() {
    const w = W(); if (!w || !w.S) return; const real = w.S.mode === 'real', inp = document.getElementById('chatIn'), go = document.getElementById('chatGo'), st = document.getElementById('chatSt'); if (!inp) return;
    place(); inp.disabled = go.disabled = !real || A.busy;
    inp.placeholder = real ? 'Ask about your portfolio, the markets, taxes or what to do next...' : 'Unlock real numbers (🔒) to ask';
    inp.title = real ? 'e.g. "Is my portfolio too concentrated in TSMC?" - Enter sends, Shift+Enter makes a new line' : 'Unlock your real numbers (🔒) to ask questions';
    if (real && Date.now() - A.stAt > 60000 && !A.busy) { A.stAt = Date.now(); w.api('/api/ask/status').then(r => { A.st = r; paintSt(); }).catch(() => { }); } else paintSt();
  }
  function paintSt() { const st = document.getElementById('chatSt'); if (!st) return; const s = A.st; st.innerHTML = W().S.mode !== 'real' ? 'Ask anything · locked' : !s ? 'Ask anything' : s.ok ? 'Ask anything // local model <b>' + esc(s.model) + '</b>' : '<span class="or">▲ ' + esc(s.error || 'LM Studio not reachable') + '</span>'; }
  function addLog(html) { const l = document.getElementById('log'), b = document.getElementById('logb'); l.classList.add('on'); b.insertAdjacentHTML('beforeend', html); l.scrollTop = l.scrollHeight; if (A.act) A.act(); }
  async function send() {
    const w = W(), inp = document.getElementById('chatIn'), q = (inp.value || '').trim(); if (!q || A.busy || w.S.mode !== 'real') return;
    if (A.rec) A.rec.stop();
    inp.value = ''; A.grow(); A.busy = true; sync(); addLog(`<div class="q">${esc(q)}</div><div class="a" id="pend"><span class="spinner"></span> thinking… (a local model can need a minute; web look-ups add a few seconds)</div>`);
    let out;
    try { out = await w.api('/api/ask', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question: q, history: A.hist }) }); }
    catch (e) { out = { ok: false, error: e.locked ? 'Locked - unlock your real numbers again.' : 'The server did not answer.' }; }
    const p = document.getElementById('pend'); if (p) p.removeAttribute('id');
    const qs = (out.queries || []).map(x => `<pre>${esc(x.sql)}${x.error ? '\n-- refused: ' + esc(x.error) : '\n-- ' + x.rows + ' row(s)' + (x.truncated ? ', cut off' : '')}</pre>`).join('');
    const srcs = (out.sources || []).filter(s => safeHref(s.url)).map(s => `<a href="${esc(safeHref(s.url))}" target="_blank" rel="noopener noreferrer" title="${esc(s.url)}">${esc(s.title || s.url)}</a>`).join('');
    const searches = (out.searches || []).map(s => esc(s.q)).join(' · ');
    const html = out.ok ? `<div class="a">${mdBold(blurAmts(esc(out.answer || '')))}</div>` + (srcs ? `<div class="srcs">Sources: ${srcs}</div>` : '') + (searches ? `<div class="srcs">Searched the web for: ${searches}</div>` : '') : `<div class="a e">${esc(out.error || 'Something went wrong.')}</div>` + (out.detail ? `<div class="srcs">Details: ${esc(String(out.detail).slice(0, 300))}</div>` : '');
    if (p) p.outerHTML = html; else addLog(html);
    if (qs) addLog(`<details><summary>${out.queries.length} database quer${out.queries.length === 1 ? 'y' : 'ies'} used - check the answer against these</summary>${qs}</details>`);
    if (out.ok) { A.hist.push({ role: 'user', content: q }, { role: 'assistant', content: out.answer }); A.hist = A.hist.slice(-8); }
    A.busy = false; A.stAt = 0; sync(); const l = document.getElementById('log'); l.scrollTop = l.scrollHeight; A.act();
  }
  window.addEventListener('DOMContentLoaded', () => setTimeout(askUI, 0));
  window.WVI = { pTime, tipItems, dbLine, demoInsights, place };
})();
