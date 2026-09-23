from backend.services.view_stream import ViewStreamService


def frame(pts: float, boxes=None, epoch: int = 0):
    return {
        "type": "view.frame",
        "camera_id": "r1",
        "stream_epoch": epoch,
        "pts": pts,
        "boxes": boxes or [],
    }


def test_direct_subscriber_replays_pts_history():
    service = ViewStreamService(history_camera_ids={"r1"})
    service.publish(frame(0.0))
    service.publish(frame(0.1, [{"track_uuid": "t1"}]))

    subscriber = service.subscribe("r1", replay_history=True)

    assert subscriber.get_nowait()["pts"] == 0.0
    assert subscriber.get_nowait()["pts"] == 0.1


def test_live_subscriber_does_not_replay_history():
    service = ViewStreamService(history_camera_ids={"r1"})
    service.publish(frame(10.0))

    subscriber = service.subscribe("r1", replay_history=False)

    assert subscriber.empty()


def test_new_epoch_replaces_old_direct_history():
    service = ViewStreamService(history_camera_ids={"r1"})
    service.publish(frame(10.0, epoch=0))
    service.publish(frame(0.0, epoch=1))

    subscriber = service.subscribe("r1", replay_history=True)

    replayed = subscriber.get_nowait()
    assert replayed["stream_epoch"] == 1
    assert subscriber.empty()
