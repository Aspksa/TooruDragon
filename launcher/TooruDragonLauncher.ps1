param([switch]$AutoStart)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$iconPath=Join-Path $Root "assets\launcher\toorudragon.ico"
if(-not(Test-Path $iconPath)){
    try{& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\create_icon.ps1") | Out-Null}catch{}
}
$appIcon=if(Test-Path $iconPath){New-Object Drawing.Icon -ArgumentList $iconPath}else{[Drawing.SystemIcons]::Application}

$bg = [Drawing.Color]::FromArgb(9,12,23)
$panel = [Drawing.Color]::FromArgb(17,23,41)
$panel2 = [Drawing.Color]::FromArgb(24,31,53)
$text = [Drawing.Color]::FromArgb(242,245,255)
$muted = [Drawing.Color]::FromArgb(155,166,194)
$purple = [Drawing.Color]::FromArgb(164,82,255)
$blue = [Drawing.Color]::FromArgb(64,145,255)
$pink = [Drawing.Color]::FromArgb(255,82,190)
$green = [Drawing.Color]::FromArgb(57,224,127)
$red = [Drawing.Color]::FromArgb(255,80,112)
$cyan = [Drawing.Color]::FromArgb(42,210,238)
$yellow = [Drawing.Color]::FromArgb(255,199,73)

$cores = @(
    @{Key="main";Name="Главное ядро";Port=8700;Icon="♛";Color=$blue},
    @{Key="tooru_ai";Name="Tooru/AI";Port=8701;Icon="✦";Color=$purple},
    @{Key="laboratory";Name="Лаборатория Tooru/AI";Port=8702;Icon="⚗";Color=$pink},
    @{Key="home";Name="Дом";Port=8703;Icon="⌂";Color=$green},
    @{Key="work";Name="Работа";Port=8704;Icon="▣";Color=$yellow},
    @{Key="mobile";Name="Мобильное ядро";Port=8705;Icon="▯";Color=$cyan}
)

function F([float]$size,[Drawing.FontStyle]$style=[Drawing.FontStyle]::Regular){
    New-Object Drawing.Font("Segoe UI",$size,$style)
}
function L([string]$t,[int]$x,[int]$y,[int]$w,[int]$h,[float]$s=10,[Drawing.Color]$c=$text,[Drawing.FontStyle]$st=[Drawing.FontStyle]::Regular){
    $o=New-Object Windows.Forms.Label
    $o.Text=$t
    $o.Location=New-Object Drawing.Point($x,$y)
    $o.Size=New-Object Drawing.Size($w,$h)
    $o.ForeColor=$c
    $o.BackColor=[Drawing.Color]::Transparent
    $o.Font=F $s $st
    $o
}
function P([int]$x,[int]$y,[int]$w,[int]$h,[Drawing.Color]$c=$panel){
    $o=New-Object Windows.Forms.Panel
    $o.Location=New-Object Drawing.Point($x,$y)
    $o.Size=New-Object Drawing.Size($w,$h)
    $o.BackColor=$c
    $o
}
function B([string]$t,[int]$x,[int]$y,[int]$w,[int]$h,[Drawing.Color]$c){
    $o=New-Object Windows.Forms.Button
    $o.Text=$t
    $o.Location=New-Object Drawing.Point($x,$y)
    $o.Size=New-Object Drawing.Size($w,$h)
    $o.FlatStyle=[Windows.Forms.FlatStyle]::Flat
    $o.FlatAppearance.BorderColor=$c
    $o.FlatAppearance.BorderSize=1
    $o.BackColor=$panel2
    $o.ForeColor=$text
    $o.Font=F 10 ([Drawing.FontStyle]::Bold)
    $o.Cursor=[Windows.Forms.Cursors]::Hand
    $o.Add_MouseEnter({$this.BackColor=[Drawing.Color]::FromArgb(45,35,72)})
    $o.Add_MouseLeave({$this.BackColor=[Drawing.Color]::FromArgb(24,31,53)})
    $o
}

function Test-Core([int]$port){
    try{
        $r=Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $port) -TimeoutSec 1
        return $r
    }catch{return $null}
}
function Invoke-CoreAction([string]$Core,[string]$Action){
    $body=@{core=$Core;action=$Action}|ConvertTo-Json -Compress
    try{
        $supervisorHeaders=@{}
        if($env:TOORUDRAGON_API_TOKEN){$supervisorHeaders["Authorization"]="Bearer "+$env:TOORUDRAGON_API_TOKEN}
        $result=Invoke-RestMethod -Uri "http://127.0.0.1:8699/core/action" -Method Post -ContentType "application/json; charset=utf-8" -Headers $supervisorHeaders -Body $body -TimeoutSec 20
        Notify "Supervisor" ("{0}: {1}" -f $Core,$Action)
        return $result
    }catch{
        if($Core -eq "main"){
            Notify "Supervisor" ("Команда "+$Action+" для Main Core завершилась ошибкой: "+$_.Exception.Message)
            return $null
        }
        try{
            $headers=@{}
            if($env:TOORUDRAGON_API_TOKEN){$headers["Authorization"]="Bearer "+$env:TOORUDRAGON_API_TOKEN}
            $result=Invoke-RestMethod -Uri "http://127.0.0.1:8700/api/core/action" -Method Post -ContentType "application/json; charset=utf-8" -Headers $headers -Body $body -TimeoutSec 20
            Notify "Core Manager" $result.message
            return $result
        }catch{
            Notify "Core Manager" ("Команда "+$Action+" для "+$Core+" завершилась ошибкой: "+$_.Exception.Message)
            return $null
        }
    }
}
function Stop-Port([int]$port){
    try{
        if(Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue){
            $conn=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if($conn){Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop;return $true}
        }else{
            $line=netstat -ano -p tcp | Select-String (":{0}\\s+.*LISTENING\\s+(\\d+)$" -f $port) | Select-Object -First 1
            if($line -and $line.Matches.Count -gt 0){
                $pidValue=[int]$line.Matches[0].Groups[1].Value
                Stop-Process -Id $pidValue -Force -ErrorAction Stop
                return $true
            }
        }
    }catch{}
    return $false
}
function Start-System{
    if(Find-Python){
        $hidden=Join-Path $Root "scripts\start_hidden.ps1"
        Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File","`"$hidden`"") -WorkingDirectory $Root -WindowStyle Hidden
        Notify "TooruDragon" "Запуск ядер начат в фоновом режиме."
    }else{
        $startBat=Join-Path $Root "StartTooruDragon.bat"
        Start-Process -FilePath "cmd.exe" -ArgumentList @("/c","`"$startBat`"") -WorkingDirectory $Root
        Notify "TooruDragon" "Python ещё не подготовлен — открыт первый технический запуск."
    }
}
function Stop-System{
    $py=Find-Python
    if($py){
        try{& $py (Join-Path $Root "scripts\desired_state.py") stopped --all | Out-Null}catch{}
    }
    [void](Stop-Port 8710)
    foreach($c in ($cores|Sort-Object Port -Descending)){[void](Stop-Port $c.Port)}
    [void](Stop-Port 8699)
    Notify "TooruDragon" "Система остановлена. Desired state сохранён как stopped."
}
function Restart-System{
    Stop-System
    Start-Sleep -Milliseconds 800
    Start-System
}
function Update-System{
    $py=Find-Python
    if(-not $py){Notify "Обновление" "Python не найден. Сначала выполните запуск системы.";return}
    if(-not(Get-Command git -ErrorAction SilentlyContinue)){Notify "Обновление" "Git не найден. Автообновление недоступно.";return}
    $script=Join-Path $Root "scripts\update.py"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/k","`"$py`" `"$script`"") -WorkingDirectory $Root
    Notify "Rolling Update" "Создаётся backup. Затронутые сервисы обновятся по очереди и автоматически вернутся в работу."
}

