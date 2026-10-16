<#
.SYNOPSIS
  Engine di laptop untuk demo jarak jauh (docs/DEMO-REMOTE.md).

.DESCRIPTION
  Engine mendengarkan HANYA di IP NetBird laptop, jadi tidak terbuka di Wi-Fi
  tempat laptop berada. Backend di server yang menyambung ke sini.

  Backend belum mendukung kunci handshake engine (ENGINE_SHARED_KEY), jadi
  engine jalan tanpa kunci dan akan mencetak peringatan. Pengamannya: bind ke
  IP NetBird + ACL NetBird + firewall Windows (firewall.ps1).

  -AffinityMask opsional, mis. 0xFFFF untuk mengunci engine ke 16 thread P-core
  di laptop Intel hybrid (uji 8 Okt). Hanya berlaku bila python.exe yang
  dipakai adalah interpreter asli (env conda), bukan peluncur venv.

.EXAMPLE
  .\deploy\laptop\start-engine.ps1 -NetBirdIp 100.64.0.12

.EXAMPLE
  .\deploy\laptop\start-engine.ps1 -NetBirdIp 100.64.0.12 -Config engine/config/demo-1060.yaml -AffinityMask 0xFFFF

.EXAMPLE
  # Uji A/B (gladi A) tanpa server: hanya lag_probe di laptop yang bisa masuk.
  .\deploy\laptop\start-engine.ps1 -BindIp 127.0.0.1 -HealthSeconds 2 -AffinityMask 0xFFFF
  .\deploy\laptop\start-engine.ps1 -BindIp 127.0.0.1 -HealthSeconds 2 -AffinityMask 0xFFFF -TargetFps 6
#>
param(
    [Parameter(Mandatory = $true)][Alias("NetBirdIp")][string]$BindIp,
    [string]$Config = "engine/config/demo-4060.yaml",
    [int]$Port = 8765,
    [int]$HealthSeconds = 10,
    [string]$AffinityMask = "",
    # Menimpa core.target_fps profil (mis. 6 untuk uji free vs tick, DEMO-REMOTE §8.1).
    [double]$TargetFps = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

if (-not (Get-NetIPAddress -IPAddress $BindIp -ErrorAction SilentlyContinue)) {
    throw "IP $BindIp tidak ada di laptop ini. Untuk IP NetBird: sudah tersambung? Cek: netbird status"
}
if (-not (Test-Path $Config)) { throw "Config engine tidak ditemukan: $Config" }

$python = (Get-Command python -ErrorAction Stop).Source
Write-Host "Python : $python"
if ($AffinityMask -and $python -match "\\Scripts\\python\.exe$") {
    Write-Warning "python.exe ini kemungkinan peluncur venv; afinitas bisa tidak mengenai engine. Pakai env conda atau cmd 'start /affinity'."
}

$engineArgs = @(
    "-m", "engine.runtime",
    "--config", $Config,
    "--tcp", "$($BindIp):$Port",
    "--health-seconds", "$HealthSeconds"
)
if ($TargetFps -gt 0) {
    # InvariantCulture: locale Indonesia menulis 6,5 dan argparse menolaknya.
    $engineArgs += @("--target-fps", $TargetFps.ToString([Globalization.CultureInfo]::InvariantCulture))
}
Write-Host "Engine : python $($engineArgs -join ' ')"

$proc = Start-Process -FilePath $python -ArgumentList $engineArgs -NoNewWindow -PassThru
if ($AffinityMask) {
    $proc.ProcessorAffinity = [IntPtr][Convert]::ToInt64($AffinityMask.Replace("0x", ""), 16)
    Write-Host "Afinitas: $($proc.ProcessorAffinity) (pid $($proc.Id))"
}
Wait-Process -Id $proc.Id
