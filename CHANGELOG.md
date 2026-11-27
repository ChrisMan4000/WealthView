# Changelog

The version number lives in one file, `version.js`, and is shown in the dashboard header, browser tab, intro, lock window and installer.

## v1.32 (2026-11-27)
- **LM Studio starts on click:** the local model (LM Studio + Gemma 4) is no longer started when WealthView opens. It starts only when you click the Ask box (new `POST /api/ask/start`; at most once a minute, skipped when it already runs). Opening the dashboard is now lighter when you do not use the chat.

## v1.31 (2026-11-24)
- **Bond pop-up:** shows key terms (rate, term, payouts, issuer rights), expected payouts, risks and a firm-health box when terms are configured; the Alternatives box shows the next payout. Hidden when no terms are set.
- **Groceries pop-up:** spending on online grocery orders, opened from the "Spending by category" box (needs imported order data; hidden otherwise).
- **FinTS bank sync (read-only):** optional "Bank via FinTS" step in the setup wizard with a how-to; the app can never send payments or transaction commands.
- Setup and installer fixes since v1.24; installer rebuilt at v1.31.

## v1.24 (2026-11-19)
- **Rating column** (Strong buy / Buy / Hold / Reduce / Sell) in the Securities and Crypto boxes: the same meta-score as the position pop-up, loaded in the background and remembered for 12 hours.
- **Chat:** answers may be twice as long (`max_tokens` 8192, `timeout_s` 360); a small "delete chat" button clears the chat and the model's memory of it (the X only hides it).

## v1.23 (2026-11-15)
- **House or apartment in Germany:** the value follows the Bundesbank's official house price index for the kind of area you pick (7 largest cities, other cities, towns and rural districts, Germany average); your own price per m² overrides it. Immowelt/ImmoScout are not used (no public interface).
- **Funds:** a folder of reports (CSV, PDF; unknown PDF layouts are read by your local LM Studio model and checked against the text), or the price by ISIN and units, or a typed value.

## v1.22 (2026-11-14)
- Typed assets count in the ring and allocation; real names and Yahoo symbols from the WKN (OpenFIGI); Coinbase read in plain Python (no Node.js); connection test button in Setup; pop-ups scale without scroll bars; boxes sit next to each other without gaps; the Ask box no longer invents rent income.

## v1.21 (2026-11-14)
- API connections for every kind of source (Coinbase, Binance, Kraken; keys in the Windows Credential Manager); larger small fonts for high-resolution screens; clearer apartment form; new animated installer logo and orange "Start WealthView" box.

## v1.20 (2026-11-13)
- **Setup screen** in the dashboard (Setup button): add, rename, re-point, switch off or remove banks, investments and crypto places; folder picker; sub-folder switch; no bank names built in.
- **Automatic CSV reader** for bank, card, depot and crypto exports of any layout, with one plain question when unsure (remembered per layout).
- **Typed-in assets:** house or apartment (value follows the Eurostat house price index, labelled "estimate", or your own value), loan (annuity), fund, other investment, and typed balances. They flow into net worth, totals and the new "Typed in" box. New server endpoints `/api/setup/*`.
- **Fix categories:** a correction is passed on to all bookings of the same company (except clearly different amounts); long lists update reliably; "Update dashboard now".
- Depot and crypto boxes for files read by the automatic reader (the old GLS / Coinbase setup is used first when present).
- `fund_title` setting for the fund panel name. Installer: no pre-filled bank names; texts point to Setup.
- Demo mode and the screenshots show invented fund figures; the fund is called "Example Fund".

## v1.19 (2026-11-13)
- Sources and accounts: the database now keeps a neutral list of *sources* (each thing you set up: a bank, an investment, a crypto place, with its folder or API) and of the *accounts* found inside them (current account, card, depot ...). Every booking, payment row and depot position points to its account. First step towards setting up any mix of banks and investments.
- Any number of source folders; sub-folders are read too (4 levels deep). An existing setup keeps reading exactly the same files as before.
- An existing database is upgraded automatically on the first refresh: a backup copy `data/wealthview.db.pre-accounts.bak` is written first, then everything changes in one step. If anything fails, nothing is changed and System status says "database upgrade postponed".
- System status shows the number of sources and accounts; its database line no longer names a bank.
- Ask answers show **bold** text as bold; small layout fix at the bottom of the grid.
- The dashboard is otherwise unchanged.

## v1.18 (2026-11-12)
- New logo "brain chart": a brain outline whose neurons are the points of a rising chart. New `icons/wealthview.ico` (16 to 256 px) and `icons/wealthview.png`, new installer corner image, new README banner (`assets/banner.png`). No code change.

## v1.17 (2026-11-12)
- Ask bar is now the last item of the centre column (no more overlay on the network map); the ring shrinks on short screens (minimum 12 rem). Mic and Ask buttons are stacked.
- Ask: `max_tokens` raised from 900 to 4096 and `timeout_s` set to 180, because thinking models spend the allowance on reasoning; empty replies now give a clear message plus a "Details:" line instead of "No answer."
- Pop-ups are half the screen wide (52 rem to 98 vw) and as tall as their content.
- Venture-fund overview shows companies in 4 rows.
- Installers: password minimum is 4 characters; two editions (public, private) from one codebase.

## v1.16 (2026-11-11)
- Windows installers (Inno Setup wizard) and an adaptive dashboard: `profile.json` decides which boxes a given installation shows.
- Source-plugin registry with a generic CSV column mapper; free-text password instead of a numeric PIN.
- Public payload built from an allowlist and checked by a leak scan before every release.
- First-refresh logo lookup from the user's own merchants, with a fail-closed privacy filter.

## v1.15 (2026-11-11)
- Cash-flow period selector and Sankey pop-up; editable category rules.
- Ask box knows the whole portfolio and can search the web using search words only.
- German tax model: full basic allowance, section 32a tariff, Günstigerprüfung, sale tax on owner-occupied property.

## v1.08 to v1.14
- Local SQLite database filled automatically from monthly downloads, folder watcher, "Over time" insights, Ask box on a local model, deny-by-default API gate, audit log, layered package layout, type annotations.

## v1.00 to v1.07
- Dashboard, local server, refresh pipeline, position pop-ups with research, wealth-manager analysis, Coinbase cost basis, world map of the app's own connections.
