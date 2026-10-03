"""Uji teori delay: apakah ENGINE yang tertinggal, atau jalur dashboard.

Probe ini menyambung ke engine SEBAGAI PENGGANTI BACKEND, mengirim
`set_cameras`, lalu mencatat seberapa basi hasil analisis engine dari waktu ke
waktu. Backend dan frontend tidak terlibat sama sekali, jadi hasilnya
memisahkan dua kemungkinan yang dari layar terlihat sama:

- delay yang BERTAMBAH seiring waktu  -> engine lebih lambat dari kamera (P17);
- delay yang TETAP dan kecil di sini   -> engine segar; delay di dashboard
  berasal dari jalur backend -> frontend atau sinkronisasi video (P10/P16/P18).

Yang dicatat per kamera:
- `frame_age_s`  = jam probe - `at` dari view.frame (umur kotak saat tiba).
  Termasuk bias offset awal (P18), jadi yang penting POLANYA, bukan nilainya.
  Jalankan probe di MESIN ENGINE supaya jam keduanya sama.
- `lag_s`        = engine.health.camera_metrics.lag_seconds (PTS terbaru yang
  di-decode - PTS yang dianalisis). Bebas jam dinding; butuh live_buffer: latest.
- `fps`, `dropped` = effective_fps, frames_dropped_stale.

PENTING:
- Engine hanya melayani satu backend. Probe akan menggantikan backend yang
  sedang tersambung; jangan jalankan saat backend asli dipakai.
- Probe TIDAK mengirim ACK, jadi outbox engine tidak dipangkas. Tetap disarankan
  memakai outbox uji: `--outbox engine/data/outbox-uji.sqlite3`.
- Jalankan engine dengan `--health-seconds 2` supaya lag tercatat rapat.

Contoh:
    python -m engine.runtime --config engine/config/dfine-m.yaml --health-seconds 2 \\
        --outbox engine/data/outbox-uji.sqlite3
    python scripts/lag_probe.py --camera cam01=rtsp://127.0.0.1:8554/cam01 --minutes 5
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts import handshake_auth  # noqa: E402

GROWING_SLOPE = 0.02          # dtk umur per dtk uji (= 1,2 dtk per menit)
GROWING_DELTA = 2.0           # selisih median menit terakhir - menit pertama
FRESH_AGE = 1.5               # umur kotak yang dianggap segar
REPLAY_SLACK = 5.0            # event ber-ts lebih tua dari awal uji - ini = putar ulang outbox
FUTURE_AGE = -0.5             # lebih negatif dari ini = `at` di masa depan: data tidak valid


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_at(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _send(sock: socket.socket, message: Dict[str, Any]) -> None:
    sock.sendall((json.dumps(message) + "\n").encode("utf-8"))


def connect(host: str, port: int, key: Optional[str], timeout: float = 10.0):
    """Handshake seperti backend sungguhan, termasuk HMAC bila engine memintanya."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        return _handshake(sock, key, timeout)
    except BaseException:
        sock.close()
        raise


def _handshake(sock: socket.socket, key: Optional[str], timeout: float):
    reader = sock.makefile("r", encoding="utf-8")
    hello: Dict[str, Any] = {"type": "hello", "v": 1, "ts": _now_iso(), "protocol_version": 1,
                             "client": "lag-probe", "last_event_seq": 0}

    sock.settimeout(1.0)
    first: Optional[Dict[str, Any]] = None
    try:
        line = reader.readline()
        first = json.loads(line) if line else None
    except (socket.timeout, OSError):
        # Tanpa auth engine diam menunggu hello. Reader makefile tidak bisa
        # dipakai lagi setelah timeout, jadi buat yang baru.
        reader = sock.makefile("r", encoding="utf-8")
    sock.settimeout(timeout)

    client_nonce = None
    challenge_nonce = None
    if first and first.get("type") == "auth_challenge":
        if not key:
            raise SystemExit("engine meminta autentikasi; isi ENGINE_SHARED_KEY yang sama dengan engine")
        challenge_nonce = first["nonce"]
        client_nonce = handshake_auth.new_nonce()
        hello["auth"] = {
            "client_nonce": client_nonce,
            "mac": handshake_auth.hello_mac(key, challenge_nonce, client_nonce, "lag-probe", 0),
        }
    _send(sock, hello)

    while True:
        message = json.loads(reader.readline())
        if message.get("type") == "hello_ack":
            break
        if message.get("type") == "ack" and message.get("accepted") is False:
            raise SystemExit(f"handshake ditolak engine: {message.get('reason')}")
    if challenge_nonce is not None:
        expected = handshake_auth.hello_ack_mac(key, challenge_nonce, client_nonce)
        if not handshake_auth.verify(expected, (message.get("auth") or {}).get("mac")):
            raise SystemExit("bukti balik engine salah: ini bukan engine yang memegang kunci yang sama")
    sock.settimeout(1.0)
    return sock, reader, message


def _slope(points: List[Tuple[float, float]]) -> Optional[float]:
    if len(points) < 3:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _median_in(points: List[Tuple[float, float]], lo: float, hi: float) -> Optional[float]:
    values = [y for x, y in points if lo <= x < hi]
    return statistics.median(values) if values else None


