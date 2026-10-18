"""Gerbang detector untuk kamera yang sedang kosong (`core.idle_fps`, paket eb-r11).

Masalah: lima ruangan jarang ramai bersamaan, tetapi setiap kamera dianalisis
pada `target_fps` penuh walau tidak ada siapa pun. Di GTX 1060 (D-FINE S ±48 ms
per gambar) lima kamera x 8 fps sudah melebihi satu detik GPU per detik.

Aturan, semuanya dalam detik timeline frame (PTS), bukan jam dinding, supaya
sama untuk file, RTSP, dan tes:

- kamera dianggap AKTIF selama ada track atau deteksi dalam `idle_after_seconds`
  terakhir; detector jalan di setiap langkah seperti biasa;
- sesudah itu kamera IDLE: detector hanya dijalankan sekali per `1 / idle_fps`
  detik; langkah lain tetap membaca frame (stream tetap hidup, overlay tetap
  terkirim) tetapi tracker menerima nol deteksi;
- satu deteksi atau track saja langsung membuat kamera AKTIF lagi.

Konsekuensi yang disengaja: orang yang masuk ke ruangan kosong baru terlihat
paling lambat `1 / idle_fps` detik kemudian (lalu tracker butuh beberapa frame
penuh untuk mengonfirmasi). Untuk jatah free time dalam hitungan menit itu
dapat diterima; `at` track.started bergeser sebesar itu.

Timeline mundur (epoch baru, file diputar ulang) dianggap aktivitas: gerbang
mulai lagi dari AKTIF.
"""

from __future__ import annotations

from typing import Optional


class IdleDetectionGate:
    def __init__(self, idle_fps: float, idle_after_seconds: float) -> None:
        if idle_fps <= 0:
            raise ValueError("idle_fps harus > 0")
        if idle_after_seconds < 0:
            raise ValueError("idle_after_seconds harus >= 0")
        self._interval = 1.0 / float(idle_fps)
        self._idle_after = float(idle_after_seconds)
        self._last_active: Optional[float] = None
        self._last_detect: Optional[float] = None
        self.idle = False
        self.skipped = 0
        self.idle_entries = 0

    def reset(self) -> None:
        self._last_active = None
        self._last_detect = None
        self.idle = False

    def should_detect(self, pts: float) -> bool:
        """Dipanggil sebelum detector, sekali per langkah. False = lewati detector."""
        if self._last_active is None or pts < self._last_active:
            self._last_active = pts
            self._last_detect = None
        idle = pts - self._last_active >= self._idle_after
        if idle and not self.idle:
            self.idle_entries += 1
        self.idle = idle
        if not idle:
            self._last_detect = pts
            return True
        if self._last_detect is None or pts < self._last_detect or pts - self._last_detect >= self._interval:
            self._last_detect = pts
            return True
        self.skipped += 1
        return False

    def observe(self, pts: float, active: bool) -> None:
        """Dipanggil sesudah langkah: active = ada track atau deteksi di frame ini."""
        if active:
            if self._last_active is None or pts > self._last_active:
                self._last_active = pts
            self.idle = False
