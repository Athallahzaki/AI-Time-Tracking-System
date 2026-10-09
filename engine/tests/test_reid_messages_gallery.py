"""ReID: pesan antrean dan galeri harian berjangkar wajah (dokumen 12 §3.6)."""

from __future__ import annotations

import numpy as np
import pytest

from engine.identity.reid import BodyObservation, DailyGallery, PrototypeSet, TrackClosed

DIM = 32


def _unit(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def _obs(**kw):
    base = dict(camera_id="cam1", track_id=1, track_uuid="tr_cam1_1", at=1000.0)
    base.update(kw)
    return BodyObservation(**base)


def test_pesan_menormalkan_embedding_dan_lokasi_default_kamera():
    obs = _obs(embedding=np.array([3.0, 4.0]))
    assert np.isclose(np.linalg.norm(obs.embedding), 1.0)
    assert obs.embedding.dtype == np.float32
    assert obs.location == "cam1"
    assert _obs(zone="lobby").location == "lobby"


@pytest.mark.parametrize("kw", [
    dict(track_uuid="cam1_1"),
    dict(camera_id=""),
    dict(at=float("nan")),
    dict(embedding=np.zeros(4)),
    dict(embedding=np.array([np.inf, 1.0])),
    dict(face_person_id="ANON-1"),
    dict(face_person_id="a b"),
])
def test_pesan_tidak_valid_ditolak(kw):
    with pytest.raises(ValueError):
        _obs(**kw)


def test_track_closed_memvalidasi_uuid():
    TrackClosed("cam1", "tr_x", 1.0)
    with pytest.raises(ValueError):
        TrackClosed("cam1", "x", 1.0)


def test_paket_reid_tidak_mengimpor_runtime():
    from pathlib import Path
    import engine.identity.reid as reid
    for path in Path(reid.__file__).parent.glob("*.py"):
        imports = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                   if ln.startswith(("import ", "from "))]
        assert not [ln for ln in imports if "runtime" in ln], path.name


def test_galeri_hanya_menerima_track_berjangkar_wajah():
    g = DailyGallery("2026-10-09")
    assert not g.add_observation(_obs(embedding=_unit(0)))          # tanpa wajah
    assert not g.add("4471", _unit(0), source="reid")                # dari ReID
    assert g.rejected == 2 and len(g) == 0
    assert g.add_observation(_obs(embedding=_unit(0), face_person_id="4471"))
    assert g.persons() == ["4471"]


def test_galeri_multi_sudut_menyimpan_depan_dan_belakang():
    g = DailyGallery("2026-10-09")
    g.add("4471", _unit(0), source="face")      # depan
    g.add("4471", _unit(1), source="face")      # belakang (jauh dari depan)
    g.add("4471", _unit(0) * 0.999 + _unit(2) * 0.01, source="face")  # depan lagi -> dilebur
    assert g.prototype_count("4471") == 2
    best = g.scores(_unit(1))[0]
    assert best[0] == "4471" and best[1] > 0.99


def test_prototipe_penuh_menjaga_keragaman():
    p = PrototypeSet(capacity=2, merge_similarity=0.99)
    p.add(_unit(0))
    v = _unit(0) * 0.9 + _unit(1) * 0.1
    p.add(v)                       # hampir sama dengan depan, tapi di bawah 0,99
    p.add(_unit(2))                # sudut baru: menggantikan yang redundan
    assert p.score(_unit(2)) > 0.99
    assert len(p) == 2


def test_purge_harian_mengosongkan_galeri():
    g = DailyGallery("2026-10-09")
    g.add("4471", _unit(0), source="face")
    g.add("5520", _unit(1), source="face")
    assert g.purge_day("2026-10-10") == 2
    assert len(g) == 0 and g.scores(_unit(0)) == []
    assert g.day == "2026-10-10"
    with pytest.raises(ValueError):
        g.purge_day("10-10-2026")