def _fmt(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.2f}"


def summarize(rows: List[Dict[str, Any]], duration: float) -> List[str]:
    lines: List[str] = []
    cameras = sorted({r["camera_id"] for r in rows if r["camera_id"]})
    if not cameras:
        return ["Tidak ada data kamera. Cek URI di --camera dan log engine (camera.failed?)."]
    window = min(60.0, max(duration / 3.0, 5.0))
    for camera in cameras:
        ages = [(r["elapsed_s"], r["frame_age_s"]) for r in rows
                if r["camera_id"] == camera and r["frame_age_s"] != ""]
        lags = [(r["elapsed_s"], r["lag_s"]) for r in rows
                if r["camera_id"] == camera and r["lag_s"] != ""]
        fps = [r["fps"] for r in rows if r["camera_id"] == camera and r["fps"] != ""]
        events = [r["note"] for r in rows if r["camera_id"] == camera and r["source"] == "event"]
        identified = [r["note"] for r in rows if r["camera_id"] == camera and r.get("source") == "identified"]
        drifts = [float(r["drift_s"]) for r in rows
                  if r["camera_id"] == camera and r.get("drift_s") not in ("", None)]

        lines.append(f"== {camera}")
        if not ages:
            lines.append("  tidak ada view.frame: engine tidak menganalisis kamera ini (atau --view-fps 0).")
            continue
        # Jendela "awal" dihitung dari view.frame PERTAMA, bukan dari probe dibuka:
        # engine yang lama memuat model (GPU lambat, warmup CUDA) bisa baru mulai
        # setelah lebih dari satu jendela, dan jendela kosong dulu membuat probe crash.
        start = min(x for x, _ in ages)
        end = max(x for x, _ in ages)
        first = _median_in(ages, start, start + window)
        last = _median_in(ages, end - window, end + 1)
        slope = _slope(ages)
        lines.append(f"  view.frame pertama pada detik {start:.0f} probe; {len(ages)} sampel")
        lines.append(f"  umur kotak (median) awal {_fmt(first)} dtk -> akhir {_fmt(last)} dtk; "
                     f"kemiringan {slope if slope is not None else float('nan'):+.3f} dtk/dtk")
        if lags:
            lines.append(f"  lag decode->analisis: median {statistics.median(y for _, y in lags):.2f} dtk, "
                         f"maks {max(y for _, y in lags):.2f} dtk")
        else:
            lines.append("  lag decode->analisis tidak terlapor (live_buffer bukan 'latest', "
                         "atau --health-seconds terlalu jarang untuk durasi uji).")
        if fps:
            lines.append(f"  fps analisis: median {statistics.median(fps):.1f}")
        if drifts:
            lines.append(f"  sisa bias jam (P18): awal {drifts[0]:+.2f} dtk -> akhir {drifts[-1]:+.2f} dtk")
        if identified:
            people = sorted(set(identified))
            lines.append(f"  track.identified: {len(identified)} kali ({', '.join(people[:5])})")
        for note in events:
            lines.append(f"  event: {note}")

        if last is not None and last < FUTURE_AGE:
            lines.append("  KESIMPULAN: DATA TIDAK VALID. Umur kotak negatif: `at` berada di masa depan. "
                         "Sumber diputar lebih cepat dari real-time (file tanpa pacing, mock) atau jam "
                         "probe dan engine berbeda. Uji lewat MediaMTX (RTSP) dan jalankan probe di mesin engine.")
            continue
        growing = (slope is not None and slope > GROWING_SLOPE) or (
            first is not None and last is not None and last - first > GROWING_DELTA)
        if growing:
            lines.append("  KESIMPULAN: delay BERTAMBAH -> engine lebih lambat dari kamera (P17). "
                         "Cek live_buffer: latest aktif, turunkan target_fps / pakai D-FINE s, "
                         "matikan rekognisi untuk membandingkan (P7).")
        elif last is not None and last <= FRESH_AGE:
            lines.append("  KESIMPULAN: engine SEGAR dan stabil. Kalau dashboard tetap terlihat telat, "
                         "penyebabnya di jalur backend->frontend atau sinkronisasi video "
                         "(P10 tebakan 0,8 dtk WebRTC, P16 kotak basi, P18 offset awal).")
        else:
            lines.append("  KESIMPULAN: delay TETAP tapi besar. Kemungkinan bias offset awal (P18) "
                         "atau jam probe dan engine beda mesin. Jalankan probe di mesin engine; "
                         "kalau tetap, offset frame pertama perlu dikoreksi (Engine B).")
    return lines


