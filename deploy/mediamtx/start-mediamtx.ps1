$ErrorActionPreference = "Stop"
$DeployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $DeployDir ".env.mediamtx"
$ComposeFile = Join-Path $DeployDir "docker-compose.mediamtx.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker tidak ditemukan. Instal dan jalankan Docker Desktop terlebih dahulu."
}
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $DeployDir ".env.mediamtx.example") $EnvFile
    throw "deploy/mediamtx/.env.mediamtx telah dibuat. Isi CAM01_SOURCE, lalu jalankan script ini lagi."
}

docker compose --env-file $EnvFile -f $ComposeFile config --quiet
if ($LASTEXITCODE -ne 0) { throw "Konfigurasi Docker Compose tidak valid." }
docker compose --env-file $EnvFile -f $ComposeFile up -d
if ($LASTEXITCODE -ne 0) { throw "MediaMTX gagal dijalankan." }

Write-Host "MediaMTX dijalankan. Memeriksa status..."
Start-Sleep -Seconds 3
python (Join-Path $DeployDir "..\..\scripts\check_mediamtx.py")

