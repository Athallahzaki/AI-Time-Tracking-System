"""ReID: aturan gabung — cannot-link, waktu tempuh, ambang ketat (dokumen 12 §3.6)."""

from __future__ import annotations

import pytest

from engine.identity.reid import ReidConfig, TrackSpan, check_group, check_pair, pick_best


def _span(uuid, cam, first, last, loc=None):
    loc = loc or cam
    return TrackSpan(uuid, cam, first, last, loc, loc)


CFG = ReidConfig.from_mapping({"min_travel_seconds": {"lobby": {"biliar": 20, "smoking": 10}}})


def test_dua_track_hidup_bersamaan_di_kamera_berbeda_cannot_link():
    a = _span("tr_a", "cam1", 100, 160, "lobby")
    b = _span("tr_b", "cam5", 150, 200, "biliar")
    assert check_pair(a, b, CFG) == (False, "cannot_link")


def test_dua_track_hidup_bersamaan_di_kamera_sama_cannot_link():
    a = _span("tr_a", "cam1", 100, 160)
    b = _span("tr_b", "cam1", 120, 130)
    assert not check_pair(a, b, CFG).ok


def test_perpindahan_lebih_cepat_dari_waktu_tempuh_ditolak():
    a = _span("tr_a", "cam2", 100, 160, "lobby")
    cepat = _span("tr_b", "cam5", 170, 200, "biliar")     # 10 dtk < 20
    wajar = _span("tr_c", "cam5", 185, 200, "biliar")     # 25 dtk
    assert check_pair(a, cepat, CFG) == (False, "travel_time")
    assert check_pair(cepat, a, CFG) == (False, "travel_time")  # urutan argumen bebas
    assert check_pair(a, wajar, CFG).ok


def test_pasangan_lokasi_tak_tercantum_memakai_default_ketat():
    cfg = ReidConfig()
    assert cfg.travel_seconds("luar", "hiburan") == cfg.default_min_travel_seconds >= 30
    a = _span("tr_a", "cam1", 0, 10, "luar")
    b = _span("tr_b", "cam4", 25, 30, "hiburan")
    assert check_pair(a, b, cfg) == (False, "travel_time")


def test_pergantian_id_di_kamera_sama_boleh_disambung():
    a = _span("tr_a", "cam1", 0, 10)
    b = _span("tr_b", "cam1", 10.2, 30)
    assert check_pair(a, b, CFG).ok


def test_kelompok_harus_cocok_dengan_setiap_anggota():
    members = [_span("tr_a", "cam2", 0, 10, "lobby"), _span("tr_b", "cam1", 200, 300, "smoking")]
    cand = _span("tr_c", "cam5", 250, 260, "biliar")   # cocok dengan a, bertabrakan dengan b
    assert check_group(members, cand, CFG) == (False, "cannot_link")


def test_ambang_dan_margin_ketat():
    cfg = ReidConfig(match_threshold=0.8, match_margin=0.05)
    assert pick_best([("p1", 0.9), ("p2", 0.5)], cfg) == "p1"
    assert pick_best([("p1", 0.79)], cfg) is None            # di bawah ambang
    assert pick_best([("p1", 0.90), ("p2", 0.87)], cfg) is None  # margin sempit: tidak tahu
    assert pick_best([], cfg) is None


@pytest.mark.parametrize("raw", [
    {"min_travel_seconds": {"lobby": {"lobby": 5}}},
    {"min_travel_seconds": {"lobby": {"biliar": 5}, "biliar": {"lobby": 9}}},
    {"min_travel_seconds": {"lobby": 5}},
    {"min_travel_seconds": {"lobby": {"biliar": -1}}},
    {"ambang": 0.5},
    {"match_margin": -0.1},
])
def test_config_tidak_valid_ditolak(raw):
    with pytest.raises(ValueError):
        ReidConfig.from_mapping(raw)


def test_config_waktu_tempuh_simetris():
    assert CFG.travel_seconds("biliar", "lobby") == 20
    assert CFG.travel_seconds("lobby", "lobby") == 0
