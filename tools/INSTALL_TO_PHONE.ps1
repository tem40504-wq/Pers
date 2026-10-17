# GameScreen Voice: установка APK на телефон через USB (ADB) одним кликом.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pkg  = 'dev.gamescreen.voice'

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }

# Runs adb and returns its whole output as one string (adb writes errors to stderr).
function Adb([string[]]$adbArgs) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $script:adb @adbArgs 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $old }
    return ($out -join "`n")
}

try {
    Say '=== GameScreen Voice: установка на телефон ===' 'Cyan'

    # 1. APK рядом со скриптом или в «Загрузках» (берётся самый свежий).
    $apk = Get-ChildItem -Path $here -Filter 'GameScreenVoice*.apk' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $apk) {
        $apk = Get-ChildItem -Path (Join-Path $env:USERPROFILE 'Downloads') -Filter 'GameScreenVoice*.apk' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime | Select-Object -Last 1
    }
    if (-not $apk) { throw 'Не найден файл GameScreenVoice*.apk ни рядом со скриптом, ни в папке «Загрузки».' }
    Say "APK: $($apk.FullName)"

    # 2. ADB: из PATH, из Android SDK, из папки рядом; иначе скачиваем официальный platform-tools.
    $script:adb = $null
    $found = Get-Command adb -ErrorAction SilentlyContinue
    if ($found) { $script:adb = $found.Source }
    foreach ($p in @((Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'),
                     (Join-Path $here 'platform-tools\adb.exe'))) {
        if (-not $script:adb -and (Test-Path $p)) { $script:adb = $p }
    }
    if (-not $script:adb) {
        Say 'ADB не найден. Скачиваю официальный Android platform-tools (~7 МБ) с dl.google.com...' 'Yellow'
        $zip = Join-Path $here 'platform-tools.zip'
        Invoke-WebRequest 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $here -Force
        Remove-Item $zip -Force
        $script:adb = Join-Path $here 'platform-tools\adb.exe'
    }
    Say "ADB: $script:adb"
    Adb @('start-server') | Out-Null

    # 3. Ждём телефон (до 3 минут).
    $deadline = (Get-Date).AddMinutes(3)
    $hinted = $false
    $unauthHinted = $false
    while ($true) {
        $lines = (Adb @('devices')) -split "`n" | Where-Object { $_ -match "`t" }
        $ready = @($lines | Where-Object { $_ -match "`tdevice\s*$" })
        if ($ready.Count -gt 1) { throw 'Подключено несколько устройств. Оставьте подключённым один телефон.' }
        if ($ready.Count -eq 1) { $serial = ($ready[0] -split "`t")[0].Trim(); break }
        if (($lines -match 'unauthorized') -and -not $unauthHinted) {
            Say 'На телефоне появилось окно «Разрешить отладку по USB?» — отметьте «Всегда разрешать» и нажмите «Разрешить».' 'Yellow'
            $unauthHinted = $true
        } elseif (-not $hinted) {
            Say 'Телефон не виден. Сделайте на телефоне (один раз):' 'Yellow'
            Say '  1) Настройки → Безопасность и конфиденциальность → Автоблокировщик → Выкл.'
            Say '  2) Настройки → Сведения о телефоне → Сведения о ПО → 7 раз нажмите «Номер сборки».'
            Say '  3) Настройки → Параметры разработчика → включите «Отладка по USB».'
            Say '  4) Подключите телефон кабелем к ПК и нажмите «Разрешить» в появившемся окне.'
            Say 'Жду подключения...'
            $hinted = $true
        }
        if ((Get-Date) -gt $deadline) { throw 'Телефон не подключился за 3 минуты. Проверьте кабель (он должен передавать данные) и шаги выше.' }
        Start-Sleep -Seconds 2
    }
    $model = (Adb @('-s', $serial, 'shell', 'getprop', 'ro.product.model')).Trim()
    $android = (Adb @('-s', $serial, 'shell', 'getprop', 'ro.build.version.release')).Trim()
    Say "Телефон: $model, Android $android" 'Green'

    # 4. Установка (с обновлением поверх).
    Say 'Устанавливаю, это займёт 10–40 секунд...'
    $result = Adb @('-s', $serial, 'install', '-r', $apk.FullName)
    if ($result -match 'INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match') {
        Say 'На телефоне стоит старая версия с другой подписью (0.1.2). Её нужно удалить; настройки приложения сбросятся.' 'Yellow'
        $answer = Read-Host 'Удалить старую версию и установить новую? (Y/N)'
        if ($answer -notmatch '^[YyДд]') { throw 'Отменено.' }
        Adb @('-s', $serial, 'uninstall', $pkg) | Out-Null
        $result = Adb @('-s', $serial, 'install', $apk.FullName)
    }
    if ($result -notmatch 'Success') {
        if ($result -match 'USER_RESTRICTED|blocked|INSTALL_FAILED_VERIFICATION_FAILURE|ABORTED') {
            Say 'Телефон запретил установку через USB. Выключите «Автоблокировщик» и, если есть, включите «Установка через USB» в Параметрах разработчика; подтвердите запрос на экране телефона.' 'Yellow'
        }
        throw "Установка не удалась:`n$result"
    }
    Say 'Установлено!' 'Green'

    # 5. Запуск приложения.
    Adb @('-s', $serial, 'shell', 'monkey', '-p', $pkg, '-c', 'android.intent.category.LAUNCHER', '1') | Out-Null
    Say 'GameScreen Voice открыт на телефоне.' 'Green'
    exit 0
}
catch {
    Say ''
    Say "ОШИБКА: $($_.Exception.Message)" 'Red'
    exit 1
}
