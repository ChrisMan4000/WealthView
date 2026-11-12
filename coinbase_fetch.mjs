// Coinbase read-only balance fetch (CDP API key, Ed25519 / EdDSA JWT).
// Reads the key from the USER environment variables COINBASE_KEY_NAME / COINBASE_KEY_SECRET.
// Prints ONE line of JSON to stdout. Only GET requests are made - nothing can be traded or moved.
import crypto from 'node:crypto';

const NAME = process.env.COINBASE_KEY_NAME;
const SECRET = process.env.COINBASE_KEY_SECRET;
const HOST = 'api.coinbase.com';
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };

if (!NAME || !SECRET) out({ ok: false, error: 'COINBASE_KEY_NAME / COINBASE_KEY_SECRET not set' });

const b64u = (b) => Buffer.from(b).toString('base64url');

function privateKey() {
  const raw = Buffer.from(SECRET, 'base64');
  if (raw.length === 64 || raw.length === 32) {
    // Ed25519 secret: first 32 bytes are the seed
    const der = Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), raw.subarray(0, 32)]);
    return { key: crypto.createPrivateKey({ key: der, format: 'der', type: 'pkcs8' }), alg: 'EdDSA' };
  }
  throw new Error('unsupported key format (expected base64 Ed25519 secret)');
}
const K = privateKey();

function jwt(method, path) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: K.alg, typ: 'JWT', kid: NAME, nonce: crypto.randomBytes(16).toString('hex') };
  const payload = { sub: NAME, iss: 'cdp', nbf: now, exp: now + 120, uri: `${method} ${HOST}${path}` };
  const input = b64u(JSON.stringify(header)) + '.' + b64u(JSON.stringify(payload));
  return input + '.' + b64u(crypto.sign(null, Buffer.from(input), K.key));
}

async function get(pathWithQuery) {
  const path = pathWithQuery.split('?')[0];
  const r = await fetch('https://' + HOST + pathWithQuery, {
    headers: { Authorization: 'Bearer ' + jwt('GET', path), 'CB-VERSION': '2024-10-01', Accept: 'application/json' },
  });
  const text = await r.text();
  let j; try { j = JSON.parse(text); } catch { j = { raw: text.slice(0, 200) }; }
  if (!r.ok) throw new Error(`HTTP ${r.status} ${path}: ${JSON.stringify(j).slice(0, 160)}`);
  return j;
}

async function spot(cur) {
  if (cur === 'EUR') return 1;
  try {
    const r = await fetch(`https://${HOST}/v2/prices/${cur}-EUR/spot`);
    const j = await r.json();
    return parseFloat(j.data.amount);
  } catch { return null; }
}

// every account incl. empty ones: the purchases of coins that now sit in a staking wallet are in the regular (empty) wallet
let ALL = [];
const FIAT = new Set(['EUR', 'USD', 'GBP', 'CHF']);

async function viaV2() {
  const list = [];
  let next = '/v2/accounts?limit=100';
  for (let i = 0; i < 10 && next; i++) {
    const j = await get(next);
    list.push(...j.data);
    next = j.pagination && j.pagination.next_uri ? j.pagination.next_uri : null;
  }
  ALL = list.map(a => ({ id: a.id, currency: a.balance.currency }));
  const hold = [];
  for (const a of list) {
    const bal = parseFloat(a.balance.amount);
    if (!(bal > 0)) continue;
    const cur = a.balance.currency;
    const native = a.native_balance && a.native_balance.currency === 'EUR' ? parseFloat(a.native_balance.amount) : null;
    hold.push({ id: a.id, currency: cur, name: a.currency && a.currency.name || cur, amount: bal, eur: native });
  }
  return hold;
}

// Buys, sells and transfers of one account, flattened (the Python side maps them to trades, see lots.py).
async function transactionsFor(h) {
  const rows = [];
  let next = `/v2/accounts/${h.id}/transactions?limit=100`;
  for (let i = 0; i < 20 && next; i++) {
    const j = await get(next);
    for (const t of j.data || []) {
      rows.push({
        type: t.type, date: String(t.created_at || '').slice(0, 10),
        qty: parseFloat(t.amount && t.amount.amount),
        native: t.native_amount ? parseFloat(t.native_amount.amount) : null,
        native_cur: t.native_amount ? t.native_amount.currency : null,
      });
    }
    next = j.pagination && j.pagination.next_uri ? j.pagination.next_uri : null;
  }
  return rows;
}

async function viaV3() {
  const hold = [];
  let cursor = '';
  for (let i = 0; i < 10; i++) {
    const j = await get('/api/v3/brokerage/accounts?limit=250' + (cursor ? '&cursor=' + cursor : ''));
    for (const a of j.accounts || []) {
      const bal = parseFloat(a.available_balance.value) + parseFloat((a.hold && a.hold.value) || 0);
      if (bal > 0) hold.push({ currency: a.currency, name: a.name || a.currency, amount: bal, eur: null });
    }
    if (!j.has_next) break;
    cursor = j.cursor;
  }
  return hold;
}

try {
  let hold, source = 'v2';
  try { hold = await viaV2(); }
  catch (e1) { source = 'v3'; try { hold = await viaV3(); } catch (e2) { out({ ok: false, error: `${e1.message} | ${e2.message}` }); } }
  for (const h of hold) {
    if (h.eur == null) { const p = await spot(h.currency); h.eur = p == null ? null : h.amount * p; h.price = p; }
    else h.price = h.amount ? h.eur / h.amount : null;
  }
  hold.sort((a, b) => (b.eur || 0) - (a.eur || 0));
  // trade history (read-only GETs): 'no_permission' when the key may not read transactions, 'none' when only the v3 fallback worked
  let txs = {}, trades_status = 'none';
  if (source === 'v2') {
    trades_status = 'ok';
    const held = new Set(hold.map(h => h.currency));
    for (const a of ALL.filter(a => held.has(a.currency) && !FIAT.has(a.currency))) {
      try { txs[a.currency] = (txs[a.currency] || []).concat(await transactionsFor(a)); }
      catch (e) { trades_status = /HTTP 40[13]/.test(String(e.message)) ? 'no_permission' : 'error'; txs = {}; break; }
    }
  }
  const total = hold.reduce((s, h) => s + (h.eur || 0), 0);
  out({ ok: true, source, trades_status, txs, total_eur: Math.round(total * 100) / 100, holdings: hold.map(({ id, ...h }) => ({ ...h, eur: h.eur == null ? null : Math.round(h.eur * 100) / 100 })) });
} catch (e) {
  out({ ok: false, error: String(e.message || e).slice(0, 300) });
}
