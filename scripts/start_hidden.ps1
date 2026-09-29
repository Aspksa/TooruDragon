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

$python=Find-Python
if(-not $python){exit 10}

& $python "scripts\init_db.py"
if($LASTEXITCODE -ne 0){exit 20}

$services=@(
    "core\tooru_ai\app.py",
    "core\workshop\app.py",
    "core\home\app.py",
    "core\work\app.py",
    "core\mobile\app.py"
)
foreach($service in $services){
    Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root $service)) -WorkingDirectory $Root -WindowStyle Hidden
}
Start-Sleep -Milliseconds 1200
Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root "core\main\app.py")) -WorkingDirectory $Root -WindowStyle Hidden
Start-Process -FilePath $python -ArgumentList ("`"{0}`"" -f (Join-Path $Root "web\server.py")) -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 2
& $python "scripts\check_health.py"
exit $LASTEXITCODE
