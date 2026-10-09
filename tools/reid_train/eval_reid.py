"""Evaluasi satu atau lebih model ReID (ONNX) pada crop BERLABEL milik tim.

Struktur folder:  <folder>/<orang>/<kamera>_*.jpg
  - <orang>  = nama sub-folder (satu orang satu folder)
  - <kamera> = bagian nama berkas sebelum garis bawah pertama (mis. lobby_0012.jpg)

Keluaran per model:
  - mAP dan rank-1/rank-5. Setiap gambar jadi query; galeri = semua gambar lain,
    kecuali yang orang SAMA dan kamera SAMA dengan query (protokol lintas-kamera).
  - Kurva ambang kemiripan kosinus: untuk setiap ambang, persen pasangan
    (a) orang-sama-kamera-beda yang lolos (sambungan benar) dan
    (b) orang-beda yang lolos (SALAH GABUNG). Kolom utama (b) memakai pasangan
    beda-orang-beda-kamera, yakni skenario gabung lintas kamera; kolom
    tambahan memakai semua pasangan beda-orang.
  - Ambang rekomendasi: ambang terkecil dengan salah gabung <= --max-salah-gabung (1%).

Contoh:
  python eval_reid.py --data D:\\crop_tim --onnx a.onnx b.onnx --csv-out kurva.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

from reid_common import EKSTENSI_GAMBAR, baca_bgr, l2_normalisasi, muat_batch, sha256_berkas, ubah_ukuran


def muat_folder(folder: Path):
    """Kembalikan (gambar uint8 Nx256x128x3 BGR, orang[N], kamera[N], jumlah dilewati)."""
    imgs, orang, kamera, lewat = [], [], [], 0
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        for f in sorted(sub.iterdir()):
            if f.suffix.lower() not in EKSTENSI_GAMBAR:
                continue
            if "_" not in f.stem:
                lewat += 1
                continue
            img = baca_bgr(f)
            if img is None:
                lewat += 1
                continue
            imgs.append(ubah_ukuran(img))
            orang.append(sub.name)
            kamera.append(f.stem.split("_", 1)[0])
    return imgs, np.array(orang), np.array(kamera), lewat


def embed_onnx(path: str, imgs: list[np.ndarray], batch: int, cpu: bool) -> np.ndarray:
    import onnxruntime as ort
    prov = ["CPUExecutionProvider"]
    if not cpu and "CUDAExecutionProvider" in ort.get_available_providers():
        prov.insert(0, "CUDAExecutionProvider")
    sess = ort.InferenceSession(path, providers=prov)
    nama = sess.get_inputs()[0].name
    hasil = []
    for i in range(0, len(imgs), batch):
        hasil.append(sess.run(None, {nama: muat_batch(imgs[i:i + batch])})[0])
    return l2_normalisasi(np.concatenate(hasil).reshape(len(imgs), -1))


def metrik_peringkat(sim: np.ndarray, orang: np.ndarray, kamera: np.ndarray) -> dict:
    n = len(orang)
    ap_list, r1, r5 = [], [], []
    for i in range(n):
        valid = ~((orang == orang[i]) & (kamera == kamera[i]))
        cocok = (orang == orang[i]) & valid
        if not cocok.any():
            continue
        urut = np.argsort(-sim[i][valid], kind="stable")
        hit = cocok[valid][urut].astype(np.float32)
        kumul = np.cumsum(hit)
        presisi = kumul / (np.arange(len(hit)) + 1)
        ap_list.append(float((presisi * hit).sum() / hit.sum()))
        r1.append(float(hit[0]))
        r5.append(float(hit[:5].any()))
    if not ap_list:
        return {"mAP": float("nan"), "rank1": float("nan"), "rank5": float("nan"), "n_query": 0}
    return {"mAP": float(np.mean(ap_list)), "rank1": float(np.mean(r1)),
            "rank5": float(np.mean(r5)), "n_query": len(ap_list)}


def kurva_ambang(sim: np.ndarray, orang: np.ndarray, kamera: np.ndarray, ambang: np.ndarray):
    n = len(orang)
    iu = np.triu_indices(n, k=1)
    s = sim[iu]
    sama_o = orang[iu[0]] == orang[iu[1]]
    sama_k = kamera[iu[0]] == kamera[iu[1]]
    pos = np.sort(s[sama_o & ~sama_k])
    neg_lintas = np.sort(s[~sama_o & ~sama_k])
    neg_semua = np.sort(s[~sama_o])

    def persen_lolos(arr):
        if len(arr) == 0:
            return np.full(len(ambang), np.nan)
        return 100.0 * (len(arr) - np.searchsorted(arr, ambang, side="left")) / len(arr)

    return {"tpr": persen_lolos(pos), "fpr_lintas": persen_lolos(neg_lintas),
            "fpr_semua": persen_lolos(neg_semua),
            "n_pos": len(pos), "n_neg_lintas": len(neg_lintas), "n_neg_semua": len(neg_semua)}


def rekomendasi(ambang, fpr, maks_persen):
    ok = np.where(fpr <= maks_persen)[0]
    return float(ambang[ok[0]]) if len(ok) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="folder crop berlabel <orang>/<kamera>_*.jpg")
    ap.add_argument("--onnx", required=True, nargs="+", help="satu atau lebih berkas ONNX")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--cpu", action="store_true", help="paksa CPU walau CUDA tersedia")
    ap.add_argument("--max-salah-gabung", type=float, default=1.0,
                    help="batas salah gabung dalam persen untuk rekomendasi (default 1)")
    ap.add_argument("--langkah", type=float, default=0.01, help="langkah ambang (default 0.01)")
    ap.add_argument("--csv-out", default=None, help="tulis kurva lengkap semua model ke CSV")
    a = ap.parse_args(argv)

    folder = Path(a.data)
    if not folder.is_dir():
        print(f"Folder tidak ada: {folder}", file=sys.stderr)
        return 2
    imgs, orang, kamera, lewat = muat_folder(folder)
    if lewat:
        print(f"PERINGATAN: {lewat} berkas dilewati (nama tanpa '_' atau tak terbaca)")
    n_orang, n_kam = len(set(orang)), len(set(kamera))
    print(f"Data: {len(imgs)} gambar, {n_orang} orang, {n_kam} kamera ({sorted(map(str, set(kamera)))})")
    if n_orang < 2 or n_kam < 2:
        print("Butuh minimal 2 orang dan 2 kamera.", file=sys.stderr)
        return 2

    ambang = np.round(np.arange(0.0, 1.0 + 1e-9, a.langkah), 6)
    baris_csv, ringkas = [], []
    for path in a.onnx:
        nama = Path(path).name
        print(f"\n=== {nama}  (SHA-256 {sha256_berkas(path)[:16]}…) ===")
        emb = embed_onnx(path, imgs, a.batch, a.cpu)
        sim = emb @ emb.T
        m = metrik_peringkat(sim, orang, kamera)
        k = kurva_ambang(sim, orang, kamera, ambang)
        rek = rekomendasi(ambang, k["fpr_lintas"], a.max_salah_gabung)
        print(f"mAP {m['mAP']:.4f} | rank-1 {m['rank1']:.4f} | rank-5 {m['rank5']:.4f} "
              f"(query berpasangan: {m['n_query']})")
        print(f"Pasangan: sama-orang-beda-kamera {k['n_pos']}, beda-orang-beda-kamera "
              f"{k['n_neg_lintas']}, beda-orang (semua) {k['n_neg_semua']}")
        print(f"{'ambang':>7} {'sambungan benar %':>18} {'salah gabung %':>15} {'(semua kamera) %':>17}")
        for i, t in enumerate(ambang):
            baris_csv.append([nama, f"{t:.3f}", f"{k['tpr'][i]:.4f}", f"{k['fpr_lintas'][i]:.4f}",
                              f"{k['fpr_semua'][i]:.4f}"])
            if abs(t * 20 - round(t * 20)) < 1e-6 and 0.3 <= t <= 0.95:  # tampilkan tiap 0,05
                print(f"{t:7.2f} {k['tpr'][i]:18.2f} {k['fpr_lintas'][i]:15.3f} {k['fpr_semua'][i]:17.3f}")
        if rek is None:
            print(f"Rekomendasi: TIDAK ADA ambang dengan salah gabung <= {a.max_salah_gabung}% "
                  "(model terlalu lemah untuk data ini).")
            tpr_rek = float("nan")
        else:
            i = int(np.argmin(np.abs(ambang - rek)))
            tpr_rek = float(k["tpr"][i])
            print(f"Rekomendasi: ambang {rek:.2f} → salah gabung {k['fpr_lintas'][i]:.3f}% "
                  f"(semua kamera {k['fpr_semua'][i]:.3f}%), sambungan benar {tpr_rek:.1f}%")
        ringkas.append((nama, m, rek, tpr_rek))

    if len(ringkas) > 1:
        print("\n=== Perbandingan ===")
        print(f"{'model':40} {'mAP':>7} {'rank-1':>7} {'ambang rek.':>12} {'sambungan benar %':>18}")
        for nama, m, rek, tpr in ringkas:
            rs = f"{rek:.2f}" if rek is not None else "-"
            print(f"{nama[:40]:40} {m['mAP']:7.4f} {m['rank1']:7.4f} {rs:>12} {tpr:18.1f}")
    if a.csv_out:
        with open(a.csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["model", "ambang", "sambungan_benar_persen", "salah_gabung_lintas_persen",
                        "salah_gabung_semua_persen"])
            w.writerows(baris_csv)
        print(f"\nKurva ditulis ke {a.csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
