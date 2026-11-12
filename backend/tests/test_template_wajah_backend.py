"""be-r14: template wajah dari CCTV, sisi backend (docs/RENCANA-TEMPLATE-WAJAH.md)."""
from __future__ import annotations

import base64
import time
import struct
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import database
from backend.routers import face_templates as router_module
from backend.services import face_template_service as ft
from backend.services.auth_service import auth_service
from backend.services.break_policy import break_policy
from backend.services.engine_client import EngineClient

TS = "2026-11-12T08:00:00.000Z"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
NOW = time.time()


def _vec(*values, dim=8):
    raw = list(values) + [0.0] * (dim - len(values))
    return base64.b64encode(struct.pack(f"<{dim}f", *raw)).decode()


def _item(candidate_id, vector, person_id="budi", margin=0.3):
    return {"candidate_id": candidate_id, "person_id": person_id, "camera_id": "cam01", "captured_at": TS,
            "track_uuid": "tr_ab_1", "jpeg_b64": base64.b64encode(JPEG).decode(), "embedding_b64": vector,
            "anchor_similarity": 0.6, "runner_up_id": "andi", "runner_up_similarity": 0.6 - margin,
            "margin": margin, "face_px": 60.0, "det_score": 0.8, "yaw": 0.1}


class EngineTiruan:
    """Klien engine palsu: menjawab sinkron lewat `engine_templates.handle`, seperti engine sungguhan."""

    def __init__(self, items=(), version="v1", reject=None):
        self.connected = True
        self.items = list(items)
        self.version = version
        self.reject = reject or {}
        self.sent = []
        self.next_ref = 100

    def send(self, message):
        self.sent.append(message)
        kind, rid = message["type"], message["request_id"]
        if kind == "template.pull":
            reply = {"type": "template.candidates", "request_id": rid, "embedding_version": self.version,
                     "items": self.items[: message["max_items"]]}
            self.items = self.items[message["max_items"]:]
        elif kind == "template.apply":
            results = []
            for item in message["items"]:
                if item["candidate_id"] in self.reject:
                    results.append({"candidate_id": item["candidate_id"], "accepted": False,
                                    "reason": self.reject[item["candidate_id"]]})
                else:
                    self.next_ref += 1
                    results.append({"candidate_id": item["candidate_id"], "accepted": True,
                                    "reference_id": self.next_ref})
            reply = {"type": "template.applied", "request_id": rid, "items": results}
        else:
            reply = {"type": "template.removed", "request_id": rid, "removed": len(message["reference_ids"])}
        ft.engine_templates.handle({"v": 1, "ts": TS, "channel": "control", **reply})


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database._initialized_for = None
    database.init_database()
    ft.engine_templates.engine_supported = None
    ft.engine_templates.embedding_version = None
    yield
    database._initialized_for = None


def _by_id():
    return {item["candidate_id"]: item for item in ft.list_candidates()}


def test_tarik_lalu_timbang():
    engine = EngineTiruan([
        _item("ft_bagus", _vec(1, 0, 0.2)),
        _item("ft_tipis", _vec(1, 0, 0, 0.8), margin=0.05),
        _item("ft_kembar", _vec(1, 0, 0.21)),
    ])
    assert ft.pull_once(engine) == 3
    ft.weigh_pending(ft.validate_settings({}), "v1", now=NOW)
    items = _by_id()
    assert (items["ft_bagus"]["status"], items["ft_bagus"]["reason"]) == ("queued", None)
    assert (items["ft_tipis"]["status"], items["ft_tipis"]["reason"]) == ("review", "margin_tipis")
    assert (items["ft_kembar"]["status"], items["ft_kembar"]["reason"]) == ("rejected", "duplikat")
    assert items["ft_kembar"]["has_image"] is False, "wajah yang ditolak tidak disimpan"
    assert items["ft_bagus"]["has_image"] is True


