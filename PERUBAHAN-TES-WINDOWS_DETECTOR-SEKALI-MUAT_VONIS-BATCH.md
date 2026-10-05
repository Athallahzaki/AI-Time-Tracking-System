# Perubahan: tes jalan di Windows, detector tidak dimuat ulang tiap retry, vonis batch_check

Dasar: `pytest engine/tests` dan `batch_check --cuda-graph` di laptop RTX 4060
(Windows, LibreYOLO 1.6), 3 Okt 19:28.

## 1. 16 tes soket gagal di Windows (bukan karena upgrade)

`socket.AF_UNIX` tidak ada di Python Windows; tes protokol memakai unix socket.
Engine di Windows memang lewat TCP. Baru: `engine/tests/_transport.py` memakai
unix socket bila ada dan TCP 127.0.0.1 port acak bila tidak, jadi tes yang sama
menguji jabat tangan, replay, auth, dan batas kirim lewat TCP di Windows (tidak
dilewati). `ENGINE_TEST_TCP=1` memaksa jalur TCP di Linux; kedua mode lulus.
Diubah: test_api.py, test_api_connection.py, test_engine_phase1.py.

## 2. BUG: kamera mati = bobot D-FINE dimuat ulang tiap percobaan

Akibat urutan start baru (detector dulu, lalu stream): bila sumber gagal dibuka,
detector yang baru dimuat di `factory.build_engine` ikut hilang bersama
exception, dan percobaan ulang berikutnya memuat bobot lagi (10+ dtk di 4060,
±55 dtk di 1060). Tes `test_failed_camera_is_reopened` gagal di Windows karena
ini (dengan LibreYOLO terpasang). Perbaikan di `engine/runtime/camera.py`:
detector dibuat dan disimpan di supervisor sebelum `build_engine` membuka
sumber. Tes kini memakai MockDetector dan memastikan detector dibuat SEKALI
walau sumber gagal berulang. (Jalur detector bersama tidak terdampak.)

## 3. Vonis batch_check menyesatkan

Hasil 4060: tanpa batch, eager 206,8 ms; dengan cuda_graph ukuran 1 = 29,5,
ukuran 2 = 34,3, ukuran 5 = 53,4 ms/gambar. Vonis lama: "layak dinyalakan
(batch_inference: true, max_batch: 1)". Ukuran 1 bukan batch; percepatannya dari
cuda_graph. Vonis baru membandingkan batch dengan ukuran 1 (bukan dengan eager)
dan berbunyi "batch TIDAK membantu, biarkan batch_inference: false;
cuda_graph: true layak dipakai".

## Tes

552 passed, 3 skipped (unix socket) dan 552 passed, 3 skipped (ENGINE_TEST_TCP=1).
