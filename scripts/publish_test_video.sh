#!/usr/bin/env sh
# Publish video uji ke MediaMTX sebagai "kamera" (default cam01), berulang.
# Encode ulang tanpa B-frame dan GOP 1 dtk; alasannya ada di publish_test_video.ps1.
#
# Pakai: sh scripts/publish_test_video.sh uji.mp4 [fps=25] [path=cam01] [width=0]
set -eu
VIDEO="${1:?pakai: publish_test_video.sh <video> [fps] [path] [width]}"
FPS="${2:-25}"
PATH_NAME="${3:-cam01}"
WIDTH="${4:-0}"
SERVER="${MEDIAMTX_RTSP:-rtsp://127.0.0.1:8554}"
command -v ffmpeg >/dev/null || { echo "ffmpeg tidak ditemukan" >&2; exit 1; }
[ -f "$VIDEO" ] || { echo "video tidak ditemukan: $VIDEO" >&2; exit 1; }
VF="fps=$FPS"
[ "$WIDTH" -gt 0 ] && VF="$VF,scale=$WIDTH:-2"
echo "Publish $VIDEO -> $SERVER/$PATH_NAME ($FPS fps, GOP 1 dtk, tanpa B-frame). Ctrl+C untuk berhenti."
exec ffmpeg -hide_banner -loglevel warning -re -stream_loop -1 -i "$VIDEO" -an \
    -vf "$VF" -c:v libx264 -preset veryfast -tune zerolatency -profile:v high \
    -bf 0 -g "$FPS" -keyint_min "$FPS" -sc_threshold 0 -pix_fmt yuv420p \
    -f rtsp -rtsp_transport tcp "$SERVER/$PATH_NAME"
