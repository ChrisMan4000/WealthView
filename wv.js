/* WealthView - dashboard logic. Demo numbers first; real numbers after the password (served by server.py). */
(function () {
  'use strict';
  const $ = (s, e) => (e || document).querySelector(s), $$ = (s, e) => [...(e || document).querySelectorAll(s)];
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf0 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }), nf2 = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const eur = v => v == null ? '–' : nf0.format(Math.round(v)) + ' €';
  const A = v => '<span class="amt">' + eur(v) + '</span>';
  const kfmt = v => { const a = Math.abs(v); return a >= 1e6 ? (v / 1e6).toFixed(a >= 1e7 ? 1 : 2).replace('.', ',') + ' M' : a >= 1e3 ? (v / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace('.', ',') + ' k' : nf0.format(Math.round(v)); };
  const pct = (v, d = 1) => v == null || isNaN(v) ? '–' : (v > 0 ? '+' : '') + v.toFixed(d).replace('.', ',') + ' %';
  const cl = v => v > 0 ? 'pos' : v < 0 ? 'neg' : '';
  /* performance glow: |v| <= 5 % keeps the normal text colour; above that green (good) or reddish (bad) with a glow that grows
     with the size of the move; from +/-100 % on the value "breathes", faster the further past 100 % it is. */
  const mixc = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
  function glowOf(v) {
    if (v == null || isNaN(v)) return null; const a = Math.abs(v); if (a <= 5) return { cls: 'gl gl0', style: '' };
    const t = Math.min(1, (a - 5) / 95), c = v > 0 ? mixc([121, 201, 160], [48, 255, 140], t) : mixc([224, 138, 96], [255, 36, 36], t), blur = (3 + 15 * t).toFixed(1), rgb = c.join(',');
    let style = `color:rgb(${rgb});text-shadow:0 0 ${blur}px rgba(${rgb},${(.35 + .55 * t).toFixed(2)})`, cls = 'gl';
    if (a >= 100) { cls += ' br'; style += `;--gc:rgba(${rgb},.95);--gb:${blur}px;--bd:${Math.max(.35, Math.min(3, 3 * 100 / a)).toFixed(2)}s`; }
    return { cls, style };
  }
  const PCT_RX = /([+\-−]?)\s*(\d[\d.]*(?:,\d+)?)\s*%/;
  function glowPass() {
    document.querySelectorAll('.pos,.neg,[data-gl]').forEach(el => {
      if (el.dataset.glDone || el.closest('.nogl')) return;
      const m = PCT_RX.exec(el.textContent || ''); if (!m) return;
      let v = parseFloat(m[2].replace(/\./g, '').replace(',', '.')); if (isNaN(v)) return;
      const neg = m[1] === '-' || m[1] === '−' || (!m[1] && el.classList.contains('neg')); if (neg) v = -v;
      const g = glowOf(v); if (!g) return;
      el.classList.remove('pos', 'neg'); g.cls.split(' ').forEach(c => el.classList.add(c)); if (g.style) el.style.cssText += ';' + g.style; el.dataset.glDone = '1';
    });
  }
  let glowQ = 0; new MutationObserver(() => { if (!glowQ) glowQ = requestAnimationFrame(() => { glowQ = 0; glowPass(); }); }).observe(document.documentElement, { childList: true, subtree: true });
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const mlab = m => MON[+m.slice(5, 7) - 1] + ' ' + m.slice(2, 4);
  const CLS = ['Real estate', 'Securities', 'Private equity', 'Cash', 'Crypto'];
  const CCOL = { 'Real estate': '#2a82d0', 'Securities': '#22aecf', 'Private equity': '#d98338', 'Cash': '#6fbf95', 'Crypto': '#d1ac3c' };
  const PAL = ['#22aecf', '#d98338', '#6fbf95', '#2a82d0', '#d1ac3c', '#9a7fd4', '#cf6060', '#4fb0a4', '#c67bb2', '#8199a8', '#a2bd58', '#d49784', '#7c8fd0', '#c9a06a'];
  const SS = { get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch (e) { } } };
  const S = { cfg: {}, mode: 'demo', D: null, DEMO: null, token: SS.get('wvtok'), lastGen: null, range: 'MAX', gran: 'M', sort: ['value', -1], chat: [], busy: false, liveAt: null, heatOn: {} };
  const server = location.protocol.startsWith('http');

  /* ================================================== worn-tech frame (same idea as the Jarvis boxes) */
  function rng(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  const FC = {};
  function frameSVG(w, h, seed) {
    const key = w + 'x' + h + ':' + seed; if (FC[key]) return FC[key];
    const r = rng(seed), c = Math.max(8, Math.min(20, Math.min(w, h) * .05)), col = '60,190,235', per = 2 * (w + h);
    const P = `M${c},0.6 L${w - c},0.6 L${w - .6},${c} L${w - .6},${h - c} L${w - c},${h - .6} L${c},${h - .6} L.6,${h - c} L.6,${c} Z`;
    const dash = []; let tot = 0; while (tot < per) { const l = per * (.08 + r() * .3), g = 2 + r() * 4; dash.push(l.toFixed(1), g.toFixed(1)); tot += l + g; }
    const ins = 6, c2 = c * .8, P2 = `M${c2 + ins},${ins} L${w - c2 - ins},${ins} L${w - ins},${c2 + ins} L${w - ins},${h - c2 - ins} L${w - c2 - ins},${h - ins} L${c2 + ins},${h - ins} L${ins},${h - c2 - ins} L${ins},${c2 + ins} Z`;
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a7a9e" stop-opacity=".20"/><stop offset=".22" stop-color="#001018" stop-opacity=".66"/><stop offset="1" stop-color="#000a12" stop-opacity=".78"/></linearGradient><radialGradient id="sm"><stop offset="0" stop-color="#fff" stop-opacity=".07"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>`;
    s += `<path d="${P}" fill="url(#g)"/>`;
    s += `<path d="${P}" transform="translate(3,3)" fill="none" stroke="rgba(${col},.15)" stroke-width="1"/>`;
    s += `<path d="${P2}" fill="none" stroke="rgba(${col},.26)" stroke-width="1" stroke-dasharray="${w * .22} 5 ${w * .3} 4 ${w * .2} 6"/>`;
    s += `<path d="${P}" fill="none" stroke="rgba(${col},.8)" stroke-width="1.25" stroke-dasharray="${dash.join(' ')}"/>`;
    s += `<path d="M${c},1.6 L${w - c},1.6 M1.6,${c} L1.6,${h - c}" stroke="rgba(255,255,255,.22)" stroke-width="1" fill="none"/>`;
    s += `<path d="M${w - c},${h - 1.6} L${c},${h - 1.6} M${w - 1.6},${h - c} L${w - 1.6},${c}" stroke="rgba(0,0,0,.55)" stroke-width="1" fill="none"/>`;
    if (h > 180) { let t = ''; const y0 = h * (.25 + r() * .3); for (let i = 0; i < 12; i++) t += `M${w - 1},${y0 + i * 7} l-${i % 4 === 0 ? 7 : 4},0 `; s += `<path d="${t}" stroke="rgba(${col},.55)" stroke-width="1" fill="none"/>`; }
    if (w > 300) { let t = ''; let x = w * .35; for (let i = 0; i < 26; i++) { x += 1 + r() * 2.6; t += `M${x.toFixed(1)},${h - 4} l0,-${(3 + r() * 3).toFixed(1)} `; } s += `<path d="${t}" stroke="rgba(${col},.28)" stroke-width="1" fill="none"/>`; }
    for (let i = 0; i < 1 + Math.floor(r() * 3); i++) s += `<ellipse cx="${(r() * w).toFixed(0)}" cy="${(r() * h).toFixed(0)}" rx="${(20 + r() * 70).toFixed(0)}" ry="${(10 + r() * 40).toFixed(0)}" fill="url(#sm)"/>`;
    for (let i = 0; i < 2 + Math.floor(r() * 2); i++) { const x = r() * w, y = r() * h; s += `<path d="M${x.toFixed(0)},${y.toFixed(0)} l${(r() * 60 - 20).toFixed(0)},${(r() * 24 - 12).toFixed(0)}" stroke="rgba(255,255,255,.07)" stroke-width="1"/>`; }
    s += `<text x="${w - c - 6}" y="${h - 6}" text-anchor="end" font-size="8.4" font-family="Consolas,monospace" fill="rgba(${col},.45)">WV-${String(1000 + Math.floor(r() * 9000))}// 11-26</text></svg>`;
    return FC[key] = 'url("data:image/svg+xml;utf8,' + encodeURIComponent(s) + '")';
  }
  const FRO = new ResizeObserver(es => es.forEach(e => paintFrame(e.target)));
  function paintFrame(el) { const bg = el.querySelector(':scope>.bg'); if (!bg) return; const w = Math.round(el.clientWidth), h = Math.round(el.clientHeight); if (w < 40 || h < 30) return; bg.style.background = frameSVG(w, h, hash(el.id || el.className)) + ' no-repeat 0 0/100% 100%'; }
  function frameAll(root) { $$('.bx,.modal', root || document).forEach(el => { if (!el.__fr) { el.__fr = 1; FRO.observe(el); } paintFrame(el); }); }

  /* ================================================== charts */
  const TSR = new WeakMap(), RO = new ResizeObserver(es => es.forEach(e => { const c = TSR.get(e.target); if (c) drawTS(e.target, c); }));
  function TS(el, cfg) { if (!el) return; TSR.set(el, cfg); RO.observe(el); drawTS(el, cfg); }
  function niceStep(x) { const p = Math.pow(10, Math.floor(Math.log10(x))), f = x / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; }
  function hexA(h, a) { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; }
  function drawTS(el, cfg) {
    const W = el.clientWidth, H = el.clientHeight; if (W < 50 || H < 40) return;
    const na = cfg.noaxis, L = na ? 4 : 52, R = 10, T = 14, B = na ? 4 : 22, iw = W - L - R, ih = H - T - B, n = cfg.x.length;
    if (!n) { el.innerHTML = '<div class="empty">No data for this range.</div>'; return; }
    const ser = cfg.series.filter(s => !s.off); let lo = Infinity, hi = -Infinity;
    if (cfg.stacked) { const base = new Array(n).fill(0); ser.filter(s => !(s.type === 'line' && s.fixed)).forEach(s => { s._lo = base.slice(); s._hi = s.v.map((v, i) => base[i] += v || 0); }); hi = Math.max(...base, 1); lo = 0; ser.filter(s => s.type === 'line' && s.fixed).forEach(s => s.v.forEach(v => { if (v != null) hi = Math.max(hi, v); })); }
    else { ser.forEach(s => s.v.forEach(v => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } })); }
    (cfg.refs || []).forEach(rf => { lo = Math.min(lo, rf.v); hi = Math.max(hi, rf.v); });
    /* dotted "average" line(s): the mean of what is drawn (stacked charts: of the total; otherwise per series, max. 3) */
    const avgL = []; if (!cfg.noavg) {
      const mean = a => { const v = a.filter(x => x != null && isFinite(x)); return v.length ? v.reduce((p, q) => p + q, 0) / v.length : null; };
      if (cfg.stacked) { const tot = cfg.x.map((_, i) => ser.filter(s => !(s.type === 'line' && s.fixed)).reduce((a, s) => a + (s.v[i] || 0), 0)), m = mean(tot.filter((_, i) => ser.some(s => s.v[i] != null))); if (m != null) avgL.push({ v: m, c: '#cfe6ee' }); }
      else ser.slice(0, 3).forEach(s => { const m = mean(s.v); if (m != null) avgL.push({ v: m, c: ser.length === 1 ? '#cfe6ee' : (s.c || '#cfe6ee') }); });
    }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const needZero = cfg.zero != null ? cfg.zero : ser.some(s => s.type !== 'line'); if (needZero) lo = Math.min(0, lo);
    if (hi === lo) hi = lo + 1; const pad = (hi - lo) * .06; hi += pad; if (!needZero) lo -= pad;
    const st = niceStep((hi - lo) / (na ? 3 : 4)), y0 = Math.floor(lo / st) * st, y1 = Math.ceil(hi / st) * st;
    const band = ser.some(s => s.type === 'bar'), X = i => L + iw * (band ? (i + .5) / n : (n === 1 ? .5 : i / (n - 1))), Y = v => T + ih * (1 - (v - y0) / (y1 - y0));
    const fmt = cfg.fmt || kfmt; let g = '';
    if (!na) {
      for (let v = y0; v <= y1 + st / 2; v += st) { const y = Y(v); g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="rgba(60,190,235,${Math.abs(v) < 1e-9 ? .45 : .12})"/><text x="${L - 6}" y="${y + 3}" text-anchor="end" font-size="11.4" fill="rgba(127,220,255,.6)">${fmt(v)}</text>`; }
      const step = Math.max(1, Math.ceil(n / Math.max(3, Math.floor(iw / 70))));
      for (let i = 0; i < n; i += step) g += `<text x="${X(i)}" y="${H - 5}" text-anchor="middle" font-size="11.4" fill="rgba(127,220,255,.6)">${esc(cfg.xl(i))}</text>`;
    }
    const nb = ser.filter(s => s.type === 'bar').length, bw = iw / n * (cfg.stacked ? .74 : .8), bi = ser.filter(s => s.type === 'bar'); let bk = 0;
    ser.forEach(s => {
      const col = s.c || '#19d3ff';
      if (s.type === 'bar') {
        const k = bk++;
        s.v.forEach((v, i) => { if (v == null) return; const xw = cfg.stacked ? bw : bw / nb, x = X(i) - bw / 2 + (cfg.stacked ? 0 : k * xw); const a = cfg.stacked ? Y(s._hi[i]) : Y(Math.max(v, 0)), b2 = cfg.stacked ? Y(s._lo[i]) : Y(Math.min(v, 0)); g += `<rect x="${x.toFixed(1)}" y="${Math.min(a, b2).toFixed(1)}" width="${Math.max(1, xw - 1).toFixed(1)}" height="${Math.max(.5, Math.abs(b2 - a)).toFixed(1)}" fill="${hexA(col, .78)}"/>`; });
      } else if (s.type === 'area') {
        let up = '', dn = ''; s.v.forEach((v, i) => { const vv = cfg.stacked ? s._hi[i] : v; if (vv == null) return; up += (up ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(vv).toFixed(1); });
        if (cfg.stacked) { for (let i = n - 1; i >= 0; i--) dn += 'L' + X(i).toFixed(1) + ',' + Y(s._lo[i]).toFixed(1); g += `<path d="${up}${dn}Z" fill="${hexA(col, .42)}"/><path d="${up}" fill="none" stroke="${col}" stroke-width="1.2"/>`; }
        else { const idx = s.v.map((v, i) => v == null ? -1 : i).filter(i => i >= 0); if (idx.length) g += `<path d="${up}L${X(idx[idx.length - 1]).toFixed(1)},${Y(0 > y0 ? 0 : y0)}L${X(idx[0]).toFixed(1)},${Y(0 > y0 ? 0 : y0)}Z" fill="${hexA(col, .22)}"/><path d="${up}" fill="none" stroke="${col}" stroke-width="1.5"/>`; }
      } else {
        let d = '', pen = false; s.v.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); pen = true; });
        g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="${s.w || 1.6}"${s.dash ? ' stroke-dasharray="5 4"' : ''}/>`;
      }
    });
    (cfg.refs || []).forEach(rf => { const y = Y(rf.v); g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="${rf.c || '#ff9a3d'}" stroke-dasharray="4 4" opacity=".8"/><text x="${W - R - 2}" y="${y - 3}" text-anchor="end" font-size="10.8" fill="${rf.c || '#ff9a3d'}">${esc(rf.label)}</text>`; });
    avgL.forEach((a, k) => { const y = Y(a.v); if (y < T - 2 || y > T + ih + 2) return; g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="${a.c}" stroke-width="1.3" stroke-dasharray="1.5 4" stroke-linecap="round" opacity=".85"/><text x="${L + 4}" y="${y - 3 - k * 0}" font-size="${na ? 9.5 : 11}" fill="${a.c}" opacity=".95">Ø ${fmt(a.v)}</text>`; });
    el.innerHTML = `<svg width="${W}" height="${H}" style="display:block"><g>${g}</g><line class="cx" y1="${T}" y2="${T + ih}" stroke="rgba(255,154,61,.8)" style="display:none"/><rect class="hv" x="${L}" y="${T}" width="${iw}" height="${ih}" fill="transparent"/></svg><div class="tip"></div>`;
    const svg = $('svg', el), cx = $('.cx', el), tip = $('.tip', el), hv = $('.hv', el);
    hv.onmousemove = e => {
      const r = svg.getBoundingClientRect(), px = e.clientX - r.left; let i = band ? Math.floor((px - L) / iw * n) : Math.round((px - L) / iw * (n - 1)); i = Math.max(0, Math.min(n - 1, i));
      cx.setAttribute('x1', X(i)); cx.setAttribute('x2', X(i)); cx.style.display = '';
      let rows = ser.map(s => s.v[i] == null ? '' : `<div><i style="background:${s.c || '#19d3ff'}"></i>${esc(s.n)}: <b class="wh">${(cfg.tipfmt || (v => eur(v)))(s.v[i], s)}</b></div>`).join('');
      if (cfg.stacked && ser.length > 1) rows += `<div style="border-top:1px solid rgba(60,190,235,.3);margin-top:.2rem;padding-top:.2rem">Total: <b class="wh">${(cfg.tipfmt || (v => eur(v)))(ser.filter(s => !(s.type === 'line' && s.fixed)).reduce((a, s) => a + (s.v[i] || 0), 0))}</b></div>`;
      tip.innerHTML = `<div class="or">${esc(cfg.xl(i))}</div>${rows}`; tip.style.display = 'block';
      const tw = tip.offsetWidth; let tx = X(i) + 14; if (tx + tw > W) tx = X(i) - tw - 14; tip.style.left = Math.max(0, tx) + 'px'; tip.style.top = '6px';
    };
    hv.onmouseleave = () => { cx.style.display = 'none'; tip.style.display = 'none'; };
  }
  /* range + granularity (monthly / yearly) preparation of raw monthly series */
  function prep(raw, o) {
    const ax = raw.axis; let first = ax.findIndex((_, i) => raw.series.some(s => s.v[i] != null)); if (first < 0) first = 0;
    const cut = o.range === 'MAX' ? 0 : Math.max(0, ax.length - ({ '1Y': 12, '3Y': 36, '5Y': 60 }[o.range] || ax.length)), i0 = Math.max(first, cut);
    let x = ax.slice(i0), ser = raw.series.map(s => Object.assign({}, s, { v: s.v.slice(i0) }));
    if (o.gran === 'Y') {
      const ys = [...new Set(x.map(m => m.slice(0, 4)))];
      ser = ser.map(s => Object.assign(s, { v: ys.map(y => { const vs = s.v.filter((_, i) => x[i].startsWith(y) && s.v[i] != null); if (!vs.length) return null; return (raw.kind === 'flow' || s.flow) ? vs.reduce((a, b) => a + b, 0) : vs[vs.length - 1]; }) }));
      x = ys;
    }
    return Object.assign({}, raw, { x, xl: o.gran === 'Y' ? (i => x[i] + (x[i] === String(new Date().getFullYear()) ? ' YTD' : '')) : (i => mlab(x[i])), series: ser });
  }
  function donut(items, o) {
    const size = o.size || 200, th = o.th || size * .16, R = size / 2 - th / 2 - 3, tot = items.reduce((s, i) => s + i.v, 0) || 1; let a = -Math.PI / 2, s = `<svg viewBox="0 0 ${size} ${size}" width="100%" height="100%">`;
    items.forEach((it, i) => { const f = it.v / tot, a1 = a + f * 2 * Math.PI - (items.length > 1 ? .02 : 0); const large = f > .5 ? 1 : 0, c = size / 2; const p = f > .999 ? `M${c},${c - R} A${R},${R} 0 1 1 ${c - .01},${c - R}` : `M${c + R * Math.cos(a + .01)},${c + R * Math.sin(a + .01)} A${R},${R} 0 ${large} 1 ${c + R * Math.cos(a1)},${c + R * Math.sin(a1)}`; s += `<path class="dseg" data-k="${esc(it.k)}" d="${p}" fill="none" stroke="${it.c}" stroke-width="${th}" opacity=".85" style="cursor:pointer"><title>${esc(it.k)}: ${eur(it.v)} (${(f * 100).toFixed(1).replace('.', ',')} %)</title></path>`; a += f * 2 * Math.PI; });
    s += `<text x="${size / 2}" y="${size / 2 - 2}" text-anchor="middle" font-size="${size * .14}" fill="#fff"${o.amt ? ' class="amt"' : ''}>${esc(o.center || '')}</text><text x="${size / 2}" y="${size / 2 + size * .09}" text-anchor="middle" font-size="${size * .065}" fill="rgba(127,220,255,.6)" letter-spacing="1.5">${esc(o.sub || '')}</text></svg>`; return s;
  }

  /* ================================================== logos (iron-man tinted real icons, monogram fallback) */
  function logo(key, label, big) {
    const L = window.SRC_LOGOS || {};
    if (L[key]) return `<span class="lg${big ? ' big' : ''}"><img alt="" src="${L[key]}"></span>`;
    const m = String(label || key).replace(/[^A-Za-z0-9 ]/g, '').split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?';
    return `<span class="lg m${big ? ' big' : ''}">${esc(m)}</span>`;
  }
  const ICON = { loan: '<svg viewBox="0 0 24 24" width="70%" height="70%" fill="none" stroke="#d98338" stroke-width="1.6"><circle cx="12" cy="12" r="8"/><path d="M12 7v10M9 9.5c0-1.5 6-1.5 6 0s-6 2-6 3.5 6 1.5 6 0"/></svg>', house: '<svg viewBox="0 0 24 24" width="70%" height="70%" fill="none" stroke="#19d3ff" stroke-width="1.6"><path d="M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10"/></svg>', pe: '<svg viewBox="0 0 24 24" width="70%" height="70%" fill="none" stroke="#19d3ff" stroke-width="1.6"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>' };
  const iconLg = k => `<span class="lg">${ICON[k]}</span>`;

  /* ================================================== modal */
  function closeModal() { const m = $('#modal'); m.classList.remove('on'); m.innerHTML = ''; }
  function modalShell(title, badge, size) { const m = $('#modal'); m.innerHTML = `<div class="modal${size === 'fit' ? ' fit' : ''}" id="mdl"><div class="bg"></div><div class="mh"><h3>${title}</h3><div style="display:flex;gap:.6rem;align-items:center">${badge || ''}<button id="mx">Close ✕</button></div></div><div class="tools" id="mtools"></div><div class="mb" id="mbody"></div></div>`; m.classList.add('on'); $('#mx').onclick = closeModal; m.onclick = e => { if (e.target === m) closeModal(); }; frameAll(m); return m; }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
  function statsFor(c, kind) {
    const ser = c.series.filter(s => !s.off); if (!ser.length) return '';
    const tot = c.x.map((_, i) => c.stacked ? ser.reduce((a, s) => a + (s.v[i] || 0), 0) : (ser[0].v[i])); const vs = tot.filter(v => v != null); if (!vs.length) return '';
    const a = vs[0], b = vs[vs.length - 1], mn = Math.min(...vs), mx = Math.max(...vs), months = c.x.length * (c.x[0] && c.x[0].length === 4 ? 12 : 1);
    if (kind === 'flow') { const sum = vs.reduce((x, y) => x + y, 0); return `<div>Total in range<b>${A(sum)}</b></div><div>Average per ${c.x[0].length === 4 ? 'year' : 'month'}<b>${A(sum / vs.length)}</b></div><div>Highest<b>${A(mx)}</b></div><div>Lowest<b>${A(mn)}</b></div>`; }
    const ch = b - a, cp = a ? ch / Math.abs(a) * 100 : null, cagr = a > 0 && b > 0 && months >= 12 ? (Math.pow(b / a, 12 / months) - 1) * 100 : null;
    return `<div>Start<b>${A(a)}</b></div><div>Now<b>${A(b)}</b></div><div>Change<b class="${cl(ch)}"><span class="amt">${eur(ch)}</span> ${cp == null ? '' : '(' + pct(cp) + ')'}</b></div>${cagr == null ? '' : `<div>Per year (CAGR)<b class="${cl(cagr)}">${pct(cagr)}</b></div>`}<div>Low<b>${A(mn)}</b></div><div>High<b>${A(mx)}</b></div>`;
  }
  /* generic time-series modal. make() returns {axis, series:[{n,c,v,type?}], stacked?, kind?} on the monthly axis */
  function openTS(o) {
    const m = modalShell(o.title, (o.heat ? '<button id="mheat" class="hmb">▦ Heatmap</button>' : '') + (o.badge || '')); if (o.heat) $('#mheat').onclick = () => { HEATCTX = { root: $('#mbody'), tools: $('#mtools'), back: () => openTS(o) }; try { o.heat(); } finally { HEATCTX = null; } }; const M = { range: S.range, gran: S.gran, type: o.type || (o.stacked ? 'area' : 'line') };
    const raw0 = o.make(); const tools = $('#mtools'), body = $('#mbody');
    body.innerHTML = `<div class="stats" id="mst"></div><div class="chart" id="mch"></div><div class="leg" id="mlg"></div>${o.extra ? '<div id="mex">' + o.extra() + '</div>' : ''}`;
    const draw = () => {
      const raw = raw0; raw.series.forEach(s => { if (!s.fixed) s.type = M.type === 'bar' ? 'bar' : M.type === 'area' ? 'area' : 'line'; });
      const c = prep(Object.assign({}, raw, { stacked: raw.stacked && M.type !== 'line' }), M); TS($('#mch'), c);
      $('#mst').innerHTML = statsFor(c, raw.kind); $('#mlg').innerHTML = raw.series.map((s, i) => `<span class="${s.off ? 'off' : ''}" data-i="${i}"><i style="background:${s.c}"></i>${esc(s.n)}</span>`).join('');
      $$('#mlg span').forEach(sp => sp.onclick = () => { raw.series[+sp.dataset.i].off = !raw.series[+sp.dataset.i].off; draw(); });
    };
    const bar = () => { const ax0 = raw0.axis, f0 = Math.max(0, ax0.findIndex((_, i) => raw0.series.some(s => s.v[i] != null))), av = rangesFor(ax0.length - f0); if (!av.includes(M.range)) M.range = 'MAX'; tools.innerHTML = av.map(r => `<button data-r="${r}" class="${M.range === r ? 'on' : ''}">${r}</button>`).join('') + '<span class="sep"></span>' + `<button data-g="M" class="${M.gran === 'M' ? 'on' : ''}">Monthly</button><button data-g="Y" class="${M.gran === 'Y' ? 'on' : ''}">Yearly</button><span class="sep"></span>` + ['area', 'line', 'bar'].map(t => `<button data-t="${t}" class="${M.type === t ? 'on' : ''}">${t}</button>`).join('');
      $$('#mtools button').forEach(b => b.onclick = () => { if (b.dataset.r) M.range = b.dataset.r; if (b.dataset.g) M.gran = b.dataset.g; if (b.dataset.t) M.type = b.dataset.t; bar(); draw(); }); };
    bar(); draw(); if (o.after) o.after(body);
  }
  function infoModal(title, html, badge) { modalShell(title, badge, 'fit'); $('#mbody').innerHTML = html; return $('#mbody'); }

  /* ================================================== data model */
  function D() { return S.D; }
  function lastNN(a) { for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return a[i]; return null; }
  function classValues(d) {
    const dep = (d.depot ? d.depot.positions : []).reduce((s, p) => s + (p.value || 0), 0), cr = (d.crypto ? d.crypto.holdings : []).reduce((s, h) => s + h.amount * (h.price || 0), 0), t = d.totals || {};
    const wf = d.examplefund && d.examplefund.personal ? d.examplefund.personal.nav : 0, wi = d.wiwin ? d.wiwin.invested : 0, cash = (t.giro || 0) + (t.tages || 0) + (t.card || 0) + (t.shares || 0) + (t.paypal || 0);
    return { 'Real estate': d.apartment ? d.apartment.value_used : 0, 'Securities': dep, 'Private equity': wf + wi, 'Cash': cash, 'Crypto': cr };
  }
  /* gross assets, loan, estimated German tax on unrealised gains -> net assets */
  function netInfo(d) {
    const v = classValues(d), gross = CLS.reduce((s, k) => s + v[k], 0), liab = d.loan ? d.loan.balance : ((d.totals && d.totals.liabilities) || 0), T = d.tax || { rate_pct: 26.375, allowance: 1000 }, noTax = !!(d.tax && d.tax.note && d.tax.rate_pct == null);   /* noTax: profile has no tax rules for its country */
    const secGain = (d.depot ? d.depot.positions : []).reduce((s, p) => s + (p.gain || 0), 0), wp = d.examplefund && d.examplefund.personal, peGain = wp ? Math.max(0, wp.nav - (wp.paid_in || wp.nav)) : 0;
    const taxable = Math.max(0, secGain + peGain - (T.allowance == null ? 1000 : T.allowance)), tax = noTax ? 0 : taxable * (T.rate_pct || 26.375) / 100;
    return { gross, liab, tax, net: gross - liab, after: gross - liab - tax, secGain, peGain, taxable, rate: T.rate_pct || 26.375, allow: T.allowance == null ? 1000 : T.allowance };
  }
  const logoFor = (name, dom) => window.SRC_LOGOS && window.SRC_LOGOS['m:' + name] ? logo('m:' + name, name) : logo('none:' + name, name).replace('<span ', '<span data-lgm="' + esc(name) + '" ');
  /* at start-up (and after each data load) look online for company logos that are still missing; individuals keep their initials */
  const BIZ_RX = /(gmbh|\bag\b|\bkg\b|\bug\b|\bse\b|\bltd\b|\binc\b|\be\.?v\.?\b|stiftung|verein|club|bank|kasse|versicherung|verwaltung|apotheke|shop|markt|energy|energie|solar|travel|group|service|partner|recht|kanzlei|praxis|studio|cafe|café|restaurant|mobile|telekom|werke|verlag|schule|kita|hotel|camper|fitness|food|market|store|express|foundation|institut|gesellschaft|volks|kranken)/i;
  const isPerson = (n, cat) => { n = (n || '').trim(); if (!n || BIZ_RX.test(n) || /\d/.test(n)) return false; const t = n.split(/\s+/); return t.length >= 2 && t.length <= 3 && t.every(x => /^[A-ZÄÖÜ][a-zäöüßéèáàç'.-]+$/.test(x)) && (/famil|privat|person|friend|freund/i.test(cat || '') || t.length === 2); };
  const LOGO_TRIED = new Set();
  async function logoCheck() {
    const d = S.D, f = d && d.flows; if (S.mode !== 'real' || !S.token || !f || !f.top_spenders) return;
    const seen = new Set(), todo = []; ['y1', 'all'].forEach(k => (f.top_spenders[k] || []).slice(0, 14).forEach(m => { if (!seen.has(m.n)) { seen.add(m.n); if (!(window.SRC_LOGOS || {})['m:' + m.n] && !isPerson(m.n, m.cat) && !LOGO_TRIED.has(m.n)) todo.push(m); } }));
    let done = 0, found = 0; const total = todo.length; if (!total) return;
    const one = async m => { LOGO_TRIED.add(m.n); try { const r = await api('/api/logo?name=' + encodeURIComponent(m.n) + '&cat=' + encodeURIComponent(m.cat || '') + '&dom=' + encodeURIComponent(m.dom || '')); if (r && r.data) { (window.SRC_LOGOS = window.SRC_LOGOS || {})['m:' + m.n] = r.data; found++; $$('[data-lgm]').filter(e => e.dataset.lgm === m.n).forEach(e => { e.outerHTML = logo('m:' + m.n, m.n); }); } } catch (e) { } done++; const st = $('#stat'); if (st && done < total) st.textContent = 'LOOKING UP LOGOS ' + done + '/' + total + ' …'; else setStatus(); };
    const q = todo.slice(); await Promise.all([0, 1, 2].map(async () => { while (q.length) await one(q.shift()); })); if (found) console.log('logos found online:', found);
  }
  function total(d) { const v = classValues(d); return CLS.reduce((s, k) => s + v[k], 0) - ((d.totals && d.totals.liabilities) || 0); }
  /* change since first investment per class (v1.06): only honest measures. Crypto/Securities need a known cost basis; real estate compares with the purchase price; private equity uses the Example Fund MOIC (the value series mixes in deposits); cash has no investment, so n/a */
  function chgFirst(d, k) {
    if (k === 'Crypto') return d.crypto && d.crypto.gain_pct != null ? d.crypto.gain_pct : null;
    if (k === 'Securities') return d.depot && d.depot.gain_pct != null ? d.depot.gain_pct : null;
    if (k === 'Real estate') return d.apartment && d.apartment.gain_pct != null ? d.apartment.gain_pct : null;
    if (k === 'Private equity') { const wp = d.examplefund && d.examplefund.personal; return wp && wp.tvpi_est != null ? (wp.tvpi_est - 1) * 100 : null; }
    return null;
  }
  function chgFirstAll(d) { const n = d.axis.length, tot = i => CLS.reduce((s, k) => s + ((d.nw[k] || [])[i] || 0), 0); let i = 0; while (i < n && tot(i) <= 0) i++; return i >= n ? null : (CLS.reduce((s, k) => s + classValues(d)[k], 0) / tot(i) - 1) * 100; }
  function chg12(d, k) { const a = d.nw && d.nw[k]; if (!a) return null; const now = classValues(d)[k], i = a.length - 13, before = a[i]; return before ? (now / before - 1) * 100 : null; }
  function themes(d) { const m = {}; (d.depot ? d.depot.positions : []).forEach(p => m[p.theme || 'Other'] = (m[p.theme || 'Other'] || 0) + (p.value || 0)); return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([k, v], i) => ({ k, v, c: PAL[i % PAL.length] })); }
  function typesOf(d) { const m = {}; (d.depot ? d.depot.positions : []).forEach(p => m[p.cls || 'Other'] = (m[p.cls || 'Other'] || 0) + (p.value || 0)); return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([k, v], i) => ({ k, v, c: PAL[(i + 3) % PAL.length] })); }
  function avg12(arr) { const a = arr.slice(-13, -1); return a.reduce((x, y) => x + y, 0) / Math.max(1, a.length); }
  function badge(kind, txt) { return `<span class="bd ${kind}">${esc(txt)}</span>`; }
  function srcBadge(key, d) {
    if (d.mode === 'demo') return badge('demo', 'Demo');
    const s = (d.sources || {})[key] || {};
    if (s.model) return badge('model', 'Model');
    if (key === 'depot') return s.n_live ? badge('live', `Live ${s.n_live}/${s.n_total}`) : badge('static', 'Static ' + dshort(d.depot && d.depot.asof));
    if (s.live) return badge('live', 'Live');
    const a = s.asof || (key === 'examplefund' ? 'Q' + d.examplefund.report_q + ' ' + d.examplefund.report_year : null) || (key === 'paypal' && d.paypal && d.paypal.asof) || '';
    return badge('static', 'Static' + (a ? ' · ' + dshort(a) : ''));
  }
  function dshort(s) { if (!s) return ''; if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(8, 10) + '.' + s.slice(5, 7) + '.' + s.slice(2, 4); return s; }

  /* ================================================== panels */
  const POST = [];
  /* colour accent per group of boxes (v1.06): sec = securities, red = money out, wf = Example Fund, cb = Coinbase, alt = alternatives, tip = suggestions */
  /* boxes that stay readable when the privacy blur is on (v1.06): securities allocation, spending, top pay, recent + unusual bookings; the cash-flow CHART (#flc) is exempt too, its KPI tiles are not */
  const NB = { pAlloc: 1, pSpend: 1, pTop: 1, pRec: 1, pUnusual: 1 };
  const GRP = { pDepot: 'sec', pAlloc: 'sec', pTop: 'red', pSpend: 'red', pRec: 'red', pWF: 'wf', pCB: 'cb', pAlt: 'alt', pTips: 'tip', pUnusual: 'tip', pTime: 'tip' };
  function panel(id, title, bd, body, o) {
    o = o || {}; const hOn = !!(o.heat && S.heatOn[id]);
    if (o.heat) POST.push(() => {
      const b = $('#' + id + ' .hmb'); if (b) b.onclick = e => { e.stopPropagation(); S.heatOn[id] = !S.heatOn[id]; renderAll(); };
      const root = hOn && $('#' + id + ' .hroot'); if (root) { root.addEventListener('click', e => e.stopPropagation()); HEATCTX = { root }; try { o.heat(); } catch (e) { console.error(e); } finally { HEATCTX = null; } }
    });
    return `<section class="bx ${o.cls || ''}${NB[id] ? ' nb' : ''}" id="${id}"${GRP[id] ? ' data-grp="' + GRP[id] + '"' : ''} style="${o.style || ''}"><div class="bg"></div><div class="bh"><div class="bt">${title}</div>${o.heat ? `<div style="display:flex;gap:.4rem;align-items:center"><button class="hmb ${hOn ? 'on' : ''}" title="${hOn ? 'Back to the chart' : 'Show as heatmap'}">${hOn ? '◧ Chart' : '▦ Heat'}</button>${bd || ''}</div>` : (bd || '')}</div><div class="bb ${o.sc ? 'sc' : ''}">${hOn ? '<div class="hroot" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>' : body}</div></section>`;
  }
  const nwRaw = d => ({ axis: d.axis, kind: 'stock', stacked: true, series: CLS.map(k => ({ n: k, c: CCOL[k], v: (d.nw[k] || []).map(v => v == null ? null : v), type: 'area' })) });

  function pDepot(d) {
    const dp = d.depot; if (!dp) return panel('pDepot', 'Securities // positions', '', '<div class="empty">No depot data.</div>', { cls: 'grow4', style: 'flex:4' });
    const [sk, sd] = S.sort, ps = dp.positions.slice().sort((a, b) => sd * ((a[sk] > b[sk]) - (a[sk] < b[sk])) || 0), maxw = Math.max(...ps.map(p => p.weight || 0), 1);
    const cols = '1.2rem minmax(0,1.9fr) 1fr 1.3fr .8fr';
    const rows = ps.map((p, i) => `<div class="tr" style="grid-template-columns:${cols}" data-w="${esc(p.wkn)}"><span class="dim xs">${i + 1}</span><span class="nm">${logo(p.wkn, p.name)}<span class="t">${esc(p.name)}<small>${p.live ? '<span class="pos">●</span> ' + esc(p.sym || '') : '<span class="dim">■ static</span>'} · ${esc(p.cls)}</small></span></span><span class="r wh">${A(p.value)}</span><span><span class="bar"><i style="width:${(p.weight || 0) / maxw * 100}%"></i></span><span class="xs dim">${(p.weight || 0).toFixed(1).replace('.', ',')} %</span></span><span class="r ${cl(p.gain_pct)}">${pct(p.gain_pct)}</span></div>`).join('');
    const head = `<div class="tr th" style="grid-template-columns:${cols}"><span>#</span><span class="s" data-s="name">Position</span><span class="s r" data-s="value">Value</span><span class="s" data-s="weight">Weight</span><span class="s r" data-s="gain_pct">P/L</span></div>`;
    POST.push(() => { $$('#pDepot .tr[data-w]').forEach(r => r.onclick = () => openPos(r.dataset.w)); $$('#pDepot .th .s').forEach(s => s.onclick = () => { S.sort = [s.dataset.s, S.sort[0] === s.dataset.s ? -S.sort[1] : -1]; renderAll(); }); const t = $('#pDepot .dtit'); if (t) t.onclick = () => openSec(); });
    return panel('pDepot', `<span class="dtit" style="cursor:pointer">Securities <b>//</b> ${dp.positions.length} positions</span>`, srcBadge('depot', d),
      `<div class="kpis" style="grid-template-columns:repeat(4,1fr);margin-bottom:.5rem"><div class="kp" id="kDep"><div class="l">Depot value</div><div class="v">${A(dp.total)}</div><div class="s">${esc(d.mode === 'demo' ? 'demo' : 'export ' + dshort(dp.asof))}</div></div><div class="kp"><div class="l">Gain / loss</div><div class="v ${cl(dp.gain)}">${A(dp.gain)}</div><div class="s ${cl(dp.gain_pct)}">${pct(dp.gain_pct)}</div></div><div class="kp"><div class="l">Top position</div><div class="v" title="${esc(ps.slice().sort((a, b) => b.weight - a.weight)[0].name)}">${esc(ps.slice().sort((a, b) => b.weight - a.weight)[0].name.replace(/\s*\(ADR\)/i, ''))}</div><div class="s">${(ps.slice().sort((a, b) => b.weight - a.weight)[0].weight || 0).toFixed(0)} % of depot</div></div><div class="kp"><div class="l">Live quotes</div><div class="v">${dp.n_live}/${dp.n_total}</div><div class="s" title="${esc(dp.n_live < dp.n_total ? 'rest: export price' : 'all positions live')}${ps.some(x => x.quote_t) ? ' · latest trade ' + hms(Math.max(...ps.map(x => +x.quote_t || 0)) * (Math.max(...ps.map(x => +x.quote_t || 0)) < 1e12 ? 1000 : 1)) : ''}">${d.mode === 'demo' ? 'demo' : 'updated ' + hms(S.liveAt || d.generated)}</div></div></div><div class="tbl fill" style="overflow:auto">${head}${rows}</div><div class="xs dim" style="margin-top:.4rem">Click a position for its history · click column titles to sort · header opens total securities</div>`, { cls: '', style: 'flex:7;min-height:0', heat: heatSec });
  }
  function pAlloc(d) {
    if (!d.depot) return '';
    const t = typesOf(d), want = S.allocView || 'theme', alt = want !== 'theme' && window.WVA ? WVA.allocView(d, want) : null, th = alt || themes(d), view = alt ? want : 'theme';
    POST.push(() => { const av = $('#allocView'); if (av) av.onclick = e => { e.stopPropagation(); const o = ['theme', 'country', 'sector', 'currency']; S.allocView = o[(o.indexOf(want) + 1) % o.length]; renderAll(); }; });
    POST.push(() => {
      $$('#pAlloc .dseg').forEach(p => p.onclick = () => { const k = p.dataset.k, isT = !!t.find(x => x.k === k); if (!isT && view !== 'theme') return; const ps = d.depot.positions.filter(q => isT ? q.cls === k : (q.theme || 'Other') === k); openGroup(k, ps); });
    });
    const leg = (arr) => arr.map(x => `<div class="tr" style="grid-template-columns:.8rem 1fr auto;padding:.15rem .1rem;font-size:0.744rem" data-k="${esc(x.k)}"><span style="background:${x.c};height:.6rem"></span><span>${esc(x.k)}</span><span class="r dim">${((x.v / (d.depot.total || 1)) * 100).toFixed(1).replace('.', ',')} %</span></div>`).join('');
    POST.push(() => $$('#pAlloc .tr[data-k]').forEach(r => r.onclick = () => { const k = r.dataset.k, isT = !!t.find(x => x.k === k); if (!isT && view !== 'theme') return; openGroup(k, d.depot.positions.filter(q => isT ? q.cls === k : (q.theme || 'Other') === k)); }));
    return panel('pAlloc', 'Securities <b>//</b> allocation', srcBadge('depot', d), `<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;flex:1;min-height:0"><div style="display:flex;flex-direction:column;min-height:0"><div class="xs dim" style="letter-spacing:.14em">BY TYPE</div><div class="fill" style="flex:none;height:7.4rem;min-height:0">${donut(t, { size: 200, center: kfmt(d.depot.total), sub: 'SECURITIES', amt: true })}</div><div style="overflow:hidden">${leg(t)}</div></div><div style="display:flex;flex-direction:column;min-height:0"><div class="xs dim" style="letter-spacing:.14em;cursor:pointer" id="allocView" title="Click to switch: theme / country / sector / currency">BY ${view.toUpperCase()}${view !== want ? ' (' + want + ': n/a)' : ''} ▾</div><div class="fill" style="flex:none;height:7.4rem;min-height:0">${donut(th, { size: 200, center: String(th.length), sub: view === 'theme' ? 'THEMES' : view.toUpperCase() })}</div><div style="overflow:hidden">${leg(th.slice(0, 5))}${th.length > 5 ? `<div class="xs dim" style="padding:.1rem">+ ${th.length - 5} more · click a slice</div>` : ''}</div></div></div>`, { style: 'flex:none;height:17.6rem', heat: heatSec });
  }
  const grossRaw = d => { const r = nwRaw(d); if (d.nwx && d.nwx.loan && d.nwx.loan.some(v => v) && d.nwx.net) r.series.push({ n: 'Net (gross − loan)', c: '#bcd6e2', v: d.nwx.net, type: 'line', fixed: true, dash: true, w: 1.3 }); return r; };
  /* v1.07: the gross-assets chart box is 30 % taller; the ring above it gives up exactly that height. Measured at run time because the box height depends on the screen. */
  function layoutCenter() {
    const rw = $('#ringWrap'), g = $('#pGross'), grid = $('#grid'); if (!rw || !g || !grid) return;
    rw.style.height = '43.4rem'; rw.style.flex = ''; rw.style.minHeight = ''; g.style.flex = ''; g.style.height = '';
    if (getComputedStyle(grid).position !== 'fixed') return;           // stacked (small screens): leave the layout alone
    const g0 = g.getBoundingClientRect().height; if (g0 < 20) return;
    g.style.flex = 'none'; g.style.height = (g0 * 1.3) + 'px'; rw.style.height = 'calc(43.4rem - ' + (g0 * .3) + 'px)';
    /* v1.17: the ring may SHRINK (it used to be flex:none) so the centre column never grows past the grid - nothing runs under the ask bar */
    rw.style.flex = '0 1 auto'; rw.style.minHeight = '12rem';
  }
  let LC_T = null; window.addEventListener('resize', () => { clearTimeout(LC_T); LC_T = setTimeout(() => { try { layoutCenter(); } catch (e) { } }, 150); });
  function pGross(d) {
    POST.push(() => { TS($('#nwc'), prep(grossRaw(d), S)); $('#pGross').onclick = e => { if (e.target.closest('.hv,.tip')) return; openNW(); }; });
    const first = d.axis[(d.nw['Cash'] || []).findIndex(v => v != null)];
    return panel('pGross', 'Gross assets <b>//</b> by asset class over the years' + spanTag(d.axis.length - firstIdx(d.nw['Cash'])), d.mode === 'demo' ? badge('demo', 'Demo') : badge('model', 'Back-cast + actual'), `<div class="fill" id="nwc"></div><div class="xs dim" style="margin-top:.25rem">${d.mode === 'demo' ? 'Invented numbers.' : 'Cash = actual GLS balances' + (first ? ' since ' + mlab(first) : '') + ' · securities / crypto = today\'s holdings at historical prices · real estate = benchmark model · dashed line = gross minus family loan. Click to enlarge.'}</div>`, { cls: 'click', style: 'flex:.8;min-height:7.7rem', heat: heatClasses });
  }
  const GREY = '#6c8392';
  /* length of the data behind a chart, shown after the box title: years (y) from 12 months on, else months (m) */
  const rangesFor = mo => ['1Y', '3Y', '5Y'].filter(r => mo > ({ '1Y': 12, '3Y': 36, '5Y': 60 }[r])).concat(['MAX']);
  const hms = t => new Date(t).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  function fitRing() { const v = $('#ringVal'), m = $('#ringMid'); if (!v || !m) return; v.style.fontSize = ''; const w = m.clientWidth, base = parseFloat(getComputedStyle(v).fontSize); if (v.scrollWidth > w && w > 0) v.style.fontSize = Math.max(10, base * w / v.scrollWidth * .96) + 'px'; }
  const spanTag = n => n > 0 ? ` <span class="dim" style="letter-spacing:.06em;text-transform:none"> · ${n >= 12 ? (n / 12).toFixed(1).replace('.', ',') + ' y' : n + ' m'}</span>` : '';
  const firstIdx = a => { const i = (a || []).findIndex(v => v != null); return i < 0 ? 0 : i; };
  function spendRaw(d, catFilter) {
    const f = d.flows; if (!f) return null; const names = Object.keys(f.cats).filter(k => k !== 'Sonstiges'), top = names.slice(0, 8), rest = names.slice(8), has = !!f.cats['Sonstiges'];
    const ser = top.map((k, i) => ({ n: k, c: PAL[i % PAL.length], v: f.cats[k].slice(), type: 'bar', flow: true })); if (rest.length) ser.push({ n: 'Small categories', c: '#8aa0ad', v: f.months.map((_, i) => rest.reduce((s, k) => s + f.cats[k][i], 0)), type: 'bar', flow: true });
    if (has) ser.push({ n: 'Sonstiges', c: GREY, v: f.cats['Sonstiges'].slice(), type: 'bar', flow: true });
    const colOf = k => k === 'Sonstiges' ? GREY : PAL[Object.keys(f.cats).filter(x => x !== 'Sonstiges').indexOf(k) % PAL.length];
    const raw = { axis: f.months, kind: 'flow', stacked: true, series: catFilter ? [{ n: catFilter, c: colOf(catFilter), v: f.cats[catFilter], type: 'bar', flow: true }] : ser };
    if (catFilter) raw.stacked = false; return raw;
  }
  function pSpend(d) {
    const f = d.flows; if (!f) return panel('pSpend', 'Spending', '', '<div class="empty">No bookings.</div>');
    const all = Object.keys(f.cats), base = all.filter(k => k !== 'Sonstiges'), colOf = k => k === 'Sonstiges' ? GREY : (base.indexOf(k) < 8 ? PAL[base.indexOf(k)] : '#8aa0ad');
    const l12 = all.map(k => [k, f.cats[k].slice(-13, -1).reduce((a, b) => a + b, 0)]).sort((a, b) => ((a[0] === 'Sonstiges') - (b[0] === 'Sonstiges')) || b[1] - a[1]), t12 = l12.reduce((s, x) => s + x[1], 0) || 1;
    POST.push(() => { TS($('#spc'), prep(spendRaw(d), S)); $$('#pSpend .tr[data-c]').forEach(r => r.onclick = () => openCat(r.dataset.c)); $('#spt').onclick = () => openSpend(); const cf = $('#catFix'); if (cf) cf.onclick = e => { e.stopPropagation(); WVC.open(); }; });
    const rows = l12.slice(0, 12).map(([k, v]) => `<div class="tr" style="grid-template-columns:.7rem 1fr auto 3.2rem;padding:.2rem .1rem;font-size:0.768rem" data-c="${esc(k)}"><span style="background:${colOf(k)};height:.6rem"></span><span>${esc(k)}</span><span class="r wh">${A(v)}</span><span class="r dim">${(v / t12 * 100).toFixed(0)} %</span></div>`).join('');
    return panel('pSpend', '<span id="spt" style="cursor:pointer">Spending by category <b>//</b> monthly' + spanTag(f.months.length) + '</span>', (d.mode === 'demo' || !window.WVC ? '' : '<button id="catFix" title="Correct wrong categories and save rules">✎ Fix categories</button>') + (d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d)), `<div style="display:grid;grid-template-columns:1.7fr 1fr;gap:1rem;flex:1;min-height:0"><div class="fill" id="spc" style="min-height:8rem"></div><div style="display:flex;flex-direction:column;min-height:0"><div class="xs dim" style="letter-spacing:.12em;margin-bottom:.3rem">LAST 12 MONTHS · ${A(t12)}</div><div style="overflow:auto">${rows}</div></div></div>`, { style: 'flex:3', heat: heatSpend });
  }
  function flowRaw(d, from, to) { const f = d.flows, cut = a => a.slice(from || 0, to || undefined); return { axis: cut(f.months), kind: 'flow', series: [{ n: 'Income', c: '#6fbf95', v: cut(f.income), type: 'bar', flow: true }, { n: 'Expenses', c: '#d98338', v: cut(f.expense), type: 'bar', flow: true }, { n: 'Saved (income − expenses)', c: '#22aecf', v: cut(f.savings), type: 'line', flow: true, fixed: true }] }; }
  function pFlow(d) {
    const f = d.flows; if (!f) return '';
    const F = window.WVF, st = F ? F.state() : { per: 'year' }, n = f.months.length, sp = F ? F.span(f, st) : [Math.max(0, n - 13), n - 1], i0 = sp[0], i1 = sp[1], nm = Math.max(1, i1 - i0), one = st.per === 'month';
    const sm = a => a.slice(i0, i1).reduce((x, y) => x + y, 0), inc = sm(f.income), ex = sm(f.expense), sr = inc ? (inc - ex) / inc * 100 : 0, oo = sm(f.oneoff_in) - sm(f.oneoff_out), ie = d.income_est, div = one ? 1 : nm;
    const sub = one ? (F ? F.label(f, st) : 'last month') : st.per === 'all' ? 'all-time average' : (st.yr && st.yr !== 'last12' ? st.yr + ' average' : '12 m avg');
    const from = st.per === 'all' ? 0 : one ? Math.max(0, n - 6) : i0, to = st.per === 'year' && st.yr && st.yr !== 'last12' ? i1 : n;
    POST.push(() => {
      TS($('#flc'), prep(flowRaw(d, from, to), S)); $$('#pFlow .kp').forEach(k => k.onclick = () => k.dataset.k === 'inc' ? openIncome() : openFlow());
      $$('#flSeg button').forEach(b => b.onclick = e => { e.stopPropagation(); st.per = b.dataset.per; redrawFlowBox(); });
      const fp = $('#flPop'); if (fp) fp.onclick = e => { e.stopPropagation(); F.open(); };
    });
    const bd = '<div style="display:flex;gap:.4rem;align-items:center">' + (F ? F.seg('flSeg') + '<button id="flPop" title="Interactive cash-flow chart: income, categories and payees">◈ Flow</button>' : '') + (d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d)) + '</div>';
    return panel('pFlow', 'Cash flow <b>//</b> monthly' + spanTag(f.months.length), bd, `<div class="kpis" style="margin-bottom:.4rem"><div class="kp"><div class="l">Income${one ? '' : ' / month'}</div><div class="v">${A(inc / div)}</div><div class="s">${sub} · incl. one-offs</div></div><div class="kp"><div class="l">Expenses${one ? '' : ' / month'}</div><div class="v">${A(ex / div)}</div><div class="s">${sub}</div></div><div class="kp"><div class="l">Savings rate</div><div class="v ${cl(sr)}">${pct(sr, 0)}</div><div class="s">${one ? sub : nm + ' months'}</div></div><div class="kp" data-k="inc"><div class="l">Portfolio income / mo</div><div class="v">${ie ? A(ie.monthly) : '–'}</div><div class="s">${ie ? '≈ ' + eur(ie.yearly) + ' / yr · estimate' : 'n/a'}</div></div><div class="kp"><div class="l">One-offs (in totals)</div><div class="v ${cl(oo)}">${A(oo)}</div><div class="s">net of items ≥ ${nf0.format(f.oneoff_threshold)} €</div></div></div><div class="fill nb" id="flc" style="min-height:7rem"></div>`, { style: 'flex:2.4' });
  }
  /* redraw only the Cash flow box (the period buttons use it; no full re-render) */
  function redrawFlowBox() {
    const el = $('#pFlow'); if (!el || !S.D) return; POST.length = 0; const t = document.createElement('div'); t.innerHTML = pFlow(S.D);
    el.replaceWith(t.firstElementChild); frameAll(); POST.forEach(f => { try { f(); } catch (e) { console.error(e); } }); POST.length = 0;
  }
  function pTop(d) {
    const f = d.flows; if (!f || !f.top_spenders) return panel('pTop', 'Top pay', '', '<div class="empty">No bookings.</div>', { style: 'flex:3' });
    const per = S.topPer || 'y1', list = (f.top_spenders[per] || []).slice(0, 14), mx = Math.max(1, ...list.map(x => x.v)), tot = per === 'y1' ? f.expense.slice(-13, -1).reduce((a, b) => a + b, 0) : f.expense.reduce((a, b) => a + b, 0);
    POST.push(() => { $$('#pTop .tr[data-m]').forEach(r => r.onclick = () => openMerchant(list[+r.dataset.m])); $$('#pTop [data-p]').forEach(b => b.onclick = e => { e.stopPropagation(); S.topPer = b.dataset.p; renderAll(); }); });
    const rows = list.map((m, i) => `<div class="tr" data-m="${i}" style="grid-template-columns:1rem 1.9rem minmax(0,1.5fr) 4.6rem minmax(0,.9fr) 2.4rem"><span class="dim xs">${i + 1}</span>${logoFor(m.n)}<span class="nm"><span class="t">${esc(m.n)}<small>${esc(m.cat)} · ${m.tx}×</small></span></span><span class="r wh">${A(m.v)}</span><span><span class="bar"><i style="width:${m.v / mx * 100}%"></i></span></span><span class="r dim xs">${(m.v / (tot || 1) * 100).toFixed(1).replace('.', ',')}%</span></div>`).join('');
    return panel('pTop', 'Top pay <b>//</b> where your money goes', d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), `<div style="display:flex;gap:.4rem;margin-bottom:.35rem"><button data-p="y1" class="${per === 'y1' ? 'on' : ''}">Last 12 months</button><button data-p="all" class="${per === 'all' ? 'on' : ''}">All time</button><span class="xs dim" style="margin-left:auto;align-self:center">${per === 'y1' ? '12 m' : 'since ' + mlab(f.months[0])} total spend ${A(tot)}</span></div><div class="tbl fill" style="overflow:auto">${rows}</div><div class="xs dim" style="margin-top:.3rem">Click a company for its monthly history. Internal transfers and investments are not counted.</div>`, { style: 'flex:3.3', heat: heatTop });
  }
  /* history with one company: every booking we have for that name (data.gls.bookings; demo mode falls back to the recent list) */
  function openBookings(name) {
    const d = S.D, g = d.gls || {}, list = ((g.bookings || {})[name] || (g.recent || []).filter(r => r.n === name).map(r => [r.d, r.v, r.c])).slice().sort((a, b) => String(b[0]).localeCompare(String(a[0])));
    if (!list.length) return;
    const out = list.filter(x => x[1] < 0).reduce((s, x) => s + x[1], 0), inn = list.filter(x => x[1] > 0).reduce((s, x) => s + x[1], 0), net = out + inn, sign = Math.abs(out) >= inn ? -1 : 1;
    const months = (d.flows && d.flows.months) || [], idx = {}; months.forEach((m, i) => idx[m] = i);
    const ser = months.map(() => 0); list.forEach(x => { const i = idx[String(x[0]).slice(0, 7)]; if (i != null) ser[i] += sign * x[1]; });
    const cats = [...new Set(list.map(x => x[2]).filter(Boolean))].join(', ');
    const rows = list.slice(0, 14).map(x => `<tr><td>${dfull(x[0])}</td><td>${esc(x[2] || '')}</td><td class="${x[1] < 0 ? '' : 'pos'}">${A(x[1])}</td></tr>`).join('');
    openTS({ title: name + ' · booking history', type: 'bar', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d),
      make: () => ({ axis: months, kind: 'flow', series: [{ n: name, c: sign < 0 ? '#d98338' : '#5fbf8a', v: ser, type: 'bar', flow: true }] }),
      extra: () => `<div class="stats"><div>Bookings<b>${list.length}</b></div><div>Paid to them<b>${A(Math.abs(out))}</b></div><div>Received from them<b>${A(inn)}</b></div><div>Net<b class="${cl(net)}">${A(net)}</b></div><div>First / last<b style="font-size:1rem">${dshort(list[list.length - 1][0])} – ${dshort(list[0][0])}</b></div></div><div class="pp" style="display:block;flex:none"><table><thead><tr><th>Date</th><th>Category</th><th>Amount</th></tr></thead><tbody>${rows}</tbody></table></div><p class="xs dim">${esc(cats)}${list.length > 14 ? ' · latest 14 of ' + list.length + ' bookings shown' : ''}${(d.gls.bookings || {})[name] ? '' : ' · only the recent bookings are known in this mode'}</p>` });
  }
  function openMerchant(m) {
    const d = S.D, f = d.flows; if (!m) return;
    openTS({ title: m.n + ' · spending over time', type: 'bar', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), make: () => ({ axis: f.months, kind: 'flow', series: [{ n: m.n, c: '#d98338', v: (m.m || f.months.map(() => 0)), type: 'bar', flow: true }] }),
      extra: () => `<div class="stats"><div>Category<b style="font-size:1.02rem">${esc(m.cat)}</b></div><div>Total in this list<b>${A(m.v)}</b></div><div>Bookings<b>${m.tx}</b></div><div>Average booking<b>${A(m.v / Math.max(1, m.tx))}</b></div></div>` });
  }
  function tipsFor(d) {
    const T = [], v = classValues(d), ni = netInfo(d), f = d.flows, ex = f ? avg12(f.expense) : 0, inc = f ? avg12(f.income) : 0, cash = v['Cash'], dp = d.depot;
    const top = dp && dp.positions.slice().sort((a, b) => b.weight - a.weight)[0], tg = ni.gross || 1;
    if (ex && cash > ex * 9) T.push({ l: 'idea', t: 'Cash is well above a 6-month reserve', x: `${eur(cash)} in cash vs. about ${eur(ex * 6)} for 6 months of spending. The surplus of ${eur(cash - ex * 6)} earns little; options: higher-rate savings, short-term bonds, or investing in stages.` });
    if (top && top.weight > 20) T.push({ l: 'warn', t: `Concentration: ${top.name} is ${top.weight.toFixed(0)} % of the depot`, x: `One stock carries a fifth or more of your securities. Many investors cap single names at 10–15 % or rebalance gradually.` });
    if (v['Real estate'] / tg > .35) T.push({ l: 'idea', t: `Real estate is ${(v['Real estate'] / tg * 100).toFixed(0)} % of gross assets`, x: 'One apartment in one city is a concentrated bet; new savings could go to other asset classes to diversify.' });
    if (v['Crypto'] / tg > .08) T.push({ l: 'info', t: `Crypto is ${(v['Crypto'] / tg * 100).toFixed(0)} % of gross assets`, x: 'Very volatile: decide the share you are comfortable with and rebalance when it drifts well above it.' });
    if (inc && ex > inc * 0.95) { const c = f && Object.entries(f.cats).map(([k, a]) => [k, a.slice(-13, -1).reduce((x, y) => x + y, 0)]).filter(x => x[0] !== 'Sonstiges').sort((a, b) => b[1] - a[1]).slice(0, 2); T.push({ l: 'warn', t: 'Spending is close to or above income', x: `Average spending ${eur(ex)} vs income ${eur(inc)} per month (12 m).` + (c ? ` Largest categories: ${c.map(x => x[0] + ' ' + eur(x[1])).join(', ')}.` : '') }); }
    if (ni.secGain > 5000) T.push({ l: 'idea', t: `Unrealised gains ${eur(ni.secGain)}: use the 1.000 € allowance`, x: `Estimated tax if sold today ≈ ${eur(ni.tax)}. Realising up to the yearly Sparer-Pauschbetrag (1.000 €) tax-free, and a Freistellungsauftrag at your bank, avoid paying tax unnecessarily. Check with a tax advisor.` });
    if (d.loan && d.loan.balance > 0) T.push({ l: 'info', t: `Family loan: ${eur(d.loan.balance)} left, paid off ${mlabLong(d.loan.payoff)}`, x: `Assumed 0 % interest, so repaying early earns nothing; an agreement on the exact terms (interest, early repayment) keeps it clean for both sides.` });
    const wp = d.examplefund && d.examplefund.personal; if (wp && wp.unfunded > 0) T.push({ l: 'info', t: `${eur(wp.unfunded)} still to be called by Example Fund`, x: 'Capital calls arrive on short notice; keep this amount liquid so you never have to sell investments at a bad time.' });
    const ie = d.income_est; if (ie && dp) T.push({ l: 'info', t: `Portfolio income ≈ ${eur(ie.monthly)} / month (est.)`, x: `Dividends and interest add up to about ${eur(ie.yearly)} a year, i.e. ${(ie.yearly / tg * 100).toFixed(2).replace('.', ',')} % of gross assets: your portfolio is growth-oriented. Dividend or bond holdings would raise it.` });
    const sub = f && f.cats['Subscriptions & Digital']; if (sub) { const a = sub.slice(-13, -1).reduce((x, y) => x + y, 0); if (a > 1200) T.push({ l: 'idea', t: `Subscriptions & digital: ${eur(a)} / year`, x: 'Worth a yearly review of recurring subscriptions and contracts (phone, internet, insurance) for cheaper tariffs.' }); }
    if (!T.length) T.push({ l: 'info', t: 'No suggestions right now', x: 'Everything is within the usual guard rails.' });
    return T;
  }
  function mlabLong(m) { return m ? MON[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4) : '–'; }
  /* euro amounts in suggestion texts are asset values: wrap them so the privacy blur covers them */
  const blurAmts = h => h.replace(/(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?(?:\s[kM])?)(\s?€)/g, '<span class="amt">$1$2</span>');
  /* monthly 'new data needed' reminder: d.reminders = { month, any_due, items:[{ key, source, what_to_download, where, folder, pattern, latest, due, days_old, accounts }] } */
  const remDue = d => ((d.reminders && d.reminders.items) || []).filter(i => i.due);
  const remShort = i => i.key === 'gls' ? i.source + ' (account CSVs)' : i.source;
  function remTip(d) { const due = remDue(d); return due.length ? { l: 'warn', t: 'New data needed: ' + due.map(remShort).join(', '), x: due.map(i => { const f = remFolder(i, d); return i.what_to_download + (i.pattern ? ' [' + i.pattern + ']' : '') + (f ? ' -> ' + f : '') + (i.latest ? ' (newest data ' + i.latest + ')' : ' (no data yet)'); }).join(' · ') + '. Drop the new files into these folders - WealthView imports them by itself within about a minute.' } : null; }
  /* the folder to drop files into: the real path from data.json; demo mode shows invented example paths only */
  const DEMO_DIRS = { gls: 'C:\\Demo\\GLS\\DATA', depot: 'C:\\Demo\\GLS\\DATA', paypal: 'C:\\Demo\\PayPal', examplefund: 'C:\\Demo\\ExampleFund\\Fund I Reporting' };
  const remFolder = (i, d) => d && d.mode === 'demo' ? (DEMO_DIRS[i.key] || 'C:\\Demo\\Data') : (i.folder || '');
  const pathBox = t => `<code style="user-select:text;-webkit-user-select:text;font-family:Consolas,'Courier New',monospace;word-break:break-all;color:var(--wh,#fff)">${esc(t)}</code>`;
  function remRows(r, d) { return r.items.map(i => { const f = remFolder(i, d);
    return `<div class="tr" style="cursor:default;display:block;height:auto"><span class="${i.due ? 'or' : 'pos'}">${i.due ? '▲ DUE' : '● OK'}</span> <b>${esc(i.source)}</b> <span class="dim xs">· newest data: ${i.latest ? esc(i.latest) + ' (' + esc(i.days_old) + ' d old)' : 'none yet'}</span><div class="xs dim" style="margin-left:1.6rem;line-height:1.5">Download: ${esc(i.what_to_download)}${i.where ? ' - from ' + esc(i.where) : ''}<br>Folder: ${f ? pathBox(f) : '<span class="or">not set in config.json (' + esc(i.folder_key) + ')</span>'}<br>File name: ${i.pattern ? pathBox(i.pattern) : '–'}${i.accounts && i.accounts.length ? '<br>Covers: ' + i.accounts.map(a => esc(a.name) + (a.last ? ' (' + esc(a.last) + ')' : '')).join(', ') : ''}</div></div>`; }).join(''); }
  function updChip(d) {
    const c = $('#updChip'), r = d.reminders; if (!c) return;
    if (!r || !r.items || !r.items.length) { c.style.display = 'none'; return; }
    const due = remDue(d), names = due.map(i => i.source).join(', ');
    c.style.display = 'inline-flex'; c.style.color = due.length ? 'var(--or)' : ''; c.style.borderColor = due.length ? 'var(--or)' : ''; c.style.opacity = due.length ? '' : '.55';
    c.textContent = due.length ? '▲ UPDATE DUE: ' + (names.length > 38 ? names.slice(0, 36) + '…' : names) : '● DATA UP TO DATE';
    c.onclick = () => infoModal('Which files need fresh data?', remRows(r, d) + '<p class="xs dim">Drop the new files into the usual folders - WealthView imports them by itself within about a minute.</p>');
  }
  function pTips(d) {
    const T = tipsFor(d).concat((window.WVA && WVA.tipItems(d)) || []).concat((window.WVI && WVI.tipItems(d)) || []), ord = { warn: 0, idea: 1, info: 2 }; T.sort((a, b) => (ord[a.l] - ord[b.l])); const rt = remTip(d); if (rt) T.unshift(rt);
    POST.push(() => { $$('#pTips .tip2').forEach(t => t.onclick = () => t.classList.toggle('open')); const ab = $('#bAnalysis'); if (ab) ab.onclick = e => { e.stopPropagation(); WVA.openAnalysis(S.D); }; const sy = $('#sysHead'); if (sy) sy.onclick = () => $('#sysBody').classList.toggle('open'); });
    const al = (d.alerts || []).slice().sort((a, b) => (/DATA GAP/.test(b.text) - /DATA GAP/.test(a.text))).slice(0, 7).map(a => `<div style="margin:.25rem 0;font-size:0.792rem"><span class="${a.level === 'warn' ? 'or' : 'dim'}">${a.level === 'warn' ? '▲' : '●'}</span> ${/DATA GAP/.test(a.text) ? '<b class="or">' + esc(a.text) + '</b>' : esc(a.text)}</div>`).join('') || '<div class="dim sm">No alerts.</div>';
    const nWarn = (d.alerts || []).filter(a => a.level === 'warn').length;
    const sys = `<div class="sysrow"><div id="sysHead" class="tip2 syshead"><div class="h"><span class="${nWarn ? 'or' : 'dim'}">${nWarn ? '▲' : '●'}</span> System status <span class="dim xs">· ${nWarn ? nWarn + ' warning' + (nWarn > 1 ? 's' : '') : 'all quiet'} · click to open</span></div></div><div id="sysBody" class="sysbody">${al}${(window.WVI && WVI.dbLine(d)) || ''}<div class="xs dim" style="margin-top:.4rem;border-top:1px solid rgba(60,190,235,.2);padding-top:.35rem">Last data refresh: <b class="wh">${d.generated ? new Date(d.generated).toLocaleString('de-DE') : '–'}</b></div></div></div>`;
    const btn = (window.WVA ? '<button id="bAnalysis" title="Performance, risk, exposure, liquidity, private equity, tax, costs">Portfolio analysis ▸</button>' : '') + badge(d.mode === 'demo' ? 'demo' : 'mix', d.mode === 'demo' ? 'Demo' : 'Rules on your data');
    return panel('pTips', 'Smart suggestions <b>//</b> ideas, analysis & system', btn, `<div style="overflow:auto;flex:1;min-height:0">${T.slice(0, 14).map(t => `<div class="tip2"><div class="h"><span class="${t.l === 'warn' ? 'or' : t.l === 'idea' ? 'pos' : 'dim'}">${t.l === 'warn' ? '▲' : t.l === 'idea' ? '◆' : '●'}</span> ${blurAmts(esc(t.t))}</div><div class="x">${blurAmts(esc(t.x))}</div></div>`).join('')}${sys}</div><div class="xs dim" style="margin-top:.3rem">Rule-based ideas from your own numbers. Education, not financial or tax advice.</div>`, { style: 'flex:3.4' });
  }
  function openIncome() {
    const d = S.D, ie = d.income_est; if (!ie) return;
    infoModal('Portfolio income estimate', `<div class="stats"><div>Per year<b>${A(ie.yearly)}</b></div><div>Per month<b>${A(ie.monthly)}</b></div><div>Positions with data<b>${ie.covered}/${ie.total_positions}</b></div></div><div class="tbl">${ie.items.map(i => `<div class="tr" style="grid-template-columns:2rem 1fr auto;cursor:default">${logo(i.wkn || 'none', i.n)}<span>${esc(i.n)}</span><span class="r wh">${A(i.v)}</span></div>`).join('')}</div><p class="xs dim">${esc(ie.note)}</p>`, badge(d.mode === 'demo' ? 'demo' : 'model', d.mode === 'demo' ? 'Demo' : 'Estimate'));
  }
  function taxExtra(d) {
    const t = d.tax || {}, a = d.apartment_sale; if (!t.method) return '';
    let h = `<div class="tbl" style="margin-top:.6rem"><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Tax method<small class="dim"> · lower of flat ${t.rate_pct} % and your personal tariff</small></span><span class="r wh">${t.method}</span></div><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Flat tax / personal tariff</span><span class="r wh">${eur(t.flat_tax)} / ${eur(t.tariff_tax)}</span></div><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Tax-free headroom<small class="dim"> · allowance + full Grundfreibetrag ${eur(t.grundfreibetrag)} (single, no other income, no church tax)</small></span><span class="r pos">${eur(t.tax_free_headroom)}</span></div></div>`;
    if (a) h += `<h4 style="margin:.8rem 0 .3rem">If you sold the apartment</h4><div class="tbl"><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Value ${eur(a.value)} − purchase ${eur(a.purchase_price)} − costs ${eur(a.selling_costs + a.acquisition_costs)}<small class="dim"> · gain</small></span><span class="r wh">${eur(a.gain)}</span></div><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Speculation tax (§23 EStG)<small class="dim"> · ${a.own_use_exempt ? 'exempt: own use' : a.within_speculation_period ? 'taxable until ' + a.speculation_until : 'period over since ' + a.speculation_until}</small></span><span class="r ${a.tax ? 'neg' : 'pos'}">${eur(a.tax)}</span></div><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Loan to repay</span><span class="r neg">−${eur(a.loan_balance)}</span></div><div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>Net proceeds</span><span class="r wh">${eur(a.net_proceeds)}</span></div></div><p class="xs dim">${a.notes.join(' ')}</p>`;
    return h;
  }
  function openNet() {
    const d = S.D, n = netInfo(d), row = (a, b, c, k) => `<div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>${a}${c ? '<small class="dim"> · ' + c + '</small>' : ''}</span><span class="r ${k || 'wh'}">${b}</span></div>`;
    infoModal('Gross assets → net assets', `<div class="tbl">${row('Gross assets', A(n.gross), 'everything you own, before debts and tax')}${row('− Loan', '−' + A(n.liab), d.loan ? 'family loan, ' + eur(d.loan.monthly) + ' / month' : 'no loans', 'neg')}${row('= Net worth', A(n.net), 'what you own minus what you owe')}${row('− Estimated tax on gains', '−' + A(n.tax), `${n.rate.toFixed(3).replace('.', ',')} % on ${eur(n.taxable)} (gains ${eur(n.secGain + n.peGain)} minus ${eur(n.allow)} allowance)`, 'neg')}${row('= Net assets after tax', A(n.after), 'what would be left if you sold everything today')}</div><p class="xs dim">Securities: unrealised gain ${eur(n.secGain)} (cost basis from your GLS depot). Example Fund: gain only if NAV exceeds paid-in capital (${eur(n.peGain)}). Crypto: assumed held longer than a year, tax-free. Cash: interest tax ignored. Not tax advice.</p>${taxExtra(d)}`, badge('model', 'Estimate'));
  }
  function openLoan() {
    const d = S.D, L = d.loan; if (!L) return;
    openTS({ title: `Loan from ${L.lender} · balance over time`, type: 'area', badge: d.mode === 'demo' ? badge('demo', 'Demo') : badge('model', 'Calculated'), make: () => ({ axis: d.axis, kind: 'stock', series: [{ n: 'Remaining balance', c: '#cf6060', v: d.nwx.loan, type: 'area' }] }),
      extra: () => `<div class="stats"><div>Borrowed<b>${A(L.principal)}</b></div><div>Repaid<b>${A(L.repaid)}</b></div><div>Remaining<b>${A(L.balance)}</b></div><div>Monthly<b>${A(L.monthly)}</b></div><div>Months left<b>${L.months_left}</b></div><div>Paid off<b style="font-size:1.02rem">${mlabLong(L.payoff)}</b></div></div><p class="xs dim">Calculated: ${eur(L.monthly)} per month since ${mlabLong(L.start)}, no interest assumed. Adjust loan in config.json.</p>` });
  }
  function fundTitle(d) { return (d.examplefund && d.examplefund.title) || 'Example Fund I'; }      // your own name via config.json -> fund_title
  function pWF(d) {
    const w = d.examplefund; if (!w) return '';
    const p = w.personal, f = w.fund, lg = window.WF_LOGOS || {}, strip = w.companies.slice().sort((a, b) => b.fair_value - a.fair_value).slice(0, 12).map(c => `<span class="lgw2" data-slug="${esc(c.slug)}" title="${esc(c.name)} · click for details" style="cursor:pointer;width:3.2rem;height:2.2rem;border:1px solid rgba(60,190,235,.3);background:#0b141b;display:inline-block;overflow:hidden">${lg[c.slug] ? `<img src="${lg[c.slug]}" style="width:100%;height:100%;object-fit:cover">` : ''}</span>`).join('');
    const srt = w.companies.slice().sort((a, b) => b.fair_value - a.fair_value), mxv = srt[0].fair_value;
    const top8 = srt.slice(0, 8).map(c => `<div class="tr" data-slug="${esc(c.slug)}" title="Click for company details" style="grid-template-columns:2.6rem minmax(0,1.2fr) 1.6fr 3rem;cursor:pointer"><span style="width:2.4rem;height:1.5rem;border:1px solid rgba(60,190,235,.3);background:#0b141b;overflow:hidden;display:block">${lg[c.slug] ? `<img src="${lg[c.slug]}" style="width:100%;height:100%;object-fit:cover">` : ''}</span><span>${esc(c.name)}<small class="dim"> · ${esc(c.industry)}</small></span><span><span class="bar"><i style="width:${c.fair_value / mxv * 100}%;background:${c.moic >= 1 ? '#8fe6b8' : '#ff6b6b'}"></i></span></span><span class="r ${c.moic >= 1 ? 'pos' : 'neg'}">${c.moic.toFixed(2).replace('.', ',')}x</span></div>`).join('');
    POST.push(() => { $('#wfOpen').onclick = e => { e.stopPropagation(); openWF(); }; $('#pWF').onclick = openWF; $$('#pWF [data-slug]').forEach(x => x.onclick = e => { e.stopPropagation(); openCompany(x.dataset.slug); }); });
    return panel('pWF', `${logo('examplefund', 'Example Fund')}&nbsp; ${esc(fundTitle(d))} <b>//</b> your capital account`, srcBadge('examplefund', d),
      `<div class="kpis" style="margin-bottom:.5rem"><div class="kp"><div class="l">Your NAV</div><div class="v">${A(p.nav)}</div><div class="s">${pct((p.nav / p.paid_in - 1) * 100)} vs paid-in</div></div><div class="kp"><div class="l">Paid in / commitment</div><div class="v">${A(p.paid_in)}</div><div class="s">of ${eur(p.commitment)} · ${(p.paid_in / p.commitment * 100).toFixed(0)} %</div></div><div class="kp"><div class="l">Unfunded</div><div class="v">${A(p.unfunded)}</div><div class="s">still to be called</div></div><div class="kp"><div class="l">Fund TVPI</div><div class="v">${f.tvpi.toFixed(2).replace('.', ',')}x</div><div class="s">net IRR ${pct(f.net_irr)}</div></div></div>
      <div class="xs dim" style="letter-spacing:.14em;margin-bottom:.3rem">TOP HOLDINGS BY FAIR VALUE · MOIC</div><div class="tbl" style="flex:1;min-height:0;overflow:hidden">${top8}</div>
      <div style="display:flex;gap:.3rem;flex-wrap:wrap;margin:.5rem 0">${strip}</div>
      <div style="display:flex;justify-content:space-between;align-items:center"><span class="xs dim">${w.companies.length} portfolio companies · top ${Math.round(w.companies.slice().sort((a, b) => b.fair_value - a.fair_value).slice(0, 3).reduce((s, c) => s + c.fair_value, 0) / f.fair_value_portfolio * 100)} % of fair value in 3 names</span><button id="wfOpen">Open portfolio (${w.companies.length}) ▸</button></div>`, { cls: 'click', style: 'flex:3.4', heat: heatWF });
  }
  function wfRaw(d) { const f = d.examplefund.fund, p = d.examplefund.personal; return { axis: ['2025-12', '2026-03', '2026-06'], kind: 'stock', series: [{ n: 'Your NAV (est. Dec = n/a)', c: '#ff9a3d', v: [null, p.nav_prev_quarter || null, p.nav], type: 'bar', fixed: true }] }; }
  /* one-line notice when the purchase prices could not be loaded (key without transaction permission, error, ...) */
  function cbNote(cb) {
    const st = cb.trades_status, why = { no_permission: 'The API key may not read transactions (wallet:transactions:read), so purchase prices are unknown.', error: 'Coinbase did not return the trade history.', none: 'No trade history was loaded yet (refresh the data).' }[st];
    const part = cb.cost != null && (cb.holdings || []).some(h => h.cost_known_share != null && h.cost_known_share < 0.999);
    return (st && st !== 'ok' ? `<div class="xs or" style="margin:-.1rem 0 .3rem">▲ Gain n/a: ${esc(why || st)}</div>` : '') + (part ? '<div class="xs dim" style="margin:-.1rem 0 .3rem">* part of the balance (e.g. received by transfer) has no known purchase price and is left out of the gain.</div>' : '');
  }
  function pCB(d) {
    const cb = d.crypto; if (!cb) return panel('pCB', 'Crypto', '', '<div class="empty">No Coinbase data (API key missing?).</div>');
    const hs = cb.holdings.slice().sort((a, b) => b.amount * b.price - a.amount * a.price), tot = hs.reduce((s, h) => s + h.amount * h.price, 0), cols = 'minmax(0,1.5fr) 1fr 1fr .8fr';
    const rows = hs.slice(0, 12).map(h => { const v = h.amount * h.price, gp = h.gain_pct; return `<div class="tr" style="grid-template-columns:${cols}" data-h="${esc(h.currency)}"><span class="nm">${logo('c:' + h.currency, h.currency)}<span class="t">${esc(h.currency)}<small>${esc(h.name)}</small></span></span><span class="r dim">${h.amount < 10 ? h.amount.toFixed(4).replace('.', ',') : nf2.format(h.amount)}</span><span class="r wh">${A(v)}</span><span class="r ${cl(gp)}" title="${h.cost == null ? 'No purchase price known' : 'Paid ' + eur(h.cost) + ' · gain ' + eur(h.gain)}">${gp == null ? '<span class="dim xs">cost unknown</span>' : pct(gp, 0)}${h.cost != null && h.cost_known_share != null && h.cost_known_share < 0.999 ? '<span class="dim xs" title="Part of this balance has no known purchase price"> *</span>' : ''}</span></div>`; }).join('');
    POST.push(() => { TS($('#cbc'), prep(cryptoRaw(d), S)); $$('#pCB .tr[data-h]').forEach(r => r.onclick = () => openCoin(r.dataset.h)); $('#cbt').onclick = openCrypto; });
    return panel('pCB', `<span id="cbt" style="cursor:pointer">${logo('coinbase', 'Coinbase')}&nbsp; Coinbase <b>//</b> ${hs.length} assets${spanTag(d.axis.length - Math.min(...hs.filter(h => h.hist).map(h => firstIdx(h.hist)), d.axis.length - 1))}</span>`, srcBadge('coinbase', d), `<div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:.4rem"><div class="kp"><div class="l">Total</div><div class="v">${A(tot)}</div><div class="s">${esc(d.mode === 'demo' ? 'demo' : 'price now')}</div></div><div class="kp"><div class="l">Bitcoin share</div><div class="v">${tot ? ((hs.find(h => h.currency === 'BTC') || { amount: 0, price: 0 }).amount * (hs.find(h => h.currency === 'BTC') || { price: 0 }).price / tot * 100).toFixed(0) : 0} %</div><div class="s">of crypto</div></div><div class="kp" title="${cb.cost == null ? '' : 'Paid ' + eur(cb.cost) + ' · gain ' + eur(cb.gain)}"><div class="l">Since purchase</div><div class="v ${cl(cb.gain_pct)}">${cb.gain_pct == null ? '–' : pct(cb.gain_pct, 0)}</div><div class="s">${cb.gain == null ? 'cost unknown' : '<span class="amt">' + eur(cb.gain) + '</span>'}</div></div></div>${cbNote(cb)}<div class="fill" id="cbc" style="flex:1.1"></div><div class="tbl" style="flex:2;overflow:auto"><div class="tr th" style="grid-template-columns:${cols}"><span>Asset</span><span class="r">Amount</span><span class="r">Value</span><span class="r">Gain</span></div>${rows}</div>`, { style: 'flex:3.6', heat: heatCrypto });
  }
  function cryptoRaw(d) { const hs = d.crypto.holdings.filter(h => h.hist); return { axis: d.axis, kind: 'stock', stacked: true, series: hs.map((h, i) => ({ n: h.currency, c: PAL[i % PAL.length], v: h.hist.map((p, i) => p == null || (h.first_buy && d.axis[i] < h.first_buy.slice(0, 7)) ? null : p * h.amount), type: 'area' })) }; }
  function pAlt(d) {
    const wi = d.wiwin, L = d.loan;
    if (!wi) return L ? panel('pAlt', 'Loans', '', `<div class="tr" id="altL" style="grid-template-columns:1fr auto"><span class="nm"><span class="t">Loan from ${esc(L.lender)}<small>${eur(L.monthly)} / month · paid off ${mlabLong(L.payoff)}</small></span></span><span class="r neg">−${A(L.balance)}</span></div>`, { style: 'flex:1.1' }) + (POST.push(() => { const l = $('#altL'); if (l) l.onclick = openLoan; }), '') : '';
    POST.push(() => { $('#altW').onclick = () => window.WVA ? WVA.companyModal({ name: wi.issuer, wiwin: wi, web: wi.web || '', blurb: 'Crowd investment, counted as private equity. No live price exists for stakes like this, so it is carried at cost (' + (wi.note || 'at cost') + '). Tell me the current value or repayments to update config.json.' }) : infoModal('wiwin investment', `<div class="stats"><div>Issuer<b>${esc(wi.issuer)}</b></div><div>Platform<b>${esc(wi.platform)}</b></div><div>Invested<b>${A(wi.invested)}</b></div><div>Valuation<b>${esc(wi.note || 'at cost')}</b></div></div><p class="dim sm">wiwin counts as <b>Private equity</b> in the asset classes (together with Example Fund). No live price exists for crowd-investing stakes, so it is carried at cost. Tell me the current value or repayments to update it in config.json.</p>`, srcBadge('wiwin', d)); const l = $('#altL'); if (l) l.onclick = openLoan; });
    const loan = L ? `<div class="tr" id="altL" style="grid-template-columns:2.4rem 1fr auto;margin-top:.2rem"><span>${iconLg('loan')}</span><span class="nm"><span class="t">Loan from ${esc(L.lender)}<small>${eur(L.monthly)} / month · paid off ${mlabLong(L.payoff)}</small><span class="bar" style="display:block;margin-top:.2rem"><i style="width:${L.repaid / L.principal * 100}%;background:#6fbf95"></i></span></span></span><span class="r neg">−${A(L.balance)}</span></div>` : '';
    return panel('pAlt', 'Alternatives <b>//</b> private holdings & loans', srcBadge('wiwin', d), `<div class="tr" id="altW" style="grid-template-columns:2.4rem 1fr auto"><span>${logo('wiwin', 'wiwin', true)}</span><span class="nm"><span class="t">${esc(wi.issuer)}<small>${esc(wi.platform)} · ${esc(wi.note || 'at cost')} · counts as private equity</small></span></span><span class="r wh">${A(wi.invested)}</span></div>${loan}<div class="xs dim" style="margin-top:.4rem">Private equity total (Example Fund + wiwin): <b class="wh">${A(classValues(d)['Private equity'])}</b></div>`, { style: 'flex:1.1' });
  }
  /* v1.20: what you typed in under Setup (house, loans, funds, other investments, balances). Shown only when something was typed in. */
  function pTyped(d) {
    const a = d.assets; if (!a) return '';
    const row = (name, sub, val, neg) => `<div class="tr" style="grid-template-columns:1fr auto"><span class="nm"><span class="t">${esc(name)}<small>${esc(sub)}</small></span></span><span class="r ${neg ? 'neg' : 'wh'}">${neg ? '−' : ''}${A(val)}</span></div>`;
    const rows = [];
    (a.property || []).forEach(p => rows.push(row(p.name, 'House / apartment · ' + p.basis + (p.equity != null && p.equity !== p.value ? ' · ' + eur(p.equity) + ' after its loan' : ''), p.value)));
    (a.loans || []).forEach(l => rows.push(row(l.name, 'Loan · ' + eur(l.monthly) + ' / month' + (l.payoff ? ' · paid off ' + mlabLong(l.payoff) : ''), l.balance, true)));
    (a.funds || []).forEach(f => rows.push(row(f.name, 'Fund · ' + (f.basis === 'typed' && f.gain != null ? (f.gain >= 0 ? '+' : '−') + eur(Math.abs(f.gain)) + ' on ' + eur(f.invested) + ' paid in' : 'shown at cost'), f.value)));
    (a.other || []).forEach(o => rows.push(row(o.name, 'Other investment' + (o.date ? ' · as of ' + o.date : ''), o.value)));
    (a.balances || []).forEach(b => rows.push(row(b.name, 'Balance you typed in', b.balance)));
    const est = (a.property || []).some(p => p.basis === 'estimate');
    POST.push(() => { const l = $('#tySetup'); if (l) l.onclick = e => { e.preventDefault(); if (window.WVS) WVS.open(); }; });
    return panel('pTyped', 'Typed in <b>//</b> house, loans & other investments', badge('static', 'Your numbers'), rows.join('') +
      `<div class="xs dim" style="margin-top:.5rem">${est ? '“estimate” follows the official house price index of the country (Eurostat) from your purchase price, it is not a valuation. ' : ''}<a href="#" id="tySetup">Edit in Setup</a></div>`, { style: 'flex:1' });
  }
  function acctRaw(d, kinds) { const b = d.balances; return { axis: b.months, kind: 'stock', series: kinds.map(([k, n, c]) => ({ n, c, v: b[k], type: 'line' })) }; }
  function pSrc(d) {
    const t = d.totals, ap = d.apartment, rows = [];   /* ap / wiwin / examplefund are absent when their module is off */
    const add = (key, label, sub, val, bd, fn) => rows.push(`<div class="tr" style="grid-template-columns:2.2rem minmax(0,1fr) auto auto" data-i="${rows.length}"><span>${key.startsWith('~') ? iconLg(key.slice(1)) : logo(key, label)}</span><span class="nm"><span class="t">${esc(label)}<small>${esc(sub)}</small></span></span><span class="r wh">${val == null ? '–' : A(val)}</span><span>${bd}</span></div>`);
    const fns = [];
    add('gls', 'GLS Giro', 'checking account', t.giro, srcBadge('gls', d)); fns.push(() => openAcct('Giro', [['giro', 'Giro', '#19d3ff']]));
    add('gls', 'GLS Tagesgeld', 'savings account', t.tages, srcBadge('gls', d)); fns.push(() => openAcct('Tagesgeld', [['tages', 'Tagesgeld', '#8fe6b8']]));
    add('gls', 'GLS Credit card', 'balance', t.card, srcBadge('gls', d)); fns.push(() => openAcct('Credit card', [['card', 'Card balance', '#ff6b6b']]));
    add('gls', 'GLS Bank shares', 'cooperative shares', t.shares, srcBadge('gls', d)); fns.push(() => openAcct('GLS shares', [['shares', 'Shares', '#ffd24a']]));
    add('paypal', 'PayPal', t.paypal == null ? 'balance unknown (export too old)' : 'balance', t.paypal, srcBadge('paypal', d)); fns.push(() => infoModal('PayPal', '<p class="dim">PayPal only provides balances through the activity export (Download.CSV). Download a new one into the PayPal folder to include it.</p>'));
    add('gls', 'GLS Depot', (d.depot ? d.depot.positions.length : 0) + ' positions', d.depot && d.depot.total, srcBadge('depot', d)); fns.push(() => openSec());
    add('coinbase', 'Coinbase', (d.crypto ? d.crypto.holdings.length : 0) + ' assets', d.crypto && d.crypto.total_eur, srcBadge('coinbase', d)); fns.push(() => openCrypto());
    if ('examplefund' in d) { add('examplefund', fundTitle(d), 'venture fund', d.examplefund && d.examplefund.personal.nav, srcBadge('examplefund', d)); fns.push(() => openWF()); }
    if (d.wiwin) { add('wiwin', 'wiwin · ' + d.wiwin.issuer, 'crowd investment', d.wiwin.invested, srcBadge('wiwin', d)); fns.push(() => $('#altW') && $('#altW').click()); }
    if (ap) { add('~house', ap.address.split(',')[0], ap.sqm + ' sqm · benchmark value', ap.value_used, badge(d.mode === 'demo' ? 'demo' : 'model', d.mode === 'demo' ? 'Demo' : 'Model')); fns.push(() => openApt()); }
    POST.push(() => $$('#pSrc .tr[data-i]').forEach(r => r.onclick = () => fns[+r.dataset.i]()));
    return panel('pSrc', 'Accounts & sources', d.mode === 'demo' ? badge('demo', 'Demo') : badge('mix', 'Live + static'), `<div class="tbl" style="overflow:auto">${rows.join('')}</div>`, { style: 'flex:3.6' });
  }
  function pRecent(d) {
    const rc = (d.gls && d.gls.recent || []).slice(0, 10).map(r => `<div class="tr rb" data-n="${esc(r.n)}" title="Click for the booking history with ${esc(r.n)}" style="grid-template-columns:3.2rem 1.7rem minmax(0,1fr) auto;cursor:pointer;padding:.22rem .2rem"><span class="dim xs">${dshort(r.d)}</span>${logo(r.lg || 'none:' + r.n, r.n)}<span class="nm"><span class="t">${esc(r.n)}<small>${esc(r.c)}</small></span></span><span class="r ${r.v < 0 ? '' : 'pos'}">${A(r.v)}</span></div>`).join('') || '<div class="empty">No bookings.</div>';
    POST.push(() => $$('#pRec .tr.rb').forEach(r => r.onclick = () => openBookings(r.dataset.n)));
    return panel('pRec', 'Recent bookings', d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), `<div class="tbl" style="overflow:auto">${rc}</div>`, { style: 'flex:2' });
  }
  // Links from outside (news feeds, sources) are only used when they are http(s): a javascript: link would run in this page.
  function safeUrl(u) { return /^https?:\/\//i.test(String(u || '').trim()) ? String(u).trim() : ''; }
  function aptSources(ap) {
    const l = (ap.sources && ap.sources.length) ? ap.sources : [{ label: ap.benchmark_name, url: ap.benchmark_source }]; if (ap.benchmark2_source && !(ap.sources || []).length) l.push({ label: ap.benchmark2_name, url: ap.benchmark2_source });
    return l.filter(x => safeUrl(x.url)).map(x => `<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener">${esc(x.label)} ↗</a>`).join(' · ');
  }
  /* ================================================== network world map (same look as the Jarvis HUD: dotted land, arcs with particles, ripples, pulsing home point)
     Shows ONLY the connections WealthView itself started (netlog.py): host, place and how often - never any content. */
  const MAP = { dots: [], ok: null, nodes: [], home: { name: 'Home', lat: 51.0, lon: 10.0 }, total: 0, countries: 0, err: null, Z: null, ph: 0, last: 0, sig: null, hit: {} };
  const HOME0 = MAP.home;      /* the built-in home point; profile.home (layout.js homePoint) replaces it when set */
  async function mapLoad() {
    try {
      const tp = await (await fetch('/land-110m.json')).json(), sc = tp.transform.scale, tl = tp.transform.translate;
      const arcs = tp.arcs.map(a => { let x = 0, y = 0; return a.map(p => { x += p[0]; y += p[1]; return [x * sc[0] + tl[0], y * sc[1] + tl[1]]; }); });
      const ring = ids => { let pts = []; ids.forEach(i => { const a = i < 0 ? arcs[~i].slice().reverse() : arcs[i]; pts = pts.concat(pts.length ? a.slice(1) : a); }); return pts; };
      const polys = []; const walk = o => { if (o.type === 'GeometryCollection') o.geometries.forEach(walk); else if (o.type === 'Polygon') polys.push(o.arcs); else if (o.type === 'MultiPolygon') o.arcs.forEach(q => polys.push(q)); };
      Object.values(tp.objects).forEach(walk);
      const c3 = document.createElement('canvas'); c3.width = 360; c3.height = 180; const c2 = c3.getContext('2d'); c2.fillStyle = '#fff';
      polys.forEach(po => { c2.beginPath(); po.forEach(r => { ring(r).forEach((q, i) => { const x = q[0] + 180, y = 90 - q[1]; i ? c2.lineTo(x, y) : c2.moveTo(x, y); }); c2.closePath(); }); c2.fill('evenodd'); });
      const d = c2.getImageData(0, 0, 360, 180).data;
      for (let y = 0; y < 180; y += 2) for (let x = 0; x < 360; x += 2) if (d[((y + 1) * 360 + x + 1) * 4 + 3] > 128) { const lat = 90 - (y + 1); if (lat < 84 && lat > -58) MAP.dots.push([x + 1 - 180, lat]); }
      MAP.ok = true;
    } catch (e) { MAP.ok = false; }
  }
  const mapDemo = () => { const n = Date.now() / 1000; return [['query1.finance.yahoo.com', 'Yahoo Finance', 'Sunnyvale', 'United States', 37.37, -122.04, 8, 20], ['news.google.com', 'Google News', 'Mountain View', 'United States', 37.42, -122.08, 2, 400], ['api.coinbase.com', 'Coinbase', 'San Francisco', 'United States', 37.77, -122.42, 4, 60], ['www.wikidata.org', 'Wikidata', 'Ashburn', 'United States', 39.04, -77.49, 1, 900]].map(a => ({ host: a[0], label: a[1], city: a[2], country: a[3], lat: a[4], lon: a[5], n: a[6], last: n - a[7], ok: 1 })); };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  /* wait = true: the server answers the moment WealthView starts a new connection (long poll, idle most of the time) */
  async function mapPoll(wait) {
    if (S.mode === 'real' && S.token) {
      try {
        const j = await api('/api/netlog' + (wait && MAP.sig ? '?wait=1&sig=' + encodeURIComponent(MAP.sig) : ''));
        if (j && !j.error) {
          const old = {}; MAP.nodes.forEach(n => { old[n.host] = n.n; });
          if (MAP.sig) (j.nodes || []).forEach(n => { if (old[n.host] == null || n.n > old[n.host]) MAP.hit[n.host] = performance.now(); });
          MAP.nodes = j.nodes || []; MAP.home = (window.WVL && WVL.homePoint(S.profile)) || j.home || MAP.home; MAP.total = j.total || 0; MAP.countries = j.countries || 0; MAP.sig = j.sig || MAP.sig; MAP.err = null; return true;
        }
        MAP.err = (j && j.error) || 'no answer'; return false;
      } catch (e) { MAP.err = e.locked ? null : 'server not reachable'; return !!e.locked; }
    }
    MAP.home = HOME0; MAP.nodes = mapDemo(); MAP.total = MAP.nodes.reduce((s, x) => s + x.n, 0); MAP.countries = 1; MAP.err = null; MAP.sig = null; return true;
  }
  (async function mapLoop() { for (; ;) { try { if (S.mode === 'real' && S.token && !document.hidden) { const t0 = Date.now(), ok = await mapPoll(true); if (!ok || !MAP.sig) await sleep(5000); else if (Date.now() - t0 < 300) await sleep(1000); } else await sleep(3000); } catch (e) { await sleep(5000); } } })();
  function mapDraw(t) {
    const cv = $('#mapC'); if (!cv || document.hidden) return;
    const box = cv.parentElement, W = box.clientWidth, H = box.clientHeight; if (W < 80 || H < 60) return;
    const k = window.devicePixelRatio || 1; if (cv.width !== Math.round(W * k) || cv.height !== Math.round(H * k)) { cv.width = Math.round(W * k); cv.height = Math.round(H * k); cv.style.width = W + 'px'; cv.style.height = H + 'px'; }
    const g = cv.getContext('2d'); g.setTransform(k, 0, 0, k, 0, 0); g.clearRect(0, 0, W, H);
    const C = '#19d3ff', OR = '#ff9a3d', dim = 'rgba(127,220,255,.6)', FF = 'Consolas,"Cascadia Mono",monospace', u = Math.max(.8, Math.min(1.5, W / 620));
    const tx = (s, x, y, sz, col, al) => { g.font = sz + 'px ' + FF; g.fillStyle = col; g.textAlign = al || 'left'; g.textBaseline = 'alphabetic'; g.fillText(s, x, y); };
    const ln = (a, b, c, d) => { g.beginPath(); g.moveTo(a, b); g.lineTo(c, d); g.stroke(); };
    const now = Date.now() / 1000, nodes = MAP.nodes.filter(n => Number.isFinite(n.lat) && Number.isFinite(n.lon)).slice(0, 40), home = MAP.home;
    const S0 = Math.min(W / 360, H / 142), cx = W / 2, cy = H / 2, Z = MAP.Z || (MAP.Z = {});
    /* auto-zoom to the connections (like the HUD) */
    let la = home.lon, lb = home.lon, lc = home.lat, ld = home.lat; nodes.forEach(q => { la = Math.min(la, q.lon); lb = Math.max(lb, q.lon); lc = Math.min(lc, q.lat); ld = Math.max(ld, q.lat); });
    let tS = S0, tL = 0, tA = 13;
    if (nodes.length) { const sl = Math.max((lb - la) * 1.3 + 16, 30), sa = Math.max((ld - lc) * 1.3 + 16, 30 * 142 / 360); tS = Math.max(S0, Math.min(W / sl, H / sa)); tL = (la + lb) / 2; tA = (lc + ld) / 2; }
    const dt = Math.min(100, t - (Z.t || t)) / 1000; Z.t = t; const zk = Z.s == null ? 1 : 1 - Math.exp(-dt * 3);
    Z.s = Z.s == null ? tS : Z.s + (tS - Z.s) * zk; Z.l = Z.l == null ? tL : Z.l + (tL - Z.l) * zk; Z.a = Z.a == null ? tA : Z.a + (tA - Z.a) * zk;
    const pj = (lo, la2) => [cx + (lo - Z.l) * Z.s, cy - (la2 - Z.a) * Z.s];
    g.save(); g.beginPath(); g.rect(0, 0, W, H); g.clip();
    g.strokeStyle = C; g.lineWidth = u; g.globalAlpha = .08;
    for (let lo = -180; lo <= 180; lo += 30) { const a = pj(lo, 84), b = pj(lo, -58); ln(a[0], a[1], b[0], b[1]); }
    for (let l2 = -30; l2 <= 60; l2 += 30) { const a = pj(-180, l2), b = pj(180, l2); ln(a[0], a[1], b[0], b[1]); }
    if (MAP.ok) { const ds = 0.9 * u, sz = ds * Math.min(Z.s / S0, 4); g.fillStyle = C; g.globalAlpha = .38; MAP.dots.forEach(d => { const x = cx + (d[0] - Z.l) * Z.s, y = cy - (d[1] - Z.a) * Z.s; if (x > -6 && x < W + 6 && y > -6 && y < H + 6) g.fillRect(x, y, sz, sz); }); g.globalAlpha = 1; }
    else tx(MAP.ok === null ? 'LOADING MAP...' : 'MAP DATA UNAVAILABLE', W / 2, H / 2, 14 * u, dim, 'center');
    const hp = pj(home.lon, home.lat), md = Math.min(100, t - (MAP.last || t)) / 1000; MAP.last = t;
    const act = nodes.filter(n => now - n.last < 60).length; MAP.ph += md * (.25 + Math.min(2, act * .4));
    g.save(); g.globalCompositeOperation = 'lighter';
    nodes.forEach((q, i) => {
      const e = pj(q.lon, q.lat), dx = e[0] - hp[0], dy = e[1] - hp[1], dist = Math.hypot(dx, dy);
      const lift = Math.max(0, Math.min(H * .6, dist * .5 + 12 * u, (hp[1] + e[1]) - 4 * u)), qx = (hp[0] + e[0]) / 2, qy = (hp[1] + e[1]) / 2 - lift, col = !q.ok ? '#ff5a5a' : now - q.last < 120 ? OR : C;
      g.globalAlpha = .12; g.strokeStyle = col; g.lineWidth = u; g.beginPath(); g.moveTo(hp[0], hp[1]); g.lineTo(e[0], e[1]); g.stroke();
      g.globalAlpha = .6; g.lineWidth = 1.4 * u; g.beginPath(); g.moveTo(hp[0], hp[1]); g.quadraticCurveTo(qx, qy, e[0], e[1]); g.stroke();
      for (let kk = 0; kk < 2; kk++) for (let j = 0; j < 6; j++) { const f = ((MAP.ph * .6 + i * .17 + kk * .5) % 1) - j * .02; if (f < 0) continue; const a = 1 - f, x = a * a * hp[0] + 2 * a * f * qx + f * f * e[0], y = a * a * hp[1] + 2 * a * f * qy + f * f * e[1]; g.globalAlpha = (1 - j / 6) * .95; g.fillStyle = j ? col : '#ffffff'; g.beginPath(); g.arc(x, y, Math.max(.6, 2.4 - j * .35) * u, 0, Math.PI * 2); g.fill(); }
      const rp = (MAP.ph * .8 + i * .3) % 1; g.globalAlpha = (1 - rp) * .9; g.strokeStyle = col; g.lineWidth = 1.5 * u; g.beginPath(); g.arc(e[0], e[1], (2 + rp * 8) * u, 0, Math.PI * 2); g.stroke();
      g.globalAlpha = 1; g.fillStyle = col; g.beginPath(); g.arc(e[0], e[1], 2.4 * u, 0, Math.PI * 2); g.fill();
      const hit = MAP.hit[q.host]; if (hit) { const ha = (performance.now() - hit) / 2500; if (ha < 1) { g.globalAlpha = 1 - ha; g.strokeStyle = '#ffffff'; g.lineWidth = 2 * u; g.beginPath(); g.arc(e[0], e[1], (3 + ha * 26) * u, 0, Math.PI * 2); g.stroke(); g.fillStyle = '#ffffff'; g.beginPath(); g.arc(e[0], e[1], 3.4 * u, 0, Math.PI * 2); g.fill(); } else delete MAP.hit[q.host]; }
    });
    g.restore(); g.globalAlpha = 1;
    g.strokeStyle = OR; g.lineWidth = 2 * u; g.beginPath(); g.arc(hp[0], hp[1], 5 * u + 2 * u * Math.sin(t / 300), 0, Math.PI * 2); g.stroke();
    g.fillStyle = OR; g.beginPath(); g.arc(hp[0], hp[1], 2.5 * u, 0, Math.PI * 2); g.fill();
    tx(String(home.name || 'HOME').toUpperCase(), hp[0] + 9 * u, hp[1] - 7 * u, 11 * u, OR);
    g.restore();
    /* legend (bottom right) */
    { const lx = W - 150 * u, ly = H - 64 * u; g.setLineDash([]); g.fillStyle = 'rgba(2,6,11,.8)'; g.fillRect(lx - 6 * u, ly - 4 * u, 156 * u, 66 * u); g.lineWidth = 2.5 * u;
      g.strokeStyle = OR; ln(lx, ly + 6 * u, lx + 14 * u, ly + 6 * u); tx('ORANGE: ACTIVE < 2 MIN', lx + 20 * u, ly + 10 * u, 6.65 * u, dim);
      g.strokeStyle = C; ln(lx, ly + 20 * u, lx + 14 * u, ly + 20 * u); tx('BLUE: EARLIER', lx + 20 * u, ly + 24 * u, 6.65 * u, dim);
      g.strokeStyle = '#ff5a5a'; ln(lx, ly + 34 * u, lx + 14 * u, ly + 34 * u); tx('RED: CALL FAILED', lx + 20 * u, ly + 38 * u, 6.65 * u, dim);
      g.strokeStyle = OR; g.lineWidth = 1.5 * u; g.beginPath(); g.arc(lx + 7 * u, ly + 48 * u, 3.5 * u, 0, Math.PI * 2); g.stroke(); tx('HOME: ' + String(home.name || '').toUpperCase(), lx + 20 * u, ly + 52 * u, 6.65 * u, dim); }
    /* list (bottom left) */
    const rows = Math.max(1, Math.min(6, Math.floor((H * .55 - 30 * u) / (18 * u)))), fy = H - (rows * 18 + 14) * u;
    g.fillStyle = 'rgba(2,6,11,.8)'; g.fillRect(0, fy - 16 * u, Math.min(W - 160 * u, 380 * u), (rows * 18 + 32) * u);
    const ctry = {}; nodes.forEach(q => { ctry[q.country] = 1; });
    tx(MAP.err ? 'NO DATA: ' + String(MAP.err).slice(0, 40).toUpperCase() : nodes.length + ' CONNECTIONS // ' + Object.keys(ctry).length + ' COUNTRIES // ' + MAP.total + ' CALLS', 6 * u, fy, 8.05 * u, MAP.err ? '#ff5a5a' : C);
    nodes.slice().sort((a, b) => b.last - a.last).slice(0, rows).forEach((q, i) => { const y = fy + (i + 1) * 18 * u; tx(((q.city || '?').slice(0, 14) + ', ' + (q.country || '').slice(0, 12)), 6 * u, y, 7.35 * u, dim); tx(String(q.label || q.host).slice(0, 14).toUpperCase() + ' ×' + q.n, 200 * u, y, 6.65 * u, 'rgba(180,230,255,.6)'); });
  }
  function pMap(d) {
    return panel('pMap', 'Network <b>//</b> WealthView connections', d.mode === 'demo' ? badge('demo', 'Demo connections') : badge('live', 'Only this dashboard'),
      `<div class="fill" id="mapBox" style="min-height:11rem;overflow:hidden"><canvas id="mapC" style="position:absolute;left:0;top:0"></canvas></div><div class="xs dim" style="margin-top:.25rem">${d.mode === 'demo' ? 'Example connections. ' : ''}Only connections started by WealthView itself (quotes, news, Coinbase, logos, chat) · host and time only, never content · places looked up from the server\'s address.</div>`, { cls: '', style: 'flex:1.9;min-height:14rem' });
  }
  function pApt(d) {
    const ap = d.apartment; if (!ap) return '';
    POST.push(() => { TS($('#apc'), prep(aptRaw(d), S)); $('#pApt').onclick = e => { if (!e.target.closest('.hv,.tip,a')) openApt(); }; });
    return panel('pApt', `Real estate <b>//</b> ${esc(ap.address.split(',')[0])} · ${ap.sqm} sqm` + spanTag(d.axis.length - Math.max(0, d.axis.indexOf(ap.purchase_date.slice(0, 7)))), d.mode === 'demo' ? badge('demo', 'Demo') : badge('model', 'Model · benchmark'),
      `<div class="kpis" style="margin-bottom:.4rem"><div class="kp"><div class="l">Bought ${esc(ap.purchase_date.slice(0, 7))}</div><div class="v">${A(ap.purchase_price)}</div><div class="s">${nf0.format(ap.purchase_per_sqm || ap.purchase_price / ap.sqm)} €/sqm</div></div><div class="kp"><div class="l">Estimated now</div><div class="v">${A(ap.value_used)}</div><div class="s">${nf0.format(ap.estimate_per_sqm || ap.value_used / ap.sqm)} €/sqm</div></div><div class="kp"><div class="l">Value increase</div><div class="v ${cl(ap.gain)}">${A(ap.gain)}</div><div class="s">${pct(ap.gain_pct)} since purchase</div></div></div><div class="fill" id="apc"></div><div class="xs dim" style="margin-top:.3rem">Estimate = purchase price scaled by ${esc(ap.benchmark_name)}. Sources: ${aptSources(ap)}</div>`, { cls: 'click', style: 'flex:1;min-height:0' });
  }
  function aptRaw(d) {
    const ap = d.apartment, s = [{ n: 'Estimated value (local benchmark)', c: '#2b9bff', v: ap.series, type: 'area' }];
    if (ap.series2) s.push({ n: 'Market benchmark', c: '#b48cff', v: ap.series2, type: 'line', fixed: true, dash: true });
    return { axis: d.axis, kind: 'stock', series: s, refs: [{ v: ap.purchase_price, label: 'purchase price', c: '#ff9a3d' }], zero: false };
  }

  /* ---------------- center: ring */
  function polar(cx, cy, r, a) { return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }
  function ringHTML(d) {
    const v = classValues(d), tot = CLS.reduce((s, k) => s + v[k], 0), cx = 300, cy = 300, ni = netInfo(d); let a = -Math.PI / 2, seg = '', lab = '';
    CLS.forEach(k => { const f = v[k] / tot; if (f <= 0) return; const a0 = a + .015, a1 = a + f * 2 * Math.PI - .015, [x0, y0] = polar(cx, cy, 222, a0), [x1, y1] = polar(cx, cy, 222, a1), lg = (a1 - a0) > Math.PI ? 1 : 0; seg += `<path class="seg" data-k="${k}" d="M${x0},${y0} A222,222 0 ${lg} 1 ${x1},${y1}" fill="none" stroke="${CCOL[k]}" stroke-width="38" opacity=".78"><title>${k}: ${eur(v[k])} (${(f * 100).toFixed(1).replace('.', ',')} %)</title></path>`; const am = (a0 + a1) / 2, [lx, ly] = polar(cx, cy, 262, am); if (f > .025) lab += `<text x="${lx}" y="${ly + 3}" text-anchor="middle" font-size="13.2" fill="${CCOL[k]}">${Math.round(f * 100)}%</text>`; a += f * 2 * Math.PI; });
    let ticks = ''; for (let i = 0; i < 180; i++) { const an = i / 180 * 2 * Math.PI, [x0, y0] = polar(cx, cy, 284, an), [x1, y1] = polar(cx, cy, i % 15 === 0 ? 271 : i % 5 === 0 ? 276 : 279, an); ticks += `M${x0.toFixed(1)},${y0.toFixed(1)}L${x1.toFixed(1)},${y1.toFixed(1)}`; }
    let t2 = ''; for (let i = 0; i < 72; i++) { const an = i / 72 * 2 * Math.PI, [x0, y0] = polar(cx, cy, 196, an), [x1, y1] = polar(cx, cy, 190, an); t2 += `M${x0.toFixed(1)},${y0.toFixed(1)}L${x1.toFixed(1)},${y1.toFixed(1)}`; }
    const svg = `<svg id="ringSvg" viewBox="0 0 600 600"><defs><radialGradient id="rg"><stop offset="0" stop-color="#1b6f94" stop-opacity=".28"/><stop offset="1" stop-color="#001018" stop-opacity="0"/></radialGradient></defs><circle cx="300" cy="300" r="190" fill="url(#rg)"/>
      <g class="rs spin1"><path d="${ticks}" stroke="rgba(60,190,235,.65)" stroke-width="1.2" fill="none"/></g>
      <g class="rs spin2"><circle cx="300" cy="300" r="255" fill="none" stroke="rgba(255,154,61,.6)" stroke-width="2" stroke-dasharray="70 14 8 14 160 18"/></g>
      ${seg}${lab}
      <g class="rs spin3"><circle cx="300" cy="300" r="184" fill="none" stroke="rgba(25,211,255,.5)" stroke-width="1" stroke-dasharray="3 7"/><path d="${t2}" stroke="rgba(60,190,235,.4)" fill="none"/></g>
      <circle cx="300" cy="300" r="176" fill="none" stroke="rgba(60,190,235,.35)"/><circle cx="300" cy="300" r="205" fill="none" stroke="rgba(60,190,235,.18)"/>
      <g class="rs spin2"><path d="M300,118 A182,182 0 0 1 438,180" fill="none" stroke="#19d3ff" stroke-width="3" opacity=".9"/><path d="M300,482 A182,182 0 0 1 162,420" fill="none" stroke="#ff9a3d" stroke-width="3" opacity=".9"/></g></svg>`;
    const c12 = chgFirstAll(d);
    return `<div id="ringBox">${svg}<div id="ringMid"><div class="k">GROSS ASSETS</div><div class="v amt" id="ringVal">${nf0.format(Math.round(tot))}</div><div class="u">EUR</div><div class="net" id="netLine" title="Click for the explanation"><span class="nl">NET ASSETS</span> <b class="amt">${nf0.format(Math.round(ni.after))}</b> EUR<small>after loan ${eur(ni.liab)} and est. German tax ${eur(ni.tax)}</small></div><div class="n">${CLS.length} ASSET CLASSES · ${(d.depot ? d.depot.positions.length : 0) + (d.crypto ? d.crypto.holdings.length : 0)} POSITIONS · ${d.examplefund ? d.examplefund.companies.length : 0} VENTURES<br><span class="${cl(c12)}">${pct(c12)} since first investment</span> <span class="dim">(back-cast)</span></div></div></div>`;
  }
  function wings(d) {
    const v = classValues(d), tot = CLS.reduce((s, k) => s + v[k], 0);
    const l = CLS.map(k => `<div class="w" data-k="${k}"><div class="t"><span>${k}</span><b class="amt">${kfmt(v[k])}</b></div><div class="bar"><i style="width:${v[k] / tot * 100}%;background:${CCOL[k]}"></i></div></div>`).join('');
    const rr = CLS.map(k => ({ k, c: chgFirst(d, k) })), mx = Math.max(10, ...rr.map(x => Math.abs(x.c || 0)));
    const r = rr.map(x => `<div class="w" data-k="${x.k}"><div class="t"><span>${x.k}</span><b class="${cl(x.c)}">${x.c == null ? 'n/a' : pct(x.c, 0)}</b></div><div class="bar"><i style="width:${x.c == null ? 0 : Math.min(100, Math.abs(x.c) / mx * 100)}%;background:${(x.c || 0) >= 0 ? '#8fe6b8' : '#ff6b6b'}"></i></div></div>`).join('');
    return `<div class="wing l"><h4>Allocation // value</h4>${l}</div><div class="wing r"><h4>Change since first investment</h4>${r}<div class="xs dim">Securities and crypto: gain vs. what you paid · others: back-cast values</div></div>`;
  }
  /* class boxes get wider with their value; the three flow boxes stay 1fr. Zero/negative values use the minimum. */
  function kpiCols(d) {
    const v = classValues(d), tot = CLS.reduce((s, k) => s + Math.max(0, v[k] || 0), 0) || 1;
    return CLS.map(k => 'minmax(6.5rem,' + (Math.max(0, v[k] || 0) / tot * 5).toFixed(3) + 'fr)').join(' ') + ' 1fr 1fr 1fr';
  }
  function kpiRow(d) {
    const v = classValues(d), f = d.flows, ex = f ? avg12(f.expense) : null, inc = f ? avg12(f.income) : null, sr = inc ? (inc - ex) / inc * 100 : null, liq = v['Cash'];
    const run = ex ? liq / ex : null, one = (k, l, val, s, cls) => `<div class="kp" data-k="${k}"><div class="l">${l}</div><div class="v ${cls || ''}">${val}</div><div class="s">${s}</div></div>`;
    return CLS.map(k => one(k, k, A(v[k]), (v[k] / CLS.reduce((s, x) => s + v[x], 0) * 100).toFixed(1).replace('.', ',') + ' % of total')).join('') + one('flow', 'Spend / month', A(ex), '12 m average') + one('sr', 'Savings rate', pct(sr, 0), '12 months', cl(sr)) + one('run', 'Cash runway', run ? run.toFixed(0) + ' mo' : '–', 'cash ÷ monthly spend');
  }
  /* ================================================== drill-downs */
  function openNW() { openTS({ heat: heatClasses, title: 'Gross assets development', stacked: true, badge: S.D.mode === 'demo' ? badge('demo', 'Demo') : badge('model', 'Back-cast + actual'), make: () => grossRaw(S.D), extra: () => `<p class="xs dim">Real numbers only exist where your files do: cash since the first GLS export; securities and crypto are today\'s holdings valued at historical prices; real estate follows the local benchmark; private equity starts with the first quarterly report in the data. New real snapshots are saved on every refresh.</p>` }); }
  function openClass(k) {
    const d = S.D; if (k === 'flow') return openFlow(); if (k === 'sr') return openFlow(); if (k === 'run') return openAcct('Cash', [['giro', 'Giro', '#19d3ff'], ['tages', 'Tagesgeld', '#8fe6b8'], ['card', 'Card', '#ff6b6b']]);
    if (k === 'Securities') return openSec(); if (k === 'Crypto') return openCrypto(); if (k === 'Real estate') return openApt(); if (k === 'Private equity') return openWF();
    if (k === 'Cash') return openAcct('Cash', [['giro', 'Giro', '#19d3ff'], ['tages', 'Tagesgeld', '#8fe6b8'], ['card', 'Card', '#ff6b6b'], ['shares', 'Shares', '#ffd24a']]);
  }
  function posSeries(p, d) { return p.hist ? p.hist.map(x => x == null ? null : x * (p.qty || 0)) : d.axis.map(() => null); }
  function secRaw(d) { return { axis: d.axis, kind: 'stock', stacked: true, series: d.depot.positions.map((p, i) => ({ n: p.name, c: PAL[i % PAL.length], v: posSeries(p, d), type: 'area' })) }; }
  function openSec() { const d = S.D; openTS({ heat: heatSec, title: 'Securities development (current holdings, historical prices)', stacked: true, badge: srcBadge('depot', d), make: () => secRaw(d) }); }
  function openGroup(name, ps) { const d = S.D; openTS({ heat: heatSec, title: name + ' · development', stacked: true, badge: srcBadge('depot', d), make: () => ({ axis: d.axis, kind: 'stock', stacked: true, series: ps.map((p, i) => ({ n: p.name, c: PAL[i % PAL.length], v: posSeries(p, d), type: 'area' })) }) }); }
  /* ===== position popup: logo + header, price chart with YOUR purchases on top, live meta-score, latest news, purchase-date maths ===== */
  const dfull = iso => iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4) : '–';
  const ago = t => { if (!t) return ''; const s = Date.now() / 1000 - t; return s < 3600 ? Math.max(1, Math.round(s / 60)) + ' min ago' : s < 86400 ? Math.round(s / 3600) + ' h ago' : s < 86400 * 30 ? Math.round(s / 86400) + ' d ago' : dfull(new Date(t * 1000).toISOString()); };
  const scoreCol = v => v >= 60 ? '#5fe3a0' : v >= 45 ? '#e0c24a' : v >= 33 ? '#ee9a4a' : '#ff5c5c';
  function demoTrades(p, d) {   // demo mode only: invented purchases so the popup can be shown
    if (!p.hist) return []; const ix = [Math.floor(d.axis.length * .35), Math.floor(d.axis.length * .72)], q = Math.round((p.qty || 0) * .6);
    return ix.map((i, k) => { const m = d.axis[i], pr = p.hist[i] || p.price || 1, qq = k ? (p.qty || 0) - q : q; return { d: m + '-15', side: 'buy', qty: qq, price: pr, amount: qq * pr }; }).filter(t => t.qty > 0);
  }
  function tradesAdj(p, d, splits) {
    const base = (p.trades && p.trades.length) ? p.trades : (d.mode === 'demo' ? demoTrades(p, d) : []);
    return base.map(t => { let f = 1; (splits || []).forEach(s => { if (t.d < s.d) f *= s.ratio; }); return Object.assign({}, t, { qty: t.qty * f, price: t.price / f, t: Date.parse(t.d + 'T12:00:00Z') }); });
  }
  /* FIFO: open lots from the dated buys; whatever part of today's quantity they do not explain is "earlier purchases" */
  function lotCalc(p, tr) {
    const now = p.price_live || p.price || 0, lots = []; let sold = 0;
    tr.forEach(t => { if (t.side === 'buy') lots.push({ t: t.t, d: t.d, qty: t.qty, rem: t.qty, price: t.price, cost: t.amount }); else sold += t.qty; });
    lots.sort((a, b) => a.t - b.t); let s = sold; lots.forEach(l => { const k = Math.min(l.rem, s); l.rem -= k; s -= k; });
    const open = lots.filter(l => l.rem > 1e-6).map(l => { const cost = l.cost * l.rem / l.qty, val = l.rem * now, days = (Date.now() - l.t) / 864e5, g = val - cost, gp = cost ? g / cost * 100 : null;
      return Object.assign({}, l, { cost, val, g, gp, days, pa: days >= 90 && cost > 0 && val > 0 ? (Math.pow(val / cost, 365 / days) - 1) * 100 : null }); });
    const kq = open.reduce((a, l) => a + l.rem, 0), kc = open.reduce((a, l) => a + l.cost, 0), uq = (p.qty || 0) - kq;
    const early = uq > 0.5 ? { qty: uq, cost: p.isCoin ? null : Math.max(0, (p.cost || 0) - kc), val: uq * now } : null; if (early) { early.g = early.cost == null ? null : early.val - early.cost; early.gp = early.cost ? early.g / early.cost * 100 : null; }
    // money-weighted annual return (IRR) of the dated lots only
    let irr = null; if (open.length) { const cf = open.map(l => [l.t, -l.cost]).concat([[Date.now(), open.reduce((a, l) => a + l.val, 0)]]), npv = r => cf.reduce((a, [t, v]) => a + v / Math.pow(1 + r, (t - cf[0][0]) / 864e5 / 365), 0); let lo = -.95, hi = 20; if (npv(lo) * npv(hi) < 0) { for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (npv(lo) * npv(m) <= 0) hi = m; else lo = m; } irr = (lo + hi) / 2 * 100; } }
    return { open, early, irr, mismatch: uq < -0.5, sells: tr.filter(t => t.side === 'sell'), kq, kc };
  }
  function posChart(el, o) {
    const W = el.clientWidth, H = el.clientHeight; if (W < 80 || H < 60) return;
    const L = 58, R = 16, T = 16, B = 26, iw = W - L - R, ih = H - T - B; let pts = o.pts;
    if (o.range !== 'MAX') { const cut = Date.now() - ({ '1Y': 1, '3Y': 3, '5Y': 5 }[o.range] || 5) * 365.25 * 864e5; pts = pts.filter(q => q[0] >= cut); }
    if (pts.length < 2) { el.innerHTML = '<div class="empty" style="padding:1rem">No price history for this range.</div>'; return; }
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0], tr = o.trades.filter(x => x.t >= t0 - 7 * 864e5 && x.t <= t1 + 7 * 864e5);
    let lo = Infinity, hi = -Infinity; pts.forEach(q => { lo = Math.min(lo, q[1]); hi = Math.max(hi, q[1]); }); tr.forEach(x => { lo = Math.min(lo, x.price); hi = Math.max(hi, x.price); }); if (o.avg) { lo = Math.min(lo, o.avg); hi = Math.max(hi, o.avg); }
    const pad = (hi - lo) * .08 || 1; lo = Math.max(0, lo - pad); hi += pad; const st = niceStep((hi - lo) / 4), y0 = Math.floor(lo / st) * st, y1 = Math.ceil(hi / st) * st;
    const X = t => L + iw * (t - t0) / (t1 - t0), Y = v => T + ih * (1 - (v - y0) / (y1 - y0)), fm = v => v >= 1000 ? nf0.format(v) : nf2.format(v); let g = '';
    for (let v = y0; v <= y1 + st / 2; v += st) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="rgba(60,190,235,.13)"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="rgba(127,220,255,.65)">${fm(v)}</text>`;
    const span = (t1 - t0) / 864e5 / 365, stepM = span > 3 ? 12 : span > 1.3 ? 6 : span > .6 ? 3 : 1, dd = new Date(t0); dd.setUTCDate(1); dd.setUTCHours(0, 0, 0, 0);
    for (let k = 0; k < 400; k++) { const dt = new Date(Date.UTC(dd.getUTCFullYear(), dd.getUTCMonth() + k, 1)); if (dt.getTime() > t1) break; if (dt.getTime() < t0 || (dt.getUTCMonth() % stepM)) continue; g += `<line x1="${X(dt)}" x2="${X(dt)}" y1="${T}" y2="${T + ih}" stroke="rgba(60,190,235,.07)"/><text x="${X(dt)}" y="${H - 7}" text-anchor="middle" font-size="11" fill="rgba(127,220,255,.65)">${stepM >= 12 ? dt.getUTCFullYear() : MON[dt.getUTCMonth()] + ' ' + String(dt.getUTCFullYear()).slice(2)}</text>`; }
    const line = pts.map((q, i) => (i ? 'L' : 'M') + X(q[0]).toFixed(1) + ',' + Y(q[1]).toFixed(1)).join('');
    g += `<path d="${line}L${X(t1)},${T + ih}L${X(t0)},${T + ih}Z" fill="rgba(25,211,255,.14)"/><path d="${line}" fill="none" stroke="#19d3ff" stroke-width="1.6"/>`;
    { const pm = pts.reduce((a, q) => a + q[1], 0) / pts.length; g += `<line x1="${L}" x2="${W - R}" y1="${Y(pm)}" y2="${Y(pm)}" stroke="#cfe6ee" stroke-width="1.3" stroke-dasharray="1.5 4" stroke-linecap="round" opacity=".85"/><text x="${L + 4}" y="${Y(pm) - 3}" font-size="11" fill="#cfe6ee">Ø price ${fm(pm)} €</text>`; }
    if (o.avg) g += `<line x1="${L}" x2="${W - R}" y1="${Y(o.avg)}" y2="${Y(o.avg)}" stroke="#ff9a3d" stroke-dasharray="5 4" opacity=".85"/><text x="${W - R - 3}" y="${Y(o.avg) - 4}" text-anchor="end" font-size="11" fill="#ff9a3d">Ø cost ${fm(o.avg)} €</text>`;
    const buyTot = tr.filter(x => x.side === 'buy').reduce((a, x) => a + (x.amount || 0), 0), mk = tr.length > 30 ? tr.filter(x => x.side !== 'buy' || x.amount >= Math.max(20, buyTot * .01)) : tr;
    mk.forEach(x => { const cx = X(Math.max(t0, Math.min(t1, x.t))), cy = Y(x.price), buy = x.side === 'buy', col = buy ? '#5fe3a0' : '#ff6b6b', s = 8;
      g += `<line x1="${cx}" x2="${cx}" y1="${cy}" y2="${T + ih}" stroke="${col}" stroke-dasharray="2 3" opacity=".45"/><path d="${buy ? `M${cx},${cy - s}L${cx + s * .9},${cy + s * .6}L${cx - s * .9},${cy + s * .6}Z` : `M${cx},${cy + s}L${cx + s * .9},${cy - s * .6}L${cx - s * .9},${cy - s * .6}Z`}" fill="${col}" stroke="#02060b" stroke-width="1"><title>${buy ? 'BOUGHT' : 'SOLD'} ${dfull(x.d)}: ${nf0.format(Math.round(x.qty))} × ${nf2.format(x.price)} € = ${eur(x.amount)}</title></path>`; });
    const lp = pts[pts.length - 1]; g += `<circle cx="${X(lp[0])}" cy="${Y(lp[1])}" r="3.5" fill="#fff"/>`;
    el.innerHTML = `<svg width="${W}" height="${H}" style="display:block">${g}<line class="cx" y1="${T}" y2="${T + ih}" stroke="rgba(255,154,61,.8)" style="display:none"/><rect class="hv" x="${L}" y="${T}" width="${iw}" height="${ih}" fill="transparent"/></svg><div class="tip"></div>`;
    const cx = $('.cx', el), tip = $('.tip', el), svg = $('svg', el);
    $('.hv', el).onmousemove = e => { const px = e.clientX - svg.getBoundingClientRect().left, t = t0 + (px - L) / iw * (t1 - t0); let a = 0, b = pts.length - 1; while (b - a > 1) { const m = (a + b) >> 1; if (pts[m][0] < t) a = m; else b = m; } const q = Math.abs(pts[a][0] - t) < Math.abs(pts[b][0] - t) ? pts[a] : pts[b];
      cx.setAttribute('x1', X(q[0])); cx.setAttribute('x2', X(q[0])); cx.style.display = ''; const vs = o.avg ? (q[1] / o.avg - 1) * 100 : null;
      tip.innerHTML = `<div class="or">${dfull(new Date(q[0]).toISOString())}</div><div>Price: <b class="wh">${nf2.format(q[1])} €</b></div>${vs == null ? '' : `<div>vs. your Ø cost: <b class="${cl(vs)}">${pct(vs)}</b></div>`}`; tip.style.display = 'block'; const tw = tip.offsetWidth; let tx = X(q[0]) + 14; if (tx + tw > W) tx = X(q[0]) - tw - 14; tip.style.left = Math.max(0, tx) + 'px'; tip.style.top = '6px'; };
    $('.hv', el).onmouseleave = () => { cx.style.display = 'none'; tip.style.display = 'none'; };
  }
  /* quantities: whole units for securities, up to 6 decimals for coins */
  const qf = (p, v) => p.isCoin ? (v < 1 ? v.toFixed(6).replace('.', ',') : v < 100 ? v.toFixed(4).replace('.', ',') : nf2.format(v)) : nf0.format(Math.round(v));
  function openPos(w, coin) {
    const d = S.D, p = coin || d.depot.positions.find(x => x.wkn === w); if (!p) return;
    modalShell(coin ? 'Crypto position' : 'Position', coin ? badge(coin.status === 'ok' ? 'live' : 'static', 'Coinbase') : p.live ? badge('live', 'Live ' + (p.sym || '')) : badge(d.mode === 'demo' ? 'demo' : 'static', d.mode === 'demo' ? 'Demo' : 'Static · export price'));
    const now = p.price_live || p.price || 0, st = { splits: [], pts: null, range: '5Y', research: null };
    const startMs = p.first_buy ? Date.parse(p.first_buy.slice(0, 10) + 'T00:00:00Z') - 3 * 864e5 : 0, fromBuy = a => a.filter(q => q[0] >= startMs);
    const monthly = () => fromBuy((p.hist || []).map((v, i) => v == null ? null : [Date.UTC(+d.axis[i].slice(0, 4), +d.axis[i].slice(5, 7) - 1, 15), v]).filter(Boolean));
    $('#mbody').innerHTML = `<div class="pp pos"><div class="hdr">${logo(p.isCoin ? 'c:' + p.wkn : p.wkn, p.name, true)}<div><h2>${esc(p.name)}</h2><small>${esc(p.wkn)}${p.sym ? ' · ' + esc(p.sym) : ''} · ${esc(p.cls)} · ${esc(p.theme)}</small></div></div>
      <div class="stats"><div>Quantity<b>${qf(p, p.qty || 0)}</b></div><div>Price now<b>${nf2.format(now)} €</b></div><div>Value<b>${A(p.value)}</b></div><div>Cost basis<b>${A(p.cost)}</b></div><div>P/L<b class="${cl(p.gain)}">${A(p.gain)} (${pct(p.gain_pct)})</b></div><div>Weight<b>${(p.weight || 0).toFixed(1).replace('.', ',')} %</b></div></div>
      <div class="top2"><div><div class="stats" style="margin-bottom:.4rem"><div>Chart</div><div class="leg" id="ppLeg" style="margin-top:.2rem"><span style="cursor:default"><i style="background:#19d3ff"></i>price (EUR)</span><span style="cursor:default"><i style="background:#5fe3a0"></i>▲ your buys</span><span style="cursor:default"><i style="background:#ff6b6b"></i>▼ your sells</span><span style="cursor:default"><i style="background:#ff9a3d"></i>Ø cost</span></div><div id="ppRange" style="display:flex;gap:.3rem;margin-left:auto"></div></div><div class="chartbox" id="ppChart"></div></div>
      <div class="side"><div class="card" id="ppScore"><h4>Meta-score · buy / sell</h4><div class="ld"><span class="spinner"></span>researching online …</div></div><div class="card news" id="ppNews"><h4>Latest company news</h4><div class="ld"><span class="spinner"></span>looking up headlines …</div></div></div></div>
      <div class="card" id="ppCalc"></div></div>`;
    frameAll($('#modal'));
    const draw = () => { const tr = tradesAdj(p, d, st.splits), lc = lotCalc(p, tr), pts = st.pts ? fromBuy(st.pts) : monthly(); const avg = p.qty && p.cost != null ? p.cost / p.qty : null;
      const mo = pts.length ? (Date.now() - pts[0][0]) / 2629800000 : 0, av = rangesFor(mo), rb = $('#ppRange'); if (!av.includes(st.range)) st.range = 'MAX';
      if (rb && rb.dataset.av !== av.join()) { rb.dataset.av = av.join(); rb.innerHTML = av.map(r => `<button data-r="${r}" class="${r === st.range ? 'on' : ''}">${r}</button>`).join(''); $$('#ppRange button').forEach(b => b.onclick = () => { st.range = b.dataset.r; $$('#ppRange button').forEach(x => x.classList.toggle('on', x === b)); draw(); }); }
      posChart($('#ppChart'), { pts, trades: tr, avg, range: st.range }); const lcs = lc; const cd = $('#ppCalc'); for (const mn of [0, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 1e4]) { cd.innerHTML = calcHTML(p, d, tr, lcs, now, { min: mn }); if (cd.scrollHeight <= cd.clientHeight + 1 || lcs.open.length < 4) break; } };
    const rO = new ResizeObserver(() => { if ($('#ppChart')) draw(); }); rO.observe($('#ppChart'));
    $$('#ppRange button').forEach(b => b.onclick = () => { st.range = b.dataset.r; $$('#ppRange button').forEach(x => x.classList.toggle('on', x === b)); draw(); });
    draw();
    if (d.mode === 'demo' && window.demoResearch) { const r = window.demoResearch(p); st.research = r; scoreHTML(p, r, d); newsHTML(r); return; }   // demo: canned EXAMPLE research, never call the server
    if (!server) { $('#ppScore').innerHTML = '<h4>Meta-score · buy / sell</h4><div class="ld">Live research needs the local server: open WealthView from its desktop icon.</div>'; $('#ppNews').innerHTML = '<h4>Latest company news</h4><div class="ld">Needs the local server (desktop icon).</div>'; return; }
    api('/api/research?sym=' + encodeURIComponent(p.sym || '') + '&name=' + encodeURIComponent(p.name || '') + '&wkn=' + encodeURIComponent(p.wkn || '')).then(r => {   // api() sends the token and re-locks the page on a 401
      if (!$('#ppChart')) return; st.research = r;
      if (r.ok && r.prices && r.prices.length) {   // daily closes (EUR). Align the last point with the live quote used everywhere else
        st.pts = r.prices.map(q => [q[0] * 1000, q[1]]); st.splits = r.splits || []; }
      draw(); scoreHTML(p, r, d); newsHTML(r);
    }).catch(e => { if (e.locked) { toDemo(); lockModal(); return; } if (!$('#ppScore')) return; $('#ppScore').innerHTML = '<h4>Meta-score · buy / sell</h4><div class="ld or">Could not reach the research source: ' + esc(e.message) + '</div>'; $('#ppNews').innerHTML = '<h4>Latest company news</h4><div class="ld or">Not available right now.</div>'; });
  }
  function scoreHTML(p, r, d) {
    const el = $('#ppScore'); if (!el) return; const s = r.score;
    if (!r.ok || !s) { el.innerHTML = '<h4>Meta-score · buy / sell</h4><div class="ld">' + esc((r.notes || []).join(' ') || r.error || 'Not enough online data for this security (funds without a listing cannot be scored).') + '</div>'; return; }
    const col = scoreCol(s.total), gauge = `<svg class="gauge" viewBox="0 0 100 60" style="width:7rem;height:auto"><path d="M10,54 A40,40 0 0 1 90,54" fill="none" stroke="rgba(60,190,235,.2)" stroke-width="9"/><path d="M10,54 A40,40 0 0 1 90,54" fill="none" stroke="${col}" stroke-width="9" pathLength="100" stroke-dasharray="${s.total} 100" style="filter:drop-shadow(0 0 3px ${col})"/><text x="50" y="50" text-anchor="middle" font-size="22" fill="#fff">${s.total}</text></svg>`;
    const conc = (p.weight || 0) >= 15 ? `<div class="note" style="color:var(--or);margin-top:.4rem">This position is already ${(p.weight || 0).toFixed(0)} % of your depot: even a good score does not justify adding more without raising concentration risk.</div>` : '';
    el.innerHTML = `<h4>Meta-score · buy / sell</h4><div class="score">${gauge}<div><div class="verdict" style="color:${col};text-shadow:0 0 .6rem ${col}">${s.verdict}</div><div class="note">0 = sell · 100 = buy<br>${r.demo ? badge('demo', 'EXAMPLE') + ' invented sample values' : esc(r.sym || '') + ' · live ' + new Date(r.t * 1000).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}</div></div></div>
      <div style="margin-top:.4rem">${s.factors.map(f => `<div class="fac"><span>${esc(f.name)} <span class="dim">· ${esc(f.text)}</span></span><b class="wh">${f.pts}/${f.max}</b><span class="bar"><i style="width:${f.pts / f.max * 100}%;background:${scoreCol(f.pts / f.max * 100)}"></i></span></div>`).join('')}</div>${conc}
      <div class="note" style="margin-top:.4rem">Rule-based mix of trend, momentum, RSI, 52-week range, analyst consensus / price target and headline tone from ${r.demo ? 'invented EXAMPLE values' : 'live sources'} (${s.coverage} of 100 points available). Education, not investment advice.</div>`;
  }
  function newsHTML(r) {
    const el = $('#ppNews'); if (!el) return; const n = r.news || [];
    el.innerHTML = '<h4>Latest company news' + (r.demo ? ' ' + badge('demo', 'EXAMPLE') : '') + '</h4>' + (n.length ? n.map(x => `<div class="it">${x.demo ? '<span>' + esc(x.title) + '</span>' : safeUrl(x.url) ? `<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>` : '<span>' + esc(x.title) + '</span>'}<small><span class="${x.sent > 0 ? 'pos' : x.sent < 0 ? 'neg' : 'dim'}" style="margin-right:.3rem">●</span>${esc(x.publisher || '')} · ${esc(ago(x.t))}</small></div>`).join('') : '<div class="ld">No recent headlines found.</div>');
  }
  function calcHTML(p, d, tr, lc, now, o) {
    o = o || {};
    const row = (a, b, c, e, f, g, h, i, j, k) => `<tr><td>${a}</td><td>${b}</td><td>${c}</td><td>${e}</td><td>${f}</td><td>${g}</td><td class="${cl(h)}">${h == null ? '–' : eur(h)}</td><td class="${cl(i)}">${pct(i)}</td><td>${j}</td><td class="${cl(k)}">${k == null ? '–' : pct(k, 0)}</td></tr>`;
    const small = o.min ? lc.open.filter(l => l.cost < o.min) : [], bigL = o.min ? lc.open.filter(l => l.cost >= o.min) : lc.open;
    let body = ''; if (small.length > 1) { const q = small.reduce((a, l) => a + l.rem, 0), c = small.reduce((a, l) => a + l.cost, 0), v = small.reduce((a, l) => a + l.val, 0); body += row('<span class="dim">' + small.length + ' small purchases (each under ' + nf0.format(o.min) + ' €, e.g. rewards)</span>', 'Buy', qf(p, q), q ? nf2.format(c / q) + ' € <span class="dim">Ø</span>' : '–', A(c), A(v), v - c, c ? (v / c - 1) * 100 : null, 'Ø ' + Math.round(small.reduce((a, l) => a + l.days * l.cost, 0) / (c || 1)) + ' d', null); } else bigL.splice(0, 0, ...small);
    body += bigL.map(l => row(dfull(l.d), 'Buy', qf(p, l.rem) + (l.rem < l.qty - (p.isCoin ? 1e-9 : .5) ? ' <span class="dim">of ' + qf(p, l.qty) + '</span>' : ''), nf2.format(l.price) + ' €', A(l.cost), A(l.val), l.g, l.gp, Math.round(l.days) + ' d', l.pa)).join('');
    if (lc.early) body += row((p.isCoin ? '<span class="dim">received earlier / no dated purchase</span>' : '<span class="dim">before ' + dfull(d.depot.trades_from || '') + ' / not in bookings</span>'), 'Buy', qf(p, lc.early.qty), lc.early.qty && lc.early.cost != null ? nf2.format(lc.early.cost / lc.early.qty) + ' € <span class="dim">Ø</span>' : '–', A(lc.early.cost), A(lc.early.val), lc.early.g, lc.early.gp, '–', null);
    body += lc.sells.map(s => `<tr><td>${dfull(s.d)}</td><td>Sell</td><td>${qf(p, s.qty)}</td><td>${nf2.format(s.price)} €</td><td colspan="2" class="dim">proceeds ${A(s.amount)}</td><td colspan="4" class="dim"></td></tr>`).join('');
    const tot = row('<b>Total</b>', '', qf(p, p.qty || 0), p.qty && p.cost != null ? nf2.format(p.cost / p.qty) + ' € <span class="dim">Ø</span>' : '–', A(p.cost), A(p.value), p.gain, p.gain_pct, lc.open.length ? 'Ø ' + Math.round(lc.open.reduce((a, l) => a + l.days * l.cost, 0) / (lc.kc || 1)) + ' d' : '–', lc.irr);
    const be = p.qty && p.cost != null ? p.cost / p.qty : null, dist = be ? (now / be - 1) * 100 : null;
    const nodata = !lc.open.length && !tr.length;
    return `<h4>Your purchases · calculation from actual purchase dates</h4><div style="overflow:hidden"><table><thead><tr><th>Date</th><th>Type</th><th>Qty</th><th>Price</th><th>Cost</th><th>Value now</th><th>Gain</th><th>Gain %</th><th>Held</th><th>p.a.</th></tr></thead><tbody>${body}<tr class="tot">${tot.replace(/^<tr>/, '').replace(/<\/tr>$/, '')}</tr></tbody></table></div>
      <div class="note" style="margin-top:.4rem">${p.isCoin ? (nodata ? 'No dated purchase of this coin was found in your Coinbase trade history, so the cost is unknown.' : 'Dated rows come from your Coinbase trade history (buys, converts and staking rewards at their value when received); sells use first-in-first-out. Cost is the EUR value Coinbase reports for each trade.') + (lc.early ? ' Part of the balance has no purchase date (e.g. sent in from elsewhere) and is shown with unknown cost.' : '') : nodata ? 'No purchase of this security appears in your GLS bookings' + (d.depot.trades_from ? ' since ' + dfull(d.depot.trades_from) : '') + ', so it was bought earlier or elsewhere. Cost and gain come from the depot export.' : 'Dated rows come from the "Wertpapierabrechnung" bookings in your GLS exports' + (d.depot.trades_from ? ' (bank data starts ' + dfull(d.depot.trades_from) + ')' : '') + ': cost includes fees, sells use first-in-first-out, split-adjusted. ' + (d.mode === 'demo' ? 'Demo: invented purchases. ' : '')}${lc.mismatch ? ' Note: more units were sold than the bookings explain.' : ''}</div>
      <div class="stats" style="margin-top:.5rem"><div>Break-even price<b>${be ? nf2.format(be) + ' €' : '–'}</b></div><div>Price vs. break-even<b class="${cl(dist)}">${pct(dist)}</b></div><div>Annualised return (dated buys, IRR)<b class="${cl(lc.irr)}">${lc.irr == null ? '–' : pct(lc.irr, 0)}</b></div><div>Dated lots cover<b>${p.qty ? Math.round((lc.kq / p.qty) * 100) : 0} % of units</b></div></div>`;
  }
  /* ===== HEATMAP: TradingView-style treemap. Block size = value, colour = change (red - grey - green), grouped like sectors ===== */
  let HEATCTX = null;      /* set while a heatmap is drawn INSIDE a dashboard box or an open window instead of a separate popup */
  const heatCol = (c, sc) => { const N = [18, 52, 72], G = [38, 170, 125], R = [200, 70, 78], D = [4, 18, 28]; let m = N; if (c != null && !isNaN(c)) { const t = Math.max(-1, Math.min(1, c / sc)); m = t >= 0 ? mixc(N, G, t) : mixc(N, R, -t); } return `linear-gradient(160deg,rgb(${m.join(',')}),rgb(${mixc(m, D, .5).join(',')}))`; };
  function squarify(items, x, y, w, h) {   // items: [{v,...}] sorted desc -> [{item,x,y,w,h}]
    const out = [], tot = items.reduce((s, i) => s + i.v, 0); if (!tot || w <= 0 || h <= 0) return out;
    let arr = items.map(i => ({ i, a: i.v / tot * w * h })), R = { x, y, w, h };
    const worst = (row, sum, side) => { const mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a)); return Math.max(side * side * mx / (sum * sum), sum * sum / (side * side * mn)); };
    while (arr.length) {
      const side = Math.min(R.w, R.h); let row = [arr[0]], sum = arr[0].a, wr = worst(row, sum, side), k = 1;
      while (k < arr.length) { const nr = row.concat([arr[k]]), ns = sum + arr[k].a, nw = worst(nr, ns, side); if (nw <= wr) { row = nr; sum = ns; wr = nw; k++; } else break; }
      const th = sum / side; let cx = R.x, cy = R.y;
      if (R.w >= R.h) { row.forEach(r => { const hh = r.a / th; out.push({ item: r.i, x: R.x, y: cy, w: th, h: hh }); cy += hh; }); R = { x: R.x + th, y: R.y, w: R.w - th, h: R.h }; }
      else { row.forEach(r => { const ww = r.a / th; out.push({ item: r.i, x: cx, y: R.y, w: ww, h: th }); cx += ww; }); R = { x: R.x, y: R.y + th, w: R.w, h: R.h - th }; }
      arr = arr.slice(row.length);
    }
    return out;
  }
  /* o = {title, badge, metrics:[{k,label,scale}], groupings?:[{k,label}], build(metric, grouping) -> {groups:[{name,items:[{id,label,size,chg,tip}]}], note?}, click?(id)} */
  function openHeat(o) {
    const cx = HEATCTX; let root, tools = null;
    if (cx) { root = cx.root; tools = cx.tools || null; } else { modalShell(o.title + ' · heatmap', o.badge); root = $('#mbody'); tools = $('#mtools'); }
    const own = !tools; root.innerHTML = (own ? '<div class="htools"></div>' : '') + '<div class="heat fill"></div><div class="hleg"></div><div class="xs dim hnote"></div>';
    if (own) tools = $('.htools', root); const hm = $('.heat', root), hl = $('.hleg', root), hn = $('.hnote', root), st = { m: o.metrics[0].k, g: o.groupings ? o.groupings[0].k : null };
    if (root.closest('#modal')) frameAll($('#modal'));
    const back = cx && cx.tools && cx.back ? '<button class="hmb on" data-back="1">◧ Chart</button><span class="sep"></span>' : '';
    const bar = () => { tools.innerHTML = back + (o.metrics.length > 1 ? o.metrics.map(m => `<button data-m="${m.k}" class="${st.m === m.k ? 'on' : ''}">${esc(m.label)}</button>`).join('') : '') + (o.groupings ? '<span class="sep"></span><span class="xs dim">group by</span>' + o.groupings.map(g => `<button data-g="${g.k}" class="${st.g === g.k ? 'on' : ''}">${esc(g.label)}</button>`).join('') : '');
      $$('button', tools).forEach(b => b.onclick = e => { e.stopPropagation(); if (b.dataset.back) return cx.back(); if (b.dataset.m) st.m = b.dataset.m; if (b.dataset.g) st.g = b.dataset.g; bar(); draw(); }); };
    const draw = () => {
      const W = hm.clientWidth, H = hm.clientHeight; if (W < 80 || H < 60) return; const mt = o.metrics.find(m => m.k === st.m), data = o.build(st.m, st.g); let h = '';
      const gs = data.groups.map(g => ({ name: g.name, items: g.items.filter(i => i.size > 0).sort((a, b) => b.size - a.size), v: g.items.reduce((s, i) => s + Math.max(0, i.size), 0) })).filter(g => g.v > 0).sort((a, b) => b.v - a.v);
      const single = gs.length === 1 && !gs[0].name, HEAD = single ? 0 : 20;
      squarify(gs.map(g => Object.assign({ v: g.v }, { g })), 0, 0, W, H).forEach(r => {
        const g = r.item.g, gx = r.x + 1, gy = r.y + 1, gw = r.w - 2, gh = r.h - 2; if (gw < 4 || gh < 4) return;
        if (!single) h += `<div class="hg" style="left:${gx}px;top:${gy}px;width:${gw}px">${esc(g.name)}</div>`;
        squarify(g.items.map(i => Object.assign({ v: i.size }, { it: i })), gx, gy + HEAD, gw, gh - HEAD).forEach(b => {
          const it = b.item.it, w = b.w, hh = b.h, col = heatCol(it.chg == null ? null : (mt.invert ? -it.chg : it.chg), mt.scale), fs = Math.max(8, Math.min(26, w / Math.max(4, it.label.length * .62), hh / 3.1)), show = w > 36 && hh > 24;
          h += `<div class="hb" data-id="${esc(it.id)}" title="${esc(it.tip || it.label)}" style="left:${b.x.toFixed(1)}px;top:${b.y.toFixed(1)}px;width:${w.toFixed(1)}px;height:${hh.toFixed(1)}px;background:${col}">${show ? `<b style="font-size:${fs.toFixed(1)}px">${esc(it.label)}</b><span style="font-size:${Math.max(8, fs * .82).toFixed(1)}px">${it.chg == null ? '–' : pct(it.chg, Math.abs(it.chg) < 10 ? 1 : 0)}</span>${hh > 70 && w > 90 && it.sub ? `<small style="font-size:${Math.max(8, fs * .62).toFixed(1)}px">${it.sub}</small>` : ''}` : ''}</div>`;
        });
      });
      hm.innerHTML = h; $$('.hb', hm).forEach(b => b.onclick = e => { e.stopPropagation(); if (o.click) o.click(b.dataset.id); });
      hl.innerHTML = `<span class="xs dim">${esc(mt.label)}:</span><span class="xs dim">${mt.invert ? '+' : '−'}${mt.scale} %</span><i class="hgr"></i><span class="xs dim">${mt.invert ? '−' : '+'}${mt.scale} %</span><span class="xs dim" style="margin-left:1.2rem">block size = ${esc(o.sizeLabel || 'value')}</span>`;
      hn.textContent = data.note || '';
    };
    new ResizeObserver(() => draw()).observe(hm); bar(); draw();
  }
  const chgOf = (hist, now, n) => { if (!hist || !now) return null; const b = hist[hist.length - 1 - n]; return b ? (now / b - 1) * 100 : null; };
  function heatSec() {
    const d = S.D, ps = d.depot.positions;
    openHeat({ title: 'Securities', badge: srcBadge('depot', d), sizeLabel: 'current value', click: id => openPos(id),
      metrics: [{ k: 'pl', label: 'Since purchase', scale: 60 }, { k: 'm12', label: '12 months', scale: 40 }, { k: 'm3', label: '3 months', scale: 20 }, { k: 'm1', label: '1 month', scale: 10 }],
      groupings: [{ k: 'theme', label: 'Theme' }, { k: 'cls', label: 'Type' }],
      build: (m, g) => { const by = {}; ps.forEach(p => { const now = p.price_live || p.price, c = m === 'pl' ? p.gain_pct : chgOf(p.hist, now, m === 'm12' ? 12 : m === 'm3' ? 3 : 1), k = (g === 'cls' ? p.cls : p.theme) || 'Other'; (by[k] = by[k] || []).push({ id: p.wkn, label: p.name.replace(/\s*\(ADR\)/i, ''), size: p.value, chg: c, sub: A(p.value), tip: `${p.name}: ${eur(p.value)} · ${pct(c)}` }); });
        return { groups: Object.keys(by).map(k => ({ name: k, items: by[k] })), note: m === 'pl' ? 'Colour = gain/loss against your cost basis (depot export).' : 'Colour = price change over the period (monthly closes; positions without a live quote are grey).' }; } });
  }
  function heatCrypto() {
    const d = S.D, hs = d.crypto.holdings;
    openHeat({ title: 'Crypto', badge: srcBadge('coinbase', d), sizeLabel: 'current value',
      metrics: [{ k: 'p', label: 'Since purchase', scale: 80 }, { k: '12', label: '12 months', scale: 80 }, { k: '3', label: '3 months', scale: 40 }, { k: '1', label: '1 month', scale: 20 }],
      build: m => ({ groups: [{ name: '', items: hs.map(h => ({ id: h.currency, label: h.currency, size: h.amount * h.price, chg: m === 'p' ? h.gain_pct : chgOf(h.hist, h.price, +m), sub: A(h.amount * h.price), tip: `${h.name}: ${eur(h.amount * h.price)}` })) }] }) });
  }
  function heatClasses() {
    const d = S.D, v = classValues(d);
    openHeat({ title: 'Asset classes', badge: badge(d.mode === 'demo' ? 'demo' : 'model', d.mode === 'demo' ? 'Demo' : 'Back-cast + actual'), sizeLabel: 'current value',
      metrics: [{ k: '12', label: '12 months', scale: 30 }],
      build: () => ({ groups: [{ name: '', items: CLS.map(k => ({ id: k, label: k, size: v[k], chg: chg12(d, k), sub: A(v[k]), tip: `${k}: ${eur(v[k])}` })) }], note: 'Securities / crypto / real estate use back-cast values (today\'s holdings at past prices).' }), click: k => { closeModal(); openClass(k); } });
  }
  function heatSpend() {
    const d = S.D, f = d.flows; if (!f) return;
    const sum = (a, i, j) => a.slice(i, j).reduce((x, y) => x + y, 0);
    openHeat({ title: 'Spending by category', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), sizeLabel: 'spending, last 12 months',
      metrics: [{ k: 'vs', label: 'vs. previous 12 months', scale: 50, invert: true }],
      build: () => ({ groups: [{ name: '', items: Object.keys(f.cats).map(k => { const a = f.cats[k], cur = sum(a, -13, -1), prev = f.months.length >= 25 ? sum(a, -25, -13) : null; return { id: k, label: k, size: cur, chg: prev ? (cur / prev - 1) * 100 : null, sub: A(cur), tip: `${k}: ${eur(cur)} (last 12 months)` }; }) }], note: 'Colour = change against the 12 months before: red = you spent more, green = you spent less.' }) });
  }
  function heatTop() {
    const d = S.D, f = d.flows; if (!f || !f.top_spenders) return; const per = S.topPer || 'y1', list = f.top_spenders[per] || [], sum = (a, i, j) => a.slice(i, j).reduce((x, y) => x + y, 0);
    openHeat({ title: 'Top pay', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), sizeLabel: per === 'y1' ? 'paid in the last 12 months' : 'paid in total',
      metrics: [{ k: 'vs', label: 'last 12 m vs. previous 12 m', scale: 60, invert: true }],
      build: () => { const by = {}; list.forEach(m => { const a = m.m, cur = a ? sum(a, -13, -1) : null, prev = a && a.length >= 25 ? sum(a, -25, -13) : null; (by[m.cat || 'Other'] = by[m.cat || 'Other'] || []).push({ id: m.n, label: m.n, size: m.v, chg: prev ? (cur / prev - 1) * 100 : null, sub: A(m.v), tip: `${m.n}: ${eur(m.v)}` }); });
        return { groups: Object.keys(by).map(k => ({ name: k, items: by[k] })), note: 'Colour = change in what you paid this company vs. the 12 months before: red = more, green = less. Grey = not enough history.' }; }, click: n => { const m = list.find(x => x.n === n); if (m) { closeModal(); openMerchant(m); } } });
  }
  function heatWF() {
    const d = S.D, w = d.examplefund; if (!w) return;
    openHeat({ title: fundTitle(d) + ' portfolio', badge: srcBadge('examplefund', d), sizeLabel: 'fair value',
      metrics: [{ k: 'moic', label: 'MOIC vs. cost', scale: 100 }],
      build: () => { const by = {}; w.companies.forEach(c => { (by[c.industry || 'Other'] = by[c.industry || 'Other'] || []).push({ id: c.name, label: c.name, size: c.fair_value, chg: (c.moic - 1) * 100, sub: A(c.fair_value), tip: `${c.name}: ${eur(c.fair_value)} · ${c.moic.toFixed(2)}x` }); });
        return { groups: Object.keys(by).map(k => ({ name: k, items: by[k] })) }; } });
  }
  function openCrypto() { const d = S.D; openTS({ heat: heatCrypto, title: 'Crypto development (current holdings, historical prices)', stacked: true, badge: srcBadge('coinbase', d), make: () => cryptoRaw(d) }); }
  /* coin pop-up = the securities pop-up with the coin's own data: price history from the first purchase, buy/sell markers, lots table, gain vs. cost, meta-score and news */
  function openCoin(c) {
    const d = S.D, h = d.crypto.holdings.find(x => x.currency === c); if (!h) return;
    const tot = d.crypto.holdings.reduce((a, x) => a + x.amount * x.price, 0), val = h.amount * h.price;
    const trades = (h.trades || []).filter(t => ['buy', 'sell', 'out'].includes(t.side)).map(t => ({ d: String(t.date).slice(0, 10), side: t.side === 'out' ? 'sell' : t.side, qty: t.qty, price: t.price, amount: t.qty * t.price }));
    openPos(null, { isCoin: true, status: d.crypto.trades_status, wkn: h.currency, name: h.name || h.currency, sym: h.currency + '-EUR', cls: 'Crypto', theme: 'Crypto', qty: h.amount, price: h.price, price_live: h.price, value: val,
      cost: h.cost, gain: h.gain, gain_pct: h.gain_pct, first_buy: h.first_buy, weight: tot ? val / tot * 100 : 0, hist: h.hist, trades, live: false });
  }
  function openApt() {
    const d = S.D, ap = d.apartment; if (!ap) return; openTS({ title: `${ap.address} · value over the years`, badge: d.mode === 'demo' ? badge('demo', 'Demo') : badge('model', 'Model · benchmark'), type: 'area', make: () => aptRaw(d),
      extra: () => `<div class="stats"><div>Bought<b>${A(ap.purchase_price)}</b></div><div>Estimate now<b>${A(ap.value_used)}</b></div><div>Increase<b class="${cl(ap.gain)}">${A(ap.gain)} (${pct(ap.gain_pct)})</b></div></div><p class="xs dim">How this is estimated: your purchase price is moved along the yearly average apartment price per sqm of the benchmark (${esc(ap.benchmark_name)}), interpolated month by month. ${ap.benchmark ? 'Yearly benchmark values: ' + Object.entries(ap.benchmark).map(([y, v]) => y + ': ' + nf0.format(v) + ' €/sqm').join(' · ') + '. ' : ''}It is a market-level estimate, not a valuation of your flat: condition, floor, view and building matter. <a href="${esc(safeUrl(ap.benchmark_source))}" target="_blank" rel="noopener">Source ↗</a></p>` });
  }
  function openAcct(title, defs) { const d = S.D; openTS({ title: title + ' · balance history', badge: srcBadge('gls', d), type: 'line', make: () => acctRaw(d, defs) }); }
  function openFlow() { const d = S.D; openTS({ title: 'Income, expenses and savings', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), type: 'bar', make: () => flowRaw(d), extra: () => `<p class="xs dim">Internal transfers, credit-card settlements and securities purchases are not counted as spending. Items of ${nf0.format(d.flows.oneoff_threshold)} € or more are treated as one-offs and shown separately.</p>` }); }
  function openSpend() { const d = S.D; openTS({ heat: heatSpend, title: 'Spending by category · monthly', stacked: true, type: 'bar', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), make: () => spendRaw(d), extra: () => `<p class="xs dim">Categories come from WealthView's own rules (keywords in payee and purpose). Click a category on the dashboard for its merchants. Add your own rules in config.json → category_rules.</p>` }); }
  function openCat(c) { const d = S.D, tm = (d.flows.top_merchants || {})[c] || []; openTS({ title: 'Category: ' + c, type: 'bar', badge: d.mode === 'demo' ? badge('demo', 'Demo') : srcBadge('gls', d), make: () => spendRaw(d, c), extra: () => `<div class="xs dim" style="letter-spacing:.12em">TOP PAYEES · LAST 12 MONTHS</div>` + (tm.length ? tm.map(m => `<div class="tr" style="grid-template-columns:1fr auto;cursor:default"><span>${esc(m.n)}</span><span class="r wh">${A(m.v)}</span></div>`).join('') : '<div class="dim sm">–</div>') }); }
  function openCompany(slug) { const w = S.D.examplefund, c = w && w.companies.find(x => x.slug === slug); if (c && window.WVA) WVA.companyModal(c, { fund: w }); }
  function openWF() {
    const d = S.D, w = d.examplefund, lg = window.WF_LOGOS || {}, inds = [...new Set(w.companies.map(c => c.industry))].sort(); let ind = 'ALL', sort = 'fair_value';
    const html = () => { const cs = w.companies.filter(c => ind === 'ALL' || c.industry === ind).sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : (b[sort] - a[sort])); return cs.map(c => `<div class="cc" data-slug="${esc(c.slug)}" title="Click for details"><div class="top"><div class="lgw">${lg[c.slug] ? `<img src="${lg[c.slug]}" alt="">` : ''}</div><div><h5>${esc(c.name)}</h5><span class="chip">${esc(c.industry)}</span><span class="chip" style="border-color:rgba(255,154,61,.5);color:var(--or)">${esc(c.sector)}</span></div></div><p class="bl">${esc(c.blurb)}</p><div class="ft"><span>${esc(c.country)} · since ${esc(c.since)} · <b class="${c.moic >= 1 ? 'pos' : 'neg'}">${c.moic.toFixed(2).replace('.', ',')}x</b> · your look-through <b class="wh amt">${eur(c.look_through)}</b></span><a class="lk" href="${esc(c.web || w.portfolio_url)}" target="_blank" rel="noopener">${c.web ? 'Website' : 'Example Fund'} ↗</a></div></div>`).join(''); };
    const b = infoModal(`${esc(fundTitle(d))} · all ${w.companies.length} portfolio companies`, `<div class="stats"><div>Fund NAV<b>${kfmt(w.fund.nav)} €</b></div><div>Fund TVPI<b>${w.fund.tvpi.toFixed(2).replace('.', ',')}x</b></div><div>Net IRR<b class="${cl(w.fund.net_irr)}">${pct(w.fund.net_irr)}</b></div><div>Portfolio MOIC<b>${w.fund.portfolio_moic.toFixed(2).replace('.', ',')}x</b></div><div>Your share<b>${(w.personal.ownership_pct || 0).toFixed(4).replace('.', ',')} %</b></div><div>Report<b style="font-size:0.96rem">${esc(d.mode === 'demo' ? 'Q2 2026 (EXAMPLE numbers)' : 'Q' + w.report_q + ' ' + w.report_year)}</b></div></div><div class="tools" style="padding:0" id="wft"></div><div class="wfg" id="wfg"></div><p class="xs dim">Descriptions are short summaries from public sources; "look-through" = your share of the fund times the fair value of each company (fund-level numbers, not what you could sell). Where no company website was verified, the link goes to the Example Fund portfolio page.</p>`, srcBadge('examplefund', d));
    const bar = () => { $('#wft').innerHTML = ['ALL', ...inds].map(i => `<button data-i="${esc(i)}" class="${ind === i ? 'on' : ''}">${esc(i)}</button>`).join('') + '<span class="sep"></span>' + [['fair_value', 'Size'], ['moic', 'MOIC'], ['name', 'A-Z']].map(([k, l]) => `<button data-s="${k}" class="${sort === k ? 'on' : ''}">Sort: ${l}</button>`).join(''); $$('#wft button').forEach(x => x.onclick = () => { if (x.dataset.i) ind = x.dataset.i; if (x.dataset.s) sort = x.dataset.s; bar(); paint(); }); };
    const paint = () => { $('#wfg').innerHTML = html(); fitWfg(); $$('#wfg .cc').forEach(x => x.onclick = e => { if (e.target.closest('a')) return; openCompany(x.dataset.slug); }); };
    bar(); paint();
    const mb = $('#mbody'); const ro = new ResizeObserver(() => { if ($('#wfg')) fitWfg(); else ro.disconnect(); }); ro.observe(mb);
  }
  /* "Open portfolio": the cards are laid out in 4 rows (fewer when there are fewer companies); the columns follow from that and the window grows
     only as tall as the cards need - nothing scrolls, nothing is left empty. Narrow cells drop the text and keep logo + name. */
  const WFG_ROWS = 4;
  function wfgLayout(n, W) {     /* pure: -> { cols, rows, cw, ch, mode, gap } */
    const cols = n <= 3 ? Math.max(1, n) : Math.ceil(n / WFG_ROWS), rows = Math.ceil(n / cols), gap = 10, cw = Math.max(40, (W - gap * (cols - 1)) / cols);
    const mode = cw >= 330 ? 'full' : cw >= 170 ? 'mid' : 'sm', ch = mode === 'full' ? 150 : mode === 'mid' ? Math.max(96, cw * .62) : Math.max(78, cw * .8);
    return { cols, rows, cw, ch, mode, gap };
  }
  function fitWfg() {
    const g = $('#wfg'), n = g ? g.children.length : 0; if (!n) return;
    const W = g.clientWidth; if (W < 120) return; const L = wfgLayout(n, W);
    g.style.gridTemplateColumns = 'repeat(' + L.cols + ',minmax(0,1fr))'; g.style.gridTemplateRows = 'repeat(' + L.rows + ',' + Math.round(L.ch) + 'px)'; g.style.gap = L.gap + 'px'; g.style.overflow = 'visible'; g.dataset.mode = L.mode;
  }

  /* ================================================== render */
  function gapChip(d) {
    const g = (d.alerts || []).filter(a => /DATA GAP/.test(a.text)), c = $('#gapChip'); if (!c) return;
    c.style.display = g.length ? 'inline-block' : 'none'; c.textContent = '▲ DATA GAP' + (g.length > 1 ? ' ×' + g.length : ''); c.onclick = () => infoModal('Data gaps in your downloads', g.map(a => `<div class="tr" style="cursor:default"><span class="or">▲ ${esc(a.text)}</span></div>`).join('') + '<p class="xs dim">Download a fresh export from the bank (Umsätze CSV) or depot and save it in the same folder, then press Refresh data.</p>');
  }
  function renderAll() {
    const d = S.D; POST.length = 0; d.mode = S.mode;
    CLS.forEach(k => { const a = d.nw[k]; if (a) { const v = classValues(d)[k]; if (a[a.length - 1] != null) a[a.length - 1] = v; } });
    /* which boxes appear comes from layout.js (profile + screen); each box id maps to its panel builder. Builders run in the v1.15 column order (c1, c2, center, c4, c5). */
    const BUILD = {
      depot: pDepot, alloc: pAlloc, top: pTop, spend: pSpend, flow: pFlow,
      ring: d => `<div id="ringWrap" style="height:43.4rem;flex:none">${ringHTML(d)}${wings(d)}</div><div class="kpis" id="kpiRow" style="grid-template-columns:${kpiCols(d)}">${kpiRow(d)}</div>`,
      gross: pGross, time: d => (window.WVI && WVI.pTime(d)) || '', map: pMap,
      examplefund: pWF, crypto: pCB, alt: pAlt, typed: pTyped, sources: pSrc, tips: pTips, unusual: d => (window.WVA && WVA.pUnusual(d)) || '', recent: pRecent,
      empty: d => panel('pEmpty', 'Nothing to show yet', '', '<div class="empty">No asset classes are set up in this installation. Press Setup at the top to add your banks, investments and crypto, or to type in a house, a loan or a fund.</div>', { style: 'flex:1' })
    };
    const prof = S.profile || (window.WVL && WVL.LEGACY), vp = { w: window.innerWidth, h: window.innerHeight };
    /* layout.js missing or broken: fall back to the fixed v1.15 columns so the page still renders */
    const V115 = [{ dom: '#c5', boxes: ['sources', 'tips', 'unusual', 'recent'] }, { dom: '#c2', boxes: ['top', 'spend', 'flow'] }, { dom: '#center', boxes: ['ring', 'gross', 'time', 'map'] }, { dom: '#c1', boxes: ['depot', 'alloc'] }, { dom: '#c4', boxes: ['examplefund', 'crypto', 'alt'] }];
    const lay = window.WVL ? WVL.place(prof, vp) : V115, picked = window.WVL ? WVL.pickBoxes(prof, vp) : ['chat'];
    document.body.classList.toggle('nochat', !picked.includes('chat'));
    const chatEl = $('#chat'); if (chatEl && chatEl.remove) chatEl.remove();         /* the ask bar lives inside #center on wide screens: keep it (and what was typed) across the redraw */
    ['#c1', '#c2', '#center', '#c4', '#c5'].forEach(c => { const col = lay.find(x => x.dom === c); $(c).innerHTML = col ? col.boxes.map(id => (BUILD[id] || (() => ''))(d)).join('') : ''; });
    if (chatEl && chatEl.remove) { document.body.appendChild(chatEl); if (window.WVI && WVI.place) WVI.place(); }
    frameAll(); POST.forEach(f => { try { f(); } catch (e) { console.error(e); } }); layoutCenter();
    if (window.WVA) try {
      const T = (sel, txt) => { if (txt) $$(sel).forEach(e => e.title = txt); };
      T('#ringBox', WVA.rollover('ring', d));
      CLS.forEach(k => { const tx = WVA.rollover('class', d, k); T('.wing.l .w[data-k="' + k + '"]', tx); T('#kpiRow .kp[data-k="' + k + '"]', tx); });
      T('#pDepot .kpis', WVA.rollover('securities', d)); T('#pCB .kpis', WVA.rollover('crypto', d)); T('#pWF .kpis', WVA.rollover('wf', d)); T('#kpiRow .kp[data-k="run"]', WVA.rollover('cash', d));
    } catch (e) { console.error(e); }
    $$('#ringSvg .seg').forEach(p => p.onclick = () => openClass(p.dataset.k));
    $$('.wing .w').forEach(w => w.onclick = () => openClass(w.dataset.k));
    $$('#kpiRow .kp').forEach(k => k.onclick = () => openClass(k.dataset.k));
    $$('.dseg').forEach(() => 0); const nl = $('#netLine'); if (nl) nl.onclick = openNet; gapChip(d); updChip(d);
    fitRing(); setHdrRanges(d); setStatus(); lockBtn(); $$('#ctl [data-r]').forEach(b => b.classList.toggle('on', b.dataset.r === S.range)); $('#bGran').textContent = S.gran === 'M' ? 'Monthly' : 'Yearly';
  }
  function setHdrRanges(d) {
    const mo = Math.max(...CLS.map(k => d.nw[k] ? d.axis.length - firstIdx(d.nw[k]) : 0)), av = rangesFor(mo);
    if (!av.includes(S.range)) S.range = 'MAX';
    $$('#ctl [data-r]').forEach(b => { b.style.display = av.includes(b.dataset.r) ? '' : 'none'; });
  }
  /* header light = what the dashboard REALLY received: green = server answered recently, amber = nothing received for > 12 min, red = server not reachable */
  const dotState = () => S.rxErr && (!S.rxAt || S.rxErr > S.rxAt) ? 'err' : !S.rxAt ? 'stale' : Date.now() - S.rxAt > 12 * 60000 ? 'stale' : 'live' + (Date.now() - (S.rxFlash || 0) < 900 ? ' flash' : '');
  const dotTitle = () => S.rxErr && (!S.rxAt || S.rxErr > S.rxAt) ? 'Server not reachable since ' + hms(S.rxErr) : S.rxAt ? 'Last data received from the server at ' + hms(S.rxAt) + (dotState() === 'stale' ? ' (older than 12 min)' : '') : 'Nothing received yet';
  function setStatus() {
    const d = S.D, t = new Date(d.generated || Date.now()), hh = t.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    $('#s1').innerHTML = d.mode === 'demo' ? '<span class="dot"></span>DEMO · invented numbers · unlock to see your real data' : '<span class="dot ' + dotState() + '" title="' + dotTitle() + '"></span>Real data · refreshed ' + hh + (S.liveAt ? ' · quotes ' + hms(S.liveAt) : '');
    $('#stat').textContent = d.mode === 'demo' ? 'SHOWING EXAMPLE DATA (≈ 10 M EUR)' : 'LIVE QUOTES + COINBASE EVERY 5 MIN · FILES ARE READ ONLY WHEN NEW OR CHANGED';
    document.title = 'WealthView ' + (window.WV_VERSION || '') + (d.mode === 'demo' ? ' (demo)' : '');
  }
  function lockBtn() { const b = $('#bLock'); b.textContent = S.mode === 'demo' ? '🔒 Real numbers' : 'Show demo'; b.classList.toggle('on', S.mode === 'real'); $('#bRefresh').disabled = S.mode === 'demo'; $('#bSetup').style.display = S.mode === 'demo' ? 'none' : ''; $('#bRefresh').title = S.mode === 'demo' ? 'Unlock real numbers first' : 'Re-read your files and prices now (R)'; }

  /* ================================================== unlock / refresh / live */
  /* unlock field: what a keypad key does to the typed value, and whether it submits (pure; free text, no digit filter, no auto-submit) */
  function lockInput(value, key) {
    value = String(value == null ? '' : value);
    if (key === '✓' || key === 'Enter') return { value, submit: true };
    if (key === '⌫' || key === 'Backspace') return { value: [...value].slice(0, -1).join(''), submit: false };
    if (/^\d$/.test(key) && value.length < 1024) value += key;
    return { value, submit: false };
  }
  function lockModal() {
    modalShell('Real numbers', '', 'fit'); const m = $('#mdl'); m.style.width = '28rem';
    $('#mbody').innerHTML = `<div id="lock" style="text-align:center"><div class="dim sm">Enter your password to load your real data.</div><input id="pinIn" type="password" autocomplete="off" aria-label="Password" maxlength="1024" spellcheck="false"><div><button id="unlockBtn" type="button">Unlock</button></div><div class="pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9, '⌫', 0, '✓'].map(k => `<button data-k="${k}">${k}</button>`).join('')}</div><div id="lockMsg" class="sm or"></div><div class="hint">Enter confirms</div><div class="hint" style="margin-top:.5rem">WealthView ${window.WV_VERSION || ''}</div></div>`; frameAll($('#modal'));
    const inp = $('#pinIn');
    let busy = false; const ub = $('#unlockBtn');
    const go = async () => { let pin = inp.value; if (busy || !pin) return; busy = true; ub.disabled = true; ub.setAttribute('aria-busy', 'true'); $('#lockMsg').style.color = ''; $('#lockMsg').innerHTML = '<span class="spinner"></span>checking…'; try { const r = await (await fetch('/api/unlock', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pin }) })).json(); pin = ''; if (r.ok) { S.token = r.token; SS.set('wvtok', r.token); await loadReal(false, true); } else { $('#lockMsg').textContent = r.error || 'wrong password'; inp.classList.add('shake'); setTimeout(() => inp.classList.remove('shake'), 400); inp.value = ''; inp.focus(); } } catch (e) { pin = ''; $('#lockMsg').textContent = server ? 'Server not reachable.' : 'Open WealthView from its desktop shortcut (it starts the local server).'; } finally { busy = false; ub.disabled = false; ub.removeAttribute('aria-busy'); } };
    $$('#lock .pad button').forEach(b => b.onclick = () => { const r = lockInput(inp.value, b.dataset.k); inp.value = r.value; if (r.submit) go(); else inp.focus(); });
    ub.onclick = go;
    inp.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); go(); } };
    /* an older version of this screen used a window-level key listener: make sure none is left behind */
    if (window.__wvLockKey) { window.removeEventListener('keydown', window.__wvLockKey, true); window.__wvLockKey = null; }
    $('#lock').onclick = () => inp.focus(); setTimeout(() => inp.focus(), 50);
  }
  async function api(path, opt) { opt = opt || {}; opt.headers = Object.assign({ 'X-WV-Token': S.token || '' }, opt.headers || {}); let r; try { r = await fetch(path, opt); } catch (e) { S.rxErr = Date.now(); if (S.D) setStatus(); throw e; } if (r.ok) { S.rxAt = Date.now(); S.rxErr = null; S.rxFlash = Date.now(); if (S.D) { setStatus(); setTimeout(setStatus, 1000); } } else if (r.status !== 401) { S.rxErr = Date.now(); if (S.D) setStatus(); } if (r.status === 401) { S.token = null; SS.set('wvtok', null); const e = new Error('locked'); e.locked = true; throw e; } return r.json(); }
  /* recalculate everything on the server and redraw, without the loading pop-up or the intro (used after category corrections) */
  async function reloadData() {
    const st = $('#stat'); if (st) st.textContent = 'RECALCULATING…';
    try {
      /* another refresh may be running (folder watcher, Refresh button): wait for it, then run ours so the new rules are really included */
      let r = null;
      for (let i = 0; i < 60; i++) {
        r = await api('/api/refresh', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
        if (!r || !r.busy) break;
        await new Promise(res => setTimeout(res, 4000));
      }
      if (!r || !r.ok) throw new Error((r && (r.error || r.log)) || 'recalculation did not finish');
      const d = await api('/api/real'); if (d.error) throw new Error(d.error);
      S.D = d; S.lastGen = d.generated; renderAll();
      return true;
    } catch (e) { console.error(e); if (st) st.textContent = 'RECALCULATION FAILED - press Refresh data'; return false; }
  }
  async function loadReal(refresh, first) {
    modalShell('Loading your real numbers', ''); $('#mbody').innerHTML = `<div class="sm" style="padding:2rem 0;text-align:center"><span class="spinner"></span><span id="ldm">${refresh ? 'Re-reading your files, quotes and Coinbase… (20–40 s)' : 'Loading…'}</span></div>`;
    try {
      if (refresh) { const r = await api('/api/refresh', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }); if (!r.ok) { $('#ldm').textContent = 'Refresh problem: ' + (r.log || '') + ' (showing the last data if available)'; await new Promise(z => setTimeout(z, 1500)); } }
      const d = await api('/api/real'); if (d.error) throw new Error(d.error);
      try { const lg = await api('/api/src_logos'); if (lg && !lg.error) window.SRC_LOGOS = lg; } catch (e) { /* logos are optional: missing ones are fetched one by one */ }
      try { const pr = await api('/api/profile'); if (pr && !pr.error) S.profile = pr; } catch (e) { if (e.locked) throw e; /* no profile: the legacy layout stays */ }
      S.D = d; S.lastGen = d.generated; S.mode = 'real'; S.liveAt = null; closeModal(); renderAll(); mapPoll(); playIntro(refresh ? 1.6 : (first ? 1 : 1.3)); setTimeout(logoCheck, 300);
    } catch (e) { if (e.locked) { closeModal(); toDemo(); lockModal(); return; } $('#mbody').innerHTML = `<div class="or sm" style="padding:1rem">Could not load real data: ${esc(e.message)}<br><br><button id="bk">Back to demo</button></div>`; $('#bk').onclick = () => { closeModal(); toDemo(); }; }
  }
  function toDemo() { S.mode = 'demo'; S.profile = null; S.D = S.DEMO; renderAll(); mapPoll(); }
  async function quickUpdate() {
    if (S.mode !== 'real' || !S.token || S.quickBusy) return; S.quickBusy = true;
    try { $('#stat').textContent = 'UPDATING COINBASE + QUOTES…'; await api('/api/quick', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }); const d = await api('/api/real');
      if (d && !d.error) { const changed = d.generated !== S.lastGen; S.lastGen = d.generated; S.D = d; S.liveAt = Date.now(); if (!$('#modal').classList.contains('on')) { renderAll(); if (changed) playIntro(2.2); } } }
    catch (e) { if (e.locked) { toDemo(); lockModal(); } } finally { S.quickBusy = false; setStatus(); }
  }
  function playIntro(speed) {
    if (!window.WVIntro) return; const d = S.D, v = classValues(d), tot = CLS.reduce((s, k) => s + v[k], 0) || 1, dp = d.depot, cb = d.crypto;
    const lines = [S.mode === 'demo' ? 'DEMO DATA ... LOADED' : 'GLS BOOKINGS ... ' + ((d.gls && d.gls.n_tx) || (d.flows ? d.flows.months.length + ' MONTHS' : 'OK')), cb ? 'COINBASE ... ' + (S.mode === 'demo' ? 'DEMO' : 'LIVE') : 'COINBASE ... OFFLINE', dp ? 'QUOTES ... ' + dp.n_live + '/' + dp.n_total : 'QUOTES ... OFFLINE', d.examplefund ? 'EXAMPLE FUND ... ' + (d.examplefund.fund && d.examplefund.fund.quarter || 'OK') : 'EXAMPLE FUND ... OK', 'PORTFOLIO ... ONLINE'];
    try { window.WVIntro.play({ speed, lines }); } catch (e) { console.error(e); }
  }
  /* ================================================== boot */
  function tick() { const n = new Date(); $('#clock').textContent = n.toLocaleTimeString('de-DE'); $('#date').textContent = n.toLocaleDateString('en-GB', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase(); }
  function init() {
    const st = document.createElement('style'); st.textContent = '.priv .fill svg,.priv #ringBox,.priv .wing b,.priv .kp .v{filter:blur(.5rem)}.priv .nb svg,.priv .nb .fill svg,.priv .nb .kp .v,.priv .nb.fill svg{filter:none}.priv .nb text.amt{filter:blur(.45rem)}'; document.head.appendChild(st);
    setInterval(() => { if (S.D && S.mode === 'real') setStatus(); }, 5000); new ResizeObserver(() => fitRing()).observe(document.body); mapLoad(); mapPoll(); let fr = 0; (function lp(t) { try { mapDraw(t); if (++fr % 20 === 0) fitRing(); } catch (e) { } requestAnimationFrame(lp); })(0); if (/^https?:/.test(location.protocol)) {      /* heartbeat: the local server stops itself when this page is closed */
      const CID = Math.random().toString(36).slice(2, 12), hb = () => fetch('/api/hb?id=' + CID, { cache: 'no-store' }).then(r => { if (r.ok) { S.rxAt = Date.now(); S.rxErr = null; } }).catch(() => { S.rxErr = Date.now(); }).then(() => { if (S.D && S.mode === 'real') setStatus(); });
      hb(); setInterval(hb, 10000); window.addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/bye?id=' + CID); } catch (e) { } });
    }
    { const v = $('#ver'); if (v) v.textContent = window.WV_VERSION || ''; } S.DEMO = window.makeDemo(); S.D = S.DEMO; tick(); setInterval(tick, 1000); renderAll(); if (S.token) loadReal(false, true); else playIntro(1);
    $$('#ctl [data-r]').forEach(b => b.onclick = () => { S.range = b.dataset.r; renderAll(); });
    $('#bGran').onclick = () => { S.gran = S.gran === 'M' ? 'Y' : 'M'; renderAll(); };
    $('#bPriv').onclick = () => document.body.classList.toggle('priv'); $('#bFs').onclick = () => { if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => { }); else document.exitFullscreen(); };
    $('#bLock').onclick = () => { if (S.mode === 'demo') { if (S.token) loadReal(false); else lockModal(); } else toDemo(); };
    $('#bRefresh').onclick = () => { if (S.mode === 'real') loadReal(true); };
    $('#bSetup').onclick = () => { if (S.mode === 'real' && window.WVS) window.WVS.open(); };
    document.addEventListener('keydown', e => { if (e.target.tagName === 'INPUT') return; if (e.key === 'p' || e.key === 'P') document.body.classList.toggle('priv'); if ((e.key === 'r' || e.key === 'R') && S.mode === 'real' && !e.ctrlKey) loadReal(true); if (e.key === 'f' || e.key === 'F') $('#bFs').click(); });
    setInterval(quickUpdate, 300000);
    window.addEventListener('resize', () => { /* frames and charts follow via ResizeObserver */ });
  }
  window.WV = { wfgLayout, pSrc, pAlt, S, panel, infoModal, modalShell, TS, A, eur, pct, cl, esc, badge, srcBadge, logo, renderAll, POST, $, $$, kfmt, openMerchant, openBookings, openTS, api, server, PAL, GREY, MON, redrawFlowBox, closeModal, reloadData, lockInput, lockModal };
  window.addEventListener('DOMContentLoaded', init);
})();