function Find-Python{
    $portable=Join-Path $Root "runtime\python\python.exe"
    if(Test-Path $portable){return $portable}
    try{$p=& python -c "import sys;print(sys.executable)" 2>$null;if($LASTEXITCODE -eq 0){return $p.Trim()}}catch{}
    try{$p=& py -3 -c "import sys;print(sys.executable)" 2>$null;if($LASTEXITCODE -eq 0){return $p.Trim()}}catch{}
    return $null
}
function Test-Database{
    $py=Find-Python
    if(-not $py){return $false}
    & $py -c "import sqlite3; c=sqlite3.connect(r'data/toorudragon.db'); c.execute('select value from system_meta limit 1').fetchone(); c.close()" 2>$null
    return ($LASTEXITCODE -eq 0)
}
function Test-Utf8{
    try{
        $dir=Join-Path $Root "runtime";New-Item -ItemType Directory -Force -Path $dir|Out-Null
        $p=Join-Path $dir "utf8-gui-test.txt";$s="Тору • Господин • 🐉"
        [IO.File]::WriteAllText($p,$s,(New-Object Text.UTF8Encoding -ArgumentList $false))
        $ok=([IO.File]::ReadAllText($p,[Text.Encoding]::UTF8) -eq $s)
        Remove-Item $p -Force
        return $ok
    }catch{return $false}
}
function Test-Ports{
    try{
        foreach($p in 8700..8705){
            $x=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
            if($x -and -not(Test-Core $p)){return $false}
        }
        return $true
    }catch{return $true}
}
function Test-Watchdog{
    try{$w=Invoke-RestMethod -Uri "http://127.0.0.1:8700/watchdog" -TimeoutSec 1;return [bool]$w.watchdog.running}catch{return $false}
}
function Test-Registry{
    try{
        $r=Invoke-RestMethod -Uri "http://127.0.0.1:8700/registry" -TimeoutSec 1
        return ($r.registry.online -ge 1)
    }catch{return $false}
}
function Test-Supervisor{
    try{
        $r=Invoke-RestMethod -Uri "http://127.0.0.1:8699/health" -TimeoutSec 1
        return ($r.status -eq "ok")
    }catch{return $false}
}

