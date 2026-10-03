# Perubahan: engine API tidak lagi tertahan backend lama yang macet (Windows)

Dasar: `pytest engine/tests` di Windows 3 Okt 19:40, satu gagal:
`test_backend_lama_yang_macet_tidak_mengunci_handshake_baru` (TimeoutError).

## Masalah (nyata di produksi Windows, bukan hanya tes)

Backend lama berhenti membaca -> thread kirim engine tertahan di `sendall` sambil
memegang SATU kunci tulis global. Backend baru tersambung -> engine memutus
koneksi lama (`shutdown`) lalu menulis hello_ack di bawah kunci yang sama.
Di Linux `shutdown` membangunkan `sendall` yang tertahan; di Windows TIDAK.
Akibatnya backend yang reconnect setelah macet menunggu sampai batas kirim habis
(15 dtk di produksi, 60 dtk di tes) sebelum menerima hello_ack, dan thread kirim
tunggal juga tidak bisa mengirim event ke koneksi baru selama itu.

## Perbaikan (`engine/api/server.py`)

- Kunci tulis PER KONEKSI (`_lock_for(connection)`, WeakKeyDictionary), bukan
  global. Penulis ke koneksi lama hanya menahan koneksi lama.
- Thread kirim PER KONEKSI, dibuat saat handshake selesai, berhenti begitu
  generasinya lewat. Thread lama yang macet di `sendall` hanya menahan dirinya
  sendiri sampai batas kirim, lalu berhenti.
- View lama dibuang saat handshake baru (dulu dibuang oleh thread kirim tunggal
  selama tidak ada koneksi).
- Urutan tetap: hello_ack + gap ditulis dan koneksi/kursor dipasang di bawah
  kunci koneksi baru SEBELUM thread kirimnya dimulai, jadi tidak ada event yang
  mendahului hello_ack.

## Tes

Baru: `test_sendall_yang_tidak_terbangun_seperti_windows_tidak_menahan_backend_baru`
mensimulasikan perilaku Windows di Linux (koneksi lama tidak dibangunkan).
GAGAL dengan server lama, LULUS dengan yang baru.
Suite: 553 passed, 3 skipped (unix socket) dan 553 passed (ENGINE_TEST_TCP=1).
