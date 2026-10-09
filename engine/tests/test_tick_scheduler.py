"""Penjadwal berdetak (paket r9, dokumen 04 §14).

Yang diuji adalah aturannya, bukan kecepatan mesin:
- detak yang molor tidak dikejar, dan yang terlewat dihitung;
- tahap 1 (TickGate): semua kamera dilepas bersamaan, kamera sibuk tidak
  menjalankan dua langkah untuk satu detak, berhenti tetap responsif;
- tahap 2 (TickScheduler): satu batch per detak, kamera tanpa frame dilewati,
  kesalahan satu kamera tidak menjatuhkan yang lain;
- mailbox hanya menyimpan frame terbaru;
- detector bersama dengan wait_for_all berhenti menunggu begitu semua kamera masuk;
- default tetap perilaku lama (scheduler "free").
"""

from __future__ import annotations

import dataclasses
import threading
import time
from types import SimpleNamespace
from typing import Any, List, Optional

import numpy as np
import pytest

from engine.config import load_config
from engine.ingest.mailbox import FrameMailbox
from engine.ingest.nvdec_source import NvdecSource, nvdec_available
from engine.perception.shared_detector import SharedDetector
from engine.ports.frame import Frame, FrameMetadata
from engine.runtime.tick_scheduler import TickClock, TickGate, TickScheduler, tick_fps_for


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


# -- TickClock -----------------------------------------------------------------


def test_detak_tepat_waktu_tidak_dihitung_telat():
    clock = FakeClock()
    tick = TickClock(5.0, clock=clock)          # periode 0,2 dtk
    assert tick.seconds_until_next() == 0.0
    tick.fire()
    for _ in range(4):
        clock.now += tick.seconds_until_next()
        tick.fire()
    assert tick.stats.ticks == 5
    assert tick.stats.late_ticks == 0 and tick.stats.skipped_ticks == 0


def test_detak_yang_molor_tidak_dikejar_dan_tetap_sefase():
    clock = FakeClock()
    tick = TickClock(5.0, clock=clock)
    tick.fire()                                  # detak di 100.0, berikutnya 100.2
    clock.now = 100.75                           # satu langkah makan 0,75 dtk
    lateness = tick.fire()
    assert lateness == pytest.approx(0.55)
    assert tick.stats.late_ticks == 1
    assert tick.stats.skipped_ticks == 2         # 100.4 dan 100.6 tidak dijalankan
    # Detak berikutnya di kelipatan periode, bukan "sekarang + periode".
    assert tick.next_deadline == pytest.approx(100.8)


def test_jitter_kecil_tidak_dihitung_telat():
    clock = FakeClock()
    tick = TickClock(10.0, clock=clock)
    tick.fire()
    clock.now += 0.1 + 0.005                     # telat 5 ms dari periode 100 ms
    tick.fire()
    assert tick.stats.late_ticks == 0


def test_fps_detak_harus_positif():
    with pytest.raises(ValueError):
        TickClock(0)


def test_tick_fps_for_mengikuti_tick_fps_lalu_target_fps():
    assert tick_fps_for("free", 6.0, 10.0) is None
    assert tick_fps_for("tick", 6.0, 10.0) == 6.0
    assert tick_fps_for("tick", None, 10.0) == 10.0
    with pytest.raises(ValueError):
        tick_fps_for("tick", None, None)


# -- TickGate (tahap 1) ----------------------------------------------------------


def test_gerbang_melepas_semua_kamera_pada_detak_yang_sama():
    gate = TickGate(20.0)
    cams = [f"cam{i}" for i in range(5)]
    for cam in cams:
        gate.register(cam)
    released: dict = {cam: [] for cam in cams}
    stop = threading.Event()

    def run(cam):
        for _ in range(3):
            if not gate.wait(cam, stop):
                return
            released[cam].append(gate._tick)    # noqa: SLF001 -- nomor detak saat dilepas

    threads = [threading.Thread(target=run, args=(cam,)) for cam in cams]
    for thread in threads:
        thread.start()
    gate.start()
    try:
        for thread in threads:
            thread.join(timeout=3)
    finally:
        gate.stop()
    first = released[cams[0]]
    assert len(first) == 3
    assert all(released[cam] == first for cam in cams), released


def test_kamera_sibuk_tidak_menjalankan_dua_langkah_untuk_satu_detak():
    gate = TickGate(50.0)                        # periode 20 ms
    gate.register("lambat")
    stop = threading.Event()
    steps: List[int] = []

    def run():
        while len(steps) < 4:
            if not gate.wait("lambat", stop):
                return
            steps.append(gate._tick)            # noqa: SLF001
            time.sleep(0.07)                     # langkah 70 ms = 3+ detak

    thread = threading.Thread(target=run)
    gate.start()
    thread.start()
    thread.join(timeout=5)
    gate.stop()
    assert len(steps) == 4
    assert len(set(steps)) == 4, "satu detak tidak boleh dipakai dua kali"
    snap = gate.snapshot()
    assert snap["cameras"]["lambat"]["missed_ticks"] >= 3, snap


