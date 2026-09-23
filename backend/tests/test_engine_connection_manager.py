from backend.services.engine_connection_manager import EngineConnectionManager


class FakeClient:
    def __init__(self):
        self.connected = True
        self.messages = []

    def send(self, message):
        self.messages.append(message)

    def close(self):
        self.connected = False


def test_sync_sends_cameras_before_roster(monkeypatch):
    client = FakeClient()
    manager = EngineConnectionManager(client)
    monkeypatch.setattr(
        "backend.services.engine_connection_manager.get_enrollments",
        lambda: [{"person_id": "4471", "enrollment_version": 3}],
    )
    manager.sync_desired_state()
    assert [message["type"] for message in client.messages] == ["set_cameras", "set_roster"]
    assert client.messages[1]["persons"] == [
        {"person_id": "4471", "enrollment_version": 3}
    ]
