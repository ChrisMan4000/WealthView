/* WealthView layout rules: which boxes the dashboard shows for a profile and a screen. Pure functions (no DOM), so node can test them.
   window.WVL = { pickBoxes(profile, viewport) -> ordered box ids, columns(profile, viewport) -> number, place(), domIds(), homePoint(), LEGACY }
   viewport = { w, h } in CSS pixels. */
(function (root) {
  /* The box table. `col` = the column (DOM id) the box lives in; the order of this table is the order inside the column (= v1.15 renderAll).
     needs: ALL must hold; any: at least one must hold. A need is an asset class (cash, securities, privateEquity, realEstate, crypto),
     an optional module (examplefund, wiwin, loan, apartment) or 'chat'. dom = the element ids wv.js writes for the box. */
  const BOXES = [
    { id: 'sources', col: '#c5', dom: ['pSrc'] },
    { id: 'tips', col: '#c5', dom: ['pTips'] },
    { id: 'unusual', col: '#c5', needs: ['cash'], dom: ['pUnusual'] },
    { id: 'recent', col: '#c5', needs: ['cash'], dom: ['pRec'] },
    { id: 'top', col: '#c2', needs: ['cash'], dom: ['pTop'] },
    { id: 'spend', col: '#c2', needs: ['cash'], dom: ['pSpend'] },
    { id: 'flow', col: '#c2', needs: ['cash'], dom: ['pFlow'] },
    { id: 'ring', col: '#center', dom: ['ringWrap', 'kpiRow'] },
    { id: 'gross', col: '#center', dom: ['pGross'] },
    { id: 'time', col: '#center', dom: ['pTime'] },
    { id: 'map', col: '#center', dom: ['pMap'] },
    { id: 'depot', col: '#c1', needs: ['securities'], dom: ['pDepot'] },
    { id: 'alloc', col: '#c1', needs: ['securities'], dom: ['pAlloc'] },
    { id: 'examplefund', col: '#c4', needs: ['privateEquity', 'examplefund'], dom: ['pWF'] },
    { id: 'crypto', col: '#c4', needs: ['crypto'], dom: ['pCB'] },
    { id: 'alt', col: '#c4', any: ['wiwin', 'loan'], dom: ['pAlt'] },
    { id: 'chat', col: null, needs: ['chat'], dom: [] },            // the ask bar: fixed under the grid, not inside a column
    { id: 'empty', col: '#center', dom: ['pEmpty'], only: true }     // never picked by the rules: shown alone when there is nothing to show
  ];
  const COLUMNS = ['#c5', '#c2', '#center', '#c1', '#c4'];            // left to right on the ultra-wide screen (v1.15: 5, 2, 3, 1, 4)
  const CLASSES = ['realEstate', 'securities', 'privateEquity', 'cash', 'crypto'];
  const MODULES = ['examplefund', 'wiwin', 'loan', 'apartment'];
  const LEGACY = { edition: 'private', tier: 'ultrawide', asset_classes: CLASSES.slice(), sources: [], modules: { examplefund: true, wiwin: true, loan: true, apartment: true }, tax_country: 'DE', home: {}, chat: true, jarvis_url: null };

  /* tiers = the responsive rules of wealthview.html: wider than 22:10 = fixed 5-column screen; otherwise stacked with 4 columns,
     2 columns up to 1900 px wide and 1 column up to 900 px */
  const RANK = { compact: 0, laptop: 1, desktop: 2, ultrawide: 3 }, COLS = { compact: 1, laptop: 2, desktop: 4, ultrawide: 5 };
  function viewportTier(vp) {
    if (!vp || !(vp.w > 0) || !(vp.h > 0)) return 'ultrawide';
    if (vp.w / vp.h > 22 / 10) return 'ultrawide';
    return vp.w <= 900 ? 'compact' : vp.w <= 1900 ? 'laptop' : 'desktop';
  }
  /* the tier in effect: the screen's, but never wider than the tier the installer chose */
  function tierOf(profile, vp) {
    const a = viewportTier(vp), b = profile && RANK[profile.tier] != null ? profile.tier : 'ultrawide';
    return RANK[a] <= RANK[b] ? a : b;
  }
  function has(profile, need) {
    if (need === 'chat') return !!profile.chat;
    if (MODULES.indexOf(need) >= 0) return !profile.modules || profile.modules[need] !== false;      // a module is on unless the profile switches it off
    return (profile.asset_classes || []).indexOf(need) >= 0;
  }
  const wanted = (b, profile) => !b.only && (b.needs || []).every(n => has(profile, n)) && (!b.any || b.any.some(n => has(profile, n)));

  /* [{ dom: '#c5', boxes: ['sources', ...] }, ...] in column order; chat is not a column box */
  function place(profile, vp) {
    profile = profile || LEGACY;
    if (!(profile.asset_classes || []).length) return COLUMNS.map(c => ({ dom: c, boxes: c === '#center' ? ['empty'] : [] }));
    return COLUMNS.map(c => ({ dom: c, boxes: BOXES.filter(b => b.col === c && wanted(b, profile)).map(b => b.id) }));
  }
  function pickBoxes(profile, vp) {
    profile = profile || LEGACY;
    if (!(profile.asset_classes || []).length) return ['empty'];
    const ids = [].concat.apply([], place(profile, vp).map(c => c.boxes));
    BOXES.forEach(b => { if (b.col === null && wanted(b, profile)) ids.push(b.id); });
    return ids;
  }
  const columns = (profile, vp) => COLS[tierOf(profile || LEGACY, vp)];
  const domIds = id => { const b = BOXES.find(x => x.id === id); return b ? b.dom.slice() : []; };
  /* the home point of the world map: profile.home = { lat, lon, label } when set, else null (= today's behaviour: the server's config home) */
  function homePoint(profile) {
    const h = profile && profile.home; if (!h || typeof h !== 'object') return null;
    const lat = Number(h.lat), lon = Number(h.lon);
    if (h.lat == null || h.lon == null || !isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return { name: String(h.label || 'Home'), lat, lon };
  }

  const WVL = { pickBoxes, columns, place, domIds, homePoint, tierOf, LEGACY, BOXES };
  if (typeof module !== 'undefined' && module.exports) module.exports = WVL;
  if (root) root.WVL = WVL;
})(typeof window !== 'undefined' ? window : null);
