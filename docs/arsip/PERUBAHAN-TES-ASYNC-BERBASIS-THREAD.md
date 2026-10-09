# Perubahan: tes async rekognisi tidak lagi bergantung kecepatan mesin

`test_async_loop_frame_tidak_tertahan_recognizer_lambat` gagal di Windows/4060
(3 Okt 19:56): async 4410 frame vs sync 1961 = 2,25x, padahal tes meminta > 3x.
Bukan regresi: async memang 2,25x lebih cepat, tetapi rasio itu bergantung pada
seberapa cepat loop mock berputar dibanding rekognisi 50 ms, jadi berbeda per
mesin.

Tes sekarang membuktikan hal yang sebenarnya dijanjikan async: recognizer TIDAK
pernah dipanggil di thread kamera (`camera-cam01`), sedangkan di mode sync
selalu di sana. Ditambah async > sync (tanpa angka ajaib) dan async tetap
mengidentifikasi orangnya.

Berkas: engine/tests/test_recognition_worker.py. Suite: 553 passed, 3 skipped.
