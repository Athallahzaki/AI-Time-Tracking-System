#!/usr/bin/env bash
# Kalibrasi tracker/NMS + uji 5 kamera dengan detector bersama.
#
#   SRC=/kaggle/input/.../rekaman.mp4 bash scripts/bench_kalibrasi.sh
#
# Semua varian 1 kamera memakai rekaman, seed, dan profil yang SAMA; hanya satu
# kelompok pengaturan yang berubah per run, supaya kolom raw/2s bisa dibandingkan.
# Setiap pengaturan tercatat di baseline.json (config.effective).
set -euo pipefail

SRC="${SRC:?isi SRC dengan path rekaman}"
CONFIG="${CONFIG:-engine/config/demo-4060.yaml}"
OUT="${OUT:-bench-out/kalibrasi}"
ONLY="${ONLY:-}"   # mis. ONLY="k1 k2" untuk menjalankan sebagian

run() {
  local name="$1"; shift
  if [[ -n "$ONLY" && " $ONLY " != *" $name "* ]]; then return; fi
  echo "=== $name"
  python -m engine.bench --config "$CONFIG" --source "$SRC" --seed 1337 \
    --label "$name" --out "$OUT/$name" --quiet "$@"
}

# 1 kamera, throughput: berapa kali track putus lalu tersambung lagi.
run k0-dasar        --mode throughput
run k1-nms07        --mode throughput --set detector.nms_iou_threshold=0.7
run k2-nms07-buf2   --mode throughput --set detector.nms_iou_threshold=0.7 --set tracker.track_buffer_seconds=2
run k3-nms07-buf3   --mode throughput --set detector.nms_iou_threshold=0.7 --set tracker.track_buffer_seconds=3
# Resize di decoder (swscale YUV -> RGB 640 sekali jalan), bukan BGR 1080p + cv2.resize.
# Cek fps NAIK dan tracks / raw/2s TIDAK berubah banyak dibanding k0 (interpolasi beda).
run k5-swscale      --mode throughput --set detector.swscale_resize=true

# 3 kamera, realtime, satu D-FINE bersama (seperti runtime), cuda_graph dari profil (on).
# Bila crash di CUDA graph, ulangi: ONLY=r3-bersama EXTRA="--set detector.cuda_graph=false"
run r3-bersama      --mode realtime --cameras 3 --frames 3000 ${EXTRA:-}

python -m engine.bench.compare "$OUT"/*/