$tray=New-Object Windows.Forms.NotifyIcon
$tray.Icon=$appIcon
$tray.Text="TooruDragon Launcher"
$tray.Visible=$true
$trayMenu=New-Object Windows.Forms.ContextMenuStrip
$miOpen=$trayMenu.Items.Add("Открыть TooruDragon")
$miStart=$trayMenu.Items.Add("Запустить всё")
$miRestart=$trayMenu.Items.Add("Перезапустить")
$miStop=$trayMenu.Items.Add("Остановить всё")
$miWeb=$trayMenu.Items.Add("Открыть Web UI")
[void]$trayMenu.Items.Add("-")
$miExit=$trayMenu.Items.Add("Выход")
$tray.ContextMenuStrip=$trayMenu
function Notify([string]$Title,[string]$Message){
    $tray.BalloonTipTitle=$Title;$tray.BalloonTipText=$Message;$tray.BalloonTipIcon=[Windows.Forms.ToolTipIcon]::Info
    $tray.ShowBalloonTip(3500)
}

$splash=New-Object Windows.Forms.Form
$splash.FormBorderStyle=[Windows.Forms.FormBorderStyle]::None
$splash.StartPosition="CenterScreen"
$splash.Size=New-Object Drawing.Size(540,285)
$splash.BackColor=$bg
$splash.TopMost=$true
$splash.Controls.Add((L "🐉" 220 25 100 68 38 $purple ([Drawing.FontStyle]::Bold)))
$st=L "TooruDragon" 0 103 540 48 27 $text ([Drawing.FontStyle]::Bold);$st.TextAlign=[Drawing.ContentAlignment]::MiddleCenter;$splash.Controls.Add($st)
$ss=L "Пробуждение системы..." 0 158 540 28 11 $pink;$ss.TextAlign=[Drawing.ContentAlignment]::MiddleCenter;$splash.Controls.Add($ss)
$progress=New-Object Windows.Forms.ProgressBar
$progress.Location=New-Object Drawing.Point(70,215);$progress.Size=New-Object Drawing.Size(400,12);$progress.Style=[Windows.Forms.ProgressBarStyle]::Marquee
$splash.Controls.Add($progress)
$splash.Show();[Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 650

$form=New-Object Windows.Forms.Form
$form.Text="TooruDragon Launcher v0.3.0-alpha"
$form.Size=New-Object Drawing.Size(1420,900)
$form.MinimumSize=New-Object Drawing.Size(1200,760)
$form.StartPosition="CenterScreen"
$form.BackColor=$bg
$form.ForeColor=$text
$form.Icon=$appIcon

$side=P 0 0 230 900 ([Drawing.Color]::FromArgb(8,10,20))
$side.Dock=[Windows.Forms.DockStyle]::Left
$form.Controls.Add($side)
$side.Controls.Add((L "🐉 TooruDragon" 18 20 200 38 18 $text ([Drawing.FontStyle]::Bold)))
$side.Controls.Add((L "Launcher  •  v0.3.0-alpha" 22 58 190 24 9 $muted))

$host=P 230 0 1170 860 $bg
$host.Dock=[Windows.Forms.DockStyle]::Fill
$form.Controls.Add($host)

$pages=@{}
foreach($name in @("Главная","Ядра","Логи","Настройки")){
    $p=P 0 0 1170 860 $bg
    $p.Dock=[Windows.Forms.DockStyle]::Fill
    $p.Visible=$false
    $host.Controls.Add($p)
    $pages[$name]=$p
}

$nav=@{}
$y=115
foreach($item in @(
    @{N="Главная";I="⌂"},
    @{N="Ядра";I="◈"},
    @{N="Логи";I="▤"},
    @{N="Настройки";I="⚙"}
)){
    $b=B ("{0}   {1}" -f $item.I,$item.N) 14 $y 200 48 $purple
    $b.Tag=$item.N
    $b.TextAlign=[Drawing.ContentAlignment]::MiddleLeft
    $b.Padding=New-Object Windows.Forms.Padding(18,0,0,0)
    $b.Add_Click({
        foreach($k in $pages.Keys){$pages[$k].Visible=($k -eq $this.Tag)}
        foreach($k in $nav.Keys){$nav[$k].BackColor=if($k -eq $this.Tag){[Drawing.Color]::FromArgb(67,42,112)}else{$panel2}}
    })
    $side.Controls.Add($b)
    $nav[$item.N]=$b
    $y+=60
}

$quote=P 14 620 200 190 ([Drawing.Color]::FromArgb(28,19,47))
$side.Controls.Add($quote)
$quote.Controls.Add((L "♡" 155 8 30 30 18 $pink ([Drawing.FontStyle]::Bold)))
$quote.Controls.Add((L "Господин," 18 58 160 28 11 $text ([Drawing.FontStyle]::Bold)))
$quote.Controls.Add((L "система готова." 18 90 160 25 10 $muted))
$quote.Controls.Add((L "Я рядом. 🐉" 18 123 160 28 11 $pink ([Drawing.FontStyle]::Bold)))

$home=$pages["Главная"]
$hero=P 18 18 1110 230 ([Drawing.Color]::FromArgb(25,17,46))
$home.Controls.Add($hero)

$artDir=Join-Path $Root "runtime\launcher"
New-Item -ItemType Directory -Force -Path $artDir | Out-Null
$artPath=Join-Path $artDir "tooru-maid.jpg"
$artEncoded=Join-Path $Root "assets\launcher\tooru-maid-mini.jpg.b64"
if((-not(Test-Path $artPath)) -and (Test-Path $artEncoded)){
    try{
        $raw=(Get-Content $artEncoded -Raw -Encoding ASCII).Trim()
        [IO.File]::WriteAllBytes($artPath,[Convert]::FromBase64String($raw))
    }catch{}
}
if(Test-Path $artPath){
    try{
        $hero.BackgroundImage=[Drawing.Image]::FromFile($artPath)
        $hero.BackgroundImageLayout=[Windows.Forms.ImageLayout]::Zoom
    }catch{}
}

$heroInfo=P 610 15 480 200 ([Drawing.Color]::FromArgb(12,16,30))
$hero.Controls.Add($heroInfo)
$heroInfo.Controls.Add((L "TooruDragon" 22 18 310 48 27 $text ([Drawing.FontStyle]::Bold)))
$heroInfo.Controls.Add((L "ВАШ МИР. ВАШ ИИ. ВАШ ДРАКОН." 24 66 390 25 10 $pink ([Drawing.FontStyle]::Bold)))
$heroInfo.Controls.Add((L "«Я рядом, господин.»" 24 106 300 29 12 $text))
$heroInfo.Controls.Add((L "Главная панель управления" 24 143 300 24 9.5 $muted))

$clock=L "" 335 15 125 45 20 $text ([Drawing.FontStyle]::Bold)
$clock.TextAlign=[Drawing.ContentAlignment]::MiddleRight
$heroInfo.Controls.Add($clock)
$date=L "" 335 61 125 24 9 $muted
$date.TextAlign=[Drawing.ContentAlignment]::MiddleRight
$heroInfo.Controls.Add($date)

$actions=P 18 263 1110 84 $panel
$home.Controls.Add($actions)
$buttons=@(
    @{T="▶ Запустить всё";X=12;W=200;C=$green;A={Start-System}},
    @{T="■ Остановить всё";X=222;W=200;C=$red;A={Stop-System}},
    @{T="↻ Перезапустить";X=432;W=195;C=$blue;A={Restart-System}},
    @{T="↓ Обновить";X=637;W=180;C=$purple;A={Update-System}},
    @{T="◎ Открыть Web UI";X=827;W=265;C=$cyan;A={Start-Process "http://127.0.0.1:8710"}}
)
foreach($i in $buttons){
    $b=B $i.T $i.X 14 $i.W 55 $i.C
    $b.Add_Click($i.A)
    $actions.Controls.Add($b)
}

$coreBox=P 18 362 1110 315 $panel
$home.Controls.Add($coreBox)
$coreBox.Controls.Add((L "◈  Ядра системы" 18 10 350 36 16 $text ([Drawing.FontStyle]::Bold)))

$statusLabels=@{}
$versionLabels=@{}
$x=14
foreach($c in $cores){
    $card=P $x 55 170 242 ([Drawing.Color]::FromArgb(16,23,42))
    $card.BorderStyle=[Windows.Forms.BorderStyle]::FixedSingle
    $coreBox.Controls.Add($card)

    $ic=L $c.Icon 0 10 170 42 23 $c.Color ([Drawing.FontStyle]::Bold)
    $ic.TextAlign=[Drawing.ContentAlignment]::MiddleCenter
    $card.Controls.Add($ic)

    $nm=L $c.Name 8 55 154 48 9.5 $text ([Drawing.FontStyle]::Bold)
    $nm.TextAlign=[Drawing.ContentAlignment]::MiddleCenter
    $card.Controls.Add($nm)

    $vl=L ("v0.1.0  •  :{0}" -f $c.Port) 5 105 160 25 8.5 $muted
    $vl.TextAlign=[Drawing.ContentAlignment]::MiddleCenter
    $card.Controls.Add($vl)
    $versionLabels[$c.Key]=$vl

    $sl=L "● Проверка..." 8 136 154 25 9.5 $yellow ([Drawing.FontStyle]::Bold)
    $sl.TextAlign=[Drawing.ContentAlignment]::MiddleCenter
    $card.Controls.Add($sl)
    $statusLabels[$c.Key]=$sl

    $open=B "Открыть" 8 183 75 34 $c.Color
    $open.Tag=$c.Port
    $open.Add_Click({Start-Process ("http://127.0.0.1:{0}/health" -f $this.Tag)})
    $logs=B "Логи" 90 183 70 34 $c.Color
    $logs.Tag=$c.Key
    $logs.Add_Click({
        $pages["Логи"].Visible=$true;$pages["Главная"].Visible=$false;$pages["Ядра"].Visible=$false;$pages["Настройки"].Visible=$false
        $p=Join-Path $Root ("logs\{0}.log" -f $this.Tag)
        if(Test-Path $p){$logBox.Text=Get-Content $p -Raw -Encoding UTF8}else{$logBox.Text="Лог пока не создан."}
    })
    $card.Controls.Add($open);$card.Controls.Add($logs)
    $x+=183
}

$diag=P 18 692 1110 120 $panel
$home.Controls.Add($diag)
$diag.Controls.Add((L "⌁  Состояние системы" 18 9 300 34 14 $text ([Drawing.FontStyle]::Bold)))
$diagLabels=@{}
$x=18
foreach($name in @("Python","Git","SQLite","Порты","Supervisor","Watchdog","Registry","UTF-8")){
    $b=P $x 48 128 55 $panel2
    $s=L "●" 10 12 28 28 14 $yellow ([Drawing.FontStyle]::Bold)
    $v=L "Проверка..." 40 29 84 20 8 $yellow
    $b.Controls.Add($s)
    $b.Controls.Add((L $name 40 7 84 22 8.6 $text ([Drawing.FontStyle]::Bold)))
    $b.Controls.Add($v)
    $diag.Controls.Add($b)
    $diagLabels[$name]=@($s,$v)
    $x+=135
}

$corePage=$pages["Ядра"]
$corePage.Controls.Add((L "◈ Ядра TooruDragon" 24 20 520 50 25 $text ([Drawing.FontStyle]::Bold)))
$corePage.Controls.Add((L "Запуск и остановка каждого ядра отдельно" 27 70 600 28 10.5 $muted))
$y=120
foreach($c in $cores){
    $row=P 24 $y 1080 82 $panel
    $row.Controls.Add((L $c.Icon 16 16 45 45 20 $c.Color ([Drawing.FontStyle]::Bold)))
    $row.Controls.Add((L $c.Name 75 11 300 30 12 $text ([Drawing.FontStyle]::Bold)))
    $row.Controls.Add((L ("127.0.0.1:{0}  •  v0.1.0" -f $c.Port) 75 43 320 25 9 $muted))
    $st=B "▶ Запустить" 675 19 125 44 $green
    $sp=B "■ Остановить" 810 19 125 44 $red
    $op=B "◎ Открыть" 945 19 120 44 $c.Color
    $st.Tag=$c;$sp.Tag=$c;$op.Tag=$c.Port
    $st.Add_Click({[void](Invoke-CoreAction $this.Tag.Key "start")})
    $sp.Add_Click({[void](Invoke-CoreAction $this.Tag.Key "stop")})
    $op.Add_Click({Start-Process ("http://127.0.0.1:{0}/health" -f $this.Tag)})
    $row.Controls.Add($st);$row.Controls.Add($sp);$row.Controls.Add($op)
    $corePage.Controls.Add($row)
    $y+=94
}

$logsPage=$pages["Логи"]
$logsPage.Controls.Add((L "▤ Логи" 24 20 500 50 25 $text ([Drawing.FontStyle]::Bold)))
$logsPage.Controls.Add((L "События, предупреждения и ошибки системы" 27 70 600 28 10.5 $muted))
$logBox=New-Object Windows.Forms.RichTextBox
$logBox.Location=New-Object Drawing.Point(24,118)
$logBox.Size=New-Object Drawing.Size(1080,650)
$logBox.BackColor=[Drawing.Color]::FromArgb(6,9,17)
$logBox.ForeColor=[Drawing.Color]::FromArgb(191,222,255)
$logBox.Font=New-Object Drawing.Font("Consolas",10)
$logBox.ReadOnly=$true
$logsPage.Controls.Add($logBox)
$load=B "Главный лог" 24 785 150 42 $blue
$clear=B "Очистить окно" 186 785 160 42 $red
$load.Add_Click({$p=Join-Path $Root "logs\main.log";if(Test-Path $p){$logBox.Text=Get-Content $p -Raw -Encoding UTF8}})
$clear.Add_Click({$logBox.Clear()})
$logsPage.Controls.Add($load);$logsPage.Controls.Add($clear)

$settings=$pages["Настройки"]
$settings.Controls.Add((L "⚙ Настройки" 24 20 500 50 25 $text ([Drawing.FontStyle]::Bold)))
$settings.Controls.Add((L "Windows, переносимый режим и оформление" 27 70 700 28 10.5 $muted))
$box=P 24 120 880 505 $panel
$settings.Controls.Add($box)
$box.Controls.Add((L "Windows" 24 24 300 30 13 $text ([Drawing.FontStyle]::Bold)))
$autoOn=B "⚡ Включить автозапуск" 24 65 250 46 $green
$autoOff=B "○ Убрать автозапуск" 288 65 230 46 $red
$shortcut=B "★ Создать ярлык" 532 65 210 46 $purple
$autoOn.Add_Click({& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\install_startup.ps1");Notify "Автозапуск" "Автозапуск TooruDragon включён."})
$autoOff.Add_Click({& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\uninstall_startup.ps1");Notify "Автозапуск" "Автозапуск отключён."})
$shortcut.Add_Click({& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\create_shortcut.ps1");Notify "Ярлык" "Ярлык создан на рабочем столе."})
$box.Controls.Add($autoOn);$box.Controls.Add($autoOff);$box.Controls.Add($shortcut)
$backupNow=B "💾 Создать backup" 24 125 230 42 $cyan
$rollback=B "↶ Откатить последний" 268 125 250 42 $yellow
$backupNow.Add_Click({
    $py=Find-Python
    if($py){
        & $py (Join-Path $Root "scripts\backup.py")
        if($LASTEXITCODE -eq 0){Notify "Backup" "Резервная копия создана."}else{Notify "Backup" "Не удалось создать резервную копию."}
    }
})
$rollback.Add_Click({
    $answer=[Windows.Forms.MessageBox]::Show("Остановить ядра и восстановить последний backup?","TooruDragon Rollback",[Windows.Forms.MessageBoxButtons]::YesNo,[Windows.Forms.MessageBoxIcon]::Warning)
    if($answer -eq [Windows.Forms.DialogResult]::Yes){
        Stop-System
        $py=Find-Python
        if($py){
            & $py (Join-Path $Root "scripts\rollback.py")
            if($LASTEXITCODE -eq 0){Notify "Rollback" "Backup восстановлен. Запускаю систему.";Start-System}else{Notify "Rollback" "Не удалось восстановить backup."}
        }
    }
})
$box.Controls.Add($backupNow);$box.Controls.Add($rollback)
$box.Controls.Add((L "Оформление" 24 185 300 30 13 $text ([Drawing.FontStyle]::Bold)))
$box.Controls.Add((L "Аниме-фон: assets\launcher\tooru-maid.jpg" 24 225 600 26 10 $pink))
$box.Controls.Add((L "Логотип: assets\launcher\logo.svg" 24 256 600 26 10 $cyan))
$assets=B "♡ Открыть папку оформления" 24 300 280 46 $pink
$assets.Add_Click({$p=Join-Path $Root "assets\launcher";New-Item -ItemType Directory -Force -Path $p|Out-Null;Start-Process explorer.exe $p})
$box.Controls.Add($assets)
$box.Controls.Add((L "Переносимый режим" 24 375 300 30 13 $text ([Drawing.FontStyle]::Bold)))
$box.Controls.Add((L "Пути рассчитываются от папки TooruDragon. Внешний SSD, USB и смена буквы диска поддерживаются." 24 415 790 48 10 $muted))
$folder=B "📁 Открыть папку проекта" 560 125 250 42 $purple
$folder.Add_Click({Start-Process explorer.exe $Root})
$box.Controls.Add($folder)

$script:lastAllOk=$false
$script:corePrevious=@{}
$timer=New-Object Windows.Forms.Timer
$timer.Interval=1600
$timer.Add_Tick({
    $clock.Text=Get-Date -Format "HH:mm"
    $date.Text=Get-Date -Format "dd.MM.yyyy"
    $allOk=$true
    foreach($c in $cores){
        $h=Test-Core $c.Port
        $isUp=[bool]$h
        if($h){
            $statusLabels[$c.Key].Text="● Работает"
            $statusLabels[$c.Key].ForeColor=$green
            if($h.version){$versionLabels[$c.Key].Text=("v{0}  •  :{1}" -f $h.version,$c.Port)}
        }else{
            $statusLabels[$c.Key].Text="● Выключено"
            $statusLabels[$c.Key].ForeColor=$red
            $allOk=$false
        }
        if($script:corePrevious.ContainsKey($c.Key)){
            if($script:corePrevious[$c.Key] -and -not $isUp){Notify "Ядро отключилось" ("{0} перестало отвечать. Supervisor попробует восстановить его." -f $c.Name)}
            if((-not $script:corePrevious[$c.Key]) -and $isUp){Notify "Ядро восстановлено" ("{0} снова работает." -f $c.Name)}
        }
        $script:corePrevious[$c.Key]=$isUp
    }
    if($allOk -and -not $script:lastAllOk){Notify "TooruDragon" "Все ядра работают стабильно. ♡"}
    $script:lastAllOk=$allOk

    $checks=@{
        "Python"=[bool](Find-Python)
        "Git"=[bool](Get-Command git -ErrorAction SilentlyContinue)
        "SQLite"=(Test-Database)
        "Порты"=(Test-Ports)
        "Supervisor"=(Test-Supervisor)
        "Watchdog"=(Test-Watchdog)
        "Registry"=(Test-Registry)
        "UTF-8"=(Test-Utf8)
    }
    foreach($k in $checks.Keys){
        $pair=$diagLabels[$k]
        if($checks[$k]){
            $pair[0].Text="✔";$pair[0].ForeColor=$green;$pair[1].Text="Готово";$pair[1].ForeColor=$green
        }else{
            $pair[0].Text="✖";$pair[0].ForeColor=$red;$pair[1].Text="Ошибка";$pair[1].ForeColor=$red
        }
    }
})
$timer.Start()

$script:AllowExit=$false
$miOpen.Add_Click({$form.Show();$form.WindowState=[Windows.Forms.FormWindowState]::Normal;$form.Activate()})
$miStart.Add_Click({Start-System})
$miRestart.Add_Click({Restart-System})
$miStop.Add_Click({Stop-System})
$miWeb.Add_Click({Start-Process "http://127.0.0.1:8710"})
$tray.Add_DoubleClick({$form.Show();$form.WindowState=[Windows.Forms.FormWindowState]::Normal;$form.Activate()})
$miExit.Add_Click({$script:AllowExit=$true;$timer.Stop();$tray.Visible=$false;$form.Close()})
$form.Add_Resize({if($form.WindowState -eq [Windows.Forms.FormWindowState]::Minimized){$form.Hide();Notify "TooruDragon" "Лаунчер свёрнут в системный трей."}})
$form.Add_FormClosing({if(-not $script:AllowExit){$_.Cancel=$true;$form.Hide();Notify "TooruDragon" "TooruDragon продолжает работать в трее."}})

$pages["Главная"].Visible=$true
$nav["Главная"].BackColor=[Drawing.Color]::FromArgb(67,42,112)
$splash.Close();$splash.Dispose()
Notify "TooruDragon" "Лаунчер готов, господин. 🐉"
if($AutoStart -and -not(Test-Core 8700)){Start-System}
[void]$form.ShowDialog()
$timer.Stop();$tray.Dispose()
