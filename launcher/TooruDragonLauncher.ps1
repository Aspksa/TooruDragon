param()

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

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
    $o
}

function Test-Core([int]$port){
    try{
        $r=Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $port) -TimeoutSec 1
        return $r
    }catch{return $null}
}
function Stop-Port([int]$port){
    try{
        $c=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if($c){Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop;return $true}
    }catch{}
    return $false
}
function Start-System{
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c",(Join-Path $Root "StartTooruDragon.bat")) -WorkingDirectory $Root
}
function Stop-System{
    foreach($c in ($cores|Sort-Object Port -Descending)){[void](Stop-Port $c.Port)}
}
function Restart-System{
    Stop-System
    Start-Sleep -Milliseconds 800
    Start-System
}
function Update-System{
    if(Get-Command git -ErrorAction SilentlyContinue){
        Start-Process -FilePath "cmd.exe" -ArgumentList @("/k","git pull --ff-only origin main") -WorkingDirectory $Root
    }else{
        [Windows.Forms.MessageBox]::Show("Git не найден. Автообновление недоступно.","TooruDragon")
    }
}

$form=New-Object Windows.Forms.Form
$form.Text="TooruDragon Launcher v0.1.0"
$form.Size=New-Object Drawing.Size(1420,900)
$form.MinimumSize=New-Object Drawing.Size(1200,760)
$form.StartPosition="CenterScreen"
$form.BackColor=$bg
$form.ForeColor=$text

$side=P 0 0 230 900 ([Drawing.Color]::FromArgb(8,10,20))
$side.Dock=[Windows.Forms.DockStyle]::Left
$form.Controls.Add($side)
$side.Controls.Add((L "🐉 TooruDragon" 18 20 200 38 18 $text ([Drawing.FontStyle]::Bold)))
$side.Controls.Add((L "Launcher  •  v0.1.0" 22 58 180 24 9 $muted))

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
$hero.Controls.Add((L "TooruDragon" 30 28 520 55 31 $text ([Drawing.FontStyle]::Bold)))
$hero.Controls.Add((L "ВАШ ЛИЧНЫЙ МИР. ВАШ ИИ. ВАШ ДРАКОН." 33 85 650 28 11 $pink ([Drawing.FontStyle]::Bold)))
$hero.Controls.Add((L "«Я рядом, господин. Всё готово к запуску.»" 33 132 650 34 13 $text))
$hero.Controls.Add((L "Главная панель управления системой" 33 175 550 28 10 $muted))

$clock=L "" 840 45 230 62 28 $text ([Drawing.FontStyle]::Bold)
$clock.TextAlign=[Drawing.ContentAlignment]::MiddleRight
$hero.Controls.Add($clock)
$date=L "" 840 108 230 28 10 $muted
$date.TextAlign=[Drawing.ContentAlignment]::MiddleRight
$hero.Controls.Add($date)

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
$x=18
foreach($name in @("Python","Git","SQLite","Порты","Watchdog","UTF-8")){
    $b=P $x 48 165 55 $panel2
    $b.Controls.Add((L "✔" 10 12 28 28 14 $green ([Drawing.FontStyle]::Bold)))
    $b.Controls.Add((L $name 44 7 110 22 9.5 $text ([Drawing.FontStyle]::Bold)))
    $b.Controls.Add((L "Готово" 44 29 110 20 8.5 $green))
    $diag.Controls.Add($b)
    $x+=180
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
    $st.Add_Click({
        $path=Join-Path $Root ($this.Tag.Key -eq "laboratory" ? "core\workshop\start.bat" : ("core\"+$this.Tag.Key+"\start.bat"))
        if($this.Tag.Key -eq "tooru_ai"){$path=Join-Path $Root "core\tooru_ai\start.bat"}
        if(Test-Path $path){Start-Process "cmd.exe" -ArgumentList @("/k",$path) -WorkingDirectory $Root}
    })
    $sp.Add_Click({[void](Stop-Port $this.Tag.Port)})
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
$settings.Controls.Add((L "Переносимый режим и оформление" 27 70 600 28 10.5 $muted))
$box=P 24 120 800 400 $panel
$settings.Controls.Add($box)
$box.Controls.Add((L "Переносимый режим" 24 25 300 30 12 $text ([Drawing.FontStyle]::Bold)))
$box.Controls.Add((L "Все пути считаются от папки TooruDragon. Можно запускать с внешнего SSD или USB." 24 60 700 44 10 $muted))
$box.Controls.Add((L "Аниме-фон" 24 130 300 30 12 $text ([Drawing.FontStyle]::Bold)))
$box.Controls.Add((L "assets\launcher\tooru-maid.png" 24 164 500 25 10 $pink))
$box.Controls.Add((L "Положите сюда выбранную аниме-драконицу — GUI подхватит её при запуске." 24 195 700 40 10 $muted))
$folder=B "📁 Открыть папку проекта" 24 275 250 48 $purple
$assets=B "♡ Папка оформления" 290 275 220 48 $pink
$folder.Add_Click({Start-Process explorer.exe $Root})
$assets.Add_Click({$p=Join-Path $Root "assets\launcher";New-Item -ItemType Directory -Force -Path $p|Out-Null;Start-Process explorer.exe $p})
$box.Controls.Add($folder);$box.Controls.Add($assets)

$timer=New-Object Windows.Forms.Timer
$timer.Interval=1500
$timer.Add_Tick({
    $clock.Text=Get-Date -Format "HH:mm"
    $date.Text=Get-Date -Format "dd.MM.yyyy"
    foreach($c in $cores){
        $h=Test-Core $c.Port
        if($h){
            $statusLabels[$c.Key].Text="● Работает"
            $statusLabels[$c.Key].ForeColor=$green
            if($h.version){$versionLabels[$c.Key].Text=("v{0}  •  :{1}" -f $h.version,$c.Port)}
        }else{
            $statusLabels[$c.Key].Text="● Выключено"
            $statusLabels[$c.Key].ForeColor=$red
        }
    }
})
$timer.Start()

$pages["Главная"].Visible=$true
$nav["Главная"].BackColor=[Drawing.Color]::FromArgb(67,42,112)

[void]$form.ShowDialog()
$timer.Stop()
