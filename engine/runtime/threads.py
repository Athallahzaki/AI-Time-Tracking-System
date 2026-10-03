"""Batas thread CPU untuk pustaka numerik (`core.cpu_threads`).

Uji 2 Okt: `live_buffer: latest` mentok ±4 fps, `none` 6,5-8 fps, dan FP16 tidak
mengubah apa pun. GPU menganggur; yang penuh adalah CPU. Di engine tidak ada
satu pun batas thread, jadi setiap pustaka membuka pool selebar jumlah core:

- PyTorch (OpenMP/MKL) untuk pra/pasca-proses detector,
- OpenCV untuk resize (`pre_resize`) dan konversi,
- decoder FFmpeg (`decoder_threads: 0`).

Dengan `none`, decode dan inferensi bergantian di satu thread sehingga pool-pool
itu tidak pernah bertemu. Dengan `latest`, thread pembaca men-decode BERSAMAAN
dengan torch dan OpenCV: tiga pool selebar core berebut core yang sama, dan
OpenMP menunggu sambil berputar (spin) saat rebutan. Itu dugaan, bukan fakta;
knob ini ada supaya dugaan itu bisa diuji dengan satu baris config.

`0` = tidak menyentuh apa pun (perilaku lama). Nilai > 0 diterapkan sekali,
seawal mungkin. Variabel lingkungan hanya berpengaruh pada pustaka yang belum
dimuat, karena itu pustaka yang sudah dimuat juga diatur lewat API-nya.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, MutableMapping, Optional

logger = logging.getLogger("engine.runtime.threads")

ENV_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def _module(name: str, given: Any) -> Any:
    if given is not None:
        return given
    if name in sys.modules:
        return sys.modules[name]
    try:
        return __import__(name)
    except Exception:  # noqa: BLE001 -- pustaka opsional; tidak ada = tidak diatur
        return None


def apply_cpu_threads(
    count: int,
    *,
    torch_module: Any = None,
    cv2_module: Any = None,
    environ: Optional[MutableMapping[str, str]] = None,
) -> Dict[str, Any]:
    """Terapkan batas dan kembalikan apa yang benar-benar berhasil diatur."""
    report: Dict[str, Any] = {"requested": int(count), "env": {}, "torch": None, "cv2": None}
    if count <= 0:
        return report
    env = os.environ if environ is None else environ
    for name in ENV_VARS:
        env[name] = str(count)
        report["env"][name] = str(count)

    torch = _module("torch", torch_module)
    if torch is not None and hasattr(torch, "set_num_threads"):
        try:
            torch.set_num_threads(int(count))
            report["torch"] = int(torch.get_num_threads()) if hasattr(torch, "get_num_threads") else int(count)
        except Exception as exc:  # noqa: BLE001
            report["torch"] = f"gagal: {exc}"
        if hasattr(torch, "set_num_interop_threads"):
            try:
                # Hanya bisa sebelum kerja paralel pertama; sesudahnya RuntimeError.
                torch.set_num_interop_threads(int(count))
                report["torch_interop"] = int(count)
            except Exception as exc:  # noqa: BLE001
                report["torch_interop"] = f"tidak diubah: {exc}"

    cv2 = _module("cv2", cv2_module)
    if cv2 is not None and hasattr(cv2, "setNumThreads"):
        try:
            cv2.setNumThreads(int(count))
            report["cv2"] = int(cv2.getNumThreads()) if hasattr(cv2, "getNumThreads") else int(count)
        except Exception as exc:  # noqa: BLE001
            report["cv2"] = f"gagal: {exc}"

    logger.info("batas thread CPU: %s", report)
    return report
