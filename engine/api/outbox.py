"""Penomoran urut, outbox, dan replay — versi kanonik.

`engine/tools/fake_engine/outbox.py` mengimpor dari sini, bukan menyalin.
Kalau keduanya punya implementasi sendiri, suatu hari engine asli akan gagal di
skenario yang engine palsu lulus, dan kalian akan menghabiskan sehari mencari
tahu kenapa — padahal jawabannya cuma "dua kode yang seharusnya sama ternyata
tidak".

Dua kelas, satu semantik:

- `Outbox` menyimpan di memori. Cukup untuk engine palsu dan untuk tes.
- `SqliteOutbox` menyimpan ke berkas. Dipakai engine sungguhan, dan alasannya
  satu: **nomor urut harus bertahan melintasi restart engine.** Kalau engine
  restart lalu mulai lagi dari `seq = 1`, backend yang menyimpan
  `last_event_seq = 10432` akan membuang seluruh aliran berikutnya sebagai
  "sudah pernah dilihat" — diam-diam, tanpa error, dan yang hilang adalah
  kehadiran orang sepanjang sisa hari itu.

Satu keputusan yang tidak kelihatan tapi menentukan: **hanya kanal `events`
yang dinomori dan disimpan.** `view` boleh hilang. Kalau ia ikut masuk, retensi
habis oleh bbox per frame, dan backend yang reconnect memutar ulang ribuan
kotak sebelum sampai ke satu event yang benar-benar ia butuhkan.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Iterable, Iterator, List, Optional, Tuple, Union


class _OutboxBase:
    """Semantik replay yang dibagi kedua implementasi."""

    @property
    def next_seq(self) -> int:
        raise NotImplementedError

    @property
    def latest_seq(self) -> int:
        return self.next_seq - 1

    @property
    def oldest_available_seq(self) -> int:
        raise NotImplementedError

    outbox_id: str = ""

    def since(self, last_event_seq: int, limit: Optional[int] = None) -> List[Dict]:
        raise NotImplementedError

    def gap_for(self, last_event_seq: int) -> Optional[Dict]:
        """Pesan `replay_gap` kalau outbox tidak cukup jauh ke belakang.

        Dipancarkan SEBELUM pengiriman, bukan sesudah: backend harus tahu ada
        lubang sebelum ia mulai memproses, karena sesudahnya ia sudah terlanjur
        menyimpulkan bahwa tidak ada kejadian di rentang itu — dan untuk sistem
        yang mengukur ketidakhadiran, "tidak ada kejadian" berarti orangnya
        dianggap tidak di tempat.

        `last_event_seq == 0` berarti backend baru dan tidak meminta apa pun,
        jadi tidak ada lubang betapapun pendeknya outbox.
        """
        if last_event_seq <= 0:
            return None

        oldest = self.oldest_available_seq
        if oldest == 0 or oldest <= last_event_seq + 1:
            return None

        return {"type": "replay_gap", "v": 1, "from_seq": last_event_seq, "to_seq": oldest}


class Outbox(_OutboxBase):
    """Outbox di memori. Hilang saat restart — itu sebabnya ia bukan yang dipakai produksi."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: Deque[Tuple[int, Dict]] = deque(maxlen=max_entries)
        self._next_seq = 1
        self._lock = threading.Lock()
        # Baru setiap proses: penomoran di memori memang mulai ulang saat
        # restart, dan backend harus bisa melihatnya dari identitas ini.
        self.outbox_id = f"mem-{uuid.uuid4().hex}"

    @property
    def next_seq(self) -> int:
        return self._next_seq

    @property
    def oldest_available_seq(self) -> int:
        return self._entries[0][0] if self._entries else 0

    def append(self, message: Dict) -> Dict:
        with self._lock:
            message = dict(message)
            message["seq"] = self._next_seq
            self._next_seq += 1
            self._entries.append((message["seq"], message))
            return message

    def since(self, last_event_seq: int, limit: Optional[int] = None) -> List[Dict]:
        with self._lock:
            out = [message for seq, message in self._entries if seq > last_event_seq]
        return out[:limit] if limit is not None else out

    def ack(self, through_seq: int) -> int:
        """Buang apa pun sampai `through_seq`. Kembalikan jumlah yang dibuang."""
        removed = 0
        with self._lock:
            while self._entries and self._entries[0][0] <= through_seq:
                self._entries.popleft()
                removed += 1
        return removed

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Dict]:
        with self._lock:
            return iter([message for _, message in self._entries])


