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
# ByteTrack dua tahap: detector 0,3 supaya kotak 0,3-0,5 sampai ke asosiasi skor-rendah;
# track baru tetap butuh >= 0,5. Ini juga menurunkan ambang kotak yang dilihat tahap lain.
run k4-dua-tahap    --mode throughput --set detector.nms_iou_threshold=0.7 --set tracker.track_buffer_seconds=2 \
                    --set detector.confidence_threshold=0.3 --set tracker.track_threshold=0.5

# 5 kamera, realtime, satu D-FINE bersama (seperti runtime). cuda_graph tetap dari profil;
# bila crash, ulangi dengan: ONLY=r5 EXTRA="--set detector.cuda_graph=false"
run r5-bersama      --mode realtime --cameras 5 --frames 3000 ${EXTRA:-}

python -m engine.bench.compare "$OUT"/*/
