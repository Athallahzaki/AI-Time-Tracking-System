"""Outbox engine palsu — implementasinya kanonik di `engine/api/outbox.py`.

Sengaja re-export, bukan salinan. Engine palsu dan engine sungguhan harus
memakai semantik penomoran, replay, dan `replay_gap` yang sama persis; kalau
masing-masing punya implementasi sendiri, suatu hari engine asli gagal di
skenario yang engine palsu lulus, dan waktu sehari habis untuk menemukan bahwa
dua kode yang seharusnya sama ternyata tidak.

`SqliteOutbox` tidak diekspor ke sini dengan sengaja: engine palsu tidak boleh
punya state durabel. Ia harus mulai bersih setiap kali dijalankan, kalau tidak
fixture yang dihasilkannya berhenti deterministik.
"""

from ...api.outbox import Outbox

__all__ = ["Outbox"]
