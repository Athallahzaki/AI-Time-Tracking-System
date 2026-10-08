<#
.SYNOPSIS
  MediaMTX di laptop untuk demo jarak jauh (docs/DEMO-REMOTE.md).

.DESCRIPTION
  Memakai deploy/mediamtx/mediamtx.yml dari repo (path cam01 = publisher,
  RTSP 8554, HLS 8888, WHEP 8889). Tanpa -VpsPublicIp: cukup untuk mode HLS.
  Dengan -VpsPublicIp: WebRTC juga menerima media lewat TCP 8189 dan
  mengiklankan IP publik VPS sebagai kandidat ICE (mode cameras.remote-webrtc).

.EXAMPLE
  .\deploy\laptop\start-mediamtx.ps1 -MediaMtxExe C:\Users\Athallah\Desktop\test\mediamtx.exe

.EXAMPLE
  .\deploy\laptop\start-mediamtx.ps1 -MediaMtxExe C:\tools\mediamtx.exe -VpsPublicIp 203.0.113.10
#>
param(
    [string]$MediaMtxExe = "mediamtx.exe",
    [string]$VpsPublicIp = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Config = Join-Path $RepoRoot "deploy\mediamtx\mediamtx.yml"

if (-not (Test-Path $Config)) { throw "Config MediaMTX tidak ditemukan: $Config" }
$exe = Get-Command $MediaMtxExe -ErrorAction SilentlyContinue
if (-not $exe) { throw "mediamtx.exe tidak ditemukan: $MediaMtxExe (isi -MediaMtxExe dengan path lengkap)" }

if ($VpsPublicIp) {
    # Media WebRTC lewat TCP: VPS meneruskan TCP 8189 ke laptop via NetBird.
    $env:MTX_WEBRTCLOCALTCPADDRESS = ":8189"
    $env:MTX_WEBRTCADDITIONALHOSTS = $VpsPublicIp
    Write-Host "WebRTC: TCP :8189, kandidat ICE tambahan $VpsPublicIp"
} else {
    Remove-Item Env:MTX_WEBRTCLOCALTCPADDRESS -ErrorAction SilentlyContinue
    Remove-Item Env:MTX_WEBRTCADDITIONALHOSTS -ErrorAction SilentlyContinue
    Write-Host "Mode HLS (WebRTC hanya untuk jaringan lokal)."
}

Write-Host "MediaMTX: $($exe.Source)"
Write-Host "Config  : $Config"
& $exe.Source $Config
