# WealthView – Technical Architecture

**Version v1.20 · 2026-11-13.** The version number lives in one file, `version.js`, and is shown in the dashboard header, browser tab, intro, lock window, installer, `data.json` and the READMEs.

## 1. Overview
WealthView is a local web application. The dashboard is a single HTML page drawn with plain JavaScript (SVG charts, canvas map, no framework, no build step). It is served to your browser by a small Python program (standard-library `http.server`) that listens on `127.0.0.1` only (default port 8780). The Python side reads bank and broker exports into a local SQLite database, adds public market data, computes every dashboard number into one `data.json`, and hands it to the page only after the password was entered. Nothing is uploaded.

## 2. Technologies
| Layer | Technology | Files |
|---|---|---|
| Front end | HTML, CSS, vanilla JavaScript; SVG and Canvas 2D | `wealthview.html`, `wv.js`, `analytics.js`, `insights.js`, `catrules.js`, `flowpop.js`, `layout.js`, `wv_demo.js`, `wv-intro.js`, `version.js` |
| Server | Python 3.10+, standard library only | `server.py` (launcher), `wealthview/app/` |
| Data pipeline | Python 3.10+, standard library only | `refresh.py` (launcher), `wealthview/app/refresh*.py`, `wealthview/data/`, `wealthview/analysis/` |
| Database | SQLite via `sqlite3`, one file, no server | `wealthview/data/ingest/db_*.py`, `data/wealthview.db` |
| Ask box | Local LM Studio server (OpenAI-compatible API on `127.0.0.1:1234`) | `wealthview/analysis/ask.py`, `start-lmstudio.ps1` |
| Coinbase | Node.js 18+ script, signed read-only request | `coinbase_fetch.mjs` |
| Automation | PowerShell | `start-wealthview.ps1`, `start-lmstudio.ps1` |

## 3. Processes
```
Desktop shortcut -> start-wealthview.ps1 -> (background) start-lmstudio.ps1 (only if LM Studio is not running)
                                         -> python server.py (hidden, 127.0.0.1) -> default browser opens the dashboard

Browser (dashboard) <-> server.py --> refresh.py (subprocess: on demand, every 5 min "--quick", and when new files appear)
                          |            |- db_import.sync: new files in your source folders -> wealthview.db (files are only read)
                          |            |- market data (Yahoo Finance, Google News)
                          |            '- coinbase_fetch.mjs (optional) -> Coinbase API
                          |          '-> data.json (+ daily snapshot in wealthview.db)
                          '- /api/ask -> ask.py -> read-only SQL on wealthview.db <-> local model
```
- **Lifetime:** the server is not started at Windows logon. The shortcut starts it; it stops itself shortly after the last dashboard page is closed (heartbeat/goodbye). `"auto_stop": false` in `config.json` keeps it running.
- **Folder watcher:** once a minute the server compares a cheap signature of the watched folders with the stored one and runs a full refresh by itself when new downloads appear (`auto_import`, `watch_seconds`). It backs off after failures.
- **Quick refresh** (every 5 minutes) updates only live prices and Coinbase and saves today's snapshot.

## 4. Code layout
```
server.py, refresh.py   launchers in the main folder
wealthview/
  common/    shared basics (paths, config, run context, parse cache, safe network helpers, audit log, types/)
  data/
    ingest/  files, database and web lookups; plugins/ = source plugins (gls, gls_depot, paypal, coinbase, csv)
    finance/ the money model (bookings, categories, lots, positions, models)
  analysis/  totals, analytics, insights, unusual bookings, research, Ask
  app/       the two programs: server (routing, auth, lifetime, jobs) and refresh (stage list + I/O stages)
```
The folders form layers: `app -> analysis -> data (finance -> ingest) -> common`. Nothing imports in the other direction, so there are no import cycles. Everything the server changes while it runs hangs on one object (`server.STATE`); `common/config.py` is the only reader of `config.json`.

## 5. Server endpoints
| Path | Auth | Purpose |
|---|---|---|
| `/`, `/*.js`, `/land-110m.json` | none | dashboard files (static whitelist) |
| `/api/ping`, `/api/hb`, `/api/bye`, `/api/unlock` | none | health, page heartbeat, goodbye, sign-in |
| `/api/real`, `/api/refresh`, `/api/quick`, `/api/live` | token | your data and refreshes |
| `/api/research`, `/api/company`, `/api/logo` | token | on-click lookups for one security or company |
| `/api/ask`, `/api/ask/status` | token | question answered by the local model |
| `/api/cat/overview`, `/api/cat/set`, `/api/cat/delete` | token | editable category rules |
| `/api/unusual_seen`, `/api/profile`, `/api/netlog`, `/api/lock` | token | dismissed alerts, installation profile, connection log, end session |
| any other `/api/...` | token | deny by default |

