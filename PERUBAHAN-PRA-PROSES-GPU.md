# Perubahan: detector.fast_preprocess (pra-proses frame di GPU)

Dasar: batch_check 4060 dingin, cuda_graph: D-FINE M 28,5 ms, S 25,2 ms per
gambar (end-to-end). Forward M dengan graph ±12,6 ms. S hanya 12% lebih cepat
walau FLOPs-nya < setengah M -> sisa ±13-16 ms bukan model, melainkan pra/pasca-
proses LibreYOLO di CPU yang sama untuk semua ukuran. Mengganti M ke S tidak
sepadan dengan turunnya akurasi.

## Pra-proses LibreYOLO untuk input numpy (dibaca dari kode 1.6.0)

ImageLoader.load (numpy -> PIL) -> img.copy() -> np.array -> PIL.fromarray ->
resize -> float32/255 -> transpose CHW -> torch.from_numpy -> .to(cuda) (4,9 MB
float). Dengan `pre_resize: true` frame sudah RGB 640x640, dan resize PIL ke
ukuran yang sama adalah salinan polos (diverifikasi: identik), jadi input model
= uint8/255 dalam CHW.

## Perubahan

- `engine/perception/dfine_detector.py`: `fast_preprocess` + `install_fast_preprocess()`:
  memasang `_preprocess_predict` di instance model LibreYOLO (hook resmi yang dipakai
  InferenceRunner). Frame uint8 RGB berukuran persis image_size -> upload 1,2 MB
  uint8 ke GPU, float/255, CHW. Selain itu (BGR, ukuran lain, bukan uint8, kwargs
  tambahan) -> pra-proses LibreYOLO asli. Bisa dimatikan per panggilan.
- Config: `detector.fast_preprocess` (default false) di schema/loader/factory dan
  semua yaml. Butuh `pre_resize: true` (diperingatkan bila tidak).
- `engine/tools/batch_check.py`: `--fast-preprocess`; pembanding selalu PIL + eager;
  mencetak jumlah frame yang lewat jalur cepat; vonis menyebut akselerasi yang aktif.
- `docs/UJI-LAG.md`: langkah 3d.

## Tes

test_cuda_graph_batch.py +4: kasus yang tidak boleh disentuh, fallback hook, dan
dua tes yang butuh torch/LibreYOLO (di-skip di CI tanpa torch, JALAN di laptop uji):
tensor wajib `torch.equal` dengan `preprocess_image` LibreYOLO.
Suite di sini: semua lulus (2 skip karena tanpa torch).
