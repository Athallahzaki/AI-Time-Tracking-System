# Urutan start kamera: detector dimuat dulu, baru stream dibuka (3 Okt 2026)

Ekstrak di root proyek di atas paket `engineA-engineB_batas-thread-cpu_nvdec-opsional_rekognisi-async_koreksi-jam`
(dan `perbaikan-lag-probe_crash-engine-lambat-mulai`). Verifikasi: 481 tes engine+contracts lulus, smoke lulus,
policy_grep bersih.

## Temuan dari uji GTX 1060 (`lag-B-none.csv`)
Kamera online pada detik 61. Frame pertama yang dianalisis berumur 58,5 dtk, dan 5 dtk kemudian
`camera.failed stream_reconnected`.

## Penyebab
- `factory.build_engine` memanggil `resolve_source_fps`, yang MEMBUKA stream untuk membaca fps.
- Pembukaan itu terjadi sebelum `build_detector` memuat bobot dan sebelum warmup CUDA (±55 dtk di 1060).
- Selama itu RTSP terbuka tetapi tidak dibaca:
  - `live_buffer: none`: antrean socket menumpuk, lalu MediaMTX memutus pembaca yang lambat.
  - `live_buffer: latest`: thread pembaca men-decode sia-sia selama model dimuat.
- Offset jam ditetapkan saat stream dibuka, sehingga `at` frame awal salah sebesar waktu muat model.
- Dengan 5 kamera, ini terjadi di setiap kamera.

## Perbaikan (`engine/factory.py`, berkas bersama EB)
- Detector dimuat lalu dipanaskan dulu, baru sumber dibuka dan fps dibaca.
- `VisionEngine.start` tetap memanaskan lagi; biayanya satu inferensi tambahan.
- Detector yang sudah ada (reconnect / loop file) tidak dimuat atau dipanaskan ulang.
- Efek samping: config sumber yang salah (fps tidak terbaca) sekarang ketahuan setelah model dimuat, bukan
  sebelumnya. Penolakannya tetap terjadi.

## Tes
- Baru: `engine/tests/test_startup_order.py` (2).
- `engine/tests/test_b0_port.py::test_source_with_unknown_fps_is_refused_not_guessed` sekarang memakai
  detector tiruan, karena urutannya berubah. Yang diuji tetap penolakan fps.

## Catatan untuk Engine B (belum diubah)
- Setiap `CameraSupervisor` memuat detector-nya sendiri: 5 kamera berarti 5 salinan D-FINE di GPU dan
  5× waktu muat.
- Berbagi satu detector (atau batching) adalah keputusan desain untuk tahap 5 kamera.