Status contract: `401` locked, `403` wrong `Host`, `404` unknown route or file, `429` password lock-out. Domain failures answer `200` with `{ok: false, error}`.

## 6. Dashboard
`wv.js` is one IIFE with state `S`, panel builders and `renderAll()`. `layout.js` picks the boxes from the installation profile and the window size (1 to 5 columns). Charts are SVG (`drawTS`, `posChart`, donuts, treemap heatmap). Pop-ups are half the screen wide and as tall as their content. Demo mode shows invented numbers from `wv_demo.js` with clearly labelled EXAMPLE content; real data is never embedded in the HTML.

## 7. Data pipeline
1. `db_import.sync()` imports new files from the watched folders into SQLite (recognised by content hash, overlapping exports merged row by row, unreadable files retried later).
2. `refresh.py` runs an explicit `STAGES` list: database, bookings, depot with trades, daily snapshot, totals, analytics, insights, write `data.json`. Optional stages degrade to a status line instead of stopping the refresh.
3. Source plugins (`detect(path, head)` + `parse(path)`) turn exports into booking rows; a generic CSV plugin maps columns by configuration or a guess from header names.
4. A parse cache keeps parsed files keyed by path, size and modification time, so a refresh reads only new or changed files.
5. Update reminder: per source, the newest data date and whether new files are due; shown as a chip and the first suggestion.

## 8. Database
One SQLite file `data/wealthview.db`: `bookings`, `paypal_tx`, `depot_positions`, `trades`, `snapshots` (day, scope, key, value), `spending`, `monthly`, `files`, `file_seen`, `meta`, and since v1.19 `sources` and `accounts` (plus the still empty `manual_assets`, `valuations`, `formats`, `questions` for later versions). Imported tables can be rebuilt from your downloads, but **daily snapshots exist nowhere else**: back the file up. It is not encrypted.

**Sources and accounts (v1.19).** A *source* is one thing the user set up (name, section bank / investment / crypto, type folder / api / manual, folder, reader, options). An *account* is what is found inside a source (kind bank / card / depot / crypto / property / loan / fund / other, an identifier such as the IBAN, currency). One folder can hold several accounts, which is why the two are separate. `bookings.account_id`, `paypal_tx.account_id` and `depot_positions.account_id` point to `accounts.id`; `files.source_id` points to `sources.id`. Code: `data/ingest/db_accounts.py`.

**Schema version and upgrade.** `meta.schema_version` is 2 from v1.19 on; a new database starts there. An older database is upgraded once at the start of a refresh (`data/ingest/db_migrate.py`): backup copy `data/wealthview.db.pre-accounts.bak`, then one transaction that creates the sources from the folders the old version imported, one account per IBAN, links every row and rebuilds `depot_positions` with the key `(account_id, asof, wkn)`. Any error rolls everything back; the refresh continues in the old shape and reports "database upgrade postponed".

**Import from sources.** `db_import` lists the files of all active folder sources by their reader, including sub-folders (4 levels, at most 500 folders per source; hidden folders and links are skipped). A file reachable from two sources belongs to the first; an IBAN is always one account. A source whose folder is missing is reported by name and the others continue. Sources created by the upgrade keep the old reading rules, so the same files are read as before.

## 9. Ask box
Page -> `POST /api/ask` -> `ask.answer()` -> local model. The model replies with one SQL `SELECT` or a final answer; the server runs the query (at most a few rounds) and feeds the result back. Guard, enforced server-side: read-only connection, SQLite authorizer allowing only reads, internal tables unreadable, one statement, row and size limits, time limit. The model may request a web search; only the search words leave the PC. `ask.max_tokens` (4096) and `ask.timeout_s` (180) are configurable; an empty reply from a thinking model produces a clear message with a "Details:" line.

## 10. Outbound connections and network log
All outbound traffic goes through one module (`safenet`). The complete list:
| Host | What is sent | Purpose |
|---|---|---|
| `query1/query2.finance.yahoo.com`, `fc.yahoo.com` | ticker symbols | quotes, history, analyst data |
| `news.google.com` | company or security name | headlines (RSS) |
| `www.wikidata.org`, company websites | company name | company pop-ups (on click) |
| `ec.europa.eu` (Eurostat) | nothing personal | inflation index |
| `ip-api.com` | server IP address | place of a connection on the map |
| `icons.duckduckgo.com`, `www.google.com/s2/favicons`, `assets.coincap.io`, `raw.githubusercontent.com` | merchant domains, coin symbols | logos (off with `"logo_lookup": false`) |
| `html.duckduckgo.com` | search words only | only when the Ask box asks for a web search |
| `api.coinbase.com` | signed read-only request | Coinbase balances, only if you add a key |

