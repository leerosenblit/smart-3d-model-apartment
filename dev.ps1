# Windows PowerShell launcher: starts FastAPI (:8000) and Vite (:5173).
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  Write-Host 'Creating backend virtualenv...'
  py -3.12 -m venv (Join-Path $root 'backend\.venv')
  & $py -m pip install -q -r (Join-Path $root 'backend\requirements.txt')
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
  Push-Location (Join-Path $root 'frontend'); npm install --no-audit --no-fund; Pop-Location
}
$api = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $root 'backend') $py '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--reload'
$web = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $root 'frontend') 'npm.cmd' 'run','dev','--','--host','127.0.0.1'
Write-Host 'API: http://localhost:8000   Frontend: http://localhost:5173   (Ctrl+C to stop)'
try { Wait-Process -Id $api.Id, $web.Id -ErrorAction SilentlyContinue; while (-not $api.HasExited -and -not $web.HasExited) { Start-Sleep 1 } }
finally { foreach ($p in $api, $web) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } } }
