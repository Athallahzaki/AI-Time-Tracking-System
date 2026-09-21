"""Penyimpanan vektor referensi dan gambar aslinya.

Engine menyimpan vektor, backend menyimpan orangnya, disambung satu ID buram.
Backend tidak bisa melakukan apa pun dengan 512 angka float — tidak bisa
mencocokkan, tidak bisa menampilkan, tidak bisa memvalidasi — jadi vektor
tinggal di sini.

Empat keputusan yang menentukan, dan tiga di antaranya baru terasa akibatnya
berbulan-bulan kemudian:

**Setiap vektor membawa tag model yang menghasilkannya.** Embedding dari dua
model hidup di ruang vektor yang berbeda; cosine antara keduanya bukan angka
yang salah, ia angka yang **tidak punya arti apa pun**. Tanpa tag, suatu hari
embedder diganti, sistem tetap jalan tanpa satu pun error, dan akurasinya
jatuh ke tingkat acak tanpa petunjuk kenapa. Di sini versi yang tidak cocok
berarti vektornya **tidak dikembalikan sama sekali**, bukan dibandingkan
diam-diam.

**Gambar referensi aslinya ikut disimpan, dan itu wajib.** Ganti model, dan
semua vektor jadi sampah. Dengan gambar asli kamu menghitung ulang dalam
beberapa menit; tanpa itu kamu harus memanggil seluruh karyawan untuk foto
ulang. Karena itu `add_reference` menolak dipanggil tanpa gambar — bukan
peringatan, penolakan.

**SQLite, bukan vector database.** 200 karyawan x 5 referensi x 512 float32
sekitar 2 MB. Brute-force numpy selesai dalam mikrodetik; FAISS atau pgvector
di skala ini justru lebih lambat karena overhead index, sambil menambah satu
layanan yang harus dioperasikan, dimonitor, dan di-backup. Ambang di mana ANN
mulai masuk akal ada di ratusan ribu vektor — sekitar dua puluh ribu karyawan.

**Penghapusan orang menghapus vektor DAN gambarnya.** Ini data biometrik di
bawah UU 27/2022; menyimpan vektor dan bukan foto bukan pembelaan privasi,
karena template inversion bisa merekonstruksi wajah yang dikenali dari
embedding ArcFace. Yang belum ada di sini dan harus ada sebelum produksi:
enkripsi at-rest dan jadwal retensi. Keduanya butuh manajemen kunci yang belum
diputuskan, dan menuliskan enkripsi palsu lebih buruk daripada tidak punya.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

import numpy as np


class StoreError(ValueError):
    """Permintaan yang akan merusak data kalau dilayani."""


@dataclass(frozen=True)
class ReferenceRecord:
    """Satu foto referensi dan turunannya."""

    reference_id: int
    person_id: str
    embedding_version: str
    enrollment_version: int
    quality: float
    camera_id: Optional[str]
    captured_at: Optional[str]
    created_at: str

    @property
    def from_cctv(self) -> bool:
        """Referensi dari kamera yang akan dipakai, bukan dari pas foto.

        Pas foto studio dan kamera sudut ruangan berbeda pose, jarak,
        pencahayaan, dan karakteristik lensa. Tidak ada threshold yang bisa
        menutup selisih itu, jadi asal referensi adalah metadata yang berguna,
        bukan catatan administratif.
        """
        return self.camera_id is not None


@dataclass(frozen=True)
class RosterDiff:
    """Hasil rekonsiliasi deklaratif `set_roster`."""

    dropped: Tuple[str, ...]
    needs_enrollment: Tuple[str, ...]
    unchanged: Tuple[str, ...]


class SqliteReferenceStore:
    """Memenuhi `engine.identity.ports.ReferenceStore`.

    Satu berkas, tanpa server, transaksional, binding di semua bahasa.
    """

    def __init__(
        self,
        path: Union[str, Path],
        embedding_version: str,
        dimension: int = 512,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._version = embedding_version
        self._dimension = dimension
        self._lock = threading.RLock()

        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS persons (
                person_id TEXT PRIMARY KEY,
                enrollment_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS refs (
                reference_id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
                embedding_version TEXT NOT NULL,
                enrollment_version INTEGER NOT NULL,
                vector BLOB NOT NULL,
                image BLOB NOT NULL,
                quality REAL NOT NULL,
                camera_id TEXT,
                captured_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS refs_person ON refs(person_id);
            CREATE INDEX IF NOT EXISTS refs_version ON refs(embedding_version);
            """
        )
        self._db.commit()

    # ---------------- protokol ReferenceStore ----------------

    @property
    def embedding_version(self) -> str:
        return self._version

    @property
    def dimension(self) -> int:
        return self._dimension

    def references(self) -> Dict[str, Sequence[np.ndarray]]:
        """Vektor per orang, **hanya** yang versinya cocok.

        Versi tidak cocok berarti tidak dikembalikan, bukan dikembalikan lalu
        dibandingkan. Roster yang kosong setelah ganti model adalah kegagalan
        yang kelihatan; roster yang penuh vektor tak berarti adalah kegagalan
        yang tidak.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT person_id, vector FROM refs WHERE embedding_version = ? ORDER BY reference_id",
                (self._version,),
            ).fetchall()

        result: Dict[str, List[np.ndarray]] = {}
        for person_id, blob in rows:
            result.setdefault(person_id, []).append(
                np.frombuffer(blob, dtype=np.float32).copy()
            )
        return result

    # ---------------- penulisan ----------------

    def add_reference(
        self,
        person_id: str,
        embedding: np.ndarray,
        image_jpeg: bytes,
        quality: float,
        enrollment_version: int = 1,
        camera_id: Optional[str] = None,
        captured_at: Optional[str] = None,
        embedding_version: Optional[str] = None,
    ) -> int:
        """Simpan satu referensi. Gambar aslinya WAJIB.

        Menolak tanpa gambar bukan kerewelan: itu satu-satunya hal yang membuat
        pergantian model jadi pekerjaan beberapa menit alih-alih memanggil
        seluruh karyawan untuk foto ulang.
        """
        if not image_jpeg:
            raise StoreError(
                "referensi tanpa gambar asli ditolak. Tanpa itu, ganti embedder berarti "
                "seluruh vektor jadi sampah dan tidak ada cara menghitung ulang."
            )

        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size != self._dimension:
            raise StoreError(f"dimensi {vector.size}, harusnya {self._dimension}")

        norm = float(np.linalg.norm(vector))
        if norm <= 0:
            raise StoreError("vektor nol")
        vector = vector / norm

        version = embedding_version or self._version
        now = _now()

        with self._lock:
            self._db.execute(
                "INSERT INTO persons (person_id, enrollment_version, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(person_id) DO UPDATE SET "
                "  enrollment_version=MAX(persons.enrollment_version, excluded.enrollment_version), "
                "  updated_at=excluded.updated_at",
                (person_id, enrollment_version, now),
            )
            cursor = self._db.execute(
                "INSERT INTO refs (person_id, embedding_version, enrollment_version, vector, "
                "image, quality, camera_id, captured_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    person_id, version, enrollment_version, vector.tobytes(),
                    sqlite3.Binary(image_jpeg), float(quality), camera_id, captured_at, now,
                ),
            )
            self._db.commit()
            return int(cursor.lastrowid)

    def delete_person(self, person_id: str) -> int:
        """Hapus orang beserta seluruh vektor dan gambarnya.

        Langkah kedua dari penghapusan dua langkah §7.4: backend membuang
        catatan orangnya, rekonsiliasi roster membuat engine membuang datanya.
        """
        with self._lock:
            cursor = self._db.execute("DELETE FROM refs WHERE person_id = ?", (person_id,))
            removed = cursor.rowcount
            self._db.execute("DELETE FROM persons WHERE person_id = ?", (person_id,))
            self._db.commit()
            return removed

    def set_roster(self, persons: Dict[str, int]) -> RosterDiff:
        """Rekonsiliasi deklaratif: `persons` adalah SELURUH himpunan yang diinginkan.

        Perintah imperatif (`add_person` / `remove_person`) akan desync begitu
        satu pesan hilang atau satu sisi restart, dan kamu tidak akan tahu
        sampai ada vektor hantu yang masih dicocokkan padahal orangnya sudah
        keluar dari perusahaan. Deklaratif kebal terhadap itu.
        """
        with self._lock:
            known = {
                row[0]: row[1]
                for row in self._db.execute("SELECT person_id, enrollment_version FROM persons")
            }

            dropped = sorted(set(known) - set(persons))
            for person_id in dropped:
                self.delete_person(person_id)

            needs: List[str] = []
            unchanged: List[str] = []
            usable = self._people_with_usable_references()

            for person_id, wanted_version in sorted(persons.items()):
                current = known.get(person_id)
                if current is None or wanted_version > current or person_id not in usable:
                    needs.append(person_id)
                    if current is not None and wanted_version > current:
                        # Versi enrollment naik berarti referensinya berubah;
                        # yang lama dibuang supaya tidak ada pencocokan
                        # terhadap foto yang sudah dinyatakan usang.
                        self._db.execute(
                            "DELETE FROM refs WHERE person_id = ? AND enrollment_version < ?",
                            (person_id, wanted_version),
                        )
                        self._db.execute(
                            "UPDATE persons SET enrollment_version = ?, updated_at = ? WHERE person_id = ?",
                            (wanted_version, _now(), person_id),
                        )
                else:
                    unchanged.append(person_id)

            self._db.commit()

        return RosterDiff(tuple(dropped), tuple(needs), tuple(unchanged))

    def _people_with_usable_references(self) -> Set[str]:
        rows = self._db.execute(
            "SELECT DISTINCT person_id FROM refs WHERE embedding_version = ?", (self._version,)
        ).fetchall()
        return {row[0] for row in rows}

    # ---------------- pergantian model ----------------

    def pending_reembedding(self) -> List[str]:
        """Orang yang punya gambar tapi tidak punya vektor di versi sekarang.

        Daftar ini adalah rencana kerja setelah embedder diganti, dan alasan
        kenapa gambar asli disimpan.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT person_id FROM refs WHERE person_id NOT IN "
                "(SELECT person_id FROM refs WHERE embedding_version = ?)",
                (self._version,),
            ).fetchall()
        return sorted(row[0] for row in rows)

    def images_for_reembedding(self, person_id: str) -> List[Tuple[int, bytes]]:
        """Gambar asli yang perlu dihitung ulang, beserta id referensinya."""
        with self._lock:
            rows = self._db.execute(
                "SELECT reference_id, image FROM refs WHERE person_id = ? "
                "AND embedding_version != ? ORDER BY reference_id",
                (person_id, self._version),
            ).fetchall()
        return [(int(row[0]), bytes(row[1])) for row in rows]

    def attach_reembedding(self, reference_id: int, embedding: np.ndarray) -> int:
        """Tambahkan vektor versi baru untuk gambar yang sudah ada.

        Referensi lama TIDAK dihapus: kalau pergantian model ternyata
        memburukkan akurasi, jalan pulangnya masih ada.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT person_id, enrollment_version, image, quality, camera_id, captured_at "
                "FROM refs WHERE reference_id = ?",
                (reference_id,),
            ).fetchone()
        if row is None:
            raise StoreError(f"referensi {reference_id} tidak ada")

        return self.add_reference(
            person_id=row[0], embedding=embedding, image_jpeg=bytes(row[2]),
            quality=float(row[3]), enrollment_version=int(row[1]),
            camera_id=row[4], captured_at=row[5],
        )

    # ---------------- pembacaan ----------------

    def records(self, person_id: Optional[str] = None) -> List[ReferenceRecord]:
        query = (
            "SELECT reference_id, person_id, embedding_version, enrollment_version, quality, "
            "camera_id, captured_at, created_at FROM refs"
        )
        params: Tuple = ()
        if person_id is not None:
            query += " WHERE person_id = ?"
            params = (person_id,)
        query += " ORDER BY reference_id"

        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        return [ReferenceRecord(*row) for row in rows]

    def stats(self) -> Dict[str, object]:
        with self._lock:
            people = self._db.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
            total = self._db.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
            usable = self._db.execute(
                "SELECT COUNT(*) FROM refs WHERE embedding_version = ?", (self._version,)
            ).fetchone()[0]
            bytes_used = self._db.execute(
                "SELECT COALESCE(SUM(LENGTH(image)), 0) FROM refs"
            ).fetchone()[0]

        return {
            "embedding_version": self._version,
            "persons": people,
            "references_total": total,
            "references_usable": usable,
            "references_stale": total - usable,
            "image_bytes": bytes_used,
        }

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
