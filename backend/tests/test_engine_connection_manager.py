from backend.services.engine_connection_manager import EngineConnectionManager


class FakeClient:
    def __init__(self):
        self.connected = True
        self.messages = []

    def send(self, message):
        self.messages.append(message)

    def close(self):
        self.connected = False


def test_sync_sends_cameras_before_roster(monkeypatch, tmp_path):
    from backend.core import database

    # sync_tuning membaca/menulis app_settings: jangan sentuh backend/data/backend.db pengembang.
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    client = FakeClient()
    manager = EngineConnectionManager(client)
    monkeypatch.setattr(
        "backend.services.engine_connection_manager.get_enrollments",
        lambda: [{"person_id": "4471", "enrollment_version": 3}],
    )
    manager.sync_desired_state()
    # Overhaul 3 Nov: kalibrasi engine (set_tuning) ikut dikirim ulang setiap tersambung.
    assert [message["type"] for message in client.messages] == ["set_cameras", "set_roster", "set_tuning"]
    assert client.messages[1]["persons"] == [
        {"person_id": "4471", "enrollment_version": 3}
    ]
