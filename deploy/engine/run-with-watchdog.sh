#!/bin/sh
# Jalankan engine dan matikan bila MACET (padanan Linux/Docker dari
# deploy/laptop/engine-watchdog.ps1; ANALISIS-KETAHANAN §4).
#
# Docker `restart: unless-stopped` hanya menyalakan ulang proses yang KELUAR.
# Engine yang hidup tetapi menggantung (CUDA hang, deadlock) tidak pernah
# keluar. Skrip ini memantau berkas detak engine; bila basi, engine dimatikan
# dan skrip keluar dengan kode 70, sehingga Docker menyalakan ulang container.
#
# Pemakaian (compose):
#   command: ["sh", "deploy/engine/run-with-watchdog.sh", "--config", "...", "--tcp", "0.0.0.0:8765"]
#   restart: unless-stopped
# Semua argumen diteruskan ke `python -m engine.runtime`.
#
# Lingkungan (opsional):
#   ENGINE_HEARTBEAT_FILE              berkas detak (default /tmp/engine-heartbeat.json)
#   ENGINE_WATCHDOG_STALE_SECONDS      detak lebih tua dari ini = macet (default 60; detak tiap 5 dtk)
#   ENGINE_WATCHDOG_STARTUP_SECONDS    batas sampai detak pertama, mis. muat model (default 240)
#   ENGINE_WATCHDOG_KILL_SECONDS       tunggu berhenti rapi sebelum dipaksa (default 30)
#   ENGINE_PYTHON                      interpreter (default python)

HB="${ENGINE_HEARTBEAT_FILE:-/tmp/engine-heartbeat.json}"
STALE="${ENGINE_WATCHDOG_STALE_SECONDS:-60}"
STARTUP="${ENGINE_WATCHDOG_STARTUP_SECONDS:-240}"
KILL_AFTER="${ENGINE_WATCHDOG_KILL_SECONDS:-30}"
export ENGINE_HEARTBEAT_FILE="$HB"   # engine membacanya sebagai default --heartbeat-file

rm -f "$HB"
"${ENGINE_PYTHON:-python}" -m engine.runtime "$@" &
pid=$!

stop_engine() {
    kill -TERM "$pid" 2>/dev/null
    # Proses macet tidak menanggapi TERM: paksa setelah batas waktu.
    ( sleep "$KILL_AFTER"; kill -KILL "$pid" 2>/dev/null ) &
    killer=$!
    wait "$pid"
    code=$?
    kill "$killer" 2>/dev/null
    return "$code"
}

# `docker stop` mengirim TERM ke skrip ini: teruskan supaya engine menutup interval dengan rapi.
trap 'stop_engine; exit $?' TERM INT

started=$(date +%s)
while kill -0 "$pid" 2>/dev/null; do
    sleep 5 &
    wait $!                     # `wait` bisa disela trap; `sleep` langsung tidak
    now=$(date +%s)
    if [ -f "$HB" ]; then
        age=$(( now - $(stat -c %Y "$HB") ))
        limit=$STALE
    else
        age=$(( now - started ))
        limit=$STARTUP
    fi
    if [ "$age" -gt "$limit" ]; then
        echo "watchdog: detak engine basi ${age} dtk (batas ${limit}); engine dimatikan untuk dinyalakan ulang" >&2
        stop_engine
        exit 70
    fi
done

wait "$pid"
exit $?
