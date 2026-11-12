# Makes sure LM Studio (the local model that answers the Ask box) is running; if it is not, starts its server and loads Gemma 4.
# Called in the background by start-wealthview.ps1, so the dashboard opens at once. Log: lmstudio_start.log. Settings: config.json -> "ask".
$ErrorActionPreference = 'SilentlyContinue'
$d = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Get-Content "$d\config.json" -Raw | ConvertFrom-Json
$ask = $cfg.ask
if ($ask -and $ask.start_lmstudio -eq $false) { exit 0 }
$url = if ($ask.url) { [string]$ask.url } else { 'http://127.0.0.1:1234/v1' }
$match = if ($ask.model_match) { [string]$ask.model_match } else { 'gemma[-_ ]?4' }
$log = "$d\lmstudio_start.log"
function Log($m) { if ($m) { "$(Get-Date -Format 's') $m" | Add-Content -Path $log -Encoding UTF8 } }
function Up { try { (Invoke-WebRequest "$url/models" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }

if (Up) { Log 'LM Studio is already running - nothing to do'; exit 0 }

# find the lms command line tool that ships with LM Studio
$lms = $null
if ($ask.lms_path -and (Test-Path $ask.lms_path)) { $lms = [string]$ask.lms_path }
if (-not $lms) { $c = Get-Command lms.exe -ErrorAction SilentlyContinue; if ($c) { $lms = $c.Source } }
if (-not $lms -and (Test-Path "$env:USERPROFILE\.lmstudio\bin\lms.exe")) { $lms = "$env:USERPROFILE\.lmstudio\bin\lms.exe" }
if (-not $lms) { Log 'lms.exe not found - start LM Studio yourself, or set ask.lms_path in config.json'; exit 1 }

Log "LM Studio is not running - starting its server with $lms"
(& $lms server start 2>&1 | Out-String).Trim() | ForEach-Object { Log $_ }
for ($i = 0; $i -lt 45 -and -not (Up); $i++) { Start-Sleep -Seconds 1 }
if (-not (Up)) { Log 'server did not answer within 45 s - giving up (open LM Studio by hand)'; exit 3 }

# the downloaded model whose name matches (default: Gemma 4)
$key = $null
try {
  $items = (& $lms ls --json 2>$null | Out-String) | ConvertFrom-Json
  $hit = $items | Where-Object { ($_.modelKey + ' ' + $_.path) -match $match -and $_.type -ne 'embedding' } | Select-Object -First 1
  if ($hit) { $key = if ($hit.modelKey) { [string]$hit.modelKey } else { [string]$hit.path } }
} catch {}
if (-not $key) {
  $line = (& $lms ls 2>$null) | Where-Object { $_ -match $match } | Select-Object -First 1
  if ($line) { $key = ([string]$line).Trim() -split '\s+' | Select-Object -First 1 }
}
if (-not $key) { Log "no downloaded model matching '$match' - download Gemma 4 in LM Studio once"; exit 2 }

Log "loading $key"
(& $lms load $key --yes 2>&1 | Out-String).Trim() | ForEach-Object { Log $_ }
Log 'done'
