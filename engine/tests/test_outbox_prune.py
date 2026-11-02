"""Overhaul P7 (1): outbox SQLite dipangkas per gugus, bukan per append."""
from __future__ import annotations

import pytest

from engine.api.outbox import SqliteOutbox


def test_pemangkasan_per_gugus_dan_seq_tetap_naik(tmp_path):
    outbox = SqliteOutbox(tmp_path / "o.sqlite3", max_entries=10, prune_batch=5)
    for i in range(14):
        outbox.append({"type": "x", "ts": str(i)})
    assert len(outbox) == 14, "belum segugus di atas batas: tidak ada DELETE"
    outbox.append({"type": "x", "ts": "14"})
    assert len(outbox) == 10 and outbox.oldest_available_seq == 6
    assert outbox.append({"type": "x"})["seq"] == 16
    outbox.close()

    reopened = SqliteOutbox(tmp_path / "o.sqlite3", max_entries=10, prune_batch=5)
    assert reopened.next_seq == 17
    reopened.close()


def test_prune_batch_satu_sama_dengan_perilaku_lama(tmp_path):
    outbox = SqliteOutbox(tmp_path / "o.sqlite3", max_entries=3, prune_batch=1)
    for _ in range(5):
        outbox.append({"type": "x"})
    assert len(outbox) == 3 and outbox.oldest_available_seq == 3
    outbox.close()


def test_prune_batch_nol_ditolak(tmp_path):
    with pytest.raises(ValueError):
        SqliteOutbox(tmp_path / "o.sqlite3", prune_batch=0)
