"""Sumber frame NVDEC dengan frame tetap di GPU -- KERANGKA (dokumen 04 §14.5).

Status: belum diimplementasikan. Yang menentukan apakah file ini diisi adalah
spike 15-16 Oktober (`scripts/spike_nvdec.py`):

- **lanjut** -> EB mengisi `NvdecSource` di minggu 3 (26-30 Oktober);
- **tunda**  -> penjadwal tetap memakai jalur CPU (`PyAVSource`), NVDEC
  pasca-pilot. Stabilitas tidak bergantung pada file ini.

Kenapa bukan `ingest.hwaccel: cuda` yang sudah ada: hwaccel PyAV men-decode di
GPU tetapi mengunduh frame ke RAM untuk dikonversi ke BGR. Hemat CPU decode,
tidak hemat salinan, dan frame tidak bisa langsung masuk `fast_preprocess`
sebagai tensor GPU. Di sini sasarannya frame tidak pernah turun ke CPU:

    demux RTSP (CPU) -> NVDEC -> permukaan NV12 di GPU -> tensor torch (DLPack)
        -> resize/normalisasi (fast_preprocess) -> D-FINE
        -> crop wajah/badan dari frame resolusi penuh, masih di GPU

Kontrak yang harus dipenuhi implementasinya nanti, supaya penjadwal dan pipeline
tidak bercabang:

1. Turunan `BaseFrameSource`; `read()` mengembalikan frame terbaru (pola mailbox,
   lihat `ingest/mailbox.py`), dengan PTS asli, `stream_epoch` yang naik saat
   reconnect, dan offset jam per epoch -- sama persis dengan `PyAVSource`.
2. Data piksel di GPU dibawa lewat perubahan `ports/frame.py` yang disepakati
   EA-EB (kontrak 13 Oktober). Sampai itu ada, jangan menyelundupkan tensor lewat
   `metadata.extra`.
3. Decoder putus -> sumber ini yang reconnect; penjadwal hanya melihat "tidak
   ada frame baru" dan melewati kamera ini.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .base import BaseFrameSource

SPIKE_HINT = (
    "NvdecSource belum diimplementasikan. Jalankan dulu `python scripts/spike_nvdec.py "
    "--url <rtsp>` di mesin engine (dokumen 04 §14.5), lalu tulis vonisnya."
)


def nvdec_available() -> Tuple[bool, str]:
    """(tersedia, alasan). Hanya memeriksa impor; tidak membuka GPU."""
    try:
        import PyNvVideoCodec  # noqa: F401  -- pustaka NVIDIA, dipasang terpisah
    except ImportError as error:
        return False, f"PyNvVideoCodec tidak terpasang ({error})"
    except Exception as error:  # noqa: BLE001 -- DLL CUDA hilang di Windows, dll.
        return False, f"PyNvVideoCodec gagal dimuat: {error!r}"
    return True, "PyNvVideoCodec dapat diimpor"


class NvdecSource(BaseFrameSource):
    """Belum diimplementasikan; lihat docstring modul."""

    def __init__(self, uri: str, source_id: str = "default", gpu_id: int = 0) -> None:
        super().__init__(source_id=source_id)
        self._uri = uri
        self._gpu_id = gpu_id

    def start(self) -> None:
        raise NotImplementedError(SPIKE_HINT)

    def read(self):  # pragma: no cover - start() sudah menolak
        raise NotImplementedError(SPIKE_HINT)

    def stop(self) -> None:
        self._is_running = False

    @property
    def fps(self) -> float:
        return 0.0

    @property
    def resolution(self) -> Tuple[int, int]:
        return (0, 0)

    @property
    def uri(self) -> Optional[str]:
        return self._uri
