from __future__ import annotations


def writer_stats() -> dict:
    from backend.services.engine_integration import detection_writer
    return {"dropped": detection_writer.dropped}
