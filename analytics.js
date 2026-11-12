/* WealthView v1.06 - portfolio analysis (what professional wealth managers look at).
   Reads data.analytics (built by analytics.py) and renders: smart-suggestion items, the "Unusual bookings" box,
   roll-over texts and the "Portfolio analysis" pop-up. Needs window.WV (exposed by wv.js). */
(function () {
  'use strict';
  const W = () => window.WV;
  const nf1 = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 }), nf2 = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const P = (v, dg) => v == null || isNaN(v) ? 'n/a' : (v > 0 ? '+' : '') + (dg === 2 ? nf2 : nf1).format(v * 100) + ' %';   // fraction -> %
  const PP = v => v == null || isNaN(v) ? 'n/a' : (v > 0 ? '+' : '') + nf1.format(v) + ' pp';
  const N2 = v => v == null || isNaN(v) ? 'n/a' : nf2.format(v);
  const COL = ['#e08a3c', '#7cc8f2', '#5fbf8a', '#b48cff', '#ffd24a', '#ff6b6b', '#2b9bff', '#8a97a0', '#d9605a', '#3a64c8'];
  const BASIS = { live: 'Live data', model: 'Model on today\'s holdings', estimate: 'Estimate', 'n/a': 'Not available' };
  const an = d => d && d.analytics && !d.analytics.error ? d.analytics : null;
  const NA = (why) => `<span class="dim" title="${W().esc(why)}">n/a</span>`;
  const bdg = (a, key) => { const b = a && a[key] && a[key].basis; return b ? W().badge(b === 'live' ? 'live' : b === 'n/a' ? 'demo' : 'mix', BASIS[b] || b) + (a[key].len ? ` <span class="xs dim">${a[key].len} months of history</span>` : '') : ''; };

  /* ---------- tiny chart helpers (self-contained SVG / HTML) ---------- */
  function hbars(items, o) {   // items [{k, v, c?, t?}] ; o {fmt, max}
    o = o || {}; const f = o.fmt || (v => W().eur(v)), mx = o.max || Math.max(1e-9, ...items.map(i => Math.abs(i.v || 0)));
    return items.map((i, n) => `<div class="tr" style="grid-template-columns:9.5rem 1fr 6.5rem;cursor:default;padding:.18rem .1rem" title="${W().esc(i.t || '')}"><span>${W().esc(i.k)}</span><span style="position:relative;height:.7rem;align-self:center"><i style="position:absolute;left:0;top:0;bottom:0;width:${Math.min(100, Math.abs(i.v || 0) / mx * 100).toFixed(1)}%;background:${i.c || (i.v < 0 ? '#ff6b6b' : COL[n % COL.length])};opacity:.75"></i></span><span class="r wh">${o.noBlur ? f(i.v) : f(i.v)}</span></div>`).join('');
  }
  function lines(series, labels, o) {   // series [{n,c,v:[...]}] ; area optional
    o = o || {}; const Wd = 640, H = 200, L = 46, R = 8, T = 10, B = 22, n = labels.length; if (n < 2) return '<div class="dim sm">Not enough history yet.</div>';
    const all = series.flatMap(s => s.v).filter(v => v != null); if (!all.length) return '<div class="dim sm">No data.</div>';
    let lo = o.min != null ? o.min : Math.min(...all), hi = o.max != null ? o.max : Math.max(...all); if (hi === lo) hi = lo + 1;
    const X = i => L + i / (n - 1) * (Wd - L - R), Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B), f = o.fmt || (v => nf1.format(v));
    let g = ''; for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4, y = Y(v); g += `<line x1="${L}" x2="${Wd - R}" y1="${y}" y2="${y}" stroke="rgba(60,190,235,.13)"/><text x="${L - 5}" y="${y + 3}" text-anchor="end" font-size="10" fill="rgba(127,220,255,.65)">${f(v)}</text>`; }
    const st = Math.max(1, Math.ceil(n / 8)); for (let i = 0; i < n; i += st) g += `<text x="${X(i)}" y="${H - 6}" text-anchor="middle" font-size="10" fill="rgba(127,220,255,.65)">${W().esc(labels[i])}</text>`;
    series.forEach(s => { let d = '', pen = false; s.v.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); pen = true; }); if (o.area && d) g += `<path d="${d}L${X(n - 1)},${Y(Math.max(lo, Math.min(0, hi)))}L${X(0)},${Y(Math.max(lo, Math.min(0, hi)))}Z" fill="${s.c}" opacity=".18"/>`; g += `<path d="${d}" fill="none" stroke="${s.c}" stroke-width="1.8"/>`; });
    return `<svg viewBox="0 0 ${Wd} ${H}" style="width:100%;height:12rem">${g}</svg><div class="leg">${series.map(s => `<span><i style="background:${s.c}"></i>${W().esc(s.n)}</span>`).join('')}</div>`;
  }
  function heatTable(m) {   // correlation matrix {a:{b:r}}
    const ks = Object.keys(m); if (!ks.length) return '<div class="dim sm">Not enough overlapping history (needs 12 months).</div>';
    const cell = r => { if (r == null) return `<td title="Fewer than 12 months of overlapping history" style="text-align:center" class="dim">n/a</td>`; const a = Math.min(1, Math.abs(r)), c = r >= 0 ? '255,154,61' : '60,190,235'; return `<td title="Correlation ${N2(r)}" style="text-align:center;background:rgba(${c},${(a * .6).toFixed(2)})">${N2(r)}</td>`; };
    return `<table style="border-collapse:collapse;font-size:.74rem;width:100%"><tr><td></td>${ks.map(k => `<td class="xs dim" style="text-align:center;padding:.15rem .3rem">${W().esc(k.slice(0, 14))}</td>`).join('')}</tr>${ks.map(a => `<tr><td class="xs dim" style="padding:.15rem .3rem">${W().esc(a.slice(0, 16))}</td>${ks.map(b => cell(m[a][b])).join('')}</tr>`).join('')}</table>`;
  }
  const stat = (l, v, t) => `<div title="${W().esc(t || '')}">${l}<b>${v}</b></div>`;
  const kv = (l, v) => `<div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span class="dim">${l}</span><span class="wh">${v}</span></div>`;

  /* ---------- smart suggestion items from the analytics ---------- */
  function tipItems(d) {
    const a = an(d), T = [], E = W().eur; if (!a) return T;
    const dr = (a.allocation && a.allocation.drift) || {};
    Object.entries(dr).forEach(([k, x]) => { if (x && x.status && x.status !== 'ok' && x.status !== 'within') T.push({ l: 'warn', t: `${k} is ${x.status === 'over' ? 'above' : 'below'} your target band`, x: `${nf1.format(x.pct)} % of gross assets vs a target of ${x.target} % (band ${x.low}–${x.high} %). The target allocation is a standard best-practice mix for a portfolio of this size; edit it in config.json ("targets").` }); });
    const pf = a.performance && a.performance.securities;
    if (pf && pf.excess_pp != null) T.push({ l: pf.excess_pp < 0 ? 'warn' : 'info', t: `Securities ${pf.excess_pp < 0 ? 'behind' : 'ahead of'} ${pf.bench_name || 'the index'} by ${nf1.format(Math.abs(pf.excess_pp))} pp`, x: `Your depot returned ${P(pf.price_return)} (price return of today's holdings) in the same period the index returned ${P(pf.bench_return)}. Compare like with like: your depot holds different assets than the index.` });
    const rk = a.risk && a.risk.combined;
    if (rk && rk.max_dd != null && rk.max_dd < -0.15) T.push({ l: 'info', t: `Worst peak-to-trough fall of liquid assets: ${P(rk.max_dd, 0)}`, x: 'Calculated on today\'s securities and crypto over their history. A realistic reminder of what a bad phase feels like.' });
    const lq = a.liquidity;
    if (lq && lq.unfunded_wf > 0 && lq.cash_cover != null && lq.cash_cover < 1.5) T.push({ l: 'warn', t: `Cash covers the still-uncalled Example Fund capital only ${N2(lq.cash_cover)}x`, x: `${E(lq.unfunded_wf)} can be called on short notice. Many advisers want that covered at least once in cash.` });
    const al = a.tax && a.tax.allowance;
    if (al && al.left > 0 && d.depot && d.depot.gain > al.left) T.push({ l: 'idea', t: `${E(al.left)} of the yearly tax allowance is unused`, x: `Sparer-Pauschbetrag ${al.year}: used ${E(al.used)}. Realised gains up to the allowance are tax free. This is not tax advice.` });
    const ex = a.exposure;
    if (ex && ex.effective_n != null && ex.effective_n < 5 && d.depot && d.depot.positions.length >= 5) T.push({ l: 'info', t: `Effective number of positions: ${nf1.format(ex.effective_n)}`, x: `You hold ${d.depot.positions.length} positions but a few dominate; the "effective number" shows how many equal-sized positions would be as concentrated.` });
    return T;
  }

  /* ---------- roll-over texts (title attributes) ---------- */
  function rollover(kind, d, arg) {
    const a = an(d); if (!a) return '';
    const pf = a.performance || {}, s = pf.securities || {}, rk = (a.risk || {}), cs = a.costs || {}, pe = a.private_equity || {}, lq = a.liquidity || {};
    if (kind === 'ring') return ['Securities: ' + (s.xirr != null ? 'XIRR ' + P(s.xirr) + ' p.a.' : 'XIRR n/a') + (s.price_return != null ? ' · price return of today\'s holdings ' + P(s.price_return) : ''), a.real && a.real.real_change != null ? 'Gross assets last 12 months (deposits included): nominal ' + P(a.real.nominal_change) + ', real (after inflation) ' + P(a.real.real_change) : 'Real return: n/a (no inflation data)'].join('\n');
    if (kind === 'class') { const x = a.allocation && a.allocation.drift && a.allocation.drift[arg]; return x ? `${arg}: ${nf1.format(x.pct)} % of gross · target ${x.target} % (band ${x.low}–${x.high} %) · ${x.status}` : ''; }
    if (kind === 'securities') return [rk.securities && rk.securities.vol != null ? 'Volatility ' + P(rk.securities.vol) + ' p.a.' : 'Volatility n/a', rk.securities && rk.securities.max_dd != null ? 'Max drawdown ' + P(rk.securities.max_dd) : '', cs.ter_pct != null ? 'Average TER ' + N2(cs.ter_pct) + ' % (' + Math.round((cs.coverage || 0) * 100) + ' % of the depot covered)' : 'TER n/a'].filter(Boolean).join('\n');
    if (kind === 'crypto') { const c = rk.crypto || {}; return [c.vol != null ? 'Volatility ' + P(c.vol) + ' p.a.' : 'Volatility n/a', c.max_dd != null ? 'Max drawdown ' + P(c.max_dd) : '', c.sharpe != null ? 'Sharpe ' + N2(c.sharpe) : ''].filter(Boolean).join('\n'); }
    if (kind === 'wf') return pe.tvpi != null ? `TVPI ${N2(pe.tvpi)}x · DPI ${N2(pe.dpi)}x · RVPI ${N2(pe.rvpi)}x · net IRR ${pe.irr != null ? nf1.format(pe.irr) + ' %' : 'n/a'}` : '';
    if (kind === 'cash') return lq.cash_cover != null ? `Cash covers the uncalled Example Fund capital ${N2(lq.cash_cover)}x` : '';
    return '';
  }

  /* ---------- Unusual bookings box ---------- */
  const RLAB = { spike: 'much larger than usual', new_merchant: 'new merchant', duplicate: 'possible duplicate', price_rise: 'price rise' };
  /* which flagged bookings you have already looked at (kept in this browser only) */
  const SEEN_KEY = 'wv_unusual_seen';
  function seenSet() { try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || '[]')); } catch (e) { return new Set(); } }
  const MEM = new Set(); let seenLoaded = false;   // in-memory copy, so a dismissal holds even when storage is unavailable
  const seenAll = () => { const s = seenSet(); MEM.forEach(k => s.add(k)); return s; };
  function saveSeen(s) { try { localStorage.setItem(SEEN_KEY, JSON.stringify([...s].slice(-500))); } catch (e) { /* storage unavailable: the server copy still remembers */ } }
  function postSeen(keys) { const w = W(); if (!keys.length || !w || !w.S || w.S.mode !== 'real') return; try { w.api('/api/unusual_seen', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ keys }) }).catch(() => { }); } catch (e) { /* ignored: fire and forget */ } }
  function markSeen(k) { markSeenAll([k]); }
  function markSeenAll(ks) { ks.forEach(k => MEM.add(k)); saveSeen(seenAll()); postSeen(ks); }
  function loadSeen() {   // real mode, once: merge what the server remembers, then redraw once
    const w = W(); if (seenLoaded || !w || !w.S || w.S.mode !== 'real') return; seenLoaded = true;
    w.api('/api/unusual_seen').then(r => { const ks = (r && r.seen || []).filter(k => typeof k === 'string'); if (!ks.some(k => !seenAll().has(k))) return; ks.forEach(k => MEM.add(k)); saveSeen(seenAll()); w.renderAll(); }).catch(() => { });
  }
  function pUnusual(d) {
    const w = W(), U = (d.unusual || []).slice().sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 8), seen = seenAll(), key = u => [u.date, u.merchant, u.amount].join('|');
    const open = U.filter(u => !seen.has(key(u))).length;
    setTimeout(loadSeen, 0);
    w.POST.push(() => {
      w.$$('#pUnusual .tr[data-i]').forEach(r => r.onclick = () => { const u = U[+r.dataset.i]; markSeen(key(u)); r.classList.remove('unseen'); if (!w.$$('#pUnusual .tr.unseen').length) { const b = w.$('#pUnusual'); if (b) b.classList.remove('alarm'); } openFlag(u); });
      const all = w.$('#unAll'); if (all) all.onclick = e => { e.stopPropagation(); markSeenAll(U.map(key)); w.renderAll(); };
    });
    const rows = U.map((u, i) => `<div class="tr${seen.has(key(u)) ? '' : ' unseen'}" data-i="${i}" style="grid-template-columns:3.2rem minmax(0,1fr) auto;padding:.22rem .2rem" title="${w.esc(u.detail || '')}"><span class="dim xs">${w.esc(String(u.date).slice(8, 10) + '.' + String(u.date).slice(5, 7) + '.')}</span><span class="nm"><span class="t">${w.esc(u.merchant)}<small>${(u.reasons || []).map(r => `<span class="bd mix" style="margin-right:.25rem">${w.esc(RLAB[r] || r)}</span>`).join('')}</small></span></span><span class="r wh">${w.A(Math.abs(u.amount))}</span></div>`).join('');
    return w.panel('pUnusual', 'Unusual bookings <b>//</b> worth a second look' + (open ? ' · ' + open + ' new' : ''), (open ? '<button id="unAll" title="Mark all as seen">Dismiss all</button> ' : '') + (d.mode === 'demo' ? w.badge('demo', 'Demo') : w.srcBadge('gls', d)), `<div class="tbl" style="overflow:auto">${rows || '<div class="dim sm">Nothing unusual in the last months.</div>'}</div><div class="xs dim" style="margin-top:.3rem">Much larger than usual · new merchant with a large amount · possible duplicates · price rises. Thresholds: config.json "unusual".</div>`, { style: 'flex:1.6', cls: open ? 'alarm' : '' });
  }
  function openFlag(u) {
    if (!u) return; const w = W(), f = w.S.D.flows || {}, all = [].concat(...['y1', 'all'].map(k => (f.top_spenders || {})[k] || []));
    const m = all.find(x => x.n === u.merchant);
    if (m) return w.openMerchant(m);
    w.infoModal(w.esc(u.merchant) + ' · flagged booking', `<div class="stats">${stat('Date', w.esc(u.date))}${stat('Amount', w.A(Math.abs(u.amount)))}</div><p>${w.esc(u.detail || '')}</p>`, '');
  }

  /* ---------- Portfolio analysis pop-up ---------- */
  const TABS = ['Performance', 'Risk', 'Exposure', 'Liquidity', 'Private equity', 'Tax', 'Costs & income'];
  const SS = { tab: 'Performance', real: false, expo: 'class' };
  function tabHTML(d, tab) {
    const a = an(d), w = W(), E = w.A;
    if (!a) return `<div class="dim">${d.analytics && d.analytics.error ? 'The analysis could not be calculated: ' + w.esc(d.analytics.error) : 'No analysis yet. Run "Refresh data" once.'}</div>`;
    if (tab === 'Performance') {
      const p = a.performance || {}, s = p.securities || {}, c = p.crypto || {}, r = a.real || {};
      const nom = (d.nwx && d.nwx.gross) || d.axis.map((_, i) => ['Real estate', 'Securities', 'Private equity', 'Cash', 'Crypto'].reduce((t, k) => t + ((d.nw[k] || [])[i] || 0), 0));
      const n = (r.gross_real || []).length, ax = d.axis.slice(-n), ser = SS.real ? [{ n: 'Gross assets, real (today\'s money)', c: '#5fbf8a', v: r.gross_real }, { n: 'Gross assets, nominal', c: '#7cc8f2', v: nom.slice(-n) }] : [{ n: 'Gross assets, nominal', c: '#7cc8f2', v: nom.slice(-n) }];
      return `<div class="stats">${stat('Securities XIRR', s.xirr != null ? P(s.xirr) + ' p.a.' : 'n/a', 'Money-weighted return since ' + (s.xirr_since || '?') + ' (your own deposits and withdrawals count)')}${stat('Price return (today\'s holdings)', P(s.price_return), 'How today\'s positions moved in price since the start of the history; ignores what you sold and when you bought')}${stat('Index', P(s.bench_return), (s.bench_name || 'benchmark') + ' over the same months')}${stat('vs index', PP(s.excess_pp))}${stat('Crypto gain', c.gain_pct != null ? nf1.format(c.gain_pct) + ' %' : 'n/a', 'Based on what you paid (Coinbase trade history)')}${stat('Real 12 m', P(r.real_change), 'After German inflation (HICP)')}</div>
        <div class="tools" style="padding:0"><button data-real="0" class="${SS.real ? '' : 'on'}">Nominal</button><button data-real="1" class="${SS.real ? 'on' : ''}">Real (after inflation)</button></div>
        ${n ? lines(ser, ax, { fmt: v => w.kfmt(v) }) : '<div class="dim sm" title="Inflation data could not be loaded">Real values: n/a</div>'}
        <div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">CONTRIBUTION TO SECURITIES GAIN (percentage points)</div>${hbars((p.contributions || []).slice(0, 10).map(x => ({ k: x.name, v: x.share_pp, t: `Gain ${w.eur(x.gain)} (${nf1.format(x.gain_pct)} %)` })), { fmt: v => PP(v) }) || ''}
        <div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">CRYPTO GAIN BY COIN</div>${hbars((p.crypto_contributions || []).map(x => ({ k: x.name, v: x.gain })), { fmt: v => '<span class="amt">' + w.eur(v) + '</span>' }) || '<span class="dim sm">n/a</span>'}`;
    }
    if (tab === 'Risk') {
      const r = a.risk || {}, rows = [['Securities', r.securities], ['Crypto', r.crypto], ['Both together', r.combined], [(a.performance && a.performance.securities && a.performance.securities.bench_name) || 'Index', r.benchmark]].filter(x => x[1]);
      const dd = rows.map((x, i) => ({ n: x[0], c: COL[i], v: x[1].dd_series || [] })).filter(s => s.v.length), N = Math.max(0, ...dd.map(s => s.v.length)), ax = d.axis.slice(-N);
      const st = (r.stress && r.stress.by_class) || {};
      return `<div class="stats">${stat('Volatility (comb.)', r.combined && r.combined.vol != null ? P(r.combined.vol) : 'n/a', 'Annualised standard deviation of monthly returns')}${stat('Max drawdown', r.combined && r.combined.max_dd != null ? P(r.combined.max_dd) : 'n/a', 'Largest peak-to-trough fall')}${stat('Sharpe', N2(r.combined && r.combined.sharpe), 'Return above ' + P(r.rf) + ' risk-free, per unit of volatility')}${stat('Sortino', N2(r.combined && r.combined.sortino), 'Like Sharpe but only counts down moves')}${stat('Stress loss', r.stress ? w.A(r.stress.loss_eur) : 'n/a', 'Shock test: ' + Object.entries(st).map(x => x[0]).join(', '))}</div>
        <div class="xs dim sm">Risk figures describe <b>today's holdings</b> over their past prices, not your actual past portfolio.</div>
        <div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">DRAWDOWN FROM THE PREVIOUS HIGH</div>${dd.length ? lines(dd, ax, { area: true, fmt: v => nf1.format(v * 100) + ' %', max: 0 }) : '<div class="dim sm">n/a</div>'}
        <div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">CORRELATION (1 = move together, ≤ 0 = diversify)</div>${heatTable(r.corr || {})}
        <div class="xs dim" style="letter-spacing:.12em;margin:.6rem 0 .2rem">STRESS TEST: what a bad year would cost (shocks in config.json "stress")</div>${hbars(Object.entries(st).map(([k, v]) => ({ k, v })), { fmt: v => '<span class="amt">' + w.eur(v) + '</span>' })}`;
    }
    if (tab === 'Exposure') {
      const x = a.exposure || {}, views = { class: ['By type', x.by_class], theme: ['By theme', x.by_theme], country: ['By country', objItems(x.by_country)], sector: ['By sector', objItems(x.by_sector)], currency: ['By currency', objItems(x.by_currency)], top: ['Top holdings (look-through)', (x.lookthrough || []).map(t => ({ k: t.name, v: t.weight }))] };
      const isPct = ['country', 'sector', 'currency', 'top'].includes(SS.expo);
      const cur = views[SS.expo] || views.class, items = (cur[1] || []).slice(0, 14), cov = x.coverage || {};
      return `<div class="stats">${stat('Effective positions', x.effective_n != null ? nf1.format(x.effective_n) : 'n/a', 'Number of equal-sized positions that would be as concentrated as your depot')}${stat('Concentration (HHI)', x.hhi != null ? Math.round(x.hhi) : 'n/a', 'Herfindahl index, 10.000 = one single position')}${stat('Country data', Math.round((cov.country || 0) * 100) + ' %', 'Share of the depot with country information from Yahoo')}${stat('Sector data', Math.round((cov.sector || 0) * 100) + ' %')}</div>
        <div class="tools" style="padding:0">${Object.entries(views).map(([k, v]) => `<button data-expo="${k}" class="${SS.expo === k ? 'on' : ''}">${v[0]}</button>`).join('')}</div>
        ${items.length ? hbars(items.map(i => ({ k: i.k, v: i.v })), { fmt: isPct ? (v => nf1.format(v * 100) + ' % of depot') : (v => '<span class="amt">' + w.eur(v) + '</span>') }) : '<div class="dim sm" title="Yahoo has no profile for these positions (or none was loaded yet)">n/a: no data for this view yet (coverage is limited to positions with a ticker symbol)</div>'}`;
    }
    if (tab === 'Liquidity') {
      const l = a.liquidity || {};
      return `<div class="stats">${stat('Cash cover of capital calls', l.cash_cover != null ? N2(l.cash_cover) + 'x' : 'n/a', 'Cash divided by the still-uncalled Example Fund capital')}${stat('Uncalled capital', w.A(l.unfunded_wf))}</div><div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">HOW FAST COULD YOU GET AT YOUR MONEY</div>${hbars((l.ladder || []).map(x => ({ k: x.label, v: x.eur, t: (x.parts || []).join(', ') })), { fmt: v => '<span class="amt">' + w.eur(v) + '</span>' })}`;
    }
    if (tab === 'Private equity') {
      const p = a.private_equity || {}, pts = p.points || [], ps = p.personal || {};
      return `<div class="stats">${stat('TVPI', N2(p.tvpi) + 'x', 'Total value (paid out + remaining) divided by paid in')}${stat('DPI', N2(p.dpi) + 'x', 'Cash already paid back / paid in')}${stat('RVPI', N2(p.rvpi) + 'x', 'Remaining value / paid in')}${stat('Net IRR', p.irr != null ? nf1.format(p.irr) + ' %' : 'n/a')}</div>
        <div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">TVPI OVER THE FUND REPORTS (J-curve: young funds usually start below 1)</div>${pts.length > 1 ? lines([{ n: 'TVPI', c: '#5fbf8a', v: pts.map(q => q.tvpi) }], pts.map(q => q.label), { fmt: v => N2(v) + 'x' }) : '<div class="dim sm">Needs at least two reports.</div>'}
        <div class="xs dim" style="letter-spacing:.12em;margin:.4rem 0 .2rem">YOUR COMMITMENT</div>${hbars([{ k: 'Paid in', v: ps.paid_in, c: '#5fbf8a' }, { k: 'Current value (NAV)', v: ps.nav, c: '#7cc8f2' }, { k: 'Still to be called', v: ps.unfunded, c: '#ffd24a' }], { max: ps.commitment, fmt: v => '<span class="amt">' + w.eur(v) + '</span>' })}`;
    }
    if (tab === 'Tax') {
      const t = a.tax || {}, al = t.allowance || {}, ry = t.realised_by_year || {};
      if (t.note && !t.allowance) return `<p class="dim sm">${w.esc(t.note)}</p>`;   /* profile without tax rules for its country */
      return `<div class="stats">${stat('Allowance ' + (al.year || ''), w.A(al.used) + ' used', 'Sparer-Pauschbetrag')}${stat('Left', w.A(al.left))}${stat('Taxable so far', w.A(al.taxable))}</div>${Object.keys(ry).length ? Object.entries(ry).map(([y, v]) => kv(y, '<span class="amt">' + w.eur(typeof v === 'object' ? v.gain : v) + '</span>')).join('') : '<div class="dim sm">No sales recorded yet.</div>'}<p class="xs dim">${w.esc(t.note || '')} Education, not tax advice.</p>`;
    }
    if (tab === 'Costs & income') {
      const c = a.costs || {};
      return `<div class="stats">${stat('Average TER', c.ter_pct != null ? N2(c.ter_pct) + ' %' : 'n/a', 'Yearly fund costs, weighted by value')}${stat('TER per year', c.ter_eur != null ? w.A(c.ter_eur) : 'n/a')}${stat('TER coverage', Math.round((c.coverage || 0) * 100) + ' %', 'Share of the depot with a known TER')}${stat('Portfolio yield', c.yield != null ? nf1.format(c.yield) + ' %' : 'n/a', 'Estimated dividends and interest / value')}${stat('Yield on cost', c.yield_on_cost != null ? nf1.format(c.yield_on_cost) + ' %' : 'n/a')}</div><p class="xs dim">Yield figures are estimates from public data and can be off.</p>`;
    }
    return '';
  }
  const objItems = o => Object.entries(o || {}).map(([k, v]) => ({ k, v: typeof v === 'object' ? v.eur : v })).sort((a, b) => b.v - a.v);
  function openAnalysis(d, tab) {
    const w = W(); d = d || w.S.D; if (tab) SS.tab = tab; const a = an(d);
    const m = w.infoModal('Portfolio analysis <b style="color:var(--or)">//</b> what advisers look at', '', a ? w.badge('mix', 'asof ' + w.esc(a.asof || '')) : '');
    const draw = () => {
      $tools().innerHTML = TABS.map(t => `<button data-tab="${t}" class="${SS.tab === t ? 'on' : ''}">${t}</button>`).join('');
      const b = document.getElementById('mbody'); b.innerHTML = (a ? bdg(a, { Performance: 'performance', Risk: 'risk', Exposure: 'exposure', Liquidity: 'liquidity', 'Private equity': 'private_equity', Tax: 'tax', 'Costs & income': 'costs' }[SS.tab]) : '') + tabHTML(d, SS.tab);
      w.$$('#mtools [data-tab]').forEach(x => x.onclick = () => { SS.tab = x.dataset.tab; draw(); });
      w.$$('#mbody [data-real]').forEach(x => x.onclick = () => { SS.real = x.dataset.real === '1'; draw(); });
      w.$$('#mbody [data-expo]').forEach(x => x.onclick = () => { SS.expo = x.dataset.expo; draw(); });
    };
    draw();
  }
  const $tools = () => document.getElementById('mtools');

  /* allocation views for the Securities allocation box: [{k,v,c}] from exposure (null if no data) */
  function allocView(d, view) {
    const x = an(d) && an(d).exposure; if (!x) return null; const o = view === 'country' ? x.by_country : view === 'sector' ? x.by_sector : view === 'currency' ? x.by_currency : null;
    const it = objItems(o), tot = (d.depot && d.depot.total) || 0; return it.length && tot ? it.map((i, n) => ({ k: i.k, v: i.v * tot, c: COL[n % COL.length] })) : null;
  }


  /* ---------- single-company pop-up (private-equity start-ups and other single holdings) ---------- */
  const NF0 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
  function companyModal(c, o) {
    o = o || {}; const w = W(), lg = window.WF_LOGOS || {}, wi = c.wiwin, esc = w.esc;
    const web = c.web || (o.fund && o.fund.portfolio_url) || '';
    const own = wi ? [['Invested', w.A(wi.invested)], ['Platform', esc(wi.platform || 'wiwin.de')], ['Valuation', esc(wi.note || 'at cost')], ['Class', 'Private equity']]
      : [['Since', esc(c.since || 'n/a')], ['Country', esc(c.country || 'n/a')], ['Fund ownership', c.own != null ? String(c.own).replace('.', ',') + ' %' : 'n/a'], ['Cost (fund)', c.cost != null ? '<span class="amt">' + NF0.format(c.cost) + ' €</span>' : 'n/a'], ['Fair value (fund)', c.fair_value != null ? '<span class="amt">' + NF0.format(c.fair_value) + ' €</span>' : 'n/a'], ['MOIC', c.moic != null ? String(c.moic.toFixed(2)).replace('.', ',') + 'x' : 'n/a'], ['Your look-through', c.look_through != null ? w.A(c.look_through) : 'n/a']];
    const logoHtml = wi ? w.logo('wiwin', 'wiwin', true) : (lg[c.slug] ? `<img src="${lg[c.slug]}" alt="" style="width:100%;height:100%;object-fit:cover">` : '');
    const body = `<div class="pp"><div class="hdr"><div class="lgw" style="width:6rem;height:3.9rem;border:1px solid rgba(60,190,235,.3);background:#0b141b;overflow:hidden;display:flex;align-items:center;justify-content:center">${logoHtml}</div><div><h2>${esc(c.name)}</h2><small>${esc(wi ? 'Crowd investment via ' + (wi.platform || 'wiwin.de') : (c.industry || '') + (c.sector ? ' · ' + c.sector : ''))}</small></div></div>
      <div class="stats">${own.map(x => `<div>${x[0]}<b>${x[1]}</b></div>`).join('')}</div>
      <p class="dim sm">${esc(c.blurb || '')}</p>
      <div class="side" style="display:grid;grid-template-columns:1fr 1fr;gap:.8rem"><div class="card" id="coFacts"><h4>Company facts</h4><div class="ld"><span class="spinner"></span>looking up …</div></div><div class="card news" id="coNews"><h4>Latest news</h4><div class="ld"><span class="spinner"></span>looking up headlines …</div></div></div>
      <div class="xs dim" id="coLinks"></div></div>`;
    w.infoModal(esc(c.name), body, wi ? w.srcBadge('wiwin', w.S.D) : w.srcBadge('examplefund', w.S.D));
    const nf = '<span class="dim">not found</span>', link = web ? ` <a href="${esc(web)}" target="_blank" rel="noopener noreferrer">${esc(web.replace(/^https?:\/\//, '').slice(0, 40))} ↗</a>` : '';
    const fill = r => {
      if (!document.getElementById('coFacts')) return;   // window closed meanwhile
      const f = (r && r.found) || {}, row = (l, v, ok) => `<div class="fac"><span>${l}</span><b class="wh">${ok ? v : nf}</b></div>`;
      document.getElementById('coFacts').innerHTML = '<h4>Company facts</h4>' + (r && r.error ? `<div class="ld or">${esc(r.error === 'locked' ? 'Live lookup is available after unlocking the real numbers.' : r.error)}</div>` : '') +
        `<div class="note" style="margin:.2rem 0">${r && r.mission ? esc(r.mission) : 'Vision / mission: ' + nf}</div>` + row('Headquarters', esc(r && r.hq || ''), !!(r && r.hq)) + row('Employees', r && r.employees != null ? NF0.format(r.employees) : '', r && r.employees != null) + row('Founded', esc(r && r.founded || ''), !!(r && r.founded)) + row('Founders', esc(((r && r.founders) || []).join(', ')), !!(r && r.founders && r.founders.length)) + row('Industry', esc(r && r.industry || c.industry || ''), !!(r && r.industry || c.industry));
      const n = (r && r.news) || [];
      document.getElementById('coNews').innerHTML = '<h4>Latest news' + (r && r.demo ? ' <span class="bd demo">EXAMPLE</span>' : '') + '</h4>' + (n.length ? n.slice(0, 6).map(x => `<div class="it">${x.demo ? '<span>' + esc(x.title) + '</span>' : `<a href="${/^https?:\/\//i.test(x.url || '') ? esc(x.url) : '#'}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`}<small>${esc(x.source || '')} ${esc(String(x.date || '').slice(0, 10))}</small></div>`).join('') : '<div class="ld">No recent headlines found.</div>');
      const lk = document.getElementById('coLinks'); if (lk) lk.innerHTML = r && r.demo ? '<span class="bd demo">EXAMPLE</span> Invented sample content for the demo: not real facts or news.' : 'Sources: Wikidata, the company site, Google News, fetched just now. ' + (link ? 'Website:' + link : 'No website on file.') + (r && r.links && r.links.wikidata ? ' · <a href="' + esc(r.links.wikidata) + '" target="_blank" rel="noopener noreferrer">Wikidata ↗</a>' : '');
    };
    if (w.S.D.mode === 'demo') { fill(window.demoCompany ? window.demoCompany(c) : { mission: c.blurb || null, hq: c.country || null, news: [], found: {}, error: 'Demo: stored facts only, no live lookup.' }); return; }
    if (!w.server) { fill({ error: 'Live lookup needs the local server (desktop icon).' }); return; }
    w.api('/api/company?name=' + encodeURIComponent(c.name) + '&web=' + encodeURIComponent(c.web || '')).then(r => fill(r || {})).catch(e => fill({ error: 'Could not reach the lookup: ' + (e && e.message || e) }));
  }

  window.WVA = { companyModal, tipItems, rollover, pUnusual, openAnalysis, allocView };
})();
