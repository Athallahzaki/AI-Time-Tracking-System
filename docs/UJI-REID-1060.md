# Uji ReID di laptop GTX 1060 (akhir pekan 17–18 Okt)

RTX 4060 tidak tersedia sampai Senin. Dokumen ini menjalankan uji ReID di laptop 1060 dari awal
sampai jalan, termasuk bila ONNX OSNet dari laptop 4060 **tidak bisa disalin**.

**Yang dinilai di sini:** apakah OSNet lambat di onnxruntime juga terjadi di 1060 dan operasi mana
penyebabnya; apakah pipa ReID jalan (ANON, `identity.resolved`, validator bersih); apakah
`stream_epoch` naik saat stream putus lalu tersambung lagi (ea-r14).

**Yang TIDAK dinilai:** angka performa 5 kamera, perbandingan dengan baseline 4060, latihan 25 epoch.
1060 hanya kuat 1 kamera dan hasilnya bervariasi ±50–100% karena suhu (DEMO-1060).

Pakai **dua jendela PowerShell** dan jangan ditukar: jendela **ENGINE** (`conda activate vision-engine`
atau env engine di 1060) dan jendela **LATIH** (`conda activate reid-env`). Cek nama env di prompt
sebelum setiap perintah. Jangan jalankan latihan dan engine bersamaan (rebutan GPU).

## 1. Persiapan (sekali, jendela ENGINE, root repo)

1. Repo di 1060 harus sama dengan 4060: paket ea-r12, ea-r13, ea-r14 terpasang (ekstrak berurutan di
   root repo, timpa).
2. Pastikan NVRTC di PATH untuk jendela ini (ganti versi bila folder CUDA berbeda):
   ```powershell
   $env:PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin;$env:PATH"
   python scripts/check_gpu_env.py
   ```
   Harap: tidak ada GAGAL; baris `nvrtc` OK. Bila `nvrtc` PERINGATAN "tidak ditemukan":
   `pip install nvidia-cuda-nvrtc-cu12`, cari foldernya
   (`Get-ChildItem $env:CONDA_PREFIX -Recurse -Filter "nvrtc64_12*.dll"`) dan tambahkan ke PATH.
3. Tes:
   ```powershell
   python -m pytest engine/tests contracts/tests -q 2>&1 | Select-Object -Last 5
   ```

## 2. Dapatkan ONNX OSNet

### Jalur A — ONNX bisa disalin dari laptop 4060

Salin `X:\data\onnx\osnet_ain_cepat.onnx` (dan bila bisa `X:\data\runs\ain_cepat\best.pth`) lewat
flashdisk/jaringan ke 1060, misalnya ke `D:\data\onnx\`. Lanjut ke bagian 3.

### Jalur B — tidak bisa disalin: latih singkat di 1060 (jendela LATIH)

Total kira-kira 3–5 jam, sebagian besar menunggu (unduh, prepare, latih). Ikuti
`tools/reid_train/README.md`; ringkasnya:

1. Env latihan (Python 3.11; torch cu126 masih mendukung Pascal):
   ```powershell
   conda create -n reid-env python=3.11 -y
   conda activate reid-env
   cd <repo>\tools\reid_train
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
   python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   pip install -r requirements-train-deps.txt
   pip install --no-build-isolation -r requirements-train.txt
   ```
   Harus tercetak `True` dan nama GPU 1060. Bila tahap terakhir gagal karena MSVC, ikuti README §3
   (pasang torchreid tanpa ekstensi Cython).
2. Unduh **subset 132.145 gambar** RandPerson (Google Drive, tautan di
   <https://github.com/VideoObjectSearch/RandPerson>), ekstrak ke mis. `D:\data\randperson_subset`.
   Bobot ImageNet: unduh `https://drive.google.com/file/d/1-CaioD9NaqbHK_kzSMW8VE4_3KcsRjEo/view`,
   simpan sebagai `C:\Users\<nama>\.cache\torch\checkpoints\osnet_ain_x1_0_imagenet.pth`.
3. Siapkan data dan tes kit:
   ```powershell
   python prepare_randperson.py --src D:\data\randperson_subset --out D:\data\rp256 --workers 6
   python -m pytest tests -q
   ```
   Tabel ringkasan harus `query ±800`, gallery ±12.300. **`query 0` = paket ea-r13 belum terpasang.**
4. Latih singkat. **Tanpa `--amp`**: FP16 di Pascal jauh lebih lambat (tanpa tensor core).
   `--batch 32` supaya muat di VRAM 6 GB:
   ```powershell
   python train_osnet.py --data D:\data\rp256 --out D:\data\runs --name ain_1060 --init imagenet --epochs 2 --batch 32 --workers 6
   ```
   Catat lama epoch 1 (baris `epoch 1/2 ... (N dtk)`). Bila lebih dari ±90 menit, hentikan (Ctrl+C) dan
   ulangi dengan `--epochs 1`. Untuk uji pipa, 1–2 epoch cukup (di 4060, epoch 1 sudah val mAP 0,89).
   VRAM habis: `--batch 16`.
5. Ekspor:
   ```powershell
   python export_onnx.py --checkpoint D:\data\runs\ain_1060\best.pth --out D:\data\onnx\osnet_ain_1060.onnx --verify-dir D:\data\rp256\images
   ```
   Verifikasi harus lolos (selisih < 1e-3); catat SHA-256 yang dicetak.

