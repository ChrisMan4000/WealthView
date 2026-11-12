/* WealthView v1.15 - cash-flow pop-up: an interactive Sankey (income sources -> cash flow -> spending categories -> biggest payees)
   with a period selector (last month / year / all), also used by the Cash flow box on the dashboard (WVF.span, WVF.seg).
   Needs window.WV (wv.js). Everything is drawn as SVG from data.flows; nothing leaves the page. */
(function () {
  'use strict';
  const W = () => window.WV;
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const nf0 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
  const eur = v => nf0.format(Math.round(v)) + ' €';
  const pc = v => (v >= 10 ? v.toFixed(0) : v.toFixed(1)).replace('.', ',') + ' %';
  const sum = (a, i0, i1) => { let s = 0; for (let i = i0; i < i1; i++) s += (a && a[i]) || 0; return s; };
  const mlab = m => MON[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const SONST = 'Sonstiges', GREEN = '#6fbf95', CYAN = '#22aecf', AMBER = '#e0a030', SAVE = '#5fe3a0', GREY = '#6b7f8c';
  const state = () => { const S = W().S; return S.flow || (S.flow = { per: 'year', yr: 'last12', sel: null }); };

  /* period -> [from, to) indexes in f.months. The last month of the list is the current, unfinished one. */
  function span(f, st) {
    st = st || state(); const n = f.months.length;
    if (st.per === 'month') return [Math.max(0, n - 2), Math.max(1, n - 1)];
    if (st.per === 'all') return [0, n];
    if (st.yr && st.yr !== 'last12') { const ix = f.months.map((m, i) => m.startsWith(st.yr) ? i : -1).filter(i => i >= 0); if (ix.length) return [ix[0], ix[ix.length - 1] + 1]; }
    return [Math.max(0, n - 13), Math.max(1, n - 1)];
  }
  function label(f, st) {
    const [a, b] = span(f, st); st = st || state();
    if (st.per === 'month') return mlab(f.months[a]);
    if (st.per === 'year' && st.yr && st.yr !== 'last12') return st.yr;
    return mlab(f.months[a]) + ' – ' + mlab(f.months[b - 1]);
  }
  const PERS = [['month', 'Last month'], ['year', 'Year'], ['all', 'All']];
  /* the three period buttons; `cls` lets the dashboard box and the pop-up share one look */
  const seg = (id) => `<span class="fseg" id="${id}">${PERS.map(([k, t]) => `<button data-per="${k}" class="${state().per === k ? 'on' : ''}">${t}</button>`).join('')}</span>`;

  /* ------------------------------------------------------------ the Sankey model */
  function payeesOf(f, cat, i0, i1, total) {
    let ps = (f.cat_merchants && f.cat_merchants[cat]) ? f.cat_merchants[cat].map(p => ({ n: p.n, v: sum(p.m, i0, i1) })) : null;
    if (!ps) { const tm = (f.top_merchants && f.top_merchants[cat]) || [], tt = tm.reduce((a, x) => a + x.v, 0) || 1; ps = tm.map(x => ({ n: x.n, v: total * x.v / tt * Math.min(1, tt / Math.max(1, total)) })); }   // demo data has no monthly payees
    return ps.filter(p => p.v > 0.5).sort((a, b) => b.v - a.v);
  }
  function model(f, st, fs, k0) {
    const [i0, i1] = span(f, st), months = Math.max(1, i1 - i0), I = sum(f.income, i0, i1), E = sum(f.expense, i0, i1);
    if (I < 1 && E < 1) return null;
    const src = (f.income_by_source || [{ n: 'Income', m: f.income }]).map(s => ({ n: s.n, v: sum(s.m, i0, i1) })).filter(s => s.v > 0.5).sort((a, b) => b.v - a.v);
    const got = src.reduce((a, s) => a + s.v, 0); if (I - got > 0.5) src.push({ n: 'Other income', v: I - got });
    if (E - I > 0.5) src.push({ n: 'From savings & reserves', v: E - I, kind: 'draw' });
    const names = Object.keys(f.cats), base = names.filter(c => c !== SONST), PAL = W().PAL;
    const colOf = c => c === SONST ? GREY : (base.indexOf(c) >= 0 && base.indexOf(c) < 8 ? PAL[base.indexOf(c)] : '#8aa0ad');
    let cats = names.map(c => ({ n: c, v: sum(f.cats[c], i0, i1), m: f.cats[c].slice(i0, i1), col: colOf(c) })).filter(c => c.v > 0.5)
      .sort((a, b) => ((a.n === SONST) - (b.n === SONST)) || b.v - a.v);
    const minV = fs * 1.2 / k0, small = cats.filter(c => c.v < minV && c.n !== SONST);        // too thin to carry a label
    if (small.length > 1) { const rest = { n: 'Small categories', v: 0, m: Array(i1 - i0).fill(0), col: '#8aa0ad', parts: small.map(c => c.n) }; small.forEach(c => { rest.v += c.v; c.m.forEach((x, i) => rest.m[i] += x); }); cats = cats.filter(c => !small.includes(c)); const at = cats.findIndex(c => c.n === SONST); cats.splice(at < 0 ? cats.length : at, 0, rest); }
    cats.forEach(c => { c.pay = []; if (c.parts) return; const ps = payeesOf(f, c.n, i0, i1, c.v); if (c.v / Math.max(E, 1) >= 0.025) { const top = ps.filter(p => p.v >= minV * 0.8).slice(0, 4), s = top.reduce((a, p) => a + p.v, 0); c.pay = top; if (c.v - s > minV * 0.8) c.pay = top.concat([{ n: 'Other payees', v: c.v - s, other: true }]); } });
    const surplus = Math.max(0, I - E);
    return { i0, i1, months, I, E, T: Math.max(I, E), src, cats, surplus };
  }

  /* ------------------------------------------------------------ layout + drawing */
  function draw(host, f, st, onSel, tip) {
    const u = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, fs = u * 0.82;
    const Wd = host.clientWidth, Ht = host.clientHeight; if (Wd < 200 || Ht < 120) return null;
    const mt = u * 1.6, mb = u * 0.8, H = Ht - mt - mb, k0 = H / Math.max(1, Math.max(sum(f.income, ...span(f, st)), sum(f.expense, ...span(f, st))));
    const M = model(f, st, fs, k0);
    if (!M) { host.innerHTML = '<div class="dim" style="padding:2rem;text-align:center">No income or spending in this period.</div>'; return null; }
    const lm = u * 14, rm = u * 13, nw = u * 0.9, gap = u * 0.45, gap3 = u * 0.25;
    const xs = [lm, lm + (Wd - lm - rm - nw) * 0.3, lm + (Wd - lm - rm - nw) * 0.64, Wd - rm - nw];
    // columns -> nodes
    const cols = [[], [], [], []], nodes = {};
    const add = (c, id, o) => { const n = Object.assign({ id, c, x: xs[c], w: nw }, o); nodes[id] = n; cols[c].push(n); return n; };
    M.src.forEach((s, i) => add(0, 's' + i, { name: s.n, v: s.v, col: s.kind === 'draw' ? AMBER : GREEN, kind: s.kind || 'income' }));
    add(1, 'flow', { name: 'Cash flow', v: M.T, col: CYAN, kind: 'flow' });
    M.cats.forEach((c, i) => add(2, 'c' + i, { name: c.n === SONST ? 'Unsorted (Sonstiges)' : c.n, raw: c.n, v: c.v, col: c.col, kind: 'cat', m: c.m, parts: c.parts }));
    if (M.surplus > 0.5) add(2, 'save', { name: 'Saved', v: M.surplus, col: SAVE, kind: 'save' });
    M.cats.forEach((c, i) => c.pay.forEach((p, j) => add(3, 'p' + i + '_' + j, { name: p.n, v: p.v, col: c.col, kind: 'payee', parent: 'c' + i, other: p.other })));
    // vertical scale: the fullest column decides
    let k = Infinity;
    cols.forEach((col, ci) => { const g = (ci === 3 ? gap3 : gap) * Math.max(0, col.length - 1), s = col.reduce((a, n) => a + n.v, 0); if (s > 0) k = Math.min(k, (H - g) / s); });
    cols.forEach((col, ci) => { const g = ci === 3 ? gap3 : gap, tot = col.reduce((a, n) => a + n.v * k, 0) + g * Math.max(0, col.length - 1); let y = mt + (H - tot) / 2; col.forEach(n => { n.h = Math.max(1.5, n.v * k); n.y = y; y += n.h + g; }); });
    // links (stacked inside each node, in the order of the other end)
    const links = [], off = {}; Object.keys(nodes).forEach(id => off[id] = { in: 0, out: 0 });
    const link = (a, b, v, col) => { const A = nodes[a], B = nodes[b], h = v * k, l = { id: a + '>' + b, a, b, v, col, y0: A.y + off[a].out, y1: B.y + off[b].in, h }; off[a].out += h; off[b].in += h; links.push(l); };
    cols[0].forEach(n => link(n.id, 'flow', n.v, n.col));
    cols[2].forEach(n => link('flow', n.id, n.v, n.col));
    cols[3].forEach(n => link(n.parent, n.id, n.v, n.col));
    const sel = st.sel; const hi = (sel && nodes[sel]) ? new Set([sel]) : null;
    if (hi) { const grow = id => links.forEach(l => { if (l.a === id && !hi.has(l.b) && nodes[id].c >= 1 && nodes[l.b].c > nodes[id].c) { hi.add(l.b); grow(l.b); } }); grow(sel); links.forEach(l => { if (l.b === sel && !hi.has(l.a)) hi.add(l.a); }); }
    const pathOf = l => { const A = nodes[l.a], B = nodes[l.b], x1 = A.x + A.w, x2 = B.x, xm = (x1 + x2) / 2; return `M${x1},${l.y0} C${xm},${l.y0} ${xm},${l.y1} ${x2},${l.y1} L${x2},${l.y1 + l.h} C${xm},${l.y1 + l.h} ${xm},${l.y0 + l.h} ${x1},${l.y0 + l.h} Z`; };
    const cut = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
    const labelOf = n => {
      if (n.h < fs * 0.9 && n.id !== sel) return '';
      const left = n.c <= 2, x = n.c === 3 ? n.x + n.w + u * 0.5 : n.x - u * 0.5, anchor = n.c === 3 ? 'start' : 'end', big = n.c === 1 ? 1.1 : 1;
      const y = n.y + n.h / 2, two = n.h >= fs * 2.1;
      const nm = cut(n.name, n.c === 0 ? 30 : n.c === 3 ? 26 : 22);
      return `<text class="fl-t" x="${x}" y="${two ? y - fs * 0.15 : y + fs * 0.33}" text-anchor="${anchor}" font-size="${fs * big}" fill="#e6f6fb">${esc(nm)}</text>` +
        (two ? `<text class="fl-t amt" x="${x}" y="${y + fs * 1.05}" text-anchor="${anchor}" font-size="${fs * 0.92}" fill="#8fcfe6">${eur(n.v)}</text>` : '');
    };
    const flowAmt = nodes.flow, svg = `<svg width="${Wd}" height="${Ht}" viewBox="0 0 ${Wd} ${Ht}" style="display:block">
      <g id="flL">${links.map(l => `<path class="fl-l" data-id="${l.id}" d="${pathOf(l)}" fill="${l.col}" fill-opacity="${hi ? (hi.has(l.a) && hi.has(l.b) ? 0.5 : 0.07) : 0.3}"/>`).join('')}</g>
      <g id="flN">${Object.values(nodes).map(n => `<rect class="fl-n" data-id="${n.id}" x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" fill="${n.col}" fill-opacity="${hi && !hi.has(n.id) ? 0.25 : 1}" rx="2" style="cursor:${n.kind === 'cat' || n.kind === 'income' ? 'pointer' : 'default'}"/>`).join('')}</g>
      <g id="flT" style="pointer-events:none">${Object.values(nodes).map(labelOf).join('')}</g>
      <text x="${flowAmt.x + flowAmt.w / 2}" y="${mt * 0.6}" text-anchor="middle" font-size="${fs}" fill="#8fcfe6" class="amt">${eur(M.T)} in ${M.months} month${M.months > 1 ? 's' : ''}</text></svg>`;
    host.innerHTML = svg + '<div class="fl-tip" id="flTip"></div>';
    const tipEl = host.querySelector('#flTip'), pctOf = n => n.kind === 'income' || n.kind === 'draw' ? n.v / Math.max(1, M.I) * 100 : n.v / Math.max(1, M.E) * 100;
    const info = id => {
      if (id.includes('>')) { const l = links.find(x => x.id === id), A = nodes[l.a], B = nodes[l.b]; return `<b>${esc(A.name)} → ${esc(B.name)}</b><br><span class="amt">${eur(l.v)}</span>`; }
      const n = nodes[id], per = n.v / M.months;
      return `<b>${esc(n.name)}</b><br><span class="amt">${eur(n.v)}</span>${n.kind === 'flow' || n.kind === 'save' ? '' : ' · ' + pc(pctOf(n)) + (n.kind === 'cat' || n.kind === 'payee' ? ' of spending' : ' of income')}<br><span class="dim">${M.months > 1 ? 'Ø <span class="amt">' + eur(per) + '</span> / month' : 'in ' + mlab(f.months[M.i0])}</span>${n.parts ? '<br><span class="dim">' + esc(n.parts.join(', ')) + '</span>' : ''}${n.kind === 'cat' ? '<br><span class="dim">click for details</span>' : ''}`;
    };
    host.querySelectorAll('.fl-n,.fl-l').forEach(el => {
      el.addEventListener('mousemove', e => { const r = host.getBoundingClientRect(); tipEl.innerHTML = info(el.dataset.id); tipEl.style.display = 'block'; const tw = tipEl.offsetWidth; tipEl.style.left = Math.min(Wd - tw - 8, e.clientX - r.left + 14) + 'px'; tipEl.style.top = Math.max(4, e.clientY - r.top - tipEl.offsetHeight - 10) + 'px'; });
      el.addEventListener('mouseleave', () => { tipEl.style.display = 'none'; });
    });
    host.querySelectorAll('.fl-n').forEach(el => el.addEventListener('click', () => { const n = nodes[el.dataset.id]; onSel(st.sel === n.id ? null : n.id, n); }));
    return { M, nodes };
  }

  /* ------------------------------------------------------------ side panel */
  function side(el, f, st, d, cur) {
    const M = cur && cur.M; if (!M) { el.innerHTML = ''; return; }
    const A = W().A, per = M.months, saved = M.I - M.E, rate = M.I > 0 ? saved / M.I * 100 : null;
    const n = st.sel && cur.nodes[st.sel];
    if (n && n.kind === 'cat') {
      const cat = M.cats.find(c => 'c' + M.cats.indexOf(c) === n.id), ps = cat && !cat.parts ? payeesOf(f, cat.n, M.i0, M.i1, cat.v) : [];
      const mx = Math.max(1, ...n.m), bars = n.m.length > 1 ? `<svg width="100%" height="64" viewBox="0 0 ${n.m.length * 10} 64" preserveAspectRatio="none">${n.m.map((v, i) => `<rect x="${i * 10 + 1}" y="${60 - v / mx * 56}" width="8" height="${v / mx * 56 + 1}" fill="${n.col}"><title>${mlab(f.months[M.i0 + i])}: ${eur(v)}</title></rect>`).join('')}</svg>` : '';
      el.innerHTML = `<h4>${esc(n.name)}</h4><div class="fv">${A(n.v)}</div><div class="dim">${pc(n.v / Math.max(1, M.E) * 100)} of spending${per > 1 ? ' · Ø ' + A(n.v / per) + ' / month' : ''}</div>${bars}
        <div class="fh">BIGGEST PAYEES</div>${ps.length ? ps.slice(0, 8).map(p => `<div class="fr"><span>${esc(p.n)}</span><span>${A(p.v)}</span></div>`).join('') : '<div class="dim">–</div>'}
        ${cat && !cat.parts && window.WVC ? `<button class="fb" id="flFix">✎ Fix categories…</button>` : ''}<button class="fb" id="flBack">← Overview</button>`;
      const fx = el.querySelector('#flFix'); if (fx) fx.onclick = () => window.WVC.open(); el.querySelector('#flBack').onclick = () => { st.sel = null; refresh(); };
      return;
    }
    const top = M.cats.slice(0, 6);
    el.innerHTML = `<h4>${esc(label(f, st))}</h4>
      <div class="fk"><span>Income</span><b>${A(M.I)}</b></div><div class="fk"><span>Spending</span><b>${A(M.E)}</b></div>
      <div class="fk"><span>${saved >= 0 ? 'Saved' : 'Drawn from savings'}</span><b class="${saved >= 0 ? 'up' : 'dn'}">${A(Math.abs(saved))}</b></div>
      <div class="fk"><span>Savings rate</span><b class="${rate == null ? '' : rate >= 0 ? 'up' : 'dn'}">${rate == null ? '–' : pc(rate)}</b></div>
      ${per > 1 ? `<div class="fk"><span>Ø spending / month</span><b>${A(M.E / per)}</b></div>` : ''}
      <div class="fh">BIGGEST CATEGORIES · click one</div>${top.map(c => `<div class="fr cl" data-c="${M.cats.indexOf(c)}"><span><i style="background:${c.col}"></i>${esc(c.n === SONST ? 'Unsorted' : c.n)}</span><span>${A(c.v)}</span></div>`).join('')}
      <div class="dim" style="margin-top:.6rem;font-size:.72em;line-height:1.5">Money that went into investments or moved between your own accounts is not counted. If you spent more than came in, the gap shows as “From savings &amp; reserves”.</div>
      ${window.WVC ? '<button class="fb" id="flFix">✎ Fix categories…</button>' : ''}`;
    el.querySelectorAll('.cl').forEach(r => r.onclick = () => { st.sel = 'c' + r.dataset.c; refresh(); });
    const fx = el.querySelector('#flFix'); if (fx) fx.onclick = () => window.WVC.open();
  }

  /* ------------------------------------------------------------ the pop-up */
  let refresh = () => { };
  function open() {
    const w = W(), d = w.S.D, f = d && d.flows; if (!f) return;
    ensureCss();
    w.modalShell('Cash flow · where your money goes', d.mode === 'demo' ? w.badge('demo', 'Demo') : w.srcBadge('gls', d), 'fit');
    const st = state(); st.sel = null;
    const years = [...new Set(f.months.map(m => m.slice(0, 4)))].reverse();
    const tools = document.getElementById('mtools');
    tools.innerHTML = seg('fpSeg') + `<select id="fpYr" title="Which year">${['last12'].concat(years).map(y => `<option value="${y}">${y === 'last12' ? 'Last 12 months' : y}</option>`).join('')}</select><span class="dim" id="fpLbl" style="margin-left:.8rem"></span>`;
    const body = document.getElementById('mbody'); body.style.overflow = 'hidden';
    body.innerHTML = '<div class="fp"><div class="fpm" id="fpM"></div><aside class="fps" id="fpS"></aside></div>';
    let cur = null;
    const yr = document.getElementById('fpYr'); yr.value = st.yr; yr.style.display = st.per === 'year' ? '' : 'none';
    refresh = () => {
      document.querySelectorAll('#fpSeg button').forEach(b => b.classList.toggle('on', b.dataset.per === st.per));
      yr.style.display = st.per === 'year' ? '' : 'none'; document.getElementById('fpLbl').textContent = label(f, st);
      cur = draw(document.getElementById('fpM'), f, st, id => { st.sel = id && cur && cur.nodes[id] && (cur.nodes[id].kind === 'cat') ? id : (id ? st.sel : null); refresh(); }, null);
      side(document.getElementById('fpS'), f, st, d, cur);
    };
    document.querySelectorAll('#fpSeg button').forEach(b => b.onclick = () => { st.per = b.dataset.per; st.sel = null; refresh(); w.renderAll && softBox(); });
    yr.onchange = () => { st.yr = yr.value; st.sel = null; refresh(); softBox(); };
    const ro = new ResizeObserver(() => { clearTimeout(ro.t); ro.t = setTimeout(refresh, 60); }); ro.observe(document.getElementById('fpM'));
    refresh();
  }
  /* keep the dashboard box in step with the pop-up (cheap: only the box is redrawn when the page offers it) */
  function softBox() { if (window.WV && WV.redrawFlowBox) WV.redrawFlowBox(); }

  let cssDone = false;
  function ensureCss() {
    if (cssDone) return; cssDone = true; const s = document.createElement('style');
    s.textContent = `.fseg{display:inline-flex;gap:0}.fseg button{padding:.12rem .55rem;font-size:.68rem;letter-spacing:.1em;border-radius:0}.fseg button+button{margin-left:-1px}
.fp{display:flex;gap:1rem;width:min(94vw,106rem);height:min(74vh,52rem);min-height:24rem}.fpm{position:relative;flex:1;min-width:0;min-height:0}
.fps{width:21rem;flex:none;overflow:auto;border-left:1px solid rgba(60,190,235,.25);padding:.2rem .2rem .2rem 1rem;font-size:.8rem}
.fps h4{margin:0 0 .5rem;font-weight:400;font-size:.9rem;letter-spacing:.14em;color:var(--or);text-transform:uppercase}.fps .fv{font-size:1.5rem;color:#fff;margin:.1rem 0}
.fps .fh{margin:.9rem 0 .3rem;font-size:.62rem;letter-spacing:.16em;color:var(--dim)}.fps .fk,.fps .fr{display:flex;justify-content:space-between;gap:.6rem;padding:.22rem 0;border-bottom:1px solid rgba(60,190,235,.1)}
.fps .fk b{font-weight:400;color:#fff}.fps .fk b.up{color:var(--gr)}.fps .fk b.dn{color:var(--rd)}.fps .fr span:first-child{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fps .fr.cl{cursor:pointer}.fps .fr.cl:hover{color:var(--or)}.fps .fr i{display:inline-block;width:.6rem;height:.6rem;margin-right:.5rem}.fps .fb{margin-top:.8rem;width:100%}
.fl-tip{position:absolute;display:none;pointer-events:none;background:rgba(0,14,22,.96);border:1px solid rgba(60,190,235,.5);padding:.4rem .6rem;font-size:.78rem;line-height:1.45;z-index:5;max-width:22rem}
.fl-t{paint-order:stroke;stroke:rgba(0,10,16,.85);stroke-width:3px;stroke-linejoin:round}.fl-l{transition:fill-opacity .12s}.fl-l:hover{fill-opacity:.6}
#mtools select{background:rgba(0,16,26,.85);color:#fff;border:1px solid rgba(60,190,235,.45);padding:.25rem .4rem;font:inherit;font-size:.8rem}
@media (max-width:1100px){.fp{flex-direction:column;height:auto}.fpm{height:32rem;flex:none}.fps{width:auto;border-left:0;padding-left:0}}`;
    document.head.appendChild(s);
  }
  ensureCss();
  window.WVF = { open, span, label, seg, state, PERS };
})();