def test_versi_berbeda_dan_pencilan_dan_batas_harian():
    settings = ft.validate_settings({"max_per_person_per_day": 4, "duplicate_similarity": 0.999})
    ft.store_candidates([_item(f"ft_s{i}", _vec(1, 0.05 * i, 0.1)) for i in range(3)], "v1", now=NOW)
    ft.weigh_pending(settings, "v1", now=NOW)
    ft.store_candidates([_item("ft_aneh", _vec(0, 0, 0, 1))], "v1", now=NOW)
    ft.store_candidates([_item("ft_lama", _vec(1, 0.3))], "v0", now=NOW)
    ft.weigh_pending(settings, "v1", now=NOW)
    items = _by_id()
    assert items["ft_aneh"]["reason"] == "pencilan"
    assert items["ft_lama"]["reason"] == "versi_berbeda"
    ft.store_candidates([_item("ft_s3", _vec(1, 0.15, 0.12)), _item("ft_s4", _vec(1, 0.2, 0.15))], "v1", now=NOW)
    ft.weigh_pending(settings, "v1", now=NOW)
    items = _by_id()
    assert items["ft_s3"]["status"] == "queued"
    assert (items["ft_s4"]["status"], items["ft_s4"]["reason"]) == ("rejected", "batas_harian")


def _siapkan(engine, **settings):
    ft.pull_once(engine)
    ft.weigh_pending(ft.validate_settings(settings), "v1", now=NOW)
    return {item["candidate_id"]: item["id"] for item in ft.list_candidates()}


def test_mode_otomatis_memasang_queued_dan_approved_bukan_review():
    engine = EngineTiruan([_item("ft_a", _vec(1, 0, 0.2)), _item("ft_b", _vec(1, 0, 0, 0.5), margin=0.05),
                           _item("ft_c", _vec(1, 0.5), person_id="cici")], reject={"ft_c": "tanpa_jangkar"})
    ids = _siapkan(engine)
    summary = ft.apply_due(engine, ft.validate_settings({"mode": "otomatis"}), now=NOW)
    items = _by_id()
    assert summary["applied"] == 1 and summary["failed"] == 1
    assert (items["ft_a"]["status"], items["ft_a"]["reference_id"]) == ("applied", 101)
    assert items["ft_b"]["status"] == "review"
    assert (items["ft_c"]["status"], items["ft_c"]["reason"]) == ("failed", "tanpa_jangkar")
    ft.approve(ids["ft_b"], "admin")
    ft.apply_due(engine, ft.validate_settings({"mode": "otomatis"}), now=NOW)
    assert _by_id()["ft_b"]["status"] == "applied"


def test_mode_persetujuan_hanya_yang_disetujui():
    engine = EngineTiruan([_item("ft_a", _vec(1, 0, 0.2)), _item("ft_b", _vec(1, 0, 0, 0.6))])
    ids = _siapkan(engine)
    ft.approve(ids["ft_b"], "admin")
    ft.apply_due(engine, ft.validate_settings({"mode": "persetujuan"}), now=NOW)
    items = _by_id()
    assert items["ft_a"]["status"] == "queued" and items["ft_b"]["status"] == "applied"


def test_buang_yang_terpasang_mencabutnya_dari_engine():
    engine = EngineTiruan([_item("ft_a", _vec(1, 0, 0.2))])
    ids = _siapkan(engine)
    ft.apply_due(engine, ft.validate_settings({}), now=NOW)
    result = ft.discard(ids["ft_a"], "admin", engine)
    assert (result["status"], result["has_image"]) == ("removed", False)
    assert engine.sent[-1] == {**engine.sent[-1], "type": "template.remove", "reference_ids": [101]}


def test_kedaluwarsa_dan_batas_per_orang_dicabut():
    engine = EngineTiruan([_item(f"ft_{i}", _vec(1, 0, 0.1 * i, 0.05)) for i in range(3)])
    _siapkan(engine, duplicate_similarity=0.9999)
    settings = ft.validate_settings({"duplicate_similarity": 0.9999})
    ft.apply_due(engine, settings, now=NOW)
    assert ft.remove_expired(engine, ft.validate_settings({"max_per_person": 2}), now=NOW + 60) == 1
    assert ft.remove_expired(engine, ft.validate_settings({"max_age_days": 1}), now=NOW + 2 * 86400) == 2
    assert {item["status"] for item in ft.list_candidates()} == {"removed"}


