# Publish video uji ke MediaMTX sebagai "kamera" cam01, berulang tanpa henti.
#
# Kenapa encode ulang (bukan -c copy): video rekaman umumnya punya B-frame dan
# GOP panjang (keyframe tiap 5-10 dtk). B-frame menambah latensi decode dan
# membuat WebRTC rewel; GOP panjang membuat browser dan engine menunggu lama
# sebelum gambar pertama dan setelah setiap paket hilang. Di sini: tanpa
# B-frame, keyframe tiap 1 detik, mirip kamera CCTV yang disetel benar.
#
# Pakai:
#   .\scripts\publish_test_video.ps1 -Video C:\video\uji.mp4
#   .\scripts\publish_test_video.ps1 -Video uji.mp4 -Fps 25 -Path cam01 -Width 1280
param(
    [Parameter(Mandatory = $true)][string]$Video,
    [int]$Fps = 25,
    [string]$Path = "cam01",
    [string]$Server = "rtsp://127.0.0.1:8554",
    [int]$Width = 0          # 0 = resolusi asli; 1280 untuk uji ringan
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg tidak ditemukan di PATH. Instal (winget install Gyan.FFmpeg) lalu buka terminal baru."
}
if (-not (Test-Path $Video)) { throw "Video tidak ditemukan: $Video" }

$vf = "fps=$Fps"
if ($Width -gt 0) { $vf = "$vf,scale=${Width}:-2" }

Write-Host "Publish $Video -> $Server/$Path ($Fps fps, GOP 1 dtk, tanpa B-frame). Ctrl+C untuk berhenti."
ffmpeg -hide_banner -loglevel warning -re -stream_loop -1 -i $Video -an `
    -vf $vf -c:v libx264 -preset veryfast -tune zerolatency -profile:v high `
    -bf 0 -g $Fps -keyint_min $Fps -sc_threshold 0 -pix_fmt yuv420p `
    -f rtsp -rtsp_transport tcp "$Server/$Path"
