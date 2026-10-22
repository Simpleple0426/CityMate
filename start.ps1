param(
    [ValidateSet('start', 'stop')][string]$Action = 'start',
    [switch]$EnableModel
)
$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$stateFile = Join-Path $repo '.citymate-local.json'
if ($Action -eq 'stop') {
    if (Test-Path -LiteralPath $stateFile) {
        foreach ($entry in (Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json)) {
            $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
            if ($process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $entry.started) {
                Stop-Process -Id $process.Id
            }
        }
        Remove-Item -LiteralPath $stateFile
    }
    Write-Output 'CityMate local processes stopped. Database containers were not changed.'
    exit
}
if (Test-Path -LiteralPath $stateFile) { throw 'A local process record exists. Run with -Action stop before starting again.' }
foreach ($port in @(18000, 15173)) {
    if ([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port -contains $port) {
        throw "Port $port is already occupied. No process has been stopped."
    }
}
$python = Join-Path $repo '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { $python = Join-Path (Split-Path $repo -Parent) '.venv-citymate/Scripts/python.exe' }
if (!(Test-Path -LiteralPath $python)) { throw 'Create a Python 3.12 virtual environment and install backend/requirements.txt first.' }
$node = (Get-Command node.exe).Source
$vite = Join-Path $repo 'frontend/node_modules/vite/bin/vite.js'
if (!(Test-Path -LiteralPath $vite)) { throw 'Run npm ci in frontend first.' }
$logs = Join-Path $repo 'backend/logs/citymate'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$env:CITYMATE_DATABASE_URL = 'mysql+pymysql://citymate:citymate-local-only@127.0.0.1:13306/citymate?charset=utf8mb4'
$env:CITYMATE_REDIS_URL = 'redis://127.0.0.1:16379/0'
$env:CITYMATE_DEMO = 'true'
$env:PYTHONIOENCODING = 'utf-8'
$env:CITYMATE_MODEL_ENABLED = $EnableModel.IsPresent.ToString().ToLowerInvariant()
if (!$EnableModel) { $env:OPENAI_API_KEY = '' }
$processes = @()
try {
    $processes += Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'citymate.app:app', '--host', '127.0.0.1', '--port', '18000') -WorkingDirectory (Join-Path $repo 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'api.out.log') -RedirectStandardError (Join-Path $logs 'api.err.log')
    $processes += Start-Process -FilePath $python -ArgumentList @('-m', 'citymate.worker') -WorkingDirectory (Join-Path $repo 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'worker.out.log') -RedirectStandardError (Join-Path $logs 'worker.err.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:18000/health' -TimeoutSec 1
            if ($response.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (!$ready) { throw 'API did not become ready. Check backend/logs/citymate/api.err.log.' }
    $processes += Start-Process -FilePath $node -ArgumentList @(('"' + $vite + '"'), '--host', '127.0.0.1', '--port', '15173', '--strictPort') -WorkingDirectory (Join-Path $repo 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'web.out.log') -RedirectStandardError (Join-Path $logs 'web.err.log')
} finally {
    @($processes | ForEach-Object { @{ pid = $_.Id; started = $_.StartTime.ToUniversalTime().ToString('o') } }) | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
}
Write-Output 'CityMate started: http://localhost:15173 ; API docs: http://localhost:18000/docs'
Write-Output 'Local demo only. Use -Action stop to stop these three processes.'