class SqliteOutbox(_OutboxBase):
    """Outbox durabel. Satu berkas, tanpa server, transaksional.

    Dipilih SQLite dan bukan berkas NDJSON yang di-append karena pemangkasan
    (`ack`) dan pembacaan rentang (`since`) jadi satu pernyataan alih-alih
    menulis ulang seluruh berkas, dan karena penulisannya atomik: engine yang
    mati di tengah tulis tidak meninggalkan baris separuh jadi yang akan gagal
    di-parse saat dibuka lagi.
    """

    def __init__(
        self,
        path: Union[str, Path],
        max_entries: Optional[int] = 200_000,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._lock = threading.RLock()

        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS outbox ("
            "  seq INTEGER PRIMARY KEY,"
            "  ts TEXT NOT NULL,"
            "  type TEXT NOT NULL,"
            "  payload TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._db.commit()

        # Inilah properti yang membuat berkas ini ada. Nomor urut dipulihkan
        # dari yang TERTINGGI yang pernah ditulis, bukan dari yang tertua yang
        # masih tersimpan — dan itu sebabnya ada tabel `meta`: kalau seluruh isi
        # outbox sudah dipangkas, `MAX(seq)` mengembalikan NULL dan penomoran
        # akan mulai lagi dari 1. Backend yang menyimpan last_event_seq = 10432
        # lalu membuang seluruh aliran berikutnya sebagai "sudah pernah
        # dilihat" adalah kegagalan yang tidak memunculkan satu pun error.
        highest_stored = self._db.execute("SELECT MAX(seq) FROM outbox").fetchone()[0] or 0
        row = self._db.execute("SELECT value FROM meta WHERE key='high_water'").fetchone()
        high_water = int(row[0]) if row else 0

        self._high_water = max(highest_stored, high_water)
        self._next_seq = self._high_water + 1

        row = self._db.execute("SELECT value FROM meta WHERE key='outbox_id'").fetchone()
        if row is None:
            self.outbox_id = f"sql-{uuid.uuid4().hex}"
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('outbox_id', ?)", (self.outbox_id,)
            )
            self._db.commit()
        else:
            self.outbox_id = str(row[0])

    @property
    def next_seq(self) -> int:
        with self._lock:
            return self._next_seq

    @property
    def oldest_available_seq(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MIN(seq) FROM outbox").fetchone()
            return row[0] or 0

    def append(self, message: Dict) -> Dict:
        with self._lock:
            message = dict(message)
            message["seq"] = self._next_seq
            self._db.execute(
                "INSERT INTO outbox (seq, ts, type, payload) VALUES (?, ?, ?, ?)",
                (
                    message["seq"],
                    str(message.get("ts", "")),
                    str(message.get("type", "")),
                    json.dumps(message, ensure_ascii=False),
                ),
            )
            # High-water mark disimpan supaya nomor urut tetap tidak dipakai
            # ulang bahkan kalau SELURUH isi outbox sudah dipangkas.
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('high_water', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(message["seq"]),),
            )
            self._db.commit()

            self._next_seq += 1
            self._high_water = message["seq"]

            if self._max_entries is not None:
                self._enforce_cap()

            return message

    def _enforce_cap(self) -> None:
        # seq bersambung dan hanya dipangkas dari depan, jadi MIN(seq) (indeks
        # primary key) cukup untuk menghitung isi tanpa COUNT(*) per event.
        oldest = self._db.execute("SELECT MIN(seq) FROM outbox").fetchone()[0]
        if oldest is None:
            return
        cutoff = self._high_water - self._max_entries
        if oldest > cutoff:
            return
        self._db.execute("DELETE FROM outbox WHERE seq <= ?", (cutoff,))
        self._db.commit()

    def since(self, last_event_seq: int, limit: Optional[int] = None) -> List[Dict]:
        with self._lock:
            if limit is None:
                rows = self._db.execute(
                    "SELECT payload FROM outbox WHERE seq > ? ORDER BY seq", (last_event_seq,)
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT payload FROM outbox WHERE seq > ? ORDER BY seq LIMIT ?",
                    (last_event_seq, int(limit)),
                ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def ack(self, through_seq: int) -> int:
        """Pangkas setelah backend meng-ack.

        Retensi §6.5: cukup beberapa hari, dipangkas setelah di-ack. Yang tidak
        boleh: memangkas berdasarkan waktu saja, tanpa tahu backend sudah
        menerimanya atau belum.
        """
        with self._lock:
            cursor = self._db.execute("DELETE FROM outbox WHERE seq <= ?", (through_seq,))
            self._db.commit()
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def __iter__(self) -> Iterator[Dict]:
        return iter(self.since(0))
