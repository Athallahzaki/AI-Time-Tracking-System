<#
.SYNOPSIS
  Watchdog engine: jalankan engine, pantau, hidupkan ulang bila mati atau macet (paket ea-r6).

.DESCRIPTION
  Dipakai langsung untuk uji, atau lewat Task Scheduler (install-engine-task.ps1) supaya
  engine jalan sendiri saat laptop menyala. Syarat uji operasional 3 hari (dokumen 12 bagian 2.4):
  pulih sendiri tanpa intervensi.

  Engine dianggap bermasalah bila:
    - prosesnya keluar (kode apa pun), atau
    - berkas detak (--heartbeat-file, ditulis ticker engine tiap 5 dtk) tidak diperbarui
      lebih dari -StaleSeconds (proses hidup tapi macet: CUDA menggantung, GIL terkunci).
      Sebelum detak pertama muncul, yang berlaku -StartupGraceSeconds.
  Lalu engine dimatikan (bila masih ada) dan dijalankan ulang dengan jeda bertingkat
  5, 10, 20, ... dtk (maks -MaxBackoffSeconds); jeda kembali ke 5 dtk bila run sebelumnya
  bertahan lebih dari -StableSeconds.

  Berhenti rapi: buat berkas <StateDir>\watchdog.stop (install-engine-task.ps1 -Stop),
  atau Ctrl+C. Watchdog meminta engine berhenti rapi lewat berkas stop engine (interval
  ditutup engine_shutdown), menunggu -StopGraceSeconds, baru dipaksa.

  Log: <StateDir>\watchdog-<tanggal>.log, keluaran engine <StateDir>\engine-<waktu>.out.log/.err.log.
  Log lebih tua dari -KeepDays dihapus saat start.

  Rahasia (mis. ENGINE_SHARED_KEY) TIDAK lewat argumen (terbaca siapa saja lewat daftar proses):
  tulis di berkas -EnvFile (baris KEY=VALUE), lindungi dengan ACL, dibaca ulang tiap start.

.EXAMPLE
  .\deploy\laptop\engine-watchdog.ps1 -BindIp 100.64.0.12 -Config engine/config/demo-1060.yaml

.EXAMPLE
  # Uji lokal tanpa NetBird
  .\deploy\laptop\engine-watchdog.ps1 -BindIp 127.0.0.1 -StaleSeconds 30
