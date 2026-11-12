# Changelog

The version number lives in one file, `version.js`, and is shown in the dashboard header, browser tab, intro, lock window and installer.

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
