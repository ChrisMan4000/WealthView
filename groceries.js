/* WealthView v1.29 - Groceries pop-up: spending on online grocery orders (Knuspr) from the database tables groc_*.
   Opened from the "Groceries" button in the "Spending by category" box. Needs window.WV and a real-numbers session. */
(function () {
  'use strict';
  const W = () => window.WV;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf2 = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }), nf0 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
  const e2 = v => nf2.format(v) + ' €', e0 = v => nf0.format(Math.round(v)) + ' €', amt = v => '<span class="amt">' + e2(v) + '</span>';
  const ICON = { 'Kühlregal': '🧀', 'Fleisch & Fisch': '🥩', 'Brot & Gebäck': '🥖', 'Getränke': '🥤', 'Süßes & Salziges': '🍫', 'Obst & Gemüse': '🥦', 'Ready to eat': '🍱', 'Wurst & Schinken': '🥓', 'Kochen & Backen': '🍳', 'Marks & Spencer': '🛍️', 'Tiefkühlprodukte': '🧊', 'Drogerie': '🧴', 'Plant Based': '🌱', 'Baby & Kinder': '🍼', 'Haushalt & Büro': '🧽', 'Tabak': '🚬', 'Sonstiges': '📦' };
  const MON = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'], WD = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  const CDN = 'https://cdn.knuspr.de';
  let D = null, gran = 'month', range = 'all', cat = null, pTab = 'spend', imgs = true, catView = 'donut';

  const pad = n => String(n).padStart(2, '0');
  const dOf = ts => new Date(+ts.slice(0, 4), +ts.slice(5, 7) - 1, +ts.slice(8, 10));
  const iso = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  const monday = d => { const x = new Date(d); x.setDate(x.getDate() - (x.getDay() + 6) % 7); return x; };
  const keyOf = (ts, g) => g === 'year' ? ts.slice(0, 4) : g === 'month' ? ts.slice(0, 7) : g === 'day' ? ts.slice(0, 10) : iso(monday(dOf(ts)));
  function nextKey(k, g) { if (g === 'year') return String(+k + 1); if (g === 'month') { let y = +k.slice(0, 4), m = +k.slice(5, 7); if (++m > 12) { m = 1; y++; } return y + '-' + pad(m); } const d = dOf(k); d.setDate(d.getDate() + (g === 'week' ? 7 : 1)); return iso(d); }
  function labelOf(k, g) { if (g === 'year') return k; if (g === 'month') return MON[+k.slice(5, 7) - 1] + " '" + k.slice(2, 4); return k.slice(8, 10) + '.' + k.slice(5, 7) + '.'; }
  const colOf = c => { const P = W().PAL; const names = Object.keys(ICON); const i = names.indexOf(c); return P[(i < 0 ? names.length : i) % P.length]; };

  const catOf = p => /davidoff|tabak|zigarett/i.test(p[0] + ' ' + (p[3] || '')) ? 'Tabak' : (p[2] || 'Sonstiges');   // tobacco sits in several Knuspr groups: put it all together
  function view() {   // orders and items inside the chosen range (and category)
    const inR = ts => range === 'all' || (range === 'l12' ? ts >= iso(new Date(new Date().setFullYear(new Date().getFullYear() - 1))) : ts.startsWith(range));
    const ord = D.orders.filter(o => inR(o[1])), set = new Map(ord.map(o => [o[0], o]));
    let it = D.rows.filter(r => set.has(r[0])).map(r => { const p = D.products[r[1]] || ['?', '', 'Sonstiges', '', '']; return { o: set.get(r[0]), pid: r[1], q: r[2], e: r[3], cat: catOf(p), p }; });
    if (cat) it = it.filter(x => x.cat === cat);
    return { ord, it };
  }

  function barChart(v) {
    let g = gran; const o = v.ord; if (!o.length) return '<div class="dim sm">No orders in this range.</div>';
    const keyed = {}; for (const x of v.it) { const k = keyOf(x.o[1], g); const b = keyed[k] = keyed[k] || {}; b[x.cat] = (b[x.cat] || 0) + x.e; }
    let ks = Object.keys(keyed).sort(); const all = []; for (let k = ks[0]; k <= ks[ks.length - 1]; k = nextKey(k, g)) { all.push(k); if (all.length > 800) break; }
    let note = ''; if (g === 'day' && all.length > 120) { note = ' · last 120 days'; all.splice(0, all.length - 120); }
    const cats = [...new Set(v.it.map(x => x.cat))], tot = k => Object.values(keyed[k] || {}).reduce((a, b) => a + b, 0), max = Math.max(1, ...all.map(tot));
    const Wd = 1000, H = 250, L = 46, B = 26, T = 8, bw = (Wd - L) / all.length, ch = H - B - T; let s = '';
    for (let i = 0; i <= 3; i++) { const y = T + ch - ch * i / 3; s += `<line x1="${L}" x2="${Wd}" y1="${y}" y2="${y}" stroke="rgba(60,190,235,.15)"/><text x="${L - 5}" y="${y + 3}" text-anchor="end" font-size="10" fill="var(--dim)">${nf0.format(max * i / 3)}</text>`; }
    all.forEach((k, i) => { let y = T + ch; const x = L + i * bw, b = keyed[k] || {}; let tip = labelOf(k, g) + ': ' + e2(tot(k)); for (const c of cats) if (b[c]) tip += '\n' + c + ' ' + e2(b[c]);
      for (const c of cats) { const h = (b[c] || 0) / max * ch; if (h <= 0) continue; y -= h; s += `<rect x="${x + bw * .12}" y="${y}" width="${Math.max(1, bw * .76)}" height="${h}" fill="${colOf(c)}" opacity=".85"/>`; }
      s += `<rect x="${x}" y="${T}" width="${bw}" height="${ch}" fill="transparent"><title>${esc(tip)}</title></rect>`;
      if (all.length <= 24 || i % Math.ceil(all.length / 20) === 0) s += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle" font-size="10" fill="var(--dim)">${labelOf(k, g)}</text>`; });
    return `<svg viewBox="0 0 ${Wd} ${H}" style="width:100%;height:15rem">${s}</svg><div class="xs dim">Spend on items per ${g}${note}${cat ? ' · ' + esc(cat) : ''}. Hover a bar for the split.</div>`;
  }

  function donutCats(v0) {
    const t = {}; for (const x of v0.it) t[x.cat] = (t[x.cat] || 0) + x.e; const rows = Object.entries(t).sort((a, b) => b[1] - a[1]), sum = rows.reduce((a, r) => a + r[1], 0) || 1;
    let a = -Math.PI / 2, svg = ''; const R = 70, r = 44;
    for (const [c, e] of rows) { const f = e / sum, a1 = a + f * 2 * Math.PI; const p = (rad, an) => [100 + rad * Math.cos(an), 100 + rad * Math.sin(an)], [x0, y0] = p(R, a), [x1, y1] = p(R, a1), [x2, y2] = p(r, a1), [x3, y3] = p(r, a), lg = f > .5 ? 1 : 0;
      svg += f > .999 ? `<circle cx="100" cy="100" r="${(R + r) / 2}" fill="none" stroke="${colOf(c)}" stroke-width="${R - r}"/>` : `<path d="M${x0},${y0} A${R},${R} 0 ${lg} 1 ${x1},${y1} L${x2},${y2} A${r},${r} 0 ${lg} 0 ${x3},${y3}Z" fill="${colOf(c)}" opacity="${cat && cat !== c ? .25 : .9}" data-c="${esc(c)}" style="cursor:pointer"><title>${esc(c)}: ${e2(e)}</title></path>`; a = a1; }
    const leg = rows.map(([c, e]) => `<div class="tr gcat" data-c="${esc(c)}" style="grid-template-columns:1.4rem 1fr auto auto;gap:.4rem;cursor:pointer;opacity:${cat && cat !== c ? .45 : 1}"><span>${ICON[c] || '📦'}</span><span style="color:${colOf(c)}">${esc(c)}</span><span class="dim">${(100 * e / sum).toFixed(1).replace('.', ',')} %</span><span class="r wh">${amt(e)}</span></div>`).join('');
    return `<div style="display:grid;grid-template-columns:11rem 1fr;gap:1rem;align-items:start"><svg viewBox="0 0 200 200" style="width:11rem">${svg}<text x="100" y="97" text-anchor="middle" font-size="11" fill="var(--dim)">ITEMS</text><text x="100" y="114" text-anchor="middle" font-size="15" fill="var(--tx)" class="amt">${e0(sum)}</text></svg><div style="max-height:15rem;overflow:auto">${leg}</div></div><div class="xs dim">Click a category to filter every chart. Click again to clear.</div>`;
  }

  function squarify(items, x, y, w, h) {
    const out = [], tot = items.reduce((a, i) => a + i.v, 0) || 1, k = w * h / tot; let rest = items.map(i => ({ ...i, a: i.v * k }));
    const worst = (row, side) => { const s = row.reduce((a, i) => a + i.a, 0), mx = Math.max(...row.map(i => i.a)), mn = Math.min(...row.map(i => i.a)); return Math.max(side * side * mx / (s * s), s * s / (side * side * mn)); };
    while (rest.length) {
      const side = Math.min(w, h); let row = [rest.shift()]; while (rest.length && worst([...row, rest[0]], side) <= worst(row, side)) row.push(rest.shift());
      const s = row.reduce((a, i) => a + i.a, 0);
      if (w >= h) { const rw = s / h; let yy = y; for (const i of row) { const ih = i.a / rw; out.push({ ...i, x, y: yy, w: rw, h: ih }); yy += ih; } x += rw; w -= rw; }
      else { const rh = s / w; let xx = x; for (const i of row) { const iw = i.a / rh; out.push({ ...i, x: xx, y, w: iw, h: rh }); xx += iw; } y += rh; h -= rh; }
    }
    return out;
  }
  function treemap(v0) {   // heatmap: one tile per category, area = spend, with its icon
    const t = {}; for (const x of v0.it) { const c = t[x.cat] = t[x.cat] || { v: 0, sub: {} }; c.v += x.e; const sb = x.p[3] || '–'; c.sub[sb] = (c.sub[sb] || 0) + x.e; }
    const items = Object.entries(t).filter(([, c]) => c.v > 0).map(([c, o]) => ({ c, v: o.v, sub: o.sub })).sort((a, b) => b.v - a.v), sum = items.reduce((a, i) => a + i.v, 0) || 1, Wd = 640, H = 340;
    let svg = ''; for (const i of squarify(items, 0, 0, Wd, H)) {
      const big = Math.min(i.w, i.h), fs = Math.max(12, Math.min(54, big * .42)), top = Object.entries(i.sub).sort((a, b) => b[1] - a[1])[0];
      svg += `<g data-c="${esc(i.c)}" style="cursor:pointer" opacity="${cat && cat !== i.c ? .35 : 1}"><title>${esc(i.c)}: ${e2(i.v)} (${(100 * i.v / sum).toFixed(1).replace('.', ',')} %)${top ? '\nlargest: ' + esc(top[0]) + ' ' + e2(top[1]) : ''}</title><rect x="${i.x + 1}" y="${i.y + 1}" width="${Math.max(0, i.w - 2)}" height="${Math.max(0, i.h - 2)}" fill="${colOf(i.c)}" fill-opacity="${.28 + .5 * i.v / items[0].v}" stroke="${colOf(i.c)}" stroke-opacity=".8"/>`;
      if (i.w > 26 && i.h > 26) svg += `<text x="${i.x + i.w / 2}" y="${i.y + i.h / 2 + (i.h > 70 ? -4 : fs * .35)}" text-anchor="middle" font-size="${fs}">${ICON[i.c] || '📦'}</text>`;
      if (i.w > 78 && i.h > 70) svg += `<text x="${i.x + i.w / 2}" y="${i.y + i.h / 2 + fs * .55 + 8}" text-anchor="middle" font-size="11" fill="var(--tx)">${esc(i.c.slice(0, Math.floor(i.w / 7)))}</text><text x="${i.x + i.w / 2}" y="${i.y + i.h / 2 + fs * .55 + 22}" text-anchor="middle" font-size="11" fill="var(--or)">${nf0.format(i.v)} € · ${Math.round(100 * i.v / sum)} %</text>`;
      svg += '</g>';
    }
    return `<svg viewBox="0 0 ${Wd} ${H}" style="width:100%;max-height:22rem">${svg}</svg><div class="xs dim">Area = spend. Click a tile to filter every chart. Click again to clear.</div>`;
  }

  function freq(v) {   // how often: gaps between orders, and how regularly each product comes back
    const days = [...new Set(v.ord.map(o => o[1].slice(0, 10)))].sort(); if (days.length < 3) return '<div class="dim sm">Not enough orders.</div>';
    const dd = (a, b) => Math.round((dOf(b) - dOf(a)) / 864e5), gaps = days.slice(1).map((d, i) => dd(days[i], d)), srt = [...gaps].sort((a, b) => a - b), med = srt[Math.floor(srt.length / 2)], avg = gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const bins = [['1', 1, 1], ['2', 2, 2], ['3', 3, 3], ['4-5', 4, 5], ['6-7', 6, 7], ['8-10', 8, 10], ['11-14', 11, 14], ['15-21', 15, 21], ['22-30', 22, 30], ['31+', 31, 1e9]].map(([l, a, b]) => [l, gaps.filter(g => g >= a && g <= b).length]), mx = Math.max(1, ...bins.map(b => b[1]));
    let s = ''; const bw = 60; bins.forEach(([l, n], i) => { const h = n / mx * 110; s += `<rect x="${i * bw + 8}" y="${125 - h}" width="${bw - 16}" height="${h}" fill="var(--or)" opacity=".8"><title>${l} days between orders: ${n}×</title></rect><text x="${i * bw + bw / 2}" y="${140}" text-anchor="middle" font-size="10" fill="var(--dim)">${l}</text><text x="${i * bw + bw / 2}" y="${120 - h}" text-anchor="middle" font-size="10" fill="var(--tx)">${n || ''}</text>`; });
    const g = {}; for (const x of v.it) { const k = x.p[0].trim().toLowerCase(), o = g[k] = g[k] || { n: x.p[0], c: x.cat, d: new Set() }; o.d.add(x.o[1].slice(0, 10)); }
    const reg = Object.values(g).filter(o => o.d.size >= 4).map(o => { const d = [...o.d].sort(); return { n: o.n, c: o.c, k: d.length, every: dd(d[0], d[d.length - 1]) / (d.length - 1), last: d[d.length - 1] }; }).sort((a, b) => a.every - b.every).slice(0, 10);
    const k = (l, val) => `<div>${l}<b>${val}</b></div>`;
    return `<div class="stats">${k('Order every', '≈ ' + avg.toFixed(1).replace('.', ',') + ' days')}${k('Median gap', med + ' days')}${k('Shortest gap', srt[0] + ' day' + (srt[0] === 1 ? '' : 's'))}${k('Longest gap', srt[srt.length - 1] + ' days')}${k('Order days', days.length)}</div>
      <svg viewBox="0 0 ${bins.length * bw} 148" style="width:100%;margin:.4rem 0">${s}</svg><div class="xs dim">Days between two order days.</div>
      <div class="xs dim gh" style="margin-top:.6rem;letter-spacing:.14em">STAPLES · HOW OFTEN A PRODUCT COMES BACK</div>` +
      (reg.map(r => `<div class="tr" style="grid-template-columns:1.4rem 1fr auto auto;gap:.5rem;cursor:default"><span>${ICON[r.c] || '📦'}</span><span class="wh" title="${esc(r.n)}">${esc(r.n.slice(0, 44))}</span><span class="dim">${r.k}×</span><span class="r">every ${r.every.toFixed(1).replace('.', ',')} d</span></div>`).join('') || '<div class="dim sm">No product bought 4 times or more.</div>');
  }

  function products(v) {
    const t = {}; for (const x of v.it) { const k = x.p[0].trim().toLowerCase(), p = t[k] = t[k] || { p: x.p, cat: x.cat, ords: new Set(), q: 0, e: 0, last: '', ids: new Set() }; p.ords.add(x.o[0]); p.ids.add(x.pid); p.q += x.q || 0; p.e += x.e; if (x.o[1] > p.last) p.last = x.o[1]; }
    const rows = Object.values(t).map(p => ({ ...p, n: p.ords.size })).sort((a, b) => pTab === 'spend' ? b.e - a.e : b.n - a.n || b.e - a.e).slice(0, 15);
    const img = p => imgs && p.p[1] ? `<img src="${CDN}${esc(p.p[1])}" alt="" loading="lazy" referrerpolicy="no-referrer" style="width:2.4rem;height:2.4rem;object-fit:contain;background:#fff;border-radius:.2rem">` : `<span style="font-size:1.4rem">${ICON[p.cat] || '📦'}</span>`;
    return `<div class="htools" style="margin-bottom:.4rem"><button data-pt="spend" class="${pTab === 'spend' ? 'on' : ''}">Top by spend</button><button data-pt="freq" class="${pTab === 'freq' ? 'on' : ''}">Top by frequency</button><span class="sep"></span><button id="gimg" class="${imgs ? 'on' : ''}" title="Product pictures are loaded from cdn.knuspr.de">Pictures</button></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:0 1.2rem">` +
      rows.map(p => `<div class="tr" style="grid-template-columns:2.8rem 1fr auto auto;gap:.6rem;cursor:default;align-items:center"><span style="text-align:center">${img(p)}</span><span title="${esc(p.p[0])}"><span class="wh">${esc(p.p[0].slice(0, 52))}</span>${p.ids.size > 1 ? ` <span class="chip">${p.ids.size} sizes</span>` : ''}<br><span class="xs dim">${esc(p.cat)} · last ${p.last.slice(0, 10)}</span></span><span class="dim">${p.n}× </span><span class="r wh">${amt(p.e)}</span></div>`).join('') + '</div>';
  }

  function kpis(v) {
    const o = v.ord, n = o.length; if (!n) return '';
    const sum = i => o.reduce((a, r) => a + (r[i] || 0), 0), tot = sum(2), first = o.reduce((a, r) => r[1] < a ? r[1] : a, '9'), last = o.reduce((a, r) => r[1] > a ? r[1] : a, '');
    const months = Math.max(1, (dOf(last) - dOf(first)) / 2629800000 + 1), days = Math.max(1, (dOf(last) - dOf(first)) / 86400000 + 1);
    const wd = Array(7).fill(0); o.forEach(r => wd[(dOf(r[1]).getDay() + 6) % 7]++); const best = wd.indexOf(Math.max(...wd));
    const big = o.reduce((a, r) => r[2] > a[2] ? r : a, o[0]), items = o.reduce((a, r) => a + r[8], 0);
    const k = (l, val, sub) => `<div>${l}<b>${val}</b>${sub ? `<span class="xs dim">${sub}</span>` : ''}</div>`;
    return `<div class="stats">${k('Total spent', amt(tot), n + ' orders')}${k('Ø per order', amt(tot / n), items + ' items')}${k('Ø per month', amt(tot / months), 'Ø per day ' + e2(tot / days))}${k('Orders per month', (n / months).toFixed(1).replace('.', ','), 'every ' + Math.max(1, Math.round(days / n)) + ' days')}${k('Delivery + tips', amt(sum(4) + sum(5)), 'deposit/packaging ' + e2(sum(6)))}${k('Biggest order', amt(big[2]), big[1].slice(0, 10))}${k('Favourite day', WD[best], wd[best] + ' orders')}</div>`;
  }

  function paint() {
    const v = view(), v0 = (() => { const c = cat; cat = null; const r = view(); cat = c; return r; })(), m = document.getElementById('mbody'); if (!m) return;
    const sw = `<span style="display:flex;gap:.3rem"><button data-cv="donut" class="${catView === 'donut' ? 'on' : ''}">Donut</button><button data-cv="heat" class="${catView === 'heat' ? 'on' : ''}">Heatmap</button></span>`;
    m.innerHTML = kpis(v) + `<div class="gbox"><div class="xs dim gh">SPEND OVER TIME</div>${barChart(v)}</div>
      <div class="ggrid"><div class="gbox"><div class="xs dim gh" style="display:flex;justify-content:space-between;align-items:center"><span>BY CATEGORY</span>${sw}</div>${catView === 'heat' ? treemap(v0) : donutCats(v0)}</div><div class="gbox"><div class="xs dim gh">FREQUENCY</div>${freq(v)}</div></div>
      <div class="gbox"><div class="xs dim gh">PRODUCTS</div>${products(v)}</div>`;
    m.querySelectorAll('[data-c]').forEach(x => x.onclick = () => { cat = cat === x.dataset.c ? null : x.dataset.c; paint(); });
    m.querySelectorAll('[data-pt]').forEach(x => x.onclick = () => { pTab = x.dataset.pt; paint(); });
    m.querySelectorAll('[data-cv]').forEach(x => x.onclick = () => { catView = x.dataset.cv; paint(); });
    const gi = m.querySelector('#gimg'); if (gi) gi.onclick = () => { imgs = !imgs; paint(); };
  }

  function tools() {
    const yrs = [...new Set(D.orders.map(o => o[1].slice(0, 4)))].sort();
    const g = [['year', 'Yearly'], ['month', 'Monthly'], ['week', 'Weekly'], ['day', 'Daily']], r = [['all', 'All time'], ['l12', 'Last 12 months'], ...yrs.reverse().map(y => [y, y])];
    const t = document.getElementById('mtools'); t.innerHTML = r.map(([k, l]) => `<button data-r="${k}" class="${range === k ? 'on' : ''}">${l}</button>`).join('') + '<span class="sep"></span>' + g.map(([k, l]) => `<button data-g="${k}" class="${gran === k ? 'on' : ''}">${l}</button>`).join('');
    t.querySelectorAll('button').forEach(b => b.onclick = () => { if (b.dataset.r) range = b.dataset.r; if (b.dataset.g) gran = b.dataset.g; tools(); paint(); });
  }

  function css() {
    if (document.getElementById('grocCss')) return; const s = document.createElement('style'); s.id = 'grocCss';
    s.textContent = '.gbox{border:1px solid rgba(60,190,235,.3);background:rgba(0,16,26,.55);padding:.6rem .8rem}.gbox .gh{letter-spacing:.14em;margin-bottom:.4rem}.ggrid{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}.gcat:hover,.gord:hover{background:rgba(60,190,235,.08)}@media(max-width:1100px){.ggrid{grid-template-columns:1fr}}';
    document.head.appendChild(s);
  }

  async function open() {
    const w = W(); if (!w) return; css();
    w.modalShell('Groceries · Knuspr', w.badge('static', 'Database'), 'wide'); const mb = document.getElementById('mbody'); mb.innerHTML = '<div class="dim sm">Loading…</div>';
    document.getElementById('mdl').style.width = 'min(98vw,82rem)';
    try { const r = await w.api('/api/groceries'); if (!r.ok) throw new Error(r.error || 'could not load'); if (r.empty) { mb.innerHTML = '<div class="empty">No grocery orders in the database yet. Import a Knuspr export first (see docs: "WealthView - v1.29 changes").</div>'; return; }
      D = r; gran = 'month'; range = 'all'; cat = null; tools(); paint(); }
    catch (e) { mb.innerHTML = '<div class="empty">' + esc(e.message) + '</div>'; }
  }
  window.WVG = { open };
})();
