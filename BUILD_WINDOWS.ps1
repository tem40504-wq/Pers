# One-click build from official Gradle distribution. Android SDK Platform 35 must be installed first.
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1: the download progress bar slows Invoke-WebRequest by 10-50x; TLS 1.2 may be off by default.
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project
# Full log next to the script: build.log (useful to send for diagnostics).
try { Start-Transcript -Path (Join-Path $project 'build.log') -Force | Out-Null } catch {}
$version = '8.11.1'
$sdk = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
if (-not (Test-Path (Join-Path $sdk 'platforms\android-35'))) {
    throw "Android SDK Platform 35 not found in $sdk. Install Android Studio > SDK Manager > Android API 35."
}

# Gradle does not know where the SDK is unless ANDROID_HOME is set or local.properties exists.
$localProps = Join-Path $project 'local.properties'
if (-not (Test-Path $localProps)) {
    $escaped = $sdk.Replace('\', '\\').Replace(':', '\:')
    [IO.File]::WriteAllText($localProps, "sdk.dir=$escaped`r`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host "Created local.properties (sdk.dir=$sdk)"
}

if (-not $env:JAVA_HOME) {
    $jbr = Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'
    if (Test-Path $jbr) { $env:JAVA_HOME = $jbr }
}
if (-not $env:JAVA_HOME -and -not (Get-Command java -ErrorAction SilentlyContinue)) {
    throw 'JDK 17+ not found. Install Android Studio (it bundles JBR) or set JAVA_HOME.'
}

$tools = Join-Path $project '.buildtools'
$gradleExe = Join-Path $tools "gradle-$version\bin\gradle.bat"
if (-not (Test-Path $gradleExe)) {
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    $archive = Join-Path $tools "gradle-$version-bin.zip"
    $shaFile = "$archive.sha256"
    Write-Host "Downloading Gradle $version from services.gradle.org..."
    Invoke-WebRequest "https://services.gradle.org/distributions/gradle-$version-bin.zip" -OutFile $archive -UseBasicParsing
    # Download the checksum to a file: in PS 5.1 .Content may be a byte[] for octet-stream responses.
    Invoke-WebRequest "https://services.gradle.org/distributions/gradle-$version-bin.zip.sha256" -OutFile $shaFile -UseBasicParsing
    $checksum = (Get-Content -Raw $shaFile).Trim().Split(' ')[0].ToLowerInvariant()
    $actual = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($checksum -ne $actual) { Remove-Item $archive -Force; throw 'Gradle SHA256 mismatch' }
    Expand-Archive -Path $archive -DestinationPath $tools -Force
}
Write-Host 'Building debug APK...'
# Gradle prints warnings to stderr: with 'Stop' PowerShell 5.1 would abort on the first one.
$ErrorActionPreference = 'Continue'
& $gradleExe --no-daemon ':app:assembleDebug' 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath (Join-Path $project 'gradle.log')
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { throw "Gradle build failed (code $code). See gradle.log" }
Write-Host "Built: $project\app\build\outputs\apk\debug\app-debug.apk"
