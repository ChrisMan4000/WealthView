# Opens WealthView in Firefox in your default browser (a normal window or tab). Starts the local server first if needed.
$ErrorActionPreference = 'SilentlyContinue'
# Minimize this PowerShell window right away (it stays in the taskbar, out of the way).
try {
  Add-Type -Namespace WV -Name Win -MemberDefinition '[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow(); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);'
  $h = [WV.Win]::GetConsoleWindow(); if ($h -ne [IntPtr]::Zero) { [void][WV.Win]::ShowWindow($h, 6) }
} catch {}
$d = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = $null
try { $cfg = Get-Content "$d\config.json" -Raw | ConvertFrom-Json } catch {}
$port = 0
try { $port = [int]$cfg.port } catch {}
if ($port -le 0) { $port = 8780 }
function Up { try { (Invoke-WebRequest "http://127.0.0.1:$port/api/ping" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } }
# LM Studio is NOT started here any more: the server starts it (start-lmstudio.ps1) only when you click the Ask box.
if (-not (Up)) {
  # the installer records the Python it checked (3.10+); one that winget has just installed may not be on PATH
  $py = $null
  $rec = "$d\setup-engine\python-path.txt"
  if (Test-Path $rec) { try { $p0 = (Get-Content $rec -TotalCount 1).Trim(); $pw = Join-Path (Split-Path $p0) 'pythonw.exe'; if (Test-Path $pw) { $py = $pw } elseif (Test-Path $p0) { $py = $p0 } } catch {} }
  if (-not $py) { $py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
  if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
  if ($py) { Start-Process $py -ArgumentList "`"$d\server.py`"" -WorkingDirectory $d -WindowStyle Hidden }
  for ($i = 0; $i -lt 40 -and -not (Up); $i++) { Start-Sleep -Milliseconds 300 }
}
$url = "http://127.0.0.1:$port/"
# Default browser (Firefox for you): opens a tab, or a normal window if the browser is closed. Never kiosk / fullscreen.
Start-Process $url
