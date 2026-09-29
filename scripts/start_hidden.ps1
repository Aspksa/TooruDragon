$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"

function Find-Python{
    $p=Join-Path $Root "runtime\python\python.exe"
    if(Test-Path $p){return $p}
    try{$x=& python -c "import sys;print(sys.executable)" 2>$null;if($LASTEXITCODE -eq 0){return $x.Trim()}}catch{}
    try{$x=& py -3 -c "import sys;print(sys.executable)" 2>$null;if($LASTEXITCODE -eq 0){return $x.Trim()}}catch{}
    return $null
}
function Port-Up([int]$port){
    try{Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $port) -TimeoutSec 1|Out-Null;return $true}catch{return $false}
}

$python=Find-Python
if(-not $python){exit 10}
& $python "scripts\init_db.py"
if($LASTEXITCODE -ne 0){exit 20}
& $python "scripts\desired_state.py" running --all
if($LASTEXITCODE -ne 0){exit 21}

if(-not(Port-Up 8699)){
    Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root "supervisor\app.py")) -WorkingDirectory $Root -WindowStyle Hidden
}

$services=@(
    @{Port=8701;Path="core\tooru_ai\app.py"},
    @{Port=8702;Path="core\workshop\app.py"},
    @{Port=8703;Path="core\home\app.py"},
    @{Port=8704;Path="core\work\app.py"},
    @{Port=8705;Path="core\mobile\app.py"}
)
foreach($service in $services){
    if(-not(Port-Up $service.Port)){
        Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root $service.Path)) -WorkingDirectory $Root -WindowStyle Hidden
    }
}
Start-Sleep -Milliseconds 1200
if(-not(Port-Up 8700)){Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root "core\main\app.py")) -WorkingDirectory $Root -WindowStyle Hidden}
try{$web=Get-NetTCPConnection -LocalPort 8710 -State Listen -ErrorAction SilentlyContinue}catch{$web=$null}
if(-not $web){Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root "web\server.py")) -WorkingDirectory $Root -WindowStyle Hidden}
Start-Sleep -Seconds 2
& $python "scripts\check_health.py"
if($LASTEXITCODE -ne 0){
    & $python "scripts\finalize_update.py" --rollback
    exit 30
}
& $python "scripts\finalize_update.py" --success | Out-Null
exit 0
