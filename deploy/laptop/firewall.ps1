<#
.SYNOPSIS
  Aturan firewall Windows laptop untuk demo jarak jauh (docs/DEMO-REMOTE.md).
  Jalankan di PowerShell Admin.

.DESCRIPTION
  Membuka port HANYA untuk IP NetBird server (dan VPS bila WebRTC dipakai):
    8765  engine         <- backend di server
    8888  MediaMTX HLS   <- nginx di server
    8889  MediaMTX WHEP  <- nginx di server
    8189  WebRTC TCP     <- VPS (hanya bila -VpsNetBirdIp diisi)
  RTSP 8554 dan API 9997 sengaja tidak dibuka: hanya dipakai di laptop.

  Catatan: aturan BLOCK per aplikasi (mis. python.exe yang dulu ditolak di
  dialog firewall) mengalahkan aturan ALLOW ini. Cek di "Allowed apps".

.EXAMPLE
  .\deploy\laptop\firewall.ps1 -ServerNetBirdIp 100.64.0.5
.EXAMPLE
  .\deploy\laptop\firewall.ps1 -ServerNetBirdIp 100.64.0.5 -VpsNetBirdIp 100.64.0.9
.EXAMPLE
  .\deploy\laptop\firewall.ps1 -Remove
#>
param(
    [string]$ServerNetBirdIp = "",
    [string]$VpsNetBirdIp = "",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Prefix = "AITT demo remote"

$existing = Get-NetFirewallRule -DisplayName "$Prefix*" -ErrorAction SilentlyContinue
if ($existing) { $existing | Remove-NetFirewallRule }
if ($Remove) {
    Write-Host "Aturan '$Prefix*' dihapus."
    return
}
if (-not $ServerNetBirdIp) { throw "Isi -ServerNetBirdIp (IP NetBird server), atau pakai -Remove." }

New-NetFirewallRule -DisplayName "$Prefix - engine 8765" -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 8765 -RemoteAddress $ServerNetBirdIp -Profile Any | Out-Null
New-NetFirewallRule -DisplayName "$Prefix - mediamtx 8888-8889" -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 8888, 8889 -RemoteAddress $ServerNetBirdIp -Profile Any | Out-Null
if ($VpsNetBirdIp) {
    New-NetFirewallRule -DisplayName "$Prefix - webrtc 8189" -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort 8189 -RemoteAddress $VpsNetBirdIp -Profile Any | Out-Null
}

Get-NetFirewallRule -DisplayName "$Prefix*" | Format-Table DisplayName, Enabled, Action -AutoSize