## 3. Diagnosis kecepatan OSNet (jendela ENGINE, GPU kosong)

```powershell
python tools/reid_train/diag_reid_ort.py D:\data\onnx\<berkas>.onnx
python tools/reid_train/diag_reid_profile.py D:\data\onnx\<berkas>.onnx
```

Bila ada `best.pth`, pembanding PyTorch di jendela LATIH:
`python tools\reid_train\diag_reid_torch.py <best.pth> <repo>\tools\reid_train`.

| Hasil `diag_reid_profile` | Lanjut |
|---|---|
| `InstanceNormalization` memakan sebagian besar waktu | 3a |
| Operasi lain yang mendominasi | kirim keluarannya; jangan lanjut ke 4 dengan model lambat |
| Semua cepat (batch 8 di bawah ±50 ms di 1060) | masalah 4060 tidak terulang di sini; catat versi dari `diag_reid_ort`, lanjut 4 |

### 3a. Ganti InstanceNorm (jendela LATIH: punya paket `onnx`)

```powershell
cd <repo>\tools\reid_train
python -m pytest tests/test_ganti_instancenorm.py -q
python ganti_instancenorm.py --input D:\data\onnx\<berkas>.onnx --output D:\data\onnx\<berkas>_tanpa_in.onnx
```

Harus tercetak "N node InstanceNormalization diganti", dua baris verifikasi dengan kosinus ≥ 0,9999,
"Ditulis", dan SHA-256 baru. "DITOLAK" = jangan dipakai, kirim keluarannya. Lalu ukur ulang di
jendela ENGINE: `python tools/reid_train/diag_reid_ort.py D:\data\onnx\<berkas>_tanpa_in.onnx`.
Pakai berkas `_tanpa_in` di bagian 4 hanya bila jauh lebih cepat.

## 4. Pipa ReID 1 kamera (jendela ENGINE + 2 terminal lain)

```powershell
mkdir engine\models\reid -Force
Copy-Item D:\data\onnx\<berkas terpilih>.onnx engine\models\reid\osnet_ain_reid.onnx
(Get-FileHash engine\models\reid\osnet_ain_reid.onnx -Algorithm SHA256).Hash.ToLower()
Copy-Item engine\config\demo-1060.yaml engine\config\lokal-reid-1060.yaml
```

Di blok `reid:` berkas `lokal-reid-1060.yaml` (jangan di-commit): `enabled: true`,
`model_sha256: "<hash di atas>"`. Lalu:

```powershell
# terminal 1
.\deploy\mediamtx\start-mediamtx.ps1
# terminal 2
.\scripts\publish_test_video.ps1 -Video <video>.mp4 -Fps 25
# jendela ENGINE (NVRTC di PATH, lihat 1.2)
python -m engine.runtime --config engine/config/lokal-reid-1060.yaml --tcp 127.0.0.1:8765 --health-seconds 2 2>&1 | Tee-Object -FilePath logs\engine-reid-1060.log
# terminal 4, setelah "engine siap"
python scripts/lag_probe.py --camera cam01=rtsp://127.0.0.1:8554/cam01 --minutes 5 --out bench-out\reid-1060.csv --events-out bench-out\reid-1060.ndjson
python -m contracts.validator bench-out\reid-1060.ndjson --channel events
Select-String -Path logs\engine-reid-1060.log -Pattern "ReID:|ANON-|diselesaikan|rekognisi:|tidak dikenal|nvrtc" | Select-Object -Last 30
```

Harap: engine start tanpa galat (galat "tidak membawanya" = jendela salah env); validator 0 GAGAL;
baris `ReID: embedding N` naik dan `rata2 ... ms/batch` jauh di bawah 1.000 ms.

## 5. Uji `stream_epoch` saat stream putus (ea-r14)

Ulangi bagian 4 (engine + probe 5 menit). Sekitar menit ke-2, di terminal 2 tekan **Ctrl+C**
(publish berhenti), tunggu ±20 detik, lalu jalankan lagi perintah publish yang sama. Setelah probe
selesai:

```powershell
python -m contracts.validator bench-out\reid-1060.ndjson --channel events
Select-String -Path bench-out\reid-1060.ndjson -Pattern '"camera.online"' | ForEach-Object { ($_ -split '"stream_epoch": ')[1].Split(',')[0] }
```

Harap: validator **0 GAGAL** (dulu: "reconnect kamera ... tidak menaikkan stream_epoch (0 -> 0)") dan
daftar epoch `camera.online` naik (0, 1, ...). Uji ini juga sah dengan `reid.enabled: false` bila
bagian 2–4 belum selesai.

## 6. Yang dikirim balik

1. Keluaran `check_gpu_env` (bagian 1) dan ringkasan pytest.
2. Keluaran `diag_reid_ort` + `diag_reid_profile` (+ `diag_reid_torch` bila ada).
3. Bila 3a: keluaran `ganti_instancenorm` dan `diag_reid_ort` untuk berkas `_tanpa_in`.
4. Bagian 4–5: keluaran validator, potongan log, dan `summarize_gladi.py --target-fps 8 bench-out\reid-1060.csv`.

Waktu terbatas: prioritasnya 1 → 3 (butuh ONNX) → 5 (tidak butuh ONNX) → 4.