def test_pesan_engine_cacat_ditolak_dan_engine_lama_dikenali():
    assert ft.engine_templates.handle({"type": "template.candidates", "v": 1, "ts": TS, "request_id": "r",
                                       "embedding_version": "v1", "items": [{"candidate_id": "x"}]})
    assert ft.engine_templates.handle({"type": "ack", "v": 1, "ts": TS, "in_reply_to": "template.pull",
                                       "accepted": False, "reason": "tidak dikenal"})
    assert ft.engine_templates.engine_supported is False
    assert not ft.engine_templates.handle({"type": "engine.health"})


def test_engine_client_meneruskan_template_tanpa_validasi_produksi():
    client = EngineClient()
    seen = []
    client.set_template_handler(seen.append)
    client.handle_message({"type": "template.removed", "v": 1, "ts": TS, "request_id": "r", "removed": 1})
    client.handle_message({"type": "ack", "in_reply_to": "template.pull", "accepted": False})
    assert [message["type"] for message in seen] == ["template.removed", "ack"]


def test_pengaturan_divalidasi():
    for bad in ({"mode": "bebas"}, {"apply_time": "25:99"}, {"review_margin": 2}, {"max_per_person": 0}):
        with pytest.raises(ValueError):
            ft.validate_settings(bad)


def test_penjadwal_tarik_dan_pasang_sekali_sehari(monkeypatch):
    engine = EngineTiruan([_item("ft_a", _vec(1, 0, 0.2))])
    scheduler = ft.FaceTemplateScheduler(lambda: engine)
    scheduler.tick(now=NOW)
    assert engine.sent == [], "pengaturan belum aktif: tidak menyentuh engine"
    local = datetime.fromtimestamp(NOW, break_policy.timezone)
    ft.save_settings({"active": True, "apply_time": local.strftime("%H:%M")}, "admin")
    scheduler.tick(now=NOW)
    assert [message["type"] for message in engine.sent] == ["template.pull", "template.apply"]
    scheduler.tick(now=NOW + 120)
    assert [message["type"] for message in engine.sent][-1] == "template.pull", "penerapan sekali per hari"


# --------------------------------------------------------------------------- rute

app = FastAPI()
app.include_router(router_module.router)
http = TestClient(app)


def _token(username, role):
    employee = database.create_employee(f"E-{username}", username)["id"] if role == "viewer" else None
    auth_service.create_user(username=username, password="rahasia-uji-123", role=role,
                             employee_internal_id=employee)
    return {"Authorization": f"Bearer {auth_service.login(username, 'rahasia-uji-123')['access_token']}"}


def test_rute_admin_saja_dan_gambar_tidak_di_cache(monkeypatch):
    admin, viewer = _token("admin1", "admin"), _token("viewer1", "viewer")
    ft.store_candidates([_item("ft_a", _vec(1, 0, 0.2))], "v1", now=NOW)
    pk = ft.list_candidates()[0]["id"]
    assert http.get("/api/face-templates", headers=viewer).status_code == 403
    assert http.get(f"/api/face-templates/{pk}/image", headers=viewer).status_code == 403
    listing = http.get("/api/face-templates", headers=admin).json()
    assert listing[0]["candidate_id"] == "ft_a" and "jpeg" not in listing[0]
    image = http.get(f"/api/face-templates/{pk}/image", headers=admin)
    assert image.content == JPEG and image.headers["cache-control"] == "no-store"
    assert http.put("/api/face-templates/settings", json={"mode": "x"}, headers=admin).status_code == 422
    assert http.put("/api/face-templates/settings", json={"mode": "persetujuan"},
                    headers=admin).json()["mode"] == "persetujuan"
    assert http.post(f"/api/face-templates/{pk}/approve", headers=admin).json()["status"] == "approved"
    assert http.post(f"/api/face-templates/{pk}/discard", headers=admin).json()["status"] == "discarded"
    assert http.get(f"/api/face-templates/{pk}/image", headers=admin).status_code == 404
    audit = [row["setting"] for row in database.get_settings_audit(10)]
    assert {"face_templates", "face_template.approve", "face_template.discard"} <= set(audit)
    status = http.get("/api/face-templates/status", headers=admin).json()
    assert status["counts"] == {"discarded": 1}
