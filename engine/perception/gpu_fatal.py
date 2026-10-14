"""Mengenali error GPU yang tidak bisa dipulihkan di dalam proses yang sama.

Setelah error CUDA "sticky" (mis. `illegal memory access`), konteks CUDA proses
itu rusak: setiap panggilan berikutnya gagal, termasuk fallback per gambar dan
detector yang dibuka ulang oleh kamera yang reconnect (uji 4060, 12 Okt, paket
eb-r1). Satu-satunya pemulihan adalah proses baru. Modul ini hanya memutuskan
"fatal atau bukan"; yang memutuskan apa yang dilakukan adalah runtime
(`core.gpu_fatal_action`).

Sengaja konservatif:
- CUDA out of memory BUKAN fatal (bisa pulih bila beban turun) dan tidak pernah
  dicocokkan sebagai fatal.
- Pola teks di bawah mengikuti pesan PyTorch/CUDA yang umum. Teks persis bisa
  berbeda antar versi PyTorch; cocokkan dengan traceback asli dari laptop dan
  tambahkan polanya di sini bila meleset (lihat SERAH-TERIMA, paket ea-r8).
"""

from __future__ import annotations

from typing import Iterator, Optional

# Huruf kecil. Dicocokkan sebagai substring dari repr exception (dan rantainya).
FATAL_PATTERNS = (
    "illegal memory access",
    "device-side assert",
    "unspecified launch failure",
    "misaligned address",
    "illegal instruction",
    "launch timed out",            # Windows TDR: driver me-reset GPU
    "cudaerrorlaunchfailure",
    "cudaerrorillegaladdress",
    "cublas_status_execution_failed",
    "cudnn_status_execution_failed",
    "cuda error: unknown error",
)

# Tipe exception yang dipakai PyTorch baru untuk error akselerator.
FATAL_TYPE_NAMES = ("AcceleratorError",)

NOT_FATAL_PATTERNS = (
    "out of memory",
)


def _chain(error: BaseException) -> Iterator[BaseException]:
    seen = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_fatal_gpu_error(error: BaseException) -> bool:
    """True bila error ini (atau penyebabnya) berarti konteks CUDA rusak."""
    for item in _chain(error):
        text = repr(item).lower()
        if any(pattern in text for pattern in NOT_FATAL_PATTERNS):
            return False
        if type(item).__name__ in FATAL_TYPE_NAMES:
            return True
        if any(pattern in text for pattern in FATAL_PATTERNS):
            return True
    return False


def describe(error: BaseException, limit: int = 300) -> str:
    """Ringkasan satu baris untuk log dan alasan berhenti."""
    text = f"{type(error).__name__}: {error}".replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."