`netlog.install()` records host and time of each outbound request started by WealthView (never the full URL or content) in `data/netlog.jsonl`; the dashboard map reads it by long poll. Place lookup order: cache, optional offline DB-IP file, ip-api.com (sends only the server IP), small built-in table.

## 11. Security model
- Password: free text, stored as a salted PBKDF2-SHA256 hash (`pin_hash` in `config.json`). The installer asks for 4 to 1024 characters; `python server.py --set-pin` accepts any non-empty password (choose a strong one). After 5 wrong tries the app locks for a minute. It is a convenience lock, not encryption.
- **Deny by default:** every `/api/` route needs a session token unless it is on a short public list. Tokens live in the browser tab only and can be revoked (`/api/lock`).
- The server binds to `127.0.0.1` and checks the `Host` header.
- All web access goes through one module that opens only `http`/`https` URLs, refuses DTD/entity XML and refuses local or internal addresses (also after DNS resolution).
- Source folders are only read. WealthView writes only in its own folder (`data/`, `logos/`, logs).
- `data/audit.log` records unlocks, failures, lock-outs, refreshes and question lengths; never the password, a token or question text.
- Coinbase: a view-only key in Windows user variables, never in a file.

## 12. Configuration
`config.default.json` is copied to `config.json` on install. Main keys: `port`, `refresh_minutes`, `quick_refresh_seconds`, `targets` (target allocation with bands), `stress` (shocks), `unusual` (thresholds), `index_benchmark`, `tax` (rate, allowance), `ask` (url, model, limits), `auto_import`, `watch_seconds`, `logo_lookup`, `debug`. Source folders and optional modules (venture fund, crowd investment, apartment, loan) are set per installation and are empty by default.

## 13. Installers (v1.16+)
Two Windows installers are built from one codebase with Inno Setup 6 and a Python engine: a **public** edition (this repo's release asset, contains no personal data) and a private edition kept by the author. The public payload is assembled from an allowlist and checked by a leak scan before each build. The wizard checks the PC (Python, hardware tier, optional LM Studio and model), asks for source folders per bank, residence, optional chat and a password, then writes `config.json` and `data/profile.json` (edition, screen tier, asset classes, sources, modules). The installer is not code-signed.

## 17. Setup, automatic reader and typed assets (v1.20)
* **Data model** (database schema 2, filled from v1.20): `sources` (what you set up), `accounts` (found inside a source), `manual_assets(account_id, fields JSON)` (typed house, loan, fund, other), `valuations(account_id, date, value, basis)` (typed balances), `formats` (layouts learned from your answers), `questions`, `crypto_tx`.
* **Automatic reader** (`data/ingest/autoread.py`, `db_auto.py`, `db_questions.py`, `db_common.py`): recognises bank, card, depot, trades and crypto files from their contents, finds the account (IBAN or card number), imports into the database and, when unsure, files one plain question. An answer is stored as a format and applies to every file with the same columns.
* **Typed assets** (`data/finance/assets.py`, `data/ingest/db_assets.py`): validation with German or English numbers and dates; `property_series` follows the Eurostat `prc_hpi_q` index from the purchase quarter (live response tolerated by a lenient JSON-stat parser, any failure = flat line labelled "purchase price"); `loan_model` is an annuity; `fund_model` is paid-in at cost or typed value; `build_assets_block` makes the `assets` block of `data.json` (`property`, `loans`, `funds`, `other`, `balances`, `totals`). Only the two-letter country code goes to Eurostat.
* **Into the numbers:** refresh stage `stage_assets` (after the apartment and loan models) -> `assets.add_to_nw` (property to Real estate, funds to Securities, other to Private equity, loans to the loan series) and `compute_totals` (groups, liabilities, typed cash). No `assets` key when nothing is typed in, so an existing `data.json` is unchanged.
* **Setup API** (`data/ingest/db_setup.py`, server handlers `_api_setup_*`): `GET /api/setup/state`, `GET /api/setup/browse?path=` (folder names and the number of CSV files only, `common/folderbrowse.py`), `POST /api/setup/source|asset|balance|answer`. Failures come back as `{ok:false, error:<plain sentence>}`. `/api/profile` merges the asset classes implied by the setup and the `typed` flag, so a bank added in the dashboard switches the cash boxes on.
* **Dashboard:** `setup.js` (window `WVS`), box `typed` (`pTyped`, column 4, only with `profile.typed` and an `assets` block).
* **Fix categories** (`data/finance/catrules.py`): `correct_booking` = `apply_to_similar` + single-booking override. A sibling follows when it is the same merchant, was in the same category as the corrected booking before, was not fixed by hand and its amount is within 1/5 to 5 times; the others stay.
* **Not in v1.20:** depot and crypto files stored by the automatic reader have no boxes of their own yet; installer wizard pages for other investments and crypto API (use Setup in the dashboard).