def test_berhenti_membangunkan_kamera_yang_menunggu():
    gate = TickGate(0.5)                         # detak tiap 2 dtk
    gate.register("cam")
    gate.start()
    stop = threading.Event()
    gate.wait("cam", stop)                       # detak pertama langsung
    result: dict = {}

    def run():
        started = time.monotonic()
        result["ok"] = gate.wait("cam", stop)
        result["dt"] = time.monotonic() - started

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=2)
    gate.stop()
    assert result["ok"] is False
    assert result["dt"] < 0.6


# -- TickScheduler (tahap 2, kerangka) ---------------------------------------------


class FakeUnit:
    def __init__(self, camera_id: str, frames: Optional[List[Any]] = None, explode: str = "") -> None:
        self.camera_id = camera_id
        self.frames = list(frames or [])
        self.explode = explode
        self.finished: List[Any] = []
        self.errors: List[BaseException] = []

    def prepare(self):
        if self.explode == "prepare":
            raise RuntimeError("decoder rusak")
        return self.frames.pop(0) if self.frames else None

    def finish(self, result):
        if self.explode == "finish":
            raise RuntimeError("tracker rusak")
        self.finished.append(result)

    def fail(self, error):
        self.errors.append(error)


def test_satu_detak_satu_batch_dan_kamera_tanpa_frame_dilewati():
    a, b, c = FakeUnit("a", ["a1"]), FakeUnit("b", []), FakeUnit("c", ["c1"])
    batches: List[List[Any]] = []

    def infer(inputs):
        batches.append(list(inputs))
        return [f"det:{x}" for x in inputs]

    scheduler = TickScheduler(6.0, units=lambda: [a, b, c], infer_batch=infer)
    assert scheduler.run_tick() == 2
    assert batches == [["a1", "c1"]]
    assert a.finished == ["det:a1"] and c.finished == ["det:c1"] and b.finished == []
    assert scheduler.run_tick() == 0             # tidak ada frame baru sama sekali
    assert scheduler.stats.empty_ticks == 1 and len(batches) == 1


def test_kesalahan_satu_kamera_tidak_menjatuhkan_yang_lain():
    ok = FakeUnit("ok", ["f1"])
    broken_prepare = FakeUnit("p", ["x"], explode="prepare")
    broken_finish = FakeUnit("f", ["y"], explode="finish")
    scheduler = TickScheduler(
        6.0, units=lambda: [broken_prepare, ok, broken_finish],
        infer_batch=lambda inputs: [f"det:{x}" for x in inputs],
    )
    assert scheduler.run_tick() == 2             # ok + broken_finish masuk batch
    assert ok.finished == ["det:f1"]
    assert len(broken_prepare.errors) == 1 and len(broken_finish.errors) == 1
    assert scheduler.stats.unit_failures == 2 and scheduler.stats.frames == 1


def test_batch_gagal_dilaporkan_ke_semua_kamera_di_batch_itu():
    a, b = FakeUnit("a", ["a1"]), FakeUnit("b", ["b1"])

    def infer(inputs):
        raise RuntimeError("CUDA OOM")

    scheduler = TickScheduler(6.0, units=lambda: [a, b], infer_batch=infer)
    assert scheduler.run_tick() == 0
    assert len(a.errors) == 1 and len(b.errors) == 1
    assert scheduler.stats.batch_failures == 1


def test_hasil_batch_yang_jumlahnya_salah_ditolak():
    a, b = FakeUnit("a", ["a1"]), FakeUnit("b", ["b1"])
    scheduler = TickScheduler(6.0, units=lambda: [a, b], infer_batch=lambda inputs: ["satu"])
    scheduler.run_tick()
    assert a.finished == [] and b.finished == []
    assert scheduler.stats.batch_failures == 1


def test_loop_memberi_sisa_waktu_ke_pekerjaan_identitas_sebelum_tenggat():
    a = FakeUnit("a", [f"a{i}" for i in range(100)])
    deadlines: List[float] = []
    stop = threading.Event()

    def idle(deadline):
        deadlines.append(deadline)
        assert time.monotonic() < deadline
        if len(deadlines) >= 3:
            stop.set()

    scheduler = TickScheduler(20.0, units=lambda: [a], infer_batch=lambda x: x, idle=idle)
    thread = threading.Thread(target=scheduler.run, args=(stop,))
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert len(deadlines) >= 3
    gaps = [b - a_ for a_, b in zip(deadlines, deadlines[1:])]
    assert all(g == pytest.approx(0.05, abs=1e-6) for g in gaps)


# -- mailbox ------------------------------------------------------------------------


