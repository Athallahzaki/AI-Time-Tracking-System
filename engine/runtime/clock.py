"""Koreksi bertahap offset jam per kamera (P18, 04 §7).

`at = offset + pts`, dan offset ditetapkan sekali saat stream dibuka. MediaMTX
mengirim mulai dari keyframe terakhir, yang direkam SEBELUM stream dibuka, jadi
`at` bisa mendahului kenyataan sebesar umur keyframe itu (GOP CCTV 1-4 dtk).
`StreamTimeline.offset_bias` mengukur biasnya; modul ini memutuskan berapa yang
dikoreksi per frame.

Koreksi dibatasi lajunya (`max_rate` detik per detik jam dinding). Karena itu
`at` tetap naik monoton selama koreksi berjalan (turunannya >= 1 - max_rate),
sehingga event satu track tidak pernah mundur waktunya. Melompat sekaligus akan
lebih sederhana tetapi bisa membuat `end_at` mendahului `start_at`.

Hanya dipakai dengan thread pembaca (`live_buffer: latest`). Tanpa itu waktu
tiba diukur saat pipeline sempat membaca, dan antrean nyata akan terbaca sebagai
bias lalu "dikoreksi": delay sungguhan jadi tersembunyi.

**Arah bias tidak simetris (uji RTX 4060, 3 Okt).** Offset diambil dari waktu
tiba frame pertama, dan frame tidak mungkin tiba sebelum direkam, jadi offset
yang salah hanya bisa membuat `at` MENDAHULUI kenyataan (bias negatif). Bias
POSITIF berarti semua frame di jendela tiba terlambat: thread pembaca atau
jaringan sedang tertinggal. Itu delay sungguhan, bukan kesalahan jam. Di uji
4060 bias naik ke +0,51 saat thread pembaca tertinggal (fps 2,9), korektor
"membereskannya" dalam ±5 dtk, lalu saat antrean terkuras biasnya muncul
kembali sebagai -0,47 dan harus dikoreksi balik: dua kali salah, dan selama itu
`at` event 0,5 dtk terlalu awal.

Satu-satunya penyebab bias positif yang sah adalah kristal kamera yang lebih
lambat dari jam PC, dan itu orde puluhan ppm (0,1 dtk per jam). Karena itu bias
positif tetap dikoreksi, tetapi dengan laju `max_rate_late` (default 0,002
dtk/dtk = 2000 ppm, jauh di atas drift kristal mana pun): drift jam tetap
terkejar, sedangkan antrean beberapa detik hampir tidak tergeser dan tetap
terlihat sebagai umur frame.
"""

from __future__ import annotations

from typing import Optional

START_SECONDS = 0.5    # 04 §7: koreksi bila bias melewati 0,5 dtk
STOP_SECONDS = 0.05
MAX_RATE = 0.1         # detik koreksi per detik jam dinding (bias negatif: `at` mendahului)
MAX_RATE_LATE = 0.002  # bias positif: hanya drift kristal kamera yang boleh dikejar


class OffsetCorrector:
    def __init__(self, start: float = START_SECONDS, stop: float = STOP_SECONDS,
                 max_rate: float = MAX_RATE, max_rate_late: float = MAX_RATE_LATE) -> None:
        if not 0 <= stop < start:
            raise ValueError("stop wajib lebih kecil dari start (histeresis)")
        if not 0 < max_rate < 1:
            raise ValueError("max_rate wajib di antara 0 dan 1 supaya `at` tetap monoton")
        if not 0 <= max_rate_late <= max_rate:
            raise ValueError("max_rate_late wajib di antara 0 dan max_rate: bias positif = delay, bukan jam")
        self._start = start
        self._stop = stop
        self._rate = max_rate
        self._rate_late = max_rate_late
        self._last: Optional[float] = None
        self.active = False
        self.corrected_total = 0.0

    def reset(self) -> None:
        """Epoch baru: offset baru, bias lama tidak berlaku lagi."""
        self._last = None
        self.active = False
        self.corrected_total = 0.0

    def observe(self, now: float, bias: Optional[float]) -> float:
        """Kembalikan geseran offset untuk frame ini (0 bila tidak ada)."""
        last, self._last = self._last, now
        if bias is None or last is None:
            return 0.0
        if not self.active:
            if abs(bias) < self._start:
                return 0.0
            self.active = True
        if abs(bias) <= self._stop:
            self.active = False
            return 0.0
        elapsed = max(0.0, now - last)
        if bias < 0:
            delta = max(-self._rate * elapsed, bias)
        else:
            delta = min(self._rate_late * elapsed, bias)
        self.corrected_total += delta
        return delta
