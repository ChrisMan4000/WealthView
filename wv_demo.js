/* WealthView DEMO data: invented numbers (~10 M EUR in total). Nothing here is real. */
(function () {
  function rng(seed) { let a = seed >>> 0; return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function gauss(r) { return Math.sqrt(-2 * Math.log(r() + 1e-9)) * Math.cos(2 * Math.PI * r()); }
  function mrange(a, b) { let y = +a.slice(0, 4), m = +a.slice(5, 7); const yb = +b.slice(0, 4), mb = +b.slice(5, 7), o = []; while (y < yb || (y === yb && m <= mb)) { o.push(y + '-' + String(m).padStart(2, '0')); if (++m === 13) { y++; m = 1; } } return o; }
  function interp(bench, ym) {
    const pts = Object.keys(bench).map(y => [+y + 0.5, bench[y]]).sort((a, b) => a[0] - b[0]);
    const x = +ym.slice(0, 4) + (+ym.slice(5, 7) - 0.5) / 12;
    if (x <= pts[0][0]) return pts[0][1]; if (x >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
    for (let i = 0; i < pts.length - 1; i++) { const [x0, y0] = pts[i], [x1, y1] = pts[i + 1]; if (x >= x0 && x <= x1) return y0 + (y1 - y0) * (x - x0) / (x1 - x0); }
  }

  /* ---- canned EXAMPLE content for demo mode: invented, generic, no real outlets, no factual claims about real companies ---- */
  function hsh(str) { let h = 2166136261; str = String(str || ''); for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function pick(seed, k) { const r = rng(seed + k * 7919); return r(); }
  const HEADS = [['Sample: quarterly results beat expectations', 1], ['Sample: management confirms full-year outlook', 1], ['Sample: new product line announced for next year', 1], ['Sample: analysts discuss valuation after recent rally', 0], ['Sample: company presents at an industry conference', 0], ['Sample: sector faces mixed demand signals', -1], ['Sample: board proposes unchanged dividend', 0], ['Sample: supply costs weigh on margins this quarter', -1], ['Sample: partnership with a research institute announced', 1]];
  const SRCS = ['Example Wire', 'Sample Daily', 'Demo Finance Desk'];
  function demoNews(name, seed, nowS, withUrl) {
    const used = new Set(), out = [];
    for (let i = 0; out.length < 3 && i < 30; i++) { const k = Math.floor(pick(seed, i) * HEADS.length); if (used.has(k)) continue; used.add(k); out.push({ k, h: HEADS[k] }); }
    return out.map((o, i) => withUrl ? { title: o.h[0] + ' (' + name + ')', url: '', source: SRCS[i % 3], date: new Date((nowS - (i * 3 + 1) * 86400) * 1000).toISOString().slice(0, 10), demo: true }
      : { title: o.h[0] + ' (' + name + ')', url: '', publisher: SRCS[i % 3], t: nowS - (i * 3 + 1) * 86400, sent: o.h[1], demo: true });
  }
  /* same shape as server /api/research: ok, sym, t, score{total,verdict,factors,coverage}, news[{title,url,publisher,t,sent}] */
  window.demoResearch = function (p) {
    const seed = hsh((p && p.name) || 'x'), nowS = Math.floor(Date.now() / 1000), u = i => .3 + .65 * pick(seed, 100 + i);
    const r6 = Math.round(-5 + 30 * u(1)), r12 = Math.round(-8 + 45 * u(2)), rsi = Math.round(35 + 35 * u(3)), hi = -Math.round(2 + 25 * u(4)), rec = Math.round((1.6 + 2 * (1 - u(5))) * 10) / 10, up = Math.round(-5 + 30 * u(6));
    const news = demoNews((p && p.name) || '', seed, nowS, false), tone = news.reduce((a, n) => a + n.sent, 0);
    const F = [{ name: 'Trend', text: u(7) > .5 ? 'above 200-day, above 50-day' : 'below 200-day, above 50-day', pts: Math.round(20 * u(7) * 10) / 10, max: 20 }, { name: 'Momentum', text: '6 m ' + (r6 >= 0 ? '+' : '') + r6 + ' % · 12 m ' + (r12 >= 0 ? '+' : '') + r12 + ' %', pts: Math.round(20 * u(8) * 10) / 10, max: 20 },
      { name: 'RSI (14)', text: String(rsi), pts: Math.round(10 * u(9) * 10) / 10, max: 10 }, { name: 'Distance to 52 w high', text: hi + ' %', pts: Math.round(10 * u(10) * 10) / 10, max: 10 },
      { name: 'Analyst consensus', text: rec.toFixed(1) + '/5 (' + (rec < 2.2 ? 'buy' : rec < 3 ? 'hold' : 'underperform') + ') · ' + Math.round(8 + 20 * u(11)) + ' analysts', pts: Math.round(15 * (5 - rec) / 4 * 10) / 10, max: 15 },
      { name: 'Price target', text: (up >= 0 ? '+' : '') + up + ' % to mean target', pts: Math.round(10 * Math.max(0, Math.min(1, .5 + up / 60)) * 10) / 10, max: 10 },
      { name: 'News tone', text: (tone > 0 ? 'positive' : tone < 0 ? 'negative' : 'neutral') + ' (' + news.length + ' headlines)', pts: Math.round((5 + 5 * Math.max(-1, Math.min(1, tone / 3))) * 10) / 10, max: 10 }];
    const mx = F.reduce((a, f) => a + f.max, 0), tot = Math.round(F.reduce((a, f) => a + f.pts, 0) / mx * 100);
    return { ok: true, demo: true, sym: (p && p.sym) || '', t: nowS, score: { total: tot, verdict: tot >= 72 ? 'STRONG BUY' : tot >= 60 ? 'BUY' : tot >= 45 ? 'HOLD' : tot >= 33 ? 'REDUCE' : 'SELL', factors: F, coverage: mx }, news, notes: [] };
  };
  /* same shape as server /api/company: mission, hq, employees, founded, founders, industry, news[{title,url,source,date}] */
  const CITIES = ['Musterstadt', 'Munich', 'Hamburg', 'Leipzig', 'Vienna', 'Zurich', 'Utrecht', 'Lisbon'], FN = ['A. Example', 'B. Sample', 'C. Muster', 'D. Beispiel', 'E. Demo'];
  window.demoCompany = function (c) {
    const seed = hsh(c && c.name), nowS = Math.floor(Date.now() / 1000), nm = (c && c.name) || 'Example Co';
    return { ok: true, demo: true, mission: 'EXAMPLE: invented sample text. ' + nm + ' is a fictional company used to show how this window looks with live data.', hq: CITIES[Math.floor(pick(seed, 1) * CITIES.length)] + ' (example)', employees: Math.round(12 + pick(seed, 2) * 480), founded: String(2012 + Math.floor(pick(seed, 3) * 11)),
      founders: [FN[Math.floor(pick(seed, 4) * 5)], FN[(Math.floor(pick(seed, 4) * 5) + 2) % 5]], industry: (c && c.industry) || 'Example sector', news: demoNews(nm, seed, nowS, true), found: {}, links: {} };
  };
  function demoExampleFund() {
    const raw = [['Example Quantum GmbH', 'Deep tech', 'Quantum computing', 'Germany', '2022-03', 25000000, 38500000, 'Fictional builder of quantum control hardware for research labs.'], ['Sample Fusion Labs', 'Energy', 'Clean power', 'Netherlands', '2021-09', 17600000, 27400000, 'Fictional developer of compact fusion test reactors.'], ['Demo Carbon Capture AG', 'Climate tech', 'Carbon removal', 'Switzerland', '2022-06', 14800000, 19600000, 'Fictional operator of direct air capture plants.'],
      ['Beispiel Batteries SE', 'Energy', 'Storage', 'Germany', '2021-02', 19200000, 22100000, 'Fictional maker of long-duration grid batteries.'], ['Muster Foods Ltd', 'Food tech', 'Alternative protein', 'United Kingdom', '2021-11', 11800000, 9800000, 'Fictional producer of plant-based seafood alternatives.'], ['Example Grid Robotics', 'Industrial tech', 'Robotics', 'Austria', '2023-01', 9000000, 12900000, 'Fictional robotics firm automating power-grid inspection.'],
      ['Sample Soil Analytics', 'Agri tech', 'Data & software', 'France', '2022-10', 6100000, 6900000, 'Fictional provider of soil-carbon measurement software.'], ['Demo Hydrogen Systems', 'Energy', 'Hydrogen', 'Denmark', '2020-12', 13500000, 16400000, 'Fictional builder of electrolyser stacks.'], ['Muster Circular Plastics', 'Materials', 'Recycling', 'Spain', '2023-04', 7100000, 8600000, 'Fictional chemical recycler for mixed plastic waste.']];
    const companies = raw.map(x => { const slug = x[0].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); return { slug, name: x[0], since: x[4], country: x[3], sector: x[2], own: Math.round((4 + pick(hsh(x[0]), 1) * 20) * 100) / 100, cost: x[5], fair_value: x[6], moic: Math.round(x[6] / x[5] * 100) / 100, irr: Math.round((x[6] / x[5] - 1) * 1000) / 10, web: '', industry: x[1], blurb: 'EXAMPLE: ' + x[7], demo: true }; });
    const fv = companies.reduce((a, c) => a + c.fair_value, 0), cost = companies.reduce((a, c) => a + c.cost, 0);
    return { source: 'EXAMPLE fund (invented numbers)', report_year: 2026, report_q: 2, fund: { name: 'Example Fund I (demo)', commitments: 240000000, paid_in: 168000000, paid_in_pct: 70, distributions: 1200000, unfunded: 72000000, nav: 175000000, fair_value_portfolio: fv, invested_cost: cost, gross_irr: 6.4, net_irr: 2.7, gross_multiple: 1.19, tvpi: 1.05, rvpi: 1.04, dpi: 0.01, portfolio_moic: Math.round(fv / cost * 100) / 100 }, portfolio_url: 'https://example.com/', site: 'https://example.com/', personal: {}, companies };
  }
  window.makeDemo = function () {
    const r = rng(20261105), now = new Date(), NOWM = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
    const axis = mrange('2018-01', NOWM), n = axis.length;
    function path(end, vol, drift) { // random walk ending exactly at `end`
      const a = [1]; for (let i = 1; i < n; i++) a.push(a[i - 1] * Math.exp(drift + vol * gauss(r)));
      const k = end / a[n - 1]; return a.map(v => Math.round(v * k * 10000) / 10000);
    }
    // ---- depot (fictional companies)
    const P = [
      ['Aurora Chips', 'DEMO01', 'Stock', 'Semiconductors', 612000, .06, .018], ['Helios Solar', 'DEMO02', 'Stock', 'Energy transition', 348000, .07, .01],
      ['Nordic Robotics', 'DEMO03', 'Stock', 'AI & Robotics', 296000, .09, .014], ['Blue Planet Water', 'DEMO04', 'Fund', 'Water', 264000, .035, .006],
      ['Quantum Leaf', 'DEMO05', 'Stock', 'Quantum', 241000, .11, .008], ['Atlas Global ETF', 'DEMO06', 'ETF', 'World equity', 402000, .04, .008],
      ['GreenGrid Utilities', 'DEMO07', 'Stock', 'Energy transition', 188000, .05, .005], ['Meridian Health', 'DEMO08', 'Stock', 'Healthcare', 214000, .05, .007],
      ['Polar Lithium', 'DEMO09', 'Stock', 'Batteries', 126000, .13, .002], ['Sustain Equity Fund', 'DEMO10', 'Fund', 'Sustainable equity', 231000, .035, .007],
      ['Hydrogen Frontier ETF', 'DEMO11', 'ETF', 'Hydrogen', 98000, .08, -.002], ['Vega Photonics', 'DEMO12', 'Stock', 'Photonics', 139000, .08, .01],
      ['Corona Bond Tracker', 'DEMO13', 'Tracker', 'Bonds', 140000, .012, .002], ['Tundra Mining', 'DEMO14', 'Stock', 'Materials', 99000, .1, .004],
    ];
    const positions = P.map(p => {
      const value = p[4], hist = path(1, p[6] * 3 + .03, p[5] / 12), gainPct = (hist[n - 1] / hist[Math.max(0, n - 40)] - 1) * 55 + 18;
      const price = Math.round((20 + r() * 380) * 100) / 100, qty = Math.round(value / price);
      const real = qty * price, cost = real / (1 + gainPct / 100);
      const k = price / hist[n - 1];
      return { wkn: p[1], name: p[0], cls: p[2], theme: p[3], qty, price, price_live: price, value: Math.round(real), cost: Math.round(cost), gain: Math.round(real - cost), gain_pct: Math.round(gainPct * 100) / 100, live: true, sym: 'DEMO', hist: hist.map(v => Math.round(v * k * 100) / 100) };
    }).sort((a, b) => b.value - a.value);
    const dTot = positions.reduce((s, p) => s + p.value, 0);
    positions.forEach(p => p.weight = Math.round(p.value / dTot * 1000) / 10);
    const depot = { asof: now.toISOString().slice(0, 10), positions, total: dTot, n_live: positions.length, n_total: positions.length, age_days: 0 };
    depot.gain = positions.reduce((s, p) => s + p.gain, 0); depot.cost = dTot - depot.gain; depot.gain_pct = Math.round(depot.gain / depot.cost * 10000) / 100;
    // ---- crypto
    const cs = [['BTC', 'Bitcoin', 3.1, 71000], ['ETH', 'Ethereum', 41, 2150], ['SOL', 'Solana', 820, 86], ['LINK', 'Chainlink', 5200, 10.3], ['ADA', 'Cardano', 90000, .177], ['LTC', 'Litecoin', 420, 49.8]];
    const holdings = cs.map(c => { const hist = path(c[3], .17, .018); return { currency: c[0], name: c[1], amount: c[2], price: c[3], eur: Math.round(c[2] * c[3]), hist }; });
    // invented purchase history: one or two buys per coin, cost = value / (1 + invented gain)
    holdings.forEach((h, i) => {
      const g = [1.9, .85, 2.6, -.12, -.45, .31][i % 6], cost = h.eur / (1 + g), m0 = Math.max(0, n - 40 + i * 4), d0 = axis[m0] + '-15', d1 = axis[Math.min(n - 2, m0 + 14)] + '-10', q1 = h.amount * .6, q2 = h.amount - q1;
      h.cost = Math.round(cost); h.gain = h.eur - h.cost; h.gain_pct = Math.round(g * 1000) / 10; h.first_buy = d0; h.cost_known_share = 1; h.avg_price = Math.round(cost / h.amount * 100) / 100;
      h.trades = [{ date: d0, side: 'buy', qty: q1, price: Math.round(cost * .55 / q1 * 100) / 100, fee: 0 }, { date: d1, side: 'buy', qty: q2, price: Math.round(cost * .45 / q2 * 100) / 100, fee: 0 }];
      h.lots = h.trades.map(t => ({ date: t.date, qty: t.qty, price: t.price, cost_known: true }));
    });
    const cCost = holdings.reduce((a, h) => a + h.cost, 0), cGain = holdings.reduce((a, h) => a + h.gain, 0);
    const crypto = { holdings, total_eur: holdings.reduce((s, h) => s + h.eur, 0), asof: now.toISOString(), trades_status: 'ok', cost: cCost, gain: cGain, gain_pct: Math.round(cGain / cCost * 10000) / 100 };
    // ---- apartment (invented villa) with an invented benchmark shape
    const bench = { 2018: 3100, 2019: 3600, 2020: 4250, 2021: 4600, 2022: 5525, 2023: 5167, 2024: 4794, 2025: 4850, 2026: 4930 };
    const ap0 = { address: 'Beispielallee 7, 12345 Musterstadt (demo)', sqm: 260, purchase_price: 2450000, purchase_date: '2019-04' };
    const base = interp(bench, '2019-04');
    const series = axis.map(m => m < '2019-04' ? null : Math.round(ap0.purchase_price * interp(bench, m) / base / 1000) * 1000);
    const est = series[n - 1];
    const apartment = Object.assign({}, ap0, { series, estimate: est, value_used: est, purchase_per_sqm: Math.round(ap0.purchase_price / ap0.sqm), estimate_per_sqm: Math.round(est / ap0.sqm), gain: est - ap0.purchase_price, gain_pct: Math.round((est / ap0.purchase_price - 1) * 1000) / 10, use_estimate: true, benchmark_name: 'Regional market, EUR/sqm (demo shape)', benchmark_source: 'https://example.com/' });
    // ---- cash + flows (monthly, 2018..)
    const catW = { 'Housing & Utilities': .27, 'Groceries': .13, 'Dining & Delivery': .09, 'Transport': .07, 'Insurance': .08, 'Health': .04, 'Shopping': .1, 'Subscriptions & Digital': .03, 'Travel': .09, 'Leisure & Sport': .04, 'Fees & Taxes': .04, 'Family & Private': .02 };
    const cats = {}, income = [], expense = [], oneoff_in = [], oneoff_out = [], invested = [];
    Object.keys(catW).forEach(k => cats[k] = []);
    axis.forEach((m, i) => {
      const yr = i / 12, inc = (21000 + yr * 650) * (1 + .04 * gauss(r)) + (m.endsWith('-12') ? 14000 : 0), ex = (11200 + yr * 380) * (1 + .09 * gauss(r)) * (['07', '08', '12'].includes(m.slice(5)) ? 1.18 : 1);
      income.push(Math.round(inc)); expense.push(Math.round(ex));
      Object.keys(catW).forEach(k => cats[k].push(Math.round(ex * catW[k] * (1 + .25 * gauss(r)) * (k === 'Travel' && ['07', '08', '12'].includes(m.slice(5)) ? 2 : 1))));
      oneoff_in.push(r() < .06 ? Math.round(8000 + r() * 40000) : 0); oneoff_out.push(r() < .05 ? Math.round(5000 + r() * 30000) : 0); invested.push(r() < .6 ? Math.round(3000 + r() * 9000) : 0);
    });
    const sums = Object.keys(cats).map(k => [k, cats[k].reduce((a, b) => a + b, 0)]).sort((a, b) => b[1] - a[1]), ordered = {};
    sums.forEach(([k]) => ordered[k] = cats[k]);
    const merch = { 'Housing & Utilities': ['Hausverwaltung Mitte', 'Stadtwerke Demo', 'Telekom'], 'Groceries': ['Bio Markt Demo', 'Frische Halle', 'Super Demo'], 'Dining & Delivery': ['Cafe Beispiel', 'Ristorante Uno', 'Sushi Demo'], 'Transport': ['Bahn Demo', 'Tankstelle Demo'], 'Insurance': ['Versicherung Demo AG'], 'Health': ['Apotheke Demo'], 'Shopping': ['Online Shop Demo', 'Kaufhaus Demo'], 'Subscriptions & Digital': ['Streaming Demo', 'Cloud Demo'], 'Travel': ['Airline Demo', 'Hotel Demo'], 'Leisure & Sport': ['Fitness Demo'], 'Fees & Taxes': ['Steuerberater Demo'], 'Family & Private': ['Geschenke'] };
    const tm = {}; Object.keys(merch).forEach(k => { const tot = cats[k].slice(-12).reduce((a, b) => a + b, 0); tm[k] = merch[k].map((x, i) => ({ n: x, v: Math.round(tot * [.55, .3, .15][i] || tot * .1) })); });
    const topNames = []; Object.keys(merch).forEach(k => merch[k].forEach((x, i) => topNames.push({ n: x, cat: k, w: ([.55, .3, .15][i] || .1) * catW[k] })));
    const mkTop = (from) => topNames.map(t => { const m = axis.map((mm, i) => i < from ? 0 : Math.round(expense[i] * t.w * (1 + .3 * gauss(r)))); const v = m.reduce((a, b) => a + b, 0); return { n: t.n, cat: t.cat, v, tx: Math.max(1, Math.round(v / 80)), m }; }).sort((a, b) => b.v - a.v).slice(0, 14);
    const top_spenders = { y1: mkTop(n - 13), all: mkTop(0) };
    const flows = { months: axis, cats: ordered, income, expense, oneoff_in, oneoff_out, invested, top_merchants: tm, top_spenders, oneoff_threshold: 3000, savings: income.map((v, i) => v - expense[i]) };
    const bal = { months: axis, giro: [], tages: [], card: [], shares: axis.map(() => 600) };
    let g = 22000, t = 180000; axis.forEach((m, i) => { g = Math.max(9000, g + (income[i] - expense[i]) * .35 + gauss(r) * 2500); t = t + (income[i] - expense[i]) * .6 + 4000; bal.giro.push(Math.round(g)); bal.tages.push(Math.round(t)); bal.card.push(-Math.round(900 + r() * 2200)); });
    const scale = 905000 / (bal.giro[n - 1] + bal.tages[n - 1] + bal.card[n - 1] + 600 + 1200); // land at ~0.9 M cash
    ['giro', 'tages', 'card'].forEach(k => bal[k] = bal[k].map(v => Math.round(v * scale)));
    const accounts = [{ iban_tail: '0001', name: 'Demo Giro', kind: 'giro', balance: bal.giro[n - 1] }, { iban_tail: '0002', name: 'Demo Tagesgeld', kind: 'tages', balance: bal.tages[n - 1] }, { iban_tail: '0003', name: 'Demo Credit Card', kind: 'card', balance: bal.card[n - 1] }, { iban_tail: '0004', name: 'Demo Shares', kind: 'shares', balance: 600 }];
    const recent = [['Bio Markt Demo', -84.2, 'Groceries'], ['Stadtwerke Demo', -212, 'Housing & Utilities'], ['Salary Demo GmbH', 18420, 'Income'], ['Cafe Beispiel', -23.4, 'Dining & Delivery'], ['Airline Demo', -612, 'Travel'], ['Apotheke Demo', -31.9, 'Health'], ['Online Shop Demo', -149, 'Shopping'], ['Versicherung Demo AG', -388, 'Insurance']].map((x, i) => ({ d: new Date(now - i * 86400000 * 1.4).toISOString().slice(0, 10), n: x[0], v: x[1], c: x[2] }));
    const totals = { giro: bal.giro[n - 1], tages: bal.tages[n - 1], card: bal.card[n - 1], shares: 600, paypal: 1200 };
    // ---- example fund (all numbers invented)
    const wf = demoExampleFund(); // fictional fund companies: the real wf_data.js is PIN-protected and never used in demo
    wf.personal = { commitment: 1200000, paid_in: 840000, unfunded: 360000, nav: 880000, nav_prev_quarter: 835000, q2_unrealised_gain: 31000, q2_paid_in: 96000, ownership_pct: 0.5, tvpi_est: 1.05 };
    wf.companies.forEach(c => c.look_through = Math.round(c.fair_value * wf.personal.nav / (wf.fund.nav || 175000000)));
    // ---- net worth series
    const nw = { 'Real estate': series, 'Securities': axis.map((m, i) => Math.round(positions.reduce((s, p) => s + p.qty * p.hist[i], 0))), 'Crypto': axis.map((m, i) => Math.round(holdings.reduce((s, h) => s + h.amount * h.hist[i], 0))), 'Cash': axis.map((m, i) => Math.round(bal.giro[i] + bal.tages[i] + bal.card[i] + 600 + 1200)), 'Private equity': axis.map((m, i) => m < '2022-09' ? null : Math.round(60000 + 820000 * Math.pow(Math.min(1, (i - 56) / (n - 57)), 1.3))) };
    const wiwin = { issuer: 'Demo Solar GmbH', platform: 'demo', invested: 50000, note: 'valued at cost' };
    const groups = [{ k: 'Real estate', v: est }, { k: 'Securities', v: dTot }, { k: 'Private equity', v: wf.personal.nav + wiwin.invested }, { k: 'Cash', v: totals.giro + totals.tages + totals.card + 600 + 1200 }, { k: 'Crypto', v: crypto.total_eur }];
    // fine-tune so the total lands at 10.0 M
    const sum0 = groups.reduce((s, x) => s + x.v, 0), adj = 10000000 - sum0; groups[0].v += adj; apartment.value_used = groups[0].v; apartment.estimate = groups[0].v; apartment.gain = apartment.estimate - ap0.purchase_price; apartment.gain_pct = Math.round(apartment.gain / ap0.purchase_price * 1000) / 10;
    nw['Real estate'][n - 1] = groups[0].v;
    const sources = { gls: { state: 'ok', live: false }, depot: { state: 'ok', live: true, n_live: positions.length, n_total: positions.length }, coinbase: { state: 'ok', live: true }, examplefund: { state: 'ok', live: false }, paypal: { state: 'ok', live: false }, apartment: { state: 'ok', live: false, model: true } };
    // ---- invented portfolio analysis + unusual bookings (same shape as analytics.py / unusual.py produce)
    const ddOf = a => { let pk = -1e18; return a.map(v => { pk = Math.max(pk, v); return v / pk - 1; }); };
    const gv = k => nw[k][n - 1] || 0, tg = ['Real estate', 'Securities', 'Private equity', 'Cash', 'Crypto'].reduce((a, k) => a + gv(k), 0);
    const tgt = { 'Real estate': [35, 28, 42], Securities: [40, 33, 47], 'Private equity': [12, 8, 15], Crypto: [5, 3, 8], Cash: [8, 5, 12] }, drift = {}, values = {};
    Object.keys(tgt).forEach(k => { const pc = gv(k) / tg * 100; values[k] = gv(k); drift[k] = { pct: pc, target: tgt[k][0], low: tgt[k][1], high: tgt[k][2], status: pc < tgt[k][1] ? 'under' : pc > tgt[k][2] ? 'over' : 'ok', diff_pp: pc - tgt[k][0] }; });
    const sH = positions.slice(0, 5).map(p => p.hist), secS = sH[0].map((_, i) => sH.reduce((a, h) => a + h[i], 0)), crS = holdings[0].hist.map((_, i) => holdings.reduce((a, h) => a + h.hist[i] * h.amount, 0)), tail = a => a.slice(-37);
    const rk = (a, vol, sh) => ({ vol, max_dd: Math.min(...ddOf(tail(a))), sharpe: sh, sortino: sh * 1.5, months: 36, dd_series: ddOf(tail(a)) });
    const unf = wf.personal.unfunded || 0, cash = gv('Cash');
    const analytics = { asof: now.toISOString().slice(0, 10), first_investment: { 'Real estate': '2019-04', Securities: axis[n - 60], 'Private equity': axis[n - 24], Cash: axis[0], Crypto: axis[n - 40] },
      performance: { securities: { price_return: .52, xirr: .118, xirr_since: axis[n - 60] + '-01', bench_return: .47, excess_pp: 5, bench_name: 'iShares Core MSCI World', months: 60 }, crypto: { gain_pct: crypto.gain_pct, gain: cGain, cost: cCost, status: 'ok' },
        contributions: positions.slice(0, 8).map(p => ({ name: p.name, wkn: p.wkn, gain: p.gain, gain_pct: p.gain_pct, share_pp: Math.round(p.gain / depot.cost * 1000) / 10 })), crypto_contributions: holdings.map(h => ({ name: h.currency, gain: h.gain, gain_pct: h.gain_pct })), basis: 'estimate', len: 60 },
      risk: { securities: rk(secS, .17, .74), crypto: rk(crS, .62, .55), combined: rk(secS.map((v, i) => v + crS[i]), .2, .81), benchmark: rk(sH[1].map(v => v * 1.01), .15, .8), corr: { 'Position A': { 'Position A': 1, Crypto: .31, Index: .82 }, Crypto: { 'Position A': .31, Crypto: 1, Index: .36 }, Index: { 'Position A': .82, Crypto: .36, Index: 1 } }, stress: { loss_eur: -Math.round(tg * .17), pct_of_gross: -.17, by_class: { 'Real estate': -Math.round(gv('Real estate') * .15), Securities: -Math.round(gv('Securities') * .3), 'Private equity': -Math.round(gv('Private equity') * .3), Cash: 0, Crypto: -Math.round(gv('Crypto') * .6) } }, rf: .02, basis: 'model', len: 36 },
      exposure: { top: positions.slice(0, 5).map(p => ({ name: p.name, weight: p.value / dTot })), effective_n: 9.4, hhi: 1060, by_class: [{ k: 'Stock', v: dTot * .7 }, { k: 'ETF', v: dTot * .3 }], by_theme: [{ k: 'Tech', v: dTot * .4 }, { k: 'Other', v: dTot * .6 }], by_country: { USA: .58, Germany: .14, Netherlands: .08, Others: .2 }, by_sector: { Technology: .36, Financials: .14, Health: .12, Industrials: .1, Other: .28 }, by_currency: { USD: .62, EUR: .3, Other: .08 }, lookthrough: positions.slice(0, 6).map(p => ({ name: p.name, symbol: '', weight: p.value / dTot * .6 })), coverage: { country: 1, sector: 1, currency: 1, ter: .6 }, basis: 'live', len: null },
      allocation: { drift, values, basis: 'live', len: null },
      liquidity: { ladder: [{ label: 'Within a week', eur: cash + gv('Securities') + gv('Crypto'), parts: ['Cash', 'Securities', 'Crypto'] }, { label: '6-12 months (sale of the apartment)', eur: gv('Real estate'), parts: ['Real estate'] }, { label: 'Fund term (demo)', eur: wf.personal.nav, parts: ['Example Fund'] }, { label: 'No market (wiwin)', eur: wiwin.invested, parts: ['wiwin'] }], unfunded_wf: unf, cash_cover: unf ? cash / unf : null, basis: 'model', len: null },
      private_equity: { tvpi: wf.fund.tvpi, dpi: 0, rvpi: wf.fund.tvpi, irr: wf.fund.net_irr, personal: { nav: wf.personal.nav, paid_in: wf.personal.paid_in, unfunded: unf, commitment: wf.personal.commitment }, points: [{ label: '31 Dec 2025', tvpi: .94 }, { label: 'Q2 2026', tvpi: wf.fund.tvpi }], basis: 'live', len: 2 },
      costs: { ter_pct: .21, ter_eur: Math.round(dTot * .0021), coverage: .6, yield: 1.2, yield_on_cost: 1.9, basis: 'estimate', len: null },
      tax: { realised_by_year: { 2025: 6200 }, allowance: { used: 1000, left: 0, taxable: 5200, year: now.getFullYear() }, unknown_cost_sales: 0, note: 'Demo: invented numbers.', basis: 'estimate', len: null },
      real: { nominal_change: .05, real_change: .026, gross_real: axis.slice(-13).map((_, i) => tg * (.95 + i * .0066)), cpi: axis.slice(-13).map((_, i) => 100 + i * .2), basis: 'estimate', len: 13 } };
    const unusual = [{ date: axis[n - 1] + '-04', merchant: 'Autohaus Demo GmbH', amount: -2890, reasons: ['spike'], detail: '6.2x the usual 465 EUR for Mobility' }, { date: axis[n - 1] + '-02', merchant: 'Boutique Beispiel', amount: -640, reasons: ['new_merchant'], detail: 'first booking from this merchant' }, { date: axis[n - 2] + '-27', merchant: 'Streaming Demo', amount: -17.99, reasons: ['price_rise'], detail: 'price up 12.5 % (15.99 -> 17.99 EUR)' }, { date: axis[n - 2] + '-19', merchant: 'Hotel Beispiel', amount: -420, reasons: ['duplicate'], detail: 'same amount 1 day(s) after ' + axis[n - 2] + '-18' }];
    return { analytics, unusual, mode: 'demo', generated: now.toISOString(), owner: 'DEMO', axis, totals: Object.assign(totals, { groups, liabilities: 0 }), nw, gls: { accounts, recent, runway_months: 54 }, flows, balances: bal, depot, crypto, examplefund: wf, paypal: { balance: 1200, asof: now.toISOString().slice(0, 10) }, wiwin, apartment, income_est: { yearly: 46000, monthly: 3833, covered: positions.length, total_positions: positions.length, items: positions.slice(0, 6).map(p => ({ n: p.name, wkn: p.wkn, v: Math.round(p.value * .012) })), note: 'Demo: invented dividend yield of about 1.2 %.' }, tax: { rate_pct: 26.375, allowance: 1000 }, sources, alerts: [{ level: 'info', text: 'DEMO MODE: all numbers are invented. Click "Real numbers" and enter your PIN.' }], snapshots: [], reminder: { text: 'Monthly reminder (demo)', day_of_month: 1 }, reminders: { month: now.toISOString().slice(0, 7), any_due: true, items: [{ key: 'gls', source: 'GLS Bank', what_to_download: 'GLS Umsaetze CSV for all accounts', folder_key: 'gls_dir', latest: '2026-09-30', due: true, days_old: 38, accounts: [{ name: 'GLS Giro', last: '2026-09-30' }, { name: 'GLS Tagesgeld', last: '2026-09-28' }] }, { key: 'depot', source: 'GLS Depot', what_to_download: 'GLS Depotbestand CSV', folder_key: 'gls_dir', latest: '2026-10-31', due: false, days_old: 7 }, { key: 'paypal', source: 'PayPal', what_to_download: 'PayPal Download.CSV activity export', folder_key: 'paypal_dir', latest: '2026-08-14', due: true, days_old: 85 }, { key: 'examplefund', source: 'Example Fund', what_to_download: 'Example Fund quarterly report PDF', folder_key: 'examplefund_dir', latest: '2026-06-30', due: false, days_old: 130 }] } };
  };
})();