def test_mailbox_hanya_menyimpan_frame_terbaru():
    box: FrameMailbox[str] = FrameMailbox()
    assert box.take() is None
    box.put("f1")
    box.put("f2")
    box.put("f3")
    assert box.take() == "f3"
    assert box.take() is None, "frame yang sama tidak diberikan dua kali"
    assert box.stats.overwritten == 2 and box.stats.taken == 1


def test_mailbox_wait_take_bangun_saat_ditutup():
    box: FrameMailbox[str] = FrameMailbox()
    threading.Timer(0.05, box.close).start()
    started = time.monotonic()
    assert box.wait_take(2.0) is None
    assert time.monotonic() - started < 1.0
    box.put("setelah tutup")
    assert box.take() is None


# -- detector bersama: wait_for_all ----------------------------------------------------


class FakeInner:
    class_names = {0: "person"}
    device = "cpu"

    def __init__(self):
        self.calls: List[int] = []

    def warmup(self):
        pass

    def predict_images(self, images, confidence=None):
        self.calls.append(len(images))
        return [SimpleNamespace(tag=int(image[0, 0, 0])) for image in images]

    def note_result(self, result):
        pass

    def postprocess(self, frame, result):
        return [result.tag]


def _frame(tag):
    return Frame(image=np.full((4, 4, 3), tag, dtype=np.uint8), metadata=FrameMetadata(frame_id=tag))


def test_wait_for_all_berhenti_menunggu_begitu_semua_kamera_masuk():
    inner = FakeInner()
    # batch_wait 2 dtk: kalau dispatcher tidak berhenti saat semua masuk, tes ini lambat.
    shared = SharedDetector(inner, max_batch=8, batch_wait_ms=100.0, wait_for_all=True).start()
    handles = [shared.handle(f"cam{i}") for i in range(3)]
    barrier = threading.Barrier(3)
    out = {}

    def run(i, handle):
        barrier.wait()
        out[i] = handle.detect(_frame(i + 1))

    started = time.monotonic()
    threads = [threading.Thread(target=run, args=(i, h)) for i, h in enumerate(handles)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    elapsed = time.monotonic() - started
    shared.stop()
    assert out == {0: [1], 1: [2], 2: [3]}
    assert inner.calls == [3], inner.calls
    assert elapsed < 0.09, "harus berhenti sebelum batch_wait habis"


def test_wait_for_all_tetap_dibatasi_batch_wait_bila_satu_kamera_diam():
    inner = FakeInner()
    shared = SharedDetector(inner, max_batch=8, batch_wait_ms=40.0, wait_for_all=True).start()
    live, _silent = shared.handle("hidup"), shared.handle("putus")
    started = time.monotonic()
    assert live.detect(_frame(9)) == [9]
    elapsed = time.monotonic() - started
    shared.stop()
    assert 0.03 <= elapsed < 0.5


# -- config dan default --------------------------------------------------------------


def test_default_tetap_perilaku_lama():
    config = load_config()
    assert config.scheduler == "free" and config.tick_fps is None


def test_scheduler_tick_tanpa_fps_ditolak():
    with pytest.raises(ValueError):
        dataclasses.replace(load_config(), scheduler="tick", tick_fps=None, target_fps=None)
    with pytest.raises(ValueError):
        dataclasses.replace(load_config(), scheduler="lari")


def test_profil_uji_4060_tick_termuat():
    config = load_config("engine/config/demo-4060-tick.yaml")
    assert config.scheduler == "tick" and config.tick_fps == 6.0 and config.target_fps == 6.0
    assert config.detector.share_across_cameras is True


def test_runtime_tick_memakai_gerbang_dan_menyamakan_target_fps():
    from engine.runtime import EngineRuntime, RuntimeOptions
    from engine.runtime.camera import CameraSpec

    config = dataclasses.replace(
        load_config(), source_type="mock", auto_warmup=False, scheduler="tick", tick_fps=20.0, target_fps=12.0,
    )
    runtime = EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0), max_frames=10))
    try:
        assert runtime.config.target_fps == 20.0
        runtime._reconcile({"r1": CameraSpec("r1", "mock"), "r2": CameraSpec("r2", "mock")})
        deadline = time.time() + 10
        while time.time() < deadline and any(c.alive for c in runtime.cameras.values()):
            time.sleep(0.02)
        # Sumber mock memberi 10 frame; sebagian di-decimate ke 20 fps (bukan urusan detak).
        frames = [c.stats.frames for c in runtime.cameras.values()]
        assert all(f >= 5 for f in frames), frames
        snap = runtime._tick_gate.snapshot()   # noqa: SLF001
        assert snap["ticks"] >= max(frames)
        assert snap["cameras"] == {}, "kamera yang selesai harus keluar dari gerbang"
    finally:
        runtime.close()


def test_nvdec_belum_diimplementasikan_dan_bilang_kenapa():
    available, reason = nvdec_available()
    assert isinstance(available, bool) and reason
    with pytest.raises(NotImplementedError, match="spike_nvdec"):
        NvdecSource("rtsp://127.0.0.1:8554/cam01").start()
