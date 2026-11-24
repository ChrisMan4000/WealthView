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
  /* v1.27: every card opens a detail pop-up; the box has range buttons and opens a big day-by-day chart */
  const CARDKEY = { 'Saved vs market': 'svm', 'Spending vs your norm': 'spend', 'Recurring costs': 'rec', 'Year over year': 'yoy' };
  function card(title, body, tip) {
    const key = Object.keys(CARDKEY).find(k => String(title).startsWith(k));
    return `<div class="otc${key ? ' clk' : ''}" ${key ? `data-card="${CARDKEY[key]}"` : ''} ${tip ? `title="${W().esc(tip)}${key ? ' - click for details' : ''}"` : key ? 'title="Click for details"' : ''}><div class="otn">${title}</div>${body}</div>`;
  }
  const RANGES = [['7D', 7], ['30D', 30], ['3M', 90], ['1Y', 365], ['ALL', 0]];
  const OT = { range: 'ALL' };
  const dmyy = iso => String(iso).slice(8, 10) + '.' + String(iso).slice(5, 7) + '.' + String(iso).slice(0, 4);
  /* the recorded days that fall into a range; fewer than 2 days would draw no line, so then all days are used */
  function pickIdx(c, range) {
    const ds = c.days || [], all = ds.map((_, i) => i), n = (RANGES.find(r => r[0] === range) || [0, 0])[1];
    if (!n || ds.length < 2) return all;
    const t = new Date(ds[ds.length - 1] + 'T00:00:00'); t.setDate(t.getDate() - n); const cut = t.toISOString().slice(0, 10);
    const idx = all.filter(i => ds[i] >= cut); return idx.length >= 2 ? idx : all;
  }
  function chartHtml(c) {
    const ds = c.days || []; if (ds.length < 2) return chart(c);
    const idx = pickIdx(c, OT.range), sub = { days: idx.map(i => ds[i]), gross: idx.map(i => c.gross[i]) }, v = sub.gross.filter(x => x != null);
    let line = '';
    if (v.length >= 2) {
      const ch = v[v.length - 1] - v[0], span = Math.round((new Date(sub.days[sub.days.length - 1]) - new Date(sub.days[0])) / 864e5), want = (RANGES.find(r => r[0] === OT.range) || [0, 0])[1];
      line = `<div class="xs dim" style="margin-top:.15rem">Change in this range: <b class="${cls(ch)}">${sA(ch)}${v[0] ? ' (' + sP(ch / v[0] * 100) + ')' : ''}</b>${want && span < want ? ' · recorded history is shorter than this range (since ' + dmy(sub.days[0]) + ')' : ''}</div>`;
    }
    return chart(sub) + line;
  }
  function bindTime(I) {
    const box = document.getElementById('pTime'); if (!box) return;
    box.querySelectorAll('#otRange button').forEach(b => b.onclick = e => {
      e.stopPropagation(); OT.range = b.dataset.r;
      const el = document.getElementById('otChart'); if (el) el.innerHTML = chartHtml(I.curve || {});       /* in place: no redraw of the box, so the next click lands */
      box.querySelectorAll('#otRange button').forEach(x => x.classList.toggle('on', x.dataset.r === OT.range));
    });
    box.querySelectorAll('.otc[data-card]').forEach(c => c.onclick = e => { e.stopPropagation(); openCard(c.dataset.card, I); });
    box.onclick = e => { if (e.target.closest('.otc,#otRange,.hmb')) return; openBig(I); };
  }

  /* ---- big pop-up: the recorded days as a large chart */
  function openBig(I) {
    const w = W(), c = I.curve || {}, ds = c.days || [], bdg = w.badge('live', 'Recorded by WealthView');
    if (ds.length < 2) { w.infoModal('Over time · your real history', '<div class="dim" style="padding:1rem">WealthView saves one real value per day. A chart appears as soon as there are two recorded days.</div>', bdg); return; }
    const M = { range: OT.range, show: 'gross', type: 'area' }, COL = ['#2a7fd4', '#19c3e8', '#ff9a3d', '#8fe6b8', '#ffd24a'];
    w.modalShell('Over time · your real history, day by day', bdg);
    document.getElementById('mbody').innerHTML = '<div class="stats" id="otst"></div><div class="chart" id="otch"></div><div class="leg" id="otlg"></div><p class="xs dim" id="otnote"></p>';
    const tools = () => {
      const b = (attr, val, label, on) => `<button data-${attr}="${val}" class="${on ? 'on' : ''}">${label}</button>`;
      document.getElementById('mtools').innerHTML = RANGES.map(r => b('r', r[0], r[0], M.range === r[0])).join('') + '<span class="sep"></span>' + [['gross', 'Gross'], ['net', 'Net (− loan)'], ['class', 'By class']].map(s => b('s', s[0], s[1], M.show === s[0])).join('') + '<span class="sep"></span>' + ['area', 'line', 'bar'].map(t => b('t', t, t, M.type === t)).join('');
      document.querySelectorAll('#mtools button').forEach(x => x.onclick = () => { if (x.dataset.r) M.range = x.dataset.r; if (x.dataset.s) M.show = x.dataset.s; if (x.dataset.t) M.type = x.dataset.t; tools(); draw(); });
    };
    const draw = () => {
      const idx = pickIdx(c, M.range), x = idx.map(i => ds[i]), type = M.type, one = M.show === 'net' ? 'net' : 'gross';
      let series, stacked = false;
      if (M.show === 'class') {
        stacked = type !== 'line';
        series = Object.keys(c.classes || {}).map((k, j) => ({ n: k, c: COL[j % COL.length], v: idx.map(i => c.classes[k][i]), type }));
        if (stacked && (c.net || []).some(v => v != null)) series.push({ n: 'Net (gross − loan)', c: '#bcd6e2', v: idx.map(i => c.net[i]), type: 'line', fixed: true, dash: true, w: 1.3 });
      } else series = [{ n: one === 'net' ? 'Net (gross − loan)' : 'Gross assets', c: one === 'net' ? '#bcd6e2' : '#19c3e8', v: idx.map(i => (c[one] || [])[i]), type }];
      w.TS(document.getElementById('otch'), { x, xl: i => dmy(x[i]), series, stacked, kind: 'stock' });
      const v = idx.map(i => (c[one] || [])[i]).filter(q => q != null);
      document.getElementById('otst').innerHTML = v.length ? `<div>Start<b>${w.A(v[0])}</b></div><div>Now<b>${w.A(v[v.length - 1])}</b></div><div>Change<b class="${cls(v[v.length - 1] - v[0])}"><span class="amt">${w.eur(v[v.length - 1] - v[0])}</span>${v[0] ? ' (' + sP((v[v.length - 1] / v[0] - 1) * 100) + ')' : ''}</b></div><div>Low<b>${w.A(Math.min(...v))}</b></div><div>High<b>${w.A(Math.max(...v))}</b></div><div>Days<b>${x.length}</b></div>` : '';
      document.getElementById('otlg').innerHTML = series.map(s => `<span><i style="background:${s.c}"></i>${w.esc(s.n)}</span>`).join('');
      document.getElementById('otnote').innerHTML = `Recorded since ${dmyy(ds[0])} · ${ds.length} days · real values, not estimates. For the long history back to ${w.S.D && w.S.D.axis ? w.S.D.axis[0].slice(0, 4) : '2020'} (back-cast from today's holdings) open the gross assets box: <button id="otLong">Long history →</button>`;
      document.getElementById('otLong').onclick = () => { w.closeModal(); const g = document.getElementById('pGross'); if (g) g.click(); };
    };
    tools(); draw();
  }

  /* ---- detail pop-ups of the four cards */
  function miniBars(series) {
    const v = series.map(p => p.v), hi = Math.max(...v, 1), bw = 600 / v.length;
    return `<svg viewBox="0 0 600 90" preserveAspectRatio="none" style="width:100%;height:6rem;display:block" class="amtsvg">${v.map((x, i) => `<rect x="${(i * bw + 1).toFixed(1)}" y="${(88 - x / hi * 80).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${Math.max(.5, x / hi * 80).toFixed(1)}" fill="rgba(25,211,255,.55)"><title>${series[i].m}: ${nf0.format(Math.round(x))} €</title></rect>`).join('')}</svg><div class="xs dim" style="display:flex;justify-content:space-between"><span>${series[0].m}</span><span>${series[series.length - 1].m}</span></div>`;
  }
  function openCard(key, I) {
    const w = W(), esc = w.esc, bdg = w.badge('live', 'From your bookings & records'), row = (a, b) => `<div class="otr"><span>${a}</span><span>${b}</span></div>`;
    const h = t => `<div class="cph" style="margin:.8rem 0 .3rem">${t}</div>`;
    if (key === 'svm') {
      const s = I.saved_vs_market || {}, ch = I.changes || [];
      let html = s.ready ? h('SPLIT OF THE CHANGE · ' + dmyy(s.frm) + ' → ' + dmyy(s.to)) + row('Change of gross assets', sA(s.delta)) + row('of which saved (income − spending)', sA(s.saved)) + row('market moves & other (prices, valuations)', sA(s.market)) + '<div class="xs dim" style="margin-top:.3rem">An estimate: your monthly income and spending, spread over the days between the first and last recorded day.</div>'
        : `<div class="dim sm">Needs ${s.need_days || 28} recorded days; WealthView has ${s.have_days || 0} so far. Then the growth of your gross assets is split into money you saved and market moves.</div>`;
      html += h('CHANGE OF GROSS ASSETS PER PERIOD') + (ch.map(c => row(esc(c.label) + (c.partial ? ' <span class="xs dim">(since ' + dmyy(c.base) + ')</span>' : ''), `<b class="${cls(c.gross || 0)}">${sA(c.gross)} ${c.gross_pct != null ? '(' + sP(c.gross_pct) + ')' : ''}</b>`)).join('') || '<div class="dim xs">Appears after the second recorded day.</div>');
      const last = ch[ch.length - 1]; if (last && last.classes) html += h('BY ASSET CLASS · ' + esc(last.label).toUpperCase()) + Object.entries(last.classes).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(([k, v]) => row(esc(k), `<span class="${cls(v)}">${sA(v)}</span>`)).join('');
      w.infoModal('Saved vs market', html, bdg);
    } else if (key === 'spend') {
      const sp = I.spend_vs_norm || {};
      const html = sp.ready ? h('LAST FULL MONTH · ' + esc(sp.month) + ' · AGAINST THE MEDIAN OF THE 12 MONTHS BEFORE') + `<div class="otr xs dim"><span>Category</span><span>this month · usual · difference</span></div>` + ((sp.items || []).map(i => row(esc(i.cat), `${w.A(i.value)} <span class="dim xs">usual ${w.A(i.norm)}</span> <b class="${i.delta > 0 ? 'neg' : 'pos'}">${sA(i.delta)}${i.pct != null ? ' (' + sP(i.pct) + ')' : ''}</b>`)).join('') || '<div class="dim xs">Nothing far from your usual.</div>') + '<div class="xs dim" style="margin-top:.4rem">Only categories that differ by at least 50 € and 25 % are listed (largest first, up to 6). Click a category in the spending box for its bookings.</div>' : `<div class="dim sm">${esc(sp.reason || '')}</div>`;
      w.infoModal('Spending vs your norm', html, bdg);
    } else if (key === 'rec') {
      const rc = I.recurring || {};
      const html = rc.ready ? h('MONTHLY TOTAL OF RECURRING PAYMENTS · LAST ' + (rc.series || []).length + ' MONTHS') + ((rc.series || []).length ? miniBars(rc.series) : '') + h('NOW') + row(rc.n + ' recurring payments, a month', `<b>${w.A(rc.now)}</b>`) + (rc.ago != null ? row('a year ago', w.A(rc.ago)) : '') +
        h('GOT MORE EXPENSIVE') + ((rc.creep || []).map(c => row(esc(c.n), `<span class="neg">${nf1.format(c.was)} → ${nf1.format(c.now)} € (${sP(c.pct)})</span>`)).join('') || '<div class="dim xs">None.</div>') +
        h('NEW IN THE LAST YEAR') + ((rc.new || []).map(c => row(esc(c.n), `${nf1.format(c.now)} € a month`)).join('') || '<div class="dim xs">None.</div>') : `<div class="dim sm">${esc(rc.reason || '')}</div>`;
      w.infoModal('Recurring costs', html, bdg);
    } else if (key === 'yoy') {
      const y = I.yoy || {};
      const html = y.ready ? h('LAST 12 FULL MONTHS (TO ' + esc(y.to) + ') AGAINST THE 12 BEFORE') + `<div class="otr xs dim"><span></span><span>last 12 · before · change</span></div>` + ['income', 'expense', 'saved'].map(k => row(k, `${w.A(y.now[k])} <span class="dim xs">before ${w.A(y.prev[k])}</span> <b class="${(k === 'expense' ? -1 : 1) * (y.change_pct[k] || 0) >= 0 ? 'pos' : 'neg'}">${sP(y.change_pct[k])}</b>`)).join('') + '<div class="xs dim" style="margin-top:.4rem">Green = better for you (more income or savings, less spending).</div>' : `<div class="dim sm">${esc(y.reason || '')}</div>`;
      w.infoModal('Year over year', html, bdg);
    }
  }
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
    w.POST.push(() => bindTime(I));
    const rng = RANGES.map(r => `<button data-r="${r[0]}" class="${OT.range === r[0] ? 'on' : ''}">${r[0]}</button>`).join('');
    return w.panel('pTime', 'Over time <b>//</b> your real history', bd, `<div style="overflow:auto;flex:1;min-height:0"><div class="otchips">${chips}</div><div class="otrange" id="otRange">${rng}<span class="xs dim">click the box for the big chart · click a card for details</span></div><div id="otChart">${chartHtml(I.curve || {})}</div><div class="otg">${s1}${s2}${s3}${s4}</div></div>`, { cls: 'click', style: 'flex:1.9;min-height:12rem' });
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
#chatInfo{display:flex;justify-content:space-between;font-size:max(var(--minfs,0px),0.648rem);letter-spacing:.06em;color:var(--dim);text-transform:uppercase;gap:.6rem;min-width:0}#chatInfo span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#chatInfo span:last-child{flex:0 1 auto}#chatInfo b{color:var(--c2);font-weight:400}
#log{display:none;position:absolute;left:0;right:0;bottom:100%;margin-bottom:.35rem;max-height:62vh;overflow:auto;box-sizing:border-box;border:1px solid rgba(25,211,255,.35);background:rgba(0,16,26,.96);padding:.5rem .8rem;font-size:0.864rem;line-height:1.45}#log.on{display:block}
#log .q{color:#fff;margin:.35rem 0 .1rem}#log .q::before{content:"YOU > ";opacity:.5}#log .a{margin:.1rem 0 .3rem;white-space:pre-wrap}#log .a::before{content:"WEALTHVIEW > ";opacity:.6;color:var(--or)}#log .e{color:var(--rd)}
#log details{font-size:max(var(--minfs,0px),0.72rem);color:var(--dim);margin:0 0 .4rem}#log pre{margin:.2rem 0;white-space:pre-wrap;color:#9fb4c4}#logx{position:absolute;right:.4rem;top:.3rem;padding:0 .4rem}#logdel{position:absolute;right:2.3rem;top:.3rem;padding:0 .4rem;font-size:max(var(--minfs,0px),0.62rem);letter-spacing:.08em;text-transform:uppercase}
#log .srcs{font-size:max(var(--minfs,0px),0.72rem);color:var(--dim);margin:0 0 .5rem}#log .srcs a{color:var(--c2);text-decoration:none;margin-right:.8rem;white-space:nowrap}#log .srcs a:hover{color:var(--or)}
#chatBar{display:flex;gap:.5rem;align-items:stretch}#chatBtns{display:flex;flex-direction:column;gap:.3rem;flex:none;width:4.6rem}
#chatIn{flex:1;min-width:0;box-sizing:border-box;font:inherit;font-size:0.936rem;line-height:1.4;height:3.4rem;max-height:11rem;resize:none;overflow-y:auto;background:rgba(0,16,26,.85);border:1px solid rgba(60,190,235,.45);color:#fff;padding:.4rem .6rem;outline:none;transition:min-height .15s}
#chatIn:focus{border-color:var(--or)}#chat.act #chatIn{min-height:5.6rem}
#chatBtns button{flex:1;min-height:1.55rem;padding:.1rem .5rem;width:100%}#chatMic{font-size:1rem;padding:.1rem .4rem !important}#chatMic.on{border-color:var(--rd);color:var(--rd);animation:pl 1s infinite}
.otchips{display:flex;flex-wrap:wrap;gap:.3rem .8rem;margin-bottom:.3rem;font-size:max(var(--minfs,0px),0.72rem)}.otchip b{font-weight:400}
.otg{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.4rem;margin-top:.4rem}.otc{border:1px solid rgba(60,190,235,.22);padding:.3rem .45rem;background:rgba(0,20,32,.4)}
.otn{font-size:max(var(--minfs,0px),0.62rem);letter-spacing:.12em;text-transform:uppercase;color:var(--or);margin-bottom:.2rem}.otv{font-size:0.95rem;color:#fff}.otr{display:flex;justify-content:space-between;gap:.5rem;font-size:max(var(--minfs,0px),0.74rem);padding:.05rem 0}
.otrange{display:flex;gap:.3rem;align-items:center;flex-wrap:wrap;margin:.2rem 0}.otrange button{padding:.05rem .5rem;font-size:max(var(--minfs,0px),0.72rem)}.otrange button.on{border-color:var(--or);color:var(--or);background:rgba(255,154,61,.1)}
.otc.clk{cursor:pointer}.otc.clk:hover{border-color:rgba(255,154,61,.6)}#otnote button{padding:.05rem .5rem}`;
    document.head.appendChild(st);
    const box = document.createElement('div'); box.id = 'chat';
    box.innerHTML = '<div id="log"><button id="logdel" title="Delete this chat (the answers shown and what the model remembers of it)">delete chat</button><button id="logx" title="Hide the chat (it is kept until you delete it)">✕</button><div id="logb"></div></div><div id="chatInfo"><span id="chatSt">Ask anything</span><span>your data stays on this PC · web look-ups send only search words</span></div><div id="chatBar"><textarea id="chatIn" rows="1" autocomplete="off" spellcheck="false" maxlength="1500"></textarea><div id="chatBtns"><button id="chatMic" title="Speak your question">🎤</button><button id="chatGo">Ask</button></div></div>';
    A.box = box; document.body.appendChild(box);
    const inp = document.getElementById('chatIn'), go = document.getElementById('chatGo'), mic = document.getElementById('chatMic');
    const grow = () => { inp.style.height = 'auto'; inp.style.height = Math.max(Math.min(inp.scrollHeight + 2, 176), 54) + 'px'; act(); };
    /* v1.27 double-click fix: pressing Ask / the mic blurs the text box, which used to shrink it and move the button before the mouse was
       released (click lost). While the mouse is down inside the bar the box keeps its size; it settles on release. */
    let pressed = false;
    box.addEventListener('mousedown', () => { pressed = true; });
    document.addEventListener('mouseup', () => { if (pressed) { pressed = false; setTimeout(act, 0); } }, true);
    const act = () => box.classList.toggle('act', pressed || document.activeElement === inp || !!inp.value || A.hist.length > 0 || document.getElementById('log').classList.contains('on'));
    A.grow = grow; A.act = act;
    inp.addEventListener('input', grow); inp.addEventListener('focus', act); inp.addEventListener('blur', act);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } e.stopPropagation(); });
    go.onclick = send; document.getElementById('logx').onclick = () => { document.getElementById('log').classList.remove('on'); act(); };
    document.getElementById('logdel').onclick = () => { if (A.busy) return; document.getElementById('log').classList.remove('on'); A.hist = []; document.getElementById('logb').innerHTML = ''; act(); };
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
