<#
.SYNOPSIS
  Pasang/hapus engine sebagai tugas Windows yang jalan sendiri saat laptop menyala (paket ea-r6).

.DESCRIPTION
  Memakai Task Scheduler bawaan Windows (tanpa NSSM atau biner pihak ketiga). Tugas menjalankan
  engine-watchdog.ps1, yang menjalankan engine dan menghidupkannya ulang bila mati atau macet.
  Task Scheduler sendiri menghidupkan ulang watchdog bila watchdog keluar (tiap 1 menit, 999x).

  Jalankan dari PowerShell "Run as Administrator".

  -Trigger Startup (default): jalan saat Windows menyala, sebelum ada yang login (akun ini,
     LogonType S4U, tanpa menyimpan kata sandi). Proses berjalan tanpa jendela.
  -Trigger Logon: jalan saat akun ini login (sesi interaktif). Pakai bila Startup bermasalah
     dengan GPU/driver di laptop ini.

  Isi -Python dengan path python.exe absolut dari env engine (mis. hasil `where python` di env
  conda): tugas tidak menjalankan `conda activate`. Rahasia lewat -EnvFile (baris KEY=VALUE),
  bukan argumen.

.EXAMPLE
  .\deploy\laptop\install-engine-task.ps1 -BindIp 100.64.0.12 -Config engine/config/demo-1060.yaml `
      -Python C:\Users\tim\miniconda3\envs\engine\python.exe -EnvFile C:\aitt\engine.env -StartNow

.EXAMPLE
  .\deploy\laptop\install-engine-task.ps1 -Stop          # hentikan rapi (watchdog + engine)
  .\deploy\laptop\install-engine-task.ps1 -Uninstall     # hentikan rapi lalu hapus tugas
#>
param(
    [Alias("NetBirdIp")][string]$BindIp = "",
    [string]$Config = "engine/config/demo-4060.yaml",
    [int]$Port = 8765,
    [int]$HealthSeconds = 10,
    [string]$AffinityMask = "",
    [double]$TargetFps = 0,
    [string]$Python = "",
    [string]$EnvFile = "",
    [string]$StateDir = "logs\engine",
    [ValidateSet("Startup", "Logon")][string]$Trigger = "Startup",
    # Jeda sesudah boot/login supaya jaringan, NetBird, dan driver GPU siap dulu.
    [int]$DelaySeconds = 60,
    [string]$TaskName = "AITT-Engine",
    [switch]$StartNow,
    [switch]$Stop,
    [switch]$Uninstall,
    # Opsional: matikan sleep saat terhubung listrik (uji 3 hari gagal bila laptop tidur).
    [switch]$DisableSleepOnAC
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Watchdog = Join-Path $PSScriptRoot "engine-watchdog.ps1"
if (-not [IO.Path]::IsPathRooted($StateDir)) { $StateDir = Join-Path $RepoRoot $StateDir }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Jalankan dari PowerShell 'Run as Administrator'." }

function Stop-EngineTask {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { Write-Host "Tugas $TaskName tidak ada."; return }
    if ($task.State -ne "Running") { Write-Host "Tugas $TaskName tidak sedang berjalan."; return }
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    New-Item -ItemType File -Force -Path (Join-Path $StateDir "watchdog.stop") | Out-Null
    Write-Host "Meminta watchdog berhenti rapi (maks 90 dtk)..."
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        if ((Get-ScheduledTask -TaskName $TaskName).State -ne "Running") { Write-Host "Berhenti."; return }
    }
    Write-Warning "Watchdog tidak berhenti rapi; tugas dihentikan paksa."
    Stop-ScheduledTask -TaskName $TaskName
    # Stop-ScheduledTask tidak selalu mematikan proses anak: watchdog berikutnya juga
    # mematikan engine yatim dari engine.pid saat start.
}

if ($Stop -or $Uninstall) {
    Stop-EngineTask
    if ($Uninstall -and (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tugas $TaskName dihapus."
    }
    return
}

if (-not $BindIp) { throw "-BindIp wajib (IP NetBird laptop, atau 127.0.0.1 untuk uji lokal)." }
if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path $Python)) { throw "Python tidak ditemukan: $Python" }
$Python = (Resolve-Path $Python).Path
if ($EnvFile) { $EnvFile = (Resolve-Path $EnvFile).Path }
if (-not (Test-Path (Join-Path $RepoRoot $Config)) -and -not (Test-Path $Config)) {
    throw "Config engine tidak ditemukan: $Config"
}

function Quote-Arg([string]$Text) { '"' + $Text.Replace('"', '\"') + '"' }

$watchdogArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Quote-Arg $Watchdog),
    "-BindIp", $BindIp, "-Config", (Quote-Arg $Config), "-Port", $Port,
    "-HealthSeconds", $HealthSeconds, "-Python", (Quote-Arg $Python), "-StateDir", (Quote-Arg $StateDir)
)
if ($AffinityMask) { $watchdogArgs += @("-AffinityMask", $AffinityMask) }
if ($TargetFps -gt 0) {
    $watchdogArgs += @("-TargetFps", $TargetFps.ToString([Globalization.CultureInfo]::InvariantCulture))
}
if ($EnvFile) { $watchdogArgs += @("-EnvFile", (Quote-Arg $EnvFile)) }
if ($BindIp -eq "127.0.0.1") { $watchdogArgs += "-SkipIpCheck" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($watchdogArgs -join " ") -WorkingDirectory $RepoRoot
$user = "$env:USERDOMAIN\$env:USERNAME"
if ($Trigger -eq "Startup") {
    $taskTrigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Highest
} else {
    $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
}
$taskTrigger.Delay = "PT{0}S" -f $DelaySeconds
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $taskTrigger `
    -Principal $principal -Settings $settings -Force `
    -Description "AI Time Tracking engine + watchdog (deploy/laptop/engine-watchdog.ps1)" | Out-Null
Write-Host "Tugas $TaskName terpasang ($Trigger, jeda $DelaySeconds dtk, akun $user)."
Write-Host "Perintah: powershell.exe $($watchdogArgs -join ' ')"
Write-Host "Log: $StateDir"

if ($DisableSleepOnAC) {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "Sleep/hibernate saat terhubung listrik dimatikan."
} else {
    Write-Host "Ingat: laptop yang tidur menghentikan engine. Pertimbangkan -DisableSleepOnAC."
}

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Tugas dijalankan. Cek: Get-Content (Join-Path '$StateDir' 'watchdog-*.log') -Tail 20"
}
