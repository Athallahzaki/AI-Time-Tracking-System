<#
.SYNOPSIS
    Env kloningan untuk uji TensorRT EP rekognisi wajah (paket ea-r11).

.DESCRIPTION
    Env kerja (vision-engine) TIDAK diubah: semua dipasang di kloningannya
    (vision-engine-trt). Kalau uji TensorRT gagal atau hasilnya buruk, cukup hapus
    env kloningan; engine yang sekarang tetap jalan seperti biasa.

    Langkah:
      1. conda create --clone  (menyalin env sumber, +-5-10 GB, beberapa menit)
      2. baca versi onnxruntime-gpu di env baru, pilih TensorRT yang dipakai CI
         onnxruntime untuk build tersebut (tabel sama dengan scripts/check_gpu_env.py)
      3. pip install tensorrt-cu12-libs (pustaka nvinfer, +-1-2 GB) + onnx
      4. python scripts/check_gpu_env.py --tensorrt  (sesi SCRFD sungguhan di TensorRT;
         pertama kali +-1 menit karena engine dibangun, sekaligus mengisi cache)

    Butuh internet (PyPI + pypi.nvidia.com). Tidak menyentuh model, config, atau data.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup-env-trt.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup-env-trt.ps1 -TrtVersi 10.9

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup-env-trt.ps1 -LewatiKloning
    (env vision-engine-trt sudah ada: hanya pasang ulang paket TensorRT lalu periksa)
#>
param(
    [string]$Sumber = "vision-engine",
    [string]$Nama = "vision-engine-trt",
    # Kosong = otomatis dari versi onnxruntime-gpu. Isi mis. "10.9" untuk memaksa.
    [string]$TrtVersi = "",
    [switch]$LewatiKloning
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

# Versi TensorRT yang dipakai CI onnxruntime (CUDA 12) per rilis. Sumber dan tanggal:
# scripts/check_gpu_env.py, TRT_FOR_ORT. Ubah keduanya bersamaan.
$TrtUntukOrt = @{
    "1.20" = "10.4"; "1.21" = "10.8"; "1.22" = "10.9"; "1.23" = "10.9";
    "1.24" = "10.14"; "1.25" = "10.14"; "1.26" = "10.14"
}

function Langkah([string]$Teks) {
    Write-Host ""
    Write-Host "== $Teks" -ForegroundColor Cyan
}

function Cari-Prefix([string]$NamaEnv) {
    $daftar = (& conda env list --json | Out-String | ConvertFrom-Json).envs
    foreach ($prefix in $daftar) {
        if ((Split-Path -Leaf $prefix) -ieq $NamaEnv) { return $prefix }
    }
    return $null
}

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "conda tidak ditemukan. Jalankan dari 'Anaconda Prompt (PowerShell)' atau setelah 'conda init powershell'."
}

$prefixSumber = Cari-Prefix $Sumber
if (-not $prefixSumber) { throw "env sumber '$Sumber' tidak ditemukan (conda env list)." }
$prefixTujuan = Cari-Prefix $Nama

if (-not $LewatiKloning) {
    if ($prefixTujuan) {
        throw "env '$Nama' sudah ada di $prefixTujuan. Pakai -LewatiKloning untuk memasang ulang paket, atau hapus dulu: conda env remove -n $Nama"
    }
    Langkah "1/4 kloning $Sumber -> $Nama (beberapa menit)"
    & conda create --name $Nama --clone $Sumber --yes
    if ($LASTEXITCODE -ne 0) { throw "conda create --clone gagal (kode $LASTEXITCODE)" }
    $prefixTujuan = Cari-Prefix $Nama
} elseif (-not $prefixTujuan) {
    throw "-LewatiKloning dipakai tetapi env '$Nama' belum ada."
}

$py = Join-Path $prefixTujuan "python.exe"
if (-not (Test-Path $py)) { throw "python.exe tidak ditemukan di $prefixTujuan" }
Write-Host "python env: $py"

Langkah "2/4 versi onnxruntime-gpu"
$ortVersi = (& $py -c "import onnxruntime as o; print(o.__version__)" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $ortVersi) { throw "onnxruntime tidak bisa diimpor di env $Nama" }
# Tanpa pengalihan stderr: di Windows PowerShell 5.1, stderr exe yang dialihkan
# menjadi ErrorRecord dan memicu $ErrorActionPreference = "Stop".
$null = & $py -m pip show onnxruntime-gpu
if ($LASTEXITCODE -ne 0) {
    throw "env $Nama memakai paket 'onnxruntime' (CPU), bukan onnxruntime-gpu: TensorRT EP tidak ada. Perbaiki env sumber dulu (docs/SETUP-GPU.md)."
}
$ortMinor = ($ortVersi -split "\.")[0..1] -join "."
if (-not $TrtVersi) {
    $TrtVersi = $TrtUntukOrt[$ortMinor]
    if (-not $TrtVersi) {
        throw "onnxruntime-gpu $ortVersi tidak ada di tabel. Cari versi TensorRT build-nya, lalu jalankan ulang dengan -TrtVersi <versi> -LewatiKloning."
    }
}
Write-Host "onnxruntime-gpu $ortVersi -> TensorRT $TrtVersi"

Langkah "3/4 pasang tensorrt-cu12-libs==$TrtVersi.* + onnx (+-1-2 GB)"
& $py -m pip install "tensorrt-cu12-libs==$TrtVersi.*" "onnx>=1.16" --extra-index-url https://pypi.nvidia.com
if ($LASTEXITCODE -ne 0) { throw "pip install gagal (kode $LASTEXITCODE). Coba -TrtVersi dengan versi lengkap, mis. 10.9.0.34." }

Langkah "4/4 periksa env (sesi SCRFD di TensorRT; pertama kali +-1 menit)"
Push-Location $RepoRoot
try {
    & $py scripts\check_gpu_env.py --tensorrt --json bench-out\env-trt.json
    $kode = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host ""
if ($kode -eq 0) {
    Write-Host "SIAP. Berikutnya (dari $RepoRoot):" -ForegroundColor Green
} else {
    Write-Host "Ada GAGAL di atas (hasil juga di bench-out\env-trt.json). Baris 'tensorrt*' yang menentukan untuk uji ini;" -ForegroundColor Yellow
    Write-Host "GAGAL lain (mis. driver) berlaku sama untuk env $Sumber. Langkah berikutnya bila tensorrt-sesi OK:" -ForegroundColor Yellow
}
Write-Host "  conda activate $Nama"
Write-Host "  python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --source <video> --varian cuda,trt16 --simpan-potongan bench-out\potongan --json bench-out\face-bench-trt.json"
Write-Host "  python -m engine.tools.scrfd_dynamic --input engine/models/recognition/scrfd_10g_bnkps.onnx --output engine/models/recognition/scrfd_10g_bnkps_dinamis.onnx"
exit $kode
