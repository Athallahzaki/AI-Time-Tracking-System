# Setup uji rekognisi wajah tanpa roster (3 Okt 2026)

Ekstrak di root proyek di atas paket `perbaikan-urutan-start_detector-dimuat-sebelum-stream-dibuka`.
Verifikasi: 481 tes lulus, policy_grep bersih.

## Isi
- `engine/config/dfine-m-face.yaml` dan `dfine-m-face-sync.yaml`
  - Salinan `dfine-m.yaml` dengan rekognisi menyala (SCRFD 10G + glintr100, CUDA).
  - Bedanya hanya `recognition.execution` (async vs sync), untuk uji C.
- `engine/runtime/service.py`
  - Statistik worker rekognisi sekarang dicetak di level INFO setiap laporan health:
    `rekognisi: diproses N, ditolak-penuh N, basi N, gagal N, rata2 X ms, antre N`.
  - Sebelumnya hanya DEBUG, sehingga tidak terlihat. Dengan roster kosong, baris ini satu-satunya
    bukti bahwa SCRFD dan AuraFace benar-benar jalan.
  - Mode sync tidak punya worker, jadi baris ini tidak muncul di mode sync.
