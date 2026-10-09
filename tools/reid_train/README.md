# Kit latih OSNet untuk ReID (RandPerson sintetis)

Jalur EA. Melatih OSNet dari dataset sintetis **RandPerson** (Apache-2.0,
<https://github.com/VideoObjectSearch/RandPerson>), mengekspor ke ONNX, dan mengevaluasinya
pada crop berlabel milik tim. Semua ada di `tools/reid_train/`, di luar `engine/`: torch dan
torchreid **bukan** dependensi runtime engine dan tidak boleh diimpor dari `engine/`.

Latihan dijalankan di **laptop Windows (RTX 4060 8 GB, RAM 16 GB)**, bukan di sesi cloud.
Tes mini di CPU (40 gambar palsu) ada di `tests/`.

| Berkas | Fungsi |
|---|---|
| `prepare_randperson.py` | resize 256x128, split per identitas, tulis `manifest.csv` |
| `randperson_dataset.py` | dataset torchreid dari manifest (terdaftar sebagai `randperson`) |
| `train_osnet.py` | latih (softmax+label smoothing + triplet), checkpoint, log CSV/TensorBoard |
| `export_onnx.py` | checkpoint → ONNX + verifikasi PyTorch vs onnxruntime + SHA-256 |
| `eval_reid.py` | mAP/rank-1 + kurva ambang kosinus pada crop berlabel tim |
| `reid_common.py` | pra-proses bersama (definisi resmi masukan model) |
| `MODEL-CARD.md` | templat kartu model, isi untuk setiap ONNX yang dihasilkan |

Semua perintah di bawah dijalankan dari folder `tools\reid_train` di **PowerShell**.

## 1. Prasyarat

- Python **3.10, 3.11, atau 3.12**. Python 3.13 gagal: `setup.py` torchreid memakai
  `locals()['__version__']` yang tidak berlaku lagi di 3.13 (sudah dicoba).
- Git, driver NVIDIA terbaru. Pasang CUDA toolkit **tidak perlu** (roda PyTorch membawa runtime sendiri).
- Perkiraan disk (belum diukur dengan data asli, ukur dengan `Get-ChildItem -Recurse | Measure-Object Length -Sum`):
  venv + torch CUDA ±6–8 GB; hasil `prepare` 132.145 JPG 256x128 q95 ±2–3 GB; subset RandPerson
  asli (unduhan + hasil ekstrak) sebesar yang tertulis di halaman unduhnya, sediakan beberapa GB
  tambahan; tiap run ±puluhan MB (checkpoint `best.pth`/`last.pth` + log). Total aman: sediakan **±20 GB** kosong.

## 2. Venv dan torch CUDA

```powershell
cd C:\path\ke\AI-Time-Tracking-System\tools\reid_train
py -3.11 -m venv .venv-reid
# bila diblokir: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-reid\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Pasang torch **CUDA** lebih dulu, dengan perintah dari <https://pytorch.org/get-started/locally/>
(pilih Stable, Windows, Pip, CUDA terbaru). Bentuknya kira-kira:

```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Harus tercetak `True` dan nama GPU. Bila `False`, jangan lanjut (latihan di CPU tidak praktis).
Nomor `cu126` hanyalah contoh: ikuti yang ditampilkan situs PyTorch.

## 3. Dependensi kit (dua tahap)

```powershell
pip install -r requirements-train-deps.txt
pip install --no-build-isolation -r requirements-train.txt
```

Dua tahap karena `setup.py` torchreid mengimpor paketnya sendiri (torch, scipy, cv2, …) saat
membangun metadata; tanpa tahap 1, tahap 2 gagal dengan `ModuleNotFoundError`. torchreid dipin ke
commit yang dipakai saat kit ini diuji.

**Eval Cython bisa gagal dikompilasi di Windows** (butuh MSVC Build Tools). Gejalanya: tahap 2
berhenti dengan `error: Microsoft Visual C++ 14.0 or greater is required`. Solusi: pasang torchreid
tanpa ekstensi, lalu torchreid otomatis memakai eval Python (lebih lambat, hasilnya tetap benar;
akan muncul peringatan `Cython evaluation ... is unavailable`):

```powershell
pip install onnx onnxruntime        # sisa paket di requirements-train.txt selain torchreid
git clone https://github.com/KaiyangZhou/deep-person-reid.git $env:TEMP\dpr
cd $env:TEMP\dpr
git checkout f8cd150fdf77e8d9e1ed143b7f308c2c609ded50
(Get-Content setup.py) -replace 'ext_modules=cythonize\(ext_modules\)','ext_modules=[]' | Set-Content setup.py -Encoding utf8
pip install --no-build-isolation .
cd C:\path\ke\AI-Time-Tracking-System\tools\reid_train
```

Jalur tanpa
ekstensi ini diuji di Linux (seluruh tes lulus dengan eval Python); baris PowerShell-nya sendiri
belum dicoba di Windows.

## 4. Unduh subset RandPerson (manual)

Buka <https://github.com/VideoObjectSearch/RandPerson>, ikuti tautan unduhan **subset 132.145
gambar** (Google Drive) di README mereka, ekstrak ke mis. `D:\data\randperson_subset`.
Nama berkas harus `<pid>_s<scene>_c<cam>_f<frame>.jpg` (boleh di sub-folder); yang tidak cocok
pola dilewati dan dilaporkan jumlahnya. Dataset ini sintetis berlisensi Apache-2.0; cantumkan
atribusinya di `MODEL-CARD.md`.

## 5. Siapkan data

```powershell
python prepare_randperson.py --src D:\data\randperson_subset --out D:\data\rp256 --workers 6
```

Hasil: `D:\data\rp256\images\<pid>\*.jpg`, `manifest.csv` (path, pid, camid, split), `summary.json`.
Split **per identitas** (±90% train / ±10% val, `--seed 0`); di val, satu gambar acak per
(pid, kamera) jadi query dan sisanya gallery. `camid` = gabungan scene+kamera. Bisa dihentikan dan
diulang: gambar yang sudah ada dilewati (`--overwrite` untuk menulis ulang).
Periksa tabel ringkasan: jumlah id/gambar/kamera harus masuk akal sebelum melatih.

## 6. Bobot ImageNet (hanya untuk `--init imagenet`)

`train_osnet.py` mencari `~\.cache\torch\checkpoints\<arch>_imagenet.pth`
(`C:\Users\<nama>\.cache\torch\checkpoints\`; dihormati juga `TORCH_HOME`). Bila tidak ada, ia mencoba
`gdown` sekali. Google Drive sering menolak `gdown` (kuota/halaman peringatan virus); bila gagal,
skrip berhenti dengan petunjuk. Unduh manual lewat browser (ID dari `docs/MODEL_ZOO.md` torchreid,
bagian "ImageNet pretrained models") dan simpan dengan **nama persis**:

| `--arch` | ID Google Drive | Simpan sebagai |
|---|---|---|
| `osnet_ain_x1_0` | `1-CaioD9NaqbHK_kzSMW8VE4_3KcsRjEo` | `osnet_ain_x1_0_imagenet.pth` |
| `osnet_ain_x0_25` | `1SxQt2AvmEcgWNhaRb2xC4rP6ZwVDP0Wt` | `osnet_ain_x0_25_imagenet.pth` |
| `osnet_x1_0` | `1LaG1EJpHrxdAxKnSCJ_i0u-nbxSAeiFY` | `osnet_x1_0_imagenet.pth` |

URL: `https://drive.google.com/file/d/<ID>/view`. SHA-256 berkas yang dipakai tercatat otomatis di
`runs\<nama>\config.json` (`bobot_imagenet.sha256`); salin ke MODEL-CARD.

## 7. Latih dua varian

```powershell
python train_osnet.py --data D:\data\rp256 --out D:\runs --name ain_imagenet --init imagenet --amp
python train_osnet.py --data D:\data\rp256 --out D:\runs --name ain_scratch  --init scratch  --amp
```

Default: `--arch osnet_ain_x1_0`, `--epochs` 60 (imagenet) / 120 (scratch), `--batch 64`,
`--workers 4`. Loss = softmax (label smoothing 0,1) + triplet batch-hard (margin 0,3), bobot 1:1;
Adam amsgrad lr 0,0015, cosine, pemanasan 2 epoch. Augmentasi: flip, random resized crop kecil
(skala 0,85–1), color jitter, gaussian blur ringan (p 0,3), random erasing (`--erase-prob`, default 0,5).
Setiap epoch dievaluasi pada val dengan jarak **kosinus** (sama dengan pemakaian di engine).

- `runs\<nama>\best.pth` = mAP val tertinggi; `last.pth` = terakhir; `log.csv`; `tb\`; `config.json`.
- Pantau: `tensorboard --logdir D:\runs` lalu buka <http://localhost:6006>.
- Putus di tengah: ulangi perintah yang sama + `--resume D:\runs\<nama>\last.pth` (`--epochs` wajib
  sama dengan run asal; ditolak bila beda).
- VRAM habis: turunkan `--batch` (kelipatan 4, mis. 48 atau 32). RAM habis/CPU macet: turunkan `--workers`.
- Lama per epoch tergantung disk dan CPU (augmentasi PIL di CPU sering jadi leher botol, bukan GPU);
  ukur dari epoch pertama sebelum membiarkannya semalam.
- Varian lain: `--arch osnet_x1_0` atau `--arch osnet_ain_x0_25`.

**Ingat:** mAP val RandPerson adalah mAP pada data **sintetis**. Angka itu hanya untuk memilih
epoch dan mendeteksi latihan yang rusak; ia tidak memprediksi kinerja di CCTV klien. Yang
menentukan adalah `eval_reid.py` pada crop berlabel tim (langkah 9). Torchreid sendiri mencatat
bahwa augmentasi berat seperti random erasing bisa merugikan generalisasi lintas-dataset; bila
hasil di crop tim mengecewakan, ulangi dengan `--erase-prob 0` sebagai pembanding.

## 8. Ekspor ONNX

```powershell
python export_onnx.py --checkpoint D:\runs\ain_imagenet\best.pth --out D:\onnx\osnet_ain_rp_imagenet.onnx --verify-dir D:\data\rp256\images
python export_onnx.py --checkpoint D:\runs\ain_scratch\best.pth  --out D:\onnx\osnet_ain_rp_scratch.onnx  --verify-dir D:\data\rp256\images
```

Masukan `1x3x256x128` (batch dinamis), keluaran `embedding` 512-d tanpa classifier, opset 17.
Verifikasi: selisih maks embedding PyTorch vs onnxruntime pada 8 gambar harus < 1e-3 (di tes ±1e-6);
bila tidak, kode keluar 1 dan berkas jangan dipakai. SHA-256 dicetak di akhir: salin ke MODEL-CARD.
Keluaran mentah (tidak dinormalisasi); `--l2-normalize` menanamkan normalisasi di graf. Pra-proses
yang benar ada di `reid_common.py` (BGR→RGB, resize 256x128, /255, mean/std ImageNet) dan
tercatat di metadata ONNX; worker embedding engine harus identik.

### Pembanding eksternal (bukan untuk engine)

Untuk mengukur seberapa jauh model sintetis dari model nyata, ekspor checkpoint torchreid eksternal,
mis. `osnet_ain_x1_0` MSMT17 dari <https://huggingface.co/kaiyangzhou/osnet>. Unduh berkas `.pth`-nya
lewat browser (nama berkas di sana berbeda-beda; pakai yang sesuai arsitekturnya), lalu:

```powershell
python export_onnx.py --checkpoint D:\ext\osnet_ain_x1_0_msmt17.pth --arch osnet_ain_x1_0 --out D:\onnx\PEMBANDING-msmt17.onnx
```

Berkas bernama `PEMBANDING-*` **hanya untuk evaluasi**; bobot MSMT17 berlisensi/dataset berbeda dan
tidak boleh masuk engine atau repo. Bila muncul galat pickle, berkas memuat objek non-tensor:
`--allow-pickle` hanya bila sumbernya tepercaya.

## 9. Evaluasi pada crop berlabel tim

Struktur: `<folder>\<orang>\<kamera>_*.jpg` (satu folder per orang; kamera = teks sebelum `_` pertama
pada nama berkas, mis. `lobby_0012.jpg`).

```powershell
python eval_reid.py --data D:\crop_tim --onnx D:\onnx\osnet_ain_rp_imagenet.onnx D:\onnx\osnet_ain_rp_scratch.onnx D:\onnx\PEMBANDING-msmt17.onnx --csv-out D:\onnx\kurva.csv
```

Per model: mAP, rank-1, rank-5 (protokol lintas-kamera: galeri membuang orang sama di kamera sama),
tabel ambang kosinus (% sambungan benar vs % salah gabung), dan **ambang rekomendasi** = ambang
terkecil dengan salah gabung ≤ 1% (`--max-salah-gabung`). Salah gabung utama dihitung pada pasangan
beda-orang-beda-kamera (skenario gabung lintas kamera); kolom tambahan memuat semua pasangan
beda-orang. Dengan beberapa model, ada tabel perbandingan di akhir. Jumlah pasangan dicetak;
bila data tim sedikit (puluhan orang), 1% hanyalah beberapa pasangan, jadi perlakukan ambang
sebagai perkiraan kasar dan ulangi saat crop bertambah. Pakai `--cpu` untuk memaksa CPU.

## 10. Kartu model

Untuk setiap ONNX yang akan dipertimbangkan, salin `MODEL-CARD.md`, isi, dan simpan di samping
berkas ONNX (bukan di repo bila memuat jalur lokal; kartu yang sudah diisi boleh masuk `docs/`).

## Tes

```powershell
python -m pytest tests -q
```

Ujung-ke-ujung di CPU dengan 40 gambar palsu (prepare → latih 1 epoch → ekspor → eval). Dilewati
otomatis bila torch/torchreid/onnx belum terpasang. Dari root repo:
`python -m pytest tools/reid_train/tests -q`. Tes ini tidak masuk `testpaths` di `pytest.ini`
agar tes engine/backend tidak ikut menunggu torch.