def run(host: str, port: int, cameras: List[Tuple[str, str]], seconds: float,
        out_path: Path, key: Optional[str]) -> List[str]:
    sock, reader, hello_ack = connect(host, port, key)
    _send(sock, {"type": "set_cameras", "v": 1, "ts": _now_iso(),
                 "cameras": [{"camera_id": c, "uri": u, "enabled": True} for c, u in cameras]})

    started = time.time()
    replayed = 0
    rows: List[Dict[str, Any]] = []
    last_view: Dict[str, float] = {}
    fields = ["wall_t", "elapsed_s", "camera_id", "source", "frame_age_s", "lag_s", "fps", "dropped",
              "drift_s", "note"]

    def row(camera_id: str, source: str, **values: Any) -> None:
        now = time.time()
        entry = {"wall_t": round(now, 3), "elapsed_s": round(now - started, 3), "camera_id": camera_id,
                 "source": source, "frame_age_s": "", "lag_s": "", "fps": "", "dropped": "", "drift_s": "",
                 "note": ""}
        entry.update(values)
        rows.append(entry)

    try:
        while time.time() - started < seconds:
            try:
                line = reader.readline()
            except (socket.timeout, TimeoutError):
                reader = sock.makefile("r", encoding="utf-8")
                continue
            if not line:
                row("", "event", note="engine menutup koneksi")
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = message.get("type")
            now = time.time()
            # Engine memutar ulang outbox mulai last_event_seq=0: event dari
            # run sebelumnya (outbox yang sama) bukan data uji ini.
            sent = _parse_at(message.get("ts"))
            if kind != "view.frame" and sent is not None and sent < started - REPLAY_SLACK:
                replayed += 1
                continue
            if kind == "view.frame":
                camera = message.get("camera_id", "")
                at = _parse_at(message.get("at"))
                if at is not None and now - last_view.get(camera, 0.0) >= 1.0:
                    last_view[camera] = now
                    row(camera, "view", frame_age_s=round(now - at, 3))
            elif kind == "engine.health":
                for camera, m in (message.get("camera_metrics") or {}).items():
                    row(camera, "health",
                        lag_s=m.get("lag_seconds", ""), fps=m.get("effective_fps", ""),
                        dropped=m.get("frames_dropped_stale", ""),
                        drift_s=m.get("clock_drift_seconds", ""),
                        note=(message.get("cameras") or {}).get(camera, ""))
            elif kind == "track.identified":
                row(message.get("camera_id", ""), "identified", note=str(message.get("person_id", "")))
            elif kind in ("camera.degraded", "camera.recovered", "camera.online", "camera.failed"):
                detail = message.get("reason") or message.get("kind") or ""
                row(message.get("camera_id", ""), "event", note=f"{kind} {detail}".strip())
    finally:
        try:
            sock.close()
        except OSError:
            pass
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    lines = summarize(rows, time.time() - started)
    if replayed:
        lines.append(f"(diabaikan {replayed} event putar ulang dari outbox, lebih tua dari awal uji)")
    return lines


NUMERIC_FIELDS = ("wall_t", "elapsed_s", "frame_age_s", "lag_s", "fps", "dropped", "drift_s")


def load_rows(path: Path) -> List[Dict[str, Any]]:
    """Baca CSV probe kembali, untuk meringkas ulang tanpa mengulang uji."""
    rows: List[Dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            entry: Dict[str, Any] = dict(raw)
            for name in NUMERIC_FIELDS:
                value = entry.get(name, "")
                if value not in ("", None):
                    try:
                        entry[name] = float(value)
                    except ValueError:
                        entry[name] = ""
                else:
                    entry[name] = ""
            rows.append(entry)
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", default="127.0.0.1:8765", help="host:port engine")
    parser.add_argument("--camera", action="append", default=[],
                        help="camera_id=uri, boleh berulang (default cam01=rtsp://127.0.0.1:8554/cam01)")
    parser.add_argument("--minutes", type=float, default=5.0)
    parser.add_argument("--seconds", type=float, default=None, help="override --minutes (untuk uji singkat)")
    parser.add_argument("--out", default=None, help="berkas CSV (default bench-out/lag-probe-<waktu>.csv)")
    parser.add_argument("--summarize", default=None, metavar="CSV",
                        help="ringkas ulang CSV hasil probe sebelumnya, tanpa menyambung ke engine")
    args = parser.parse_args(argv)

    if args.summarize:
        rows = load_rows(Path(args.summarize))
        duration = max((r["elapsed_s"] for r in rows if r["elapsed_s"] != ""), default=0.0)
        print("\n".join(summarize(rows, duration)))
        return 0

    host, _, port = args.engine.rpartition(":")
    cameras = [tuple(spec.split("=", 1)) for spec in (args.camera or ["cam01=rtsp://127.0.0.1:8554/cam01"])]
    if any(len(c) != 2 for c in cameras):
        parser.error("--camera harus berbentuk camera_id=uri")
    seconds = args.seconds if args.seconds is not None else args.minutes * 60.0
    out = Path(args.out) if args.out else ROOT / "bench-out" / f"lag-probe-{time.strftime('%Y%m%d-%H%M%S')}.csv"

    print(f"probe {seconds:.0f} dtk ke {host}:{port}, kamera: {', '.join(c for c, _ in cameras)}")
    lines = run(host or "127.0.0.1", int(port), cameras, seconds, out, os.environ.get("ENGINE_SHARED_KEY") or None)
    print("\n".join(lines))
    print(f"\ndata mentah: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
