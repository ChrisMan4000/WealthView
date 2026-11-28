/* WealthView insurance box (v1.33): active insurances with timeline + monthly premium, 2-week reminder, click = summary + what is included / excluded.
   window.WVINS = { pIns(d), chip(d), tipItem(d), open(id) }. Data: d.insurance (refresh stage "insurance"; real data or demo). Uses the helpers WV exports. */
(function () {
  let shotOpened = false;
  const W = () => window.WV;
  const A2 = v => '<span class="amt">' + (v == null ? '–' : Number(v).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €') + '</span>';
  const dmy = s => s ? s.slice(8, 10) + '.' + s.slice(5, 7) + '.' + s.slice(0, 4) : '–';
  const today0 = () => { const t = new Date(); t.setHours(0, 0, 0, 0); return t; };
  /* days to the end date, counted in the browser every time (data.json may be a few days old) */
  const days = i => i.end ? Math.round((new Date(i.end + 'T00:00:00') - today0()) / 864e5) : null;
  const dueList = d => ((d.insurance && d.insurance.items) || []).filter(i => { const n = days(i); return n != null && n >= 0 && n <= ((d.insurance.remind_days) || 14); });
  const inTxt = n => n == null ? 'no end date' : n < 0 ? 'ended' : n === 0 ? 'ends today' : n === 1 ? 'ends tomorrow' : n < 60 ? 'ends in ' + n + ' days' : n < 700 ? 'ends in ' + Math.round(n / 30.4) + ' months' : 'ends in ' + (n / 365).toFixed(1) + ' years';
  const bar = (i, n, soon) => {
    const p = i.elapsed == null ? null : Math.max(0, Math.min(1, (today0() - new Date(i.term_start + 'T00:00:00')) / (new Date(i.end + 'T00:00:00') - new Date(i.term_start + 'T00:00:00'))));
    const c = soon ? 'var(--or)' : '#3cbeeb';
    return `<span class="bar" style="--c:${c};display:block">${p == null ? '' : `<i style="width:${(p * 100).toFixed(1)}%"></i>`}</span><small class="dim" style="display:block;margin-top:.15rem">${i.term_start ? dmy(i.term_start) + ' → ' : ''}${dmy(i.end)} · ${inTxt(n)}</small>`;
  };
  function pIns(d) {
    const w = W(), n = d.insurance; if (!n) return '';
    const items = n.items || [], esc = w.esc, A = A2;
    POST_hook(d);
    let body;
    if (!items.length) body = `<div class="empty dim" style="padding:.8rem">${n.configured ? 'No active insurance found in your insurance folder.' : 'No insurance folder yet. Press Setup at the top and add the folder(s) where your insurance papers are.'}</div>`;
    else body = `<div class="xs dim" style="margin:.1rem 0 .35rem">Per month <b class="wh">${A(n.monthly_total)}</b> · per year <b class="wh">${A(n.yearly_total)}</b> · ${items.length} active${n.ended ? ' · ' + n.ended + ' ended' : ''}</div>` +
      `<div style="overflow:auto;flex:1;min-height:0"><div class="tr th" style="grid-template-columns:2.4rem minmax(0,1.1fr) minmax(0,1.3fr) 4.4rem;cursor:default"><span></span><span>Insurance</span><span>Timeline</span><span class="r">Per month</span></div>` +
      items.map(i => { const dd = days(i), soon = dd != null && dd >= 0 && dd <= (n.remind_days || 14); return `<div class="tr ins-row${soon ? ' or' : ''}" data-ins="${esc(i.id)}" title="Click for summary and coverage" style="grid-template-columns:2.4rem minmax(0,1.1fr) minmax(0,1.3fr) 4.4rem;min-height:2.4rem"><span>${w.logo(i.logo, i.company, true)}</span><span class="nm"><span class="t">${esc(i.name)}<small>${esc(i.company)} · ${esc(i.kind || '')}</small></span></span><span>${bar(i, dd, soon)}</span><span class="r wh">${i.monthly != null ? A(i.monthly) : '–'}</span></div>`; }).join('') + '</div>';
    const warn = dueList(d).length ? badge2('warn', '▲ ' + dueList(d).length + ' ending soon') : '';
    return w.panel('pIns', 'Insurances <b>//</b> active contracts & premiums', warn + w.srcBadge('insurance', d), `<div style="display:flex;flex-direction:column;flex:1;min-height:0">${body}</div>`, { style: 'flex:2.2;min-height:19rem' });
  }
  const badge2 = (k, t) => `<span class="bd demo" style="color:var(--or)">${W().esc(t)}</span>`;
  function POST_hook(d) {
    W().POST.push(() => {
      W().$$('#pIns .ins-row').forEach(r => r.onclick = () => open(r.dataset.ins));
      const m = /[?&]insopen=(\d)/.exec(location.search);      /* screenshots only: ?shot=1&insopen=N opens the pop-up of row N */
      if (m && !shotOpened) { shotOpened = true; setTimeout(() => { const it = ((W().S.D || {}).insurance || {}).items || []; if (it[+m[1]]) open(it[+m[1]].id); }, 400); }
    });
  }
  function open(id) {
    const w = W(), d = w.S.D, n = d.insurance, i = n && n.items.find(x => x.id === id); if (!i) return;
    const esc = w.esc, A = A2, dd = days(i), soon = dd != null && dd >= 0 && dd <= (n.remind_days || 14);
    const li = a => a && a.length ? '<ul style="margin:.2rem 0 0 1.1rem;padding:0;line-height:1.5">' + a.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>' : '';
    const cov = (i.included && i.included.length) || (i.excluded && i.excluded.length)
      ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-top:.7rem"><div><h4 class="pos" style="margin:0 0 .3rem">✔ What is included</h4>${li(i.included) || '<span class="dim">not stated</span>'}</div><div><h4 class="neg" style="margin:0 0 .3rem">✖ What is excluded</h4>${li(i.excluded) || '<span class="dim">not stated</span>'}</div></div>`
      : `<p class="xs dim" style="margin-top:.7rem">The coverage table is not available yet: it is read by the local model (LM Studio). Open LM Studio (or click the Ask box), then press Refresh data.</p>`;
    const st = (a, b) => `<div>${a}<b>${b}</b></div>`;
    w.infoModal(esc(i.name), `<div style="display:flex;gap:.8rem;align-items:center;margin-bottom:.5rem">${w.logo(i.logo, i.company, true)}<div><b>${esc(i.company)}</b><div class="dim xs">${esc(i.kind || '')}${i.policy_no ? ' · policy ' + esc(i.policy_no) : ''}</div></div></div>` +
      `<div class="stats">${st('Premium', i.premium != null ? A(i.premium) + ' <span class="dim xs">' + esc(i.interval || '') + '</span>' : '–')}${st('Per month', i.monthly != null ? A(i.monthly) : '–')}${st('Since', dmy(i.start))}${st(i.auto_renew ? 'Renews / term ends' : 'Ends', '<span class="' + (soon ? 'or' : '') + '">' + dmy(i.end) + '</span>')}${st('Left', dd == null ? '–' : dd < 0 ? 'ended' : dd + ' days')}</div>` +
      `<h4 style="margin:.7rem 0 .2rem">Summary</h4><p style="margin:0;line-height:1.55">${esc(i.summary || 'No summary yet.')}</p>${cov}` +
      `<p class="xs dim" style="margin-top:.7rem">${i.auto_renew ? 'Renews by itself each year unless cancelled. ' : ''}${i.reader === 'bookings' ? 'Premium read from your bank bookings (no papers)' : `Read from ${i.n_files || '?'} file(s) in your insurance folder (read only), ${i.reader === 'model' ? 'analysed by the local model on this PC' : 'facts found by plain patterns'}`}${i.updated ? ', updated ' + esc(String(i.updated).slice(0, 10)) : ''}. Check the original papers before you rely on it.</p>`,
      d.mode === 'demo' ? w.badge('demo', 'Demo') : w.badge('model', i.reader === 'model' ? 'Local model' : i.reader === 'bookings' ? 'Bookings' : 'Patterns'));
  }
  /* top-bar chip + Smart suggestion: from 14 days before an insurance ends */
  function chip(d) {
    const nav = document.getElementById('nav'); if (!nav) return;
    let c = document.getElementById('insChip');
    if (!c) { c = document.createElement('button'); c.id = 'insChip'; c.style.cssText = 'display:none;color:var(--or);border-color:var(--or)'; nav.appendChild(c); }
    const due = dueList(d); if (!due.length) { c.style.display = 'none'; return; }
    const f = due.slice().sort((a, b) => days(a) - days(b))[0];
    c.style.display = 'inline-flex'; c.title = 'An insurance ends soon - click for details';
    c.textContent = '▲ INSURANCE ' + inTxt(days(f)).toUpperCase() + ': ' + (f.name.length > 22 ? f.name.slice(0, 20) + '…' : f.name);
    c.onclick = () => open(f.id);
  }
  function tipItem(d) {
    const due = dueList(d); if (!due.length) return null;
    return { l: 'warn', t: 'Insurance ending soon: ' + due.map(i => i.name + ' (' + dmy(i.end) + ')').join(', '), x: due.map(i => i.name + ' ' + inTxt(days(i)) + (i.auto_renew ? ' - it renews by itself unless you cancel before the end date' : ' - decide whether to renew or replace it')).join('. ') + '. Check the terms for the notice period.' };
  }
  window.WVINS = { pIns, chip, tipItem, open };
})();