#>
param(
    [Parameter(Mandatory = $true)][Alias("NetBirdIp")][string]$BindIp,
    [string]$Config = "engine/config/demo-4060.yaml",
    [int]$Port = 8765,
    [int]$HealthSeconds = 10,
    [string]$AffinityMask = "",
    [double]$TargetFps = 0,
    # Path python.exe (env conda/venv). Kosong = python dari PATH. Untuk Task Scheduler
    # isi path absolut: task tidak menjalankan `conda activate`.
    [string]$Python = "",
    [string]$EnvFile = "",
    [string]$StateDir = "logs\engine",
    [int]$StaleSeconds = 60,
    # Import torch/onnxruntime + model ReID di GTX 1060 bisa lebih dari 1 menit.
    [int]$StartupGraceSeconds = 240,
    [int]$StopGraceSeconds = 30,
    [int]$MaxBackoffSeconds = 120,
    [int]$StableSeconds = 600,
    [int]$KeepDays = 14,
    # Saat boot, NetBird bisa belum tersambung: tunggu IP muncul sampai batas ini.
    [int]$WaitForIpSeconds = 600,
    # 0 = tanpa batas (layanan). Angka > 0 hanya untuk uji.
    [int]$MaxRestarts = 0,
    [switch]$SkipIpCheck
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

if (-not [IO.Path]::IsPathRooted($StateDir)) { $StateDir = Join-Path $RepoRoot $StateDir }
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$HeartbeatFile = Join-Path $StateDir "heartbeat.json"
$EngineStopFile = Join-Path $StateDir "engine.stop"
$WatchdogStopFile = Join-Path $StateDir "watchdog.stop"
$PidFile = Join-Path $StateDir "engine.pid"

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    $log = Join-Path $StateDir ("watchdog-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
    Add-Content -Path $log -Value $line -Encoding UTF8
}

function Quote-Arg([string]$Text) { if ($Text -match '\s') { '"' + $Text + '"' } else { $Text } }

function Import-EnvFile([string]$Path) {
    if (-not $Path) { return }
    if (-not (Test-Path $Path)) { throw "EnvFile tidak ditemukan: $Path" }
    foreach ($raw in Get-Content -Path $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { continue }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        # Ke lingkungan proses watchdog; diwarisi engine. Nilai tidak pernah ditulis ke log.
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Stop-EngineProcess($Proc, [string]$Why) {
    if ($null -eq $Proc -or $Proc.HasExited) { return }
    Write-Log "engine (pid $($Proc.Id)) dihentikan paksa: $Why"
    try { Stop-Process -Id $Proc.Id -Force -ErrorAction Stop } catch { Write-Log "gagal menghentikan pid $($Proc.Id): $_" }
    $Proc.WaitForExit(10000) | Out-Null
}

function Request-EngineStop($Proc) {
    # Berhenti rapi lewat berkas stop engine; paksa bila melewati batas.
    if ($null -eq $Proc -or $Proc.HasExited) { return }
    New-Item -ItemType File -Force -Path $EngineStopFile | Out-Null
    Write-Log "meminta engine berhenti rapi (tunggu maks $StopGraceSeconds dtk)"
    if (-not $Proc.WaitForExit($StopGraceSeconds * 1000)) {
        Stop-EngineProcess $Proc "tidak berhenti rapi dalam $StopGraceSeconds dtk"
    }
}

function Test-WatchdogStop { return (Test-Path $WatchdogStopFile) }

# ---- persiapan ---------------------------------------------------------------

Get-ChildItem -Path $StateDir -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path $WatchdogStopFile) { Remove-Item -Force $WatchdogStopFile }

# Engine yatim dari watchdog sebelumnya (mis. task dihentikan paksa) memegang port dan GPU.
if (Test-Path $PidFile) {
    $oldPid = 0
    if ([int]::TryParse((Get-Content $PidFile -Raw).Trim(), [ref]$oldPid) -and $oldPid -gt 0) {
        $old = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($null -ne $old -and $old.ProcessName -match "python") {
            Write-Log "engine lama (pid $oldPid) masih hidup; dihentikan"
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }
    Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
}

if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path $Python)) { throw "Python tidak ditemukan: $Python" }
if (-not (Test-Path $Config)) { throw "Config engine tidak ditemukan: $Config" }
if ($AffinityMask -and $Python -match "\\Scripts\\python\.exe$") {
    Write-Log "PERINGATAN: python.exe ini kemungkinan peluncur venv; afinitas bisa tidak mengenai engine."
}

if (-not $SkipIpCheck) {
    $waited = 0
    while (-not (Get-NetIPAddress -IPAddress $BindIp -ErrorAction SilentlyContinue)) {
        if ($waited -ge $WaitForIpSeconds) { throw "IP $BindIp tidak muncul dalam $WaitForIpSeconds dtk (NetBird tersambung?)" }
        if ($waited % 60 -eq 0) { Write-Log "menunggu IP $BindIp ..." }
        if (Test-WatchdogStop) { Write-Log "watchdog.stop terlihat saat menunggu IP; selesai"; exit 0 }
        Start-Sleep -Seconds 5
        $waited += 5
    }
}

$engineArgs = @(
    "-m", "engine.runtime",
    "--config", (Quote-Arg $Config),
    "--tcp", "$($BindIp):$Port",
    "--health-seconds", "$HealthSeconds",
    "--heartbeat-file", (Quote-Arg $HeartbeatFile),
    "--stop-file", (Quote-Arg $EngineStopFile)
)
if ($TargetFps -gt 0) {
    # InvariantCulture: locale Indonesia menulis 6,5 dan argparse menolaknya.
    $engineArgs += @("--target-fps", $TargetFps.ToString([Globalization.CultureInfo]::InvariantCulture))
}

Write-Log "watchdog mulai (pid $PID). python: $Python"
Write-Log "engine: python $($engineArgs -join ' ')"

# ---- loop ----------------------------------------------------------------------

$backoff = 5
$restarts = 0
$proc = $null
try {
    while (-not (Test-WatchdogStop)) {
        Import-EnvFile $EnvFile
        foreach ($stale in @($HeartbeatFile, $EngineStopFile)) {
            if (Test-Path $stale) { Remove-Item -Force $stale }
        }
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $outLog = Join-Path $StateDir "engine-$stamp.out.log"
        $errLog = Join-Path $StateDir "engine-$stamp.err.log"
        $proc = Start-Process -FilePath $Python -ArgumentList $engineArgs -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $outLog -RedirectStandardError $errLog -NoNewWindow -PassThru
        # Ambil handle sekarang: tanpa ini ExitCode dari Start-Process -PassThru bisa kosong.
        $null = $proc.Handle
        Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
        if ($AffinityMask) {
            try {
                $proc.ProcessorAffinity = [IntPtr][Convert]::ToInt64($AffinityMask.Replace("0x", ""), 16)
            } catch { Write-Log "afinitas gagal dipasang: $_" }
        }
        $started = Get-Date
        Write-Log "engine dijalankan (pid $($proc.Id)); log $errLog"

        $why = $null
        while ($null -eq $why) {
            Start-Sleep -Seconds 2
            if ($proc.HasExited) { $why = "engine keluar dengan kode $($proc.ExitCode)"; break }
            if (Test-WatchdogStop) { $why = "watchdog.stop"; break }
            $elapsed = ((Get-Date) - $started).TotalSeconds
            if (Test-Path $HeartbeatFile) {
                $age = ((Get-Date) - (Get-Item $HeartbeatFile).LastWriteTime).TotalSeconds
                if ($age -gt $StaleSeconds) {
                    $why = "detak basi $([int]$age) dtk (batas $StaleSeconds): engine macet"
                    Stop-EngineProcess $proc $why
                }
            } elseif ($elapsed -gt $StartupGraceSeconds) {
                $why = "tidak ada detak dalam $StartupGraceSeconds dtk sejak start"
                Stop-EngineProcess $proc $why
            }
        }

        if ($why -eq "watchdog.stop") { break }
        $ran = ((Get-Date) - $started).TotalSeconds
        Write-Log "$why (berjalan $([int]$ran) dtk)"
        Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
        if ($ran -ge $StableSeconds) { $backoff = 5 }
        $restarts += 1
        if ($MaxRestarts -gt 0 -and $restarts -ge $MaxRestarts) {
            Write-Log "batas $MaxRestarts kali hidup ulang tercapai; watchdog berhenti"
            exit 1
        }
        Write-Log "menjalankan ulang dalam $backoff dtk (hidup ulang ke-$restarts)"
        for ($i = 0; $i -lt $backoff -and -not (Test-WatchdogStop); $i++) { Start-Sleep -Seconds 1 }
        $backoff = [Math]::Min($backoff * 2, $MaxBackoffSeconds)
    }
} finally {
    # Ctrl+C, watchdog.stop, atau galat: engine tidak boleh tertinggal tanpa pengawas.
    Request-EngineStop $proc
    Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
    if (Test-Path $WatchdogStopFile) { Remove-Item -Force $WatchdogStopFile -ErrorAction SilentlyContinue }
    Write-Log "watchdog selesai"
}
