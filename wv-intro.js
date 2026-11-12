/* WealthView intro - HUD boot sequence, built from the dashboard's OWN elements so that it ends exactly on the final view:
     1. boot text decodes itself like code, line by line (random glyphs settle into the text; status lines come from the data just loaded) over a faint stream of code
     2. the title types in; every box traces its frame from its real position, then rolls open under a scan line
     3. the asset ring draws its segments and the gross-assets number counts up - in the real ring, not in a copy
   Nothing is drawn at an estimated position: frames, ring and numbers are the real elements, so there is no jump at the end.
   window.WVIntro.play({speed, lines, done}). A click skips it. Any error ends it (the page is never left covered). */
(function () {
  'use strict';
  let running = false;
  const clamp01 = v => Math.max(0, Math.min(1, v)), easeOut = p => 1 - Math.pow(1 - p, 3), easeIO = p => p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
  const nfde = new Intl.NumberFormat('de-DE');
  const GLY = '01{}[]<>/\\|#$%&*+=;:~^', SNIP = ['import wealthview.core as wv', 'def load_depot(path):', '  rows = csv.reader(open(path))', 'for p in positions: p.value = qty * price', 'await fetch("/api/real")', '0x7F3A 0xC0DE 0x00FF 0xB00B 0x1A2B', 'SELECT * FROM holdings WHERE qty > 0', 'if (gain_pct > 5) glow(p)', 'return sum(v for v in values)', 'const net = gross - loan - tax;', 'while (!online) retry(3);', 'checksum 9F3A-22C1-77D0-0B1E', 'render(treemap, size=value)', 'lots = fifo(trades, splits)', 'score = trend + momentum + rsi', 'async function quotes() {', '  const px = await yahoo(sym);', '}', 'class Position { wkn; qty; cost }', 'ring.draw(segments, 222)', 'git commit -m "wealth"', 'for (m of months) flow[m] += amt', 'p50 = percentile(returns, .5)', '#include <wealth.h>', 'export default dashboard;'];
  const decode = (str, p) => { const n = Math.floor(str.length * p); if (p >= 1) return str; let o = str.slice(0, n); for (let i = n; i < Math.min(str.length, n + 5); i++) o += str[i] === ' ' ? ' ' : GLY[(Math.random() * GLY.length) | 0]; return o; };
  /* every visible text node of a box (not script/style, not the gross-assets number which counts up by itself); i = order, used to stagger the decoding */
  function textNodes(el) {
    const out = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: n => { const pe = n.parentElement; return pe && /^(SCRIPT|STYLE)$/i.test(pe.tagName) || pe && pe.id === 'ringVal' ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; } }); let n;
    while ((n = w.nextNode())) if (n.data.trim()) out.push({ n, o: n.data, i: out.length, fin: false }); return out;
  }
  function play(opt) {
    opt = opt || {};
    if (running) { if (opt.done) opt.done(); return; }
    running = true;
    const speed = opt.speed || 1, W = innerWidth, H = innerHeight, dpr = Math.min(2, window.devicePixelRatio || 1), u = Math.max(.6, H / 1080);
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:200;cursor:pointer;background:transparent';
    const canvas = document.createElement('canvas'); canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); canvas.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
    overlay.appendChild(canvas); document.body.appendChild(overlay);
    const ctx = canvas.getContext('2d'), FONT = 'px Consolas,"Cascadia Mono",monospace';

    // ---- what is revealed: header, every box, the ring block, the KPI row (sorted left -> right; the ring block comes last)
    const hd = document.getElementById('hd'), ringWrap = document.getElementById('ringWrap');
    const boxes = [...document.querySelectorAll('#grid .bx, #kpiRow')].filter(e => e.getBoundingClientRect().width > 0);
    const rects = new Map(); boxes.concat(ringWrap ? [ringWrap] : []).forEach(e => rects.set(e, e.getBoundingClientRect()));
    boxes.sort((a, b) => { const A = rects.get(a), B = rects.get(b); return (A.left + A.top * .35) - (B.left + B.top * .35); });
    const all = ringWrap && rects.get(ringWrap).width > 0 ? boxes.concat([ringWrap]) : boxes;
    all.forEach(e => { e.style.opacity = '0'; e.style.clipPath = 'inset(0 0 100% 0)'; });
    if (hd) hd.style.opacity = '0';
    const titles = new Map(); all.forEach(e => titles.set(e, textNodes(e)));

    // ---- title typing + gross-assets count-up + ring segments: all on the real elements
    const h1 = document.querySelector('#title h1'), h1txt = h1 ? h1.textContent : '';
    const valEl = document.getElementById('ringVal'), finalTxt = valEl ? valEl.textContent : '', finalNum = parseInt(finalTxt.replace(/\D/g, ''), 10) || 0;
    const segEls = [...document.querySelectorAll('#ringSvg .seg')], segLen = segEls.map(e => { try { return e.getTotalLength(); } catch (x) { return 0; } });
    const mid = document.getElementById('ringMid');

    // ---- timeline (seconds at speed 1)
    const status = ['WEALTHVIEW ' + (window.WV_VERSION || '').toUpperCase() + '  //  BOOT SEQUENCE'].concat(opt.lines && opt.lines.length ? opt.lines : ['DATA ... LOADED'], ['ALL SYSTEMS ... ONLINE']).map((x, i) => '0x' + (4096 + i * 16).toString(16).toUpperCase() + '  ' + x);
    const CPS = 42, GAP = .1, lineStart = [], lineEnd = []; let tt = .15;
    status.forEach((s, i) => { lineStart[i] = tt; tt += s.length / CPS; lineEnd[i] = tt; tt += GAP; });
    const BOX0 = .55, STEP = .12, TRACE = .5, ROLL = .55;
    const startOf = i => BOX0 + i * STEP + (all[i] === ringWrap ? .25 : 0);
    const lastEnd = startOf(all.length - 1) + TRACE + ROLL, T_END = Math.max(lastEnd + .5, tt + .4, 3.6), BOOT_FADE = Math.min(2.6, T_END - 1);
    let done = false;

    // outline of a chamfered box as a polyline (clockwise from the top-left chamfer)
    function outline(r, c) {
      const x = r.left, y = r.top, w = r.width, h = r.height;
      return [[x + c, y], [x + w, y], [x + w, y + h - c], [x + w - c, y + h], [x, y + h], [x, y + c], [x + c, y]];
    }
    function strokePartial(pts, p, col, lw, glow, alpha) {
      let tot = 0; const seg = []; for (let i = 1; i < pts.length; i++) { const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); seg.push(l); tot += l; }
      let rest = tot * p; ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); let hx = pts[0][0], hy = pts[0][1];
      for (let i = 1; i < pts.length && rest > 0; i++) { const l = seg[i - 1], f = Math.min(1, rest / l); hx = pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f; hy = pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f; ctx.lineTo(hx, hy); rest -= l; }
      ctx.globalAlpha = alpha; ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.shadowColor = col; ctx.shadowBlur = glow; ctx.stroke(); ctx.shadowBlur = 0;
      if (p > 0 && p < 1) { ctx.beginPath(); ctx.arc(hx, hy, 3 * u, 0, 7); ctx.fillStyle = '#fff'; ctx.globalAlpha = alpha; ctx.shadowColor = '#19d3ff'; ctx.shadowBlur = 14; ctx.fill(); ctx.shadowBlur = 0; }
    }
    function frame(t) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.shadowBlur = 0; ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
      // header: fades in, title types itself
      if (hd) hd.style.opacity = String(clamp01((t - .1) / .5));
      if (h1) h1.textContent = decode(h1txt, clamp01((t - .2) / 1.1));
      // faint stream of code at the sides while the boot text runs
      const rainA = (1 - clamp01((t - 1.3) / .9)) * .32;
      if (rainA > 0) { const fs = Math.round(11 * u), lh = fs * 1.45, rows = Math.ceil(H / lh) + 2, off = (t * 60 * u) % lh, tick = Math.floor(t * 9); ctx.font = fs + FONT; ctx.textAlign = 'left'; ctx.fillStyle = '#19d3ff';
        [[W * .012, 1], [W * .83, 2]].forEach(([x, k]) => { for (let r = 0; r < rows; r++) { const id = (r + Math.floor(t * 60 * u / lh)) * 7 + k * 13; ctx.globalAlpha = rainA * (.35 + .65 * (((id * 2654435761) >>> 0) % 100) / 100); ctx.fillText(SNIP[Math.abs(id) % SNIP.length], x, H - r * lh + off - lh); } }); ctx.globalAlpha = 1; }
      // boot text, centred, decoded like code line by line with a blinking cursor
      const bootA = 1 - clamp01((t - (BOOT_FADE - .6)) / .6);
      if (bootA > 0) {
        const fs = Math.round(15 * u), lh = fs * 1.7, y0 = H / 2 - (status.length * lh) / 2; ctx.font = fs + FONT; ctx.textAlign = 'left';
        const widest = Math.max(...status.map(s => s.length)) * fs * .62, x0 = W / 2 - widest / 2;
        status.forEach((s, i) => {
          if (t < lineStart[i]) return; const pr0 = clamp01((t - lineStart[i]) / Math.max(.05, lineEnd[i] - lineStart[i])), n = Math.min(s.length, Math.floor(pr0 * s.length)), txt = decode(s, pr0), cur = i === status.length - 1 || t < lineStart[i + 1];
          ctx.globalAlpha = bootA * (i === 0 ? 1 : .9); ctx.fillStyle = i === 0 ? '#ff9a3d' : (s.indexOf('ONLINE') >= 0 ? '#8fe6b8' : '#19d3ff'); ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 8;
          ctx.fillText((i ? '> ' : '') + txt, x0, y0 + i * lh); ctx.shadowBlur = 0;
          if (cur && n <= s.length && (Math.floor(t * 3.2) % 2 === 0 || n < s.length)) { const w = ctx.measureText((i ? '> ' : '') + txt).width; ctx.fillRect(x0 + w + 3, y0 + i * lh - fs * .8, fs * .55, fs * .95); }
        });
        ctx.globalAlpha = 1;
      }
      // boxes: trace frame -> roll open under a scan line
      all.forEach((el, i) => {
        const r = rects.get(el), s = startOf(i), pt = clamp01((t - s) / TRACE), pr = easeOut(clamp01((t - s - TRACE * .7) / ROLL));
        if (t < s) return;
        const onscreen = r.bottom > 0 && r.top < H;
        { const t0n = s + TRACE * .45; (titles.get(el) || []).forEach(x => {
          if (x.fin) return; const st = t0n + Math.min(x.i * .012, .7), du = Math.max(.3, Math.min(1.2, .3 + x.o.length * .02)), tp = clamp01((t - st) / du);
          x.n.data = decode(x.o, tp); if (tp >= 1) x.fin = true; }); }
        if (pr > 0) { el.style.opacity = '1'; el.style.clipPath = 'inset(0 0 ' + (100 * (1 - pr)).toFixed(2) + '% 0)'; }
        if (!onscreen) { el.style.opacity = '1'; el.style.clipPath = ''; return; }
        const fa = 1 - clamp01((pr - .6) / .4);
        if (fa > 0) {
          const c = Math.min(14 * u, r.width / 6, r.height / 6);
          strokePartial(outline(r, c), easeIO(pt), el === ringWrap ? 'rgba(255,154,61,.9)' : 'rgba(25,211,255,.95)', 1.5 * u, 10, fa);
        }
        if (pr > 0 && pr < 1) { const y = r.top + r.height * pr; ctx.globalAlpha = (1 - pr) * .9; ctx.strokeStyle = '#19d3ff'; ctx.shadowColor = '#19d3ff'; ctx.shadowBlur = 12; ctx.lineWidth = 1.5 * u; ctx.beginPath(); ctx.moveTo(r.left, y); ctx.lineTo(r.left + r.width, y); ctx.stroke(); ctx.shadowBlur = 0; ctx.globalAlpha = 1; }
      });
      // ring: segments sweep one after another, the number counts up (both on the real elements)
      if (ringWrap) {
        const rs = startOf(all.length - 1) + TRACE * .7;
        segEls.forEach((e, i) => { const L = segLen[i]; if (!L) return; const p = easeOut(clamp01((t - rs - .15 - i * .18) / .9)); e.style.transition = 'none'; e.style.strokeDasharray = L + ' ' + L; e.style.strokeDashoffset = String(L * (1 - p)); });
        if (valEl) valEl.textContent = nfde.format(Math.round(finalNum * easeOut(clamp01((t - rs) / 1.5))));
        if (mid) mid.style.opacity = String(clamp01((t - rs + .1) / .5));
      }
    }
    const t0 = performance.now();
    function finish() {
      if (done) return; done = true; running = false;
      all.forEach(e => { e.style.clipPath = ''; e.style.opacity = ''; (titles.get(e) || []).forEach(x => { x.n.data = x.o; }); });
      if (hd) hd.style.opacity = ''; if (h1) h1.textContent = h1txt;
      if (valEl) valEl.textContent = finalTxt; if (mid) mid.style.opacity = '';
      segEls.forEach(e => { e.style.strokeDasharray = ''; e.style.strokeDashoffset = ''; e.style.transition = ''; });
      overlay.style.pointerEvents = 'none'; overlay.remove();
      if (opt.done) opt.done();
    }
    function tick(now) {
      if (done) return; const t = (now - t0) / 1000 * speed;
      try { frame(Math.min(t, T_END)); } catch (e) { console.error('intro stopped:', e); finish(); return; }
      if (t >= T_END) { finish(); return; } requestAnimationFrame(tick);
    }
    overlay.addEventListener('click', finish); requestAnimationFrame(tick);
  }
  window.WVIntro = { play };
})();
