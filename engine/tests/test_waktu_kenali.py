"""Waktu dari track lahir sampai dikenali (paket ea-r10).

Uji gerbang 16 Okt: konfigurasi yang lebih hemat (29 vs 54 ms per wajah) ternyata
mengenali orang dalam ±56 dtk, bukan 4-6 dtk. Angka beban saja menyesatkan, jadi
waktu sampai dikenali kini dicatat engine (log health) dan lag_probe (CSV + ringkasan).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import logging
from typing import List

import pytest

from engine.config import load_config
from engine.presence import PresenceAssembler, ZoneLabeller
from engine.presence.assembler import IDENTIFY_DELAY_SAMPLES
from engine.runtime import EngineRuntime, RuntimeOptions

DOOR = {"r1": [0.62, 0.10, 0.95, 0.55]}
DI_TENGAH = [0.40, 0.30, 0.55, 0.80]


def _assembler():
    keluaran: List[dict] = []
    assembler = PresenceAssembler(emit=keluaran.append, zones=ZoneLabeller(DOOR))
    assembler.camera_online("r1", 1758240000.0, fps=10.0)
    return assembler, keluaran


def _kenali(assembler, track, lahir, dikenali, person="4471"):
    assembler.track_started(track, "r1", pts=lahir, bbox=DI_TENGAH)
    assembler.identified(track, person, pts=dikenali, similarity=0.9, margin=0.2,
                         evidence_count=3, confidence=0.9)


def test_jeda_dari_lahir_sampai_dikenali_dicatat():
    assembler, _ = _assembler()
    _kenali(assembler, "tr_1", 10.0, 14.5)
    _kenali(assembler, "tr_2", 20.0, 76.0)
    assert list(assembler.metrics.identify_delays) == pytest.approx([4.5, 56.0])


def test_identifikasi_ulang_track_yang_sama_tidak_dihitung_dua_kali():
    assembler, _ = _assembler()
    _kenali(assembler, "tr_1", 10.0, 12.0)
    assembler.identified("tr_1", "4471", pts=40.0, similarity=0.9, margin=0.2,
                         evidence_count=4, confidence=0.9)
    assert list(assembler.metrics.identify_delays) == pytest.approx([2.0])


def test_sampel_dibatasi():
    assembler, _ = _assembler()
    for i in range(IDENTIFY_DELAY_SAMPLES + 50):
        _kenali(assembler, f"tr_{i}", float(i), float(i) + 1.0, person=f"p{i}")
    assert len(assembler.metrics.identify_delays) == IDENTIFY_DELAY_SAMPLES


class KameraPalsu:
    def __init__(self, delays):
        self._delays = delays

    def identify_delays(self):
        return list(self._delays)


def test_runtime_melaporkan_median_dan_p90(caplog):
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    runtime = EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0)))
    try:
        caplog.set_level(logging.INFO, logger="engine.runtime")
        assert runtime._report_identify_delay([]) is None
        hasil = runtime._report_identify_delay([KameraPalsu([4.0, 5.0, 6.0]), KameraPalsu([56.0])])
        assert hasil["n"] == 4 and hasil["median"] == 6.0 and hasil["max"] == 56.0
        assert any("identifikasi: 4 track" in r.getMessage() for r in caplog.records)
    finally:
        runtime.close()


def _lag_probe():
    spec = importlib.util.spec_from_file_location("lag_probe", "scripts/lag_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baris(camera, source, **nilai):
    entry = {"wall_t": 0.0, "elapsed_s": 0.0, "camera_id": camera, "source": source, "frame_age_s": "",
             "lag_s": "", "fps": "", "dropped": "", "drift_s": "", "note": "", "identify_s": ""}
    entry.update(nilai)
    return entry


def test_ringkasan_probe_menampilkan_waktu_sampai_dikenali_per_kamera():
    probe = _lag_probe()
    rows = [_baris("cam01", "view", elapsed_s=float(t), frame_age_s=0.1) for t in range(20, 80)]
    rows += [_baris("cam02", "view", elapsed_s=float(t), frame_age_s=0.1) for t in range(20, 80)]
    rows += [_baris("cam01", "identified", note="EMP123", identify_s=4.5),
             _baris("cam01", "identified", note="EMP123", identify_s=6.0)]
    teks = "\n".join(probe.summarize(rows, 80.0))
    bagian1, bagian2 = teks.split("== cam02")
    assert "track.identified: 2 kali (EMP123)" in bagian1
    assert "median 5.2 dtk" in bagian1 or "median 5.3 dtk" in bagian1
    assert "track.identified: tidak ada di kamera ini" in bagian2


def test_ringkasan_csv_lama_tanpa_kolom_identify_s_tidak_rusak():
    probe = _lag_probe()
    rows = [_baris("cam01", "view", elapsed_s=float(t), frame_age_s=0.1) for t in range(20, 80)]
    lama = _baris("cam01", "identified", note="EMP123")
    lama.pop("identify_s")
    teks = "\n".join(probe.summarize(rows + [lama], 80.0))
    assert "track.identified: 1 kali" in teks and "waktu sampai dikenali" not in teks
