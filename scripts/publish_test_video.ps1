# Publish video uji ke MediaMTX sebagai "kamera" cam01, berulang tanpa henti.
#
# Kenapa encode ulang (bukan -c copy): video rekaman umumnya punya B-frame dan
# GOP panjang (keyframe tiap 5-10 dtk). B-frame menambah latensi decode dan
# membuat WebRTC rewel; GOP panjang membuat browser dan engine menunggu lama
# sebelum gambar pertama dan setelah setiap paket hilang. Di sini: tanpa
# B-frame, keyframe tiap 1 detik, mirip kamera CCTV yang disetel benar.
#
# -Count N (default 1) mem-publish video yang sama ke cam01..camN sekaligus, satu
# proses ffmpeg per path, dengan aturan encode yang sama. Untuk baseline 5 kamera
# (DEMO-REMOTE 8.1). Dengan -Count > 1, nama path selalu cam01..camN (-Path tidak
# boleh diberikan). Bila satu proses mati, semuanya dihentikan dan skrip gagal.
# Catatan beban: tiap path = satu encode x264 penuh; 5 path memakai CPU laptop
# yang sama dengan engine, jadi baseline ini sudah termasuk biaya publish.
#
# Pakai:
#   .\scripts\publish_test_video.ps1 -Video C:\video\uji.mp4
#   .\scripts\publish_test_video.ps1 -Video uji.mp4 -Fps 25 -Path cam01 -Width 1280
#   .\scripts\publish_test_video.ps1 -Video uji.mp4 -Count 5
param(
    [Parameter(Mandatory = $true)][string]$Video,
    [int]$Fps = 25,
    [string]$Path = "cam01",
    [string]$Server = "rtsp://127.0.0.1:8554",
    [int]$Width = 0,         # 0 = resolusi asli; 1280 untuk uji ringan
    [ValidateRange(1, 99)][int]$Count = 1   # jumlah kamera: cam01..camN
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg tidak ditemukan di PATH. Instal (winget install Gyan.FFmpeg) lalu buka terminal baru."
}
if (-not (Test-Path $Video)) { throw "Video tidak ditemukan: $Video" }

$vf = "fps=$Fps"
if ($Width -gt 0) { $vf = "$vf,scale=${Width}:-2" }

# Aturan encode satu-satunya (dipakai semua path).
$encode = @(
    "-vf", $vf, "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
    "-profile:v", "high", "-bf", "0", "-g", "$Fps", "-keyint_min", "$Fps",
    "-sc_threshold", "0", "-pix_fmt", "yuv420p",
    "-f", "rtsp", "-rtsp_transport", "tcp"
)

if ($Count -eq 1) {
    Write-Host "Publish $Video -> $Server/$Path ($Fps fps, GOP 1 dtk, tanpa B-frame). Ctrl+C untuk berhenti."
    ffmpeg -hide_banner -loglevel warning -re -stream_loop -1 -i $Video -an @encode "$Server/$Path"
    return
}

if ($PSBoundParameters.ContainsKey("Path")) {
    throw "-Path tidak dipakai bersama -Count > 1 (path otomatis cam01..cam$('{0:D2}' -f $Count))."
}

$names = 1..$Count | ForEach-Object { "cam{0:D2}" -f $_ }
Write-Host "Publish $Video -> $Server/{$($names -join ',')} ($Count proses ffmpeg, $Fps fps, GOP 1 dtk, tanpa B-frame). Ctrl+C untuk berhenti."

# Start-Process tidak menambah tanda kutip di sekitar argumen berspasi: kutip sendiri.
function Quote-Arg([string]$text) { if ($text -match '\s') { '"' + $text + '"' } else { $text } }

$procs = @()
try {
    foreach ($name in $names) {
        $ffArgs = @("-hide_banner", "-loglevel", "warning", "-re", "-stream_loop", "-1",
                    "-i", (Quote-Arg $Video), "-an") + ($encode | ForEach-Object { Quote-Arg $_ }) + @("$Server/$name")
        $procs += [pscustomobject]@{
            Name = $name
            Proc = Start-Process -FilePath "ffmpeg" -ArgumentList $ffArgs -NoNewWindow -PassThru
        }
        Start-Sleep -Milliseconds 500   # jangan menyerbu MediaMTX dengan 5 handshake sekaligus
    }
    while ($true) {
        Start-Sleep -Seconds 2
        $dead = $procs | Where-Object { $_.Proc.HasExited }
        if ($dead) {
            $list = ($dead | ForEach-Object { "$($_.Name) (kode $($_.Proc.ExitCode))" }) -join ", "
            throw "Proses ffmpeg berhenti: $list. Baseline tidak valid; semua dihentikan."
        }
    }
}
finally {
    foreach ($p in $procs) {
        if (-not $p.Proc.HasExited) { Stop-Process -Id $p.Proc.Id -Force -ErrorAction SilentlyContinue }
    }
}
