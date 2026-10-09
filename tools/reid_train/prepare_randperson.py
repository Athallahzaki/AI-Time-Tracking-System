"""Siapkan subset RandPerson untuk pelatihan: resize 256x128, split per identitas, manifest.

Masukan : folder subset RandPerson (nama berkas <pid>_s<scene>_c<cam>_f<frame>.jpg,
          boleh di sub-folder).
Keluaran: <out>/images/<pid>/<nama>.jpg (JPG kualitas 95), <out>/manifest.csv,
          <out>/summary.json.

Split berdasarkan IDENTITAS (bukan gambar): ±90% id → train, ±10% id → val.
Di val, untuk setiap (pid, kamera) yang punya >=2 gambar, satu gambar acak jadi
query, sisanya gallery. (pid, kamera) yang hanya punya 1 gambar masuk gallery
saja, supaya tidak ada query tanpa pasangan di kamera lain.
camid = indeks gabungan (scene, kamera) → unik per kamera fisik.

Tidak butuh torch. Contoh:
  python prepare_randperson.py --src D:\\data\\randperson_subset --out D:\\data\\rp256
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

from reid_common import (EKSTENSI_GAMBAR, LEBAR, TINGGI, baca_bgr, simpan_jpg,
                         ubah_ukuran)

POLA_NAMA = re.compile(r"^(\d+)_s(\d+)_c(\d+)_f(\d+)\.(?:jpe?g|png)$", re.IGNORECASE)


def pindai(src: Path):
    """Kembalikan (daftar rekaman, jumlah nama tak cocok, jumlah duplikat)."""
    rekaman, tak_cocok, duplikat = [], 0, 0
    terlihat: set[str] = set()
    for akar, _dirs, berkas in os.walk(src):
        for nama in sorted(berkas):
            if not nama.lower().endswith(EKSTENSI_GAMBAR):
                continue
            m = POLA_NAMA.match(nama)
            if not m:
                tak_cocok += 1
                continue
            if nama in terlihat:
                duplikat += 1
                continue
            terlihat.add(nama)
            pid, scene, cam, frame = (int(g) for g in m.groups())
            rekaman.append({"src": os.path.join(akar, nama), "nama": nama,
                            "pid": pid, "scene": scene, "cam": cam})
    rekaman.sort(key=lambda r: r["nama"])
    return rekaman, tak_cocok, duplikat


def _proses(args):
    src, dst, tinggi, lebar, kualitas, timpa = args
    try:
        if not timpa and os.path.exists(dst):
            return True
        img = baca_bgr(src)
        if img is None:
            return False
        simpan_jpg(dst, ubah_ukuran(img, tinggi, lebar), kualitas)
        return True
    except Exception:  # satu gambar rusak tidak boleh menghentikan 132 ribu lainnya
        return False


def bagi_split(rekaman: list[dict], val_fraction: float, seed: int):
    """Tambahkan kunci 'split' (train|query|gallery) pada tiap rekaman."""
    rng = random.Random(seed)
    pids = sorted({r["pid"] for r in rekaman})
    if len(pids) < 2:
        raise SystemExit("Butuh minimal 2 identitas untuk membagi train/val.")
    acak = pids[:]
    rng.shuffle(acak)
    n_val = min(len(pids) - 1, max(1, round(val_fraction * len(pids))))
    val = set(acak[:n_val])

    per_grup: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rekaman:
        if r["pid"] in val:
            per_grup[(r["pid"], r["camid"])].append(r)
        else:
            r["split"] = "train"
    for kunci in sorted(per_grup):
        grup = per_grup[kunci]
        for r in grup:
            r["split"] = "gallery"
        if len(grup) >= 2:
            rng.choice(grup)["split"] = "query"
    return val


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="folder subset RandPerson")
    ap.add_argument("--out", required=True, help="folder keluaran")
    ap.add_argument("--tinggi", type=int, default=TINGGI)
    ap.add_argument("--lebar", type=int, default=LEBAR)
    ap.add_argument("--kualitas", type=int, default=95, help="kualitas JPG (default 95)")
    ap.add_argument("--val-fraction", type=float, default=0.10,
                    help="porsi IDENTITAS untuk val (default 0.10)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--overwrite", action="store_true",
                    help="tulis ulang gambar yang sudah ada (default: lewati, jadi bisa dilanjutkan)")
    a = ap.parse_args(argv)

    src, out = Path(a.src), Path(a.out)
    if not src.is_dir():
        print(f"Folder sumber tidak ada: {src}", file=sys.stderr)
        return 2
    if not 0.0 < a.val_fraction < 1.0:
        print("--val-fraction harus di antara 0 dan 1.", file=sys.stderr)
        return 2

    print(f"Memindai {src} ...")
    rekaman, tak_cocok, duplikat = pindai(src)
    if not rekaman:
        print("Tidak ada gambar dengan pola <pid>_s<scene>_c<cam>_f<frame>.jpg.", file=sys.stderr)
        return 2
    print(f"  {len(rekaman)} gambar cocok, {tak_cocok} nama tak cocok, {duplikat} duplikat nama (dilewati)")

    kamera = sorted({(r["scene"], r["cam"]) for r in rekaman})
    peta_cam = {k: i for i, k in enumerate(kamera)}
    for r in rekaman:
        r["camid"] = peta_cam[(r["scene"], r["cam"])]
        r["rel"] = f"images/{r['pid']}/{r['nama'].rsplit('.', 1)[0]}.jpg"

    print(f"Resize {a.tinggi}x{a.lebar}, JPG q{a.kualitas}, {a.workers} proses ...")
    tugas = [(r["src"], str(out / r["rel"]), a.tinggi, a.lebar, a.kualitas, a.overwrite)
             for r in rekaman]
    if a.workers > 1:
        with Pool(a.workers) as pool:
            hasil = []
            for i, ok in enumerate(pool.imap(_proses, tugas, chunksize=64), 1):
                hasil.append(ok)
                if i % 10000 == 0:
                    print(f"  {i}/{len(tugas)}")
    else:
        hasil = [_proses(t) for t in tugas]
    gagal = sum(1 for ok in hasil if not ok)
    rekaman = [r for r, ok in zip(rekaman, hasil) if ok]
    if gagal:
        print(f"  PERINGATAN: {gagal} gambar gagal dibaca/ditulis dan dikeluarkan dari manifest")
    if not rekaman:
        print("Tidak ada gambar yang berhasil diproses.", file=sys.stderr)
        return 2

    val = bagi_split(rekaman, a.val_fraction, a.seed)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "pid", "camid", "split"])
        for r in sorted(rekaman, key=lambda r: (r["split"], r["pid"], r["rel"])):
            w.writerow([r["rel"], r["pid"], r["camid"], r["split"]])

    ringkas = {}
    for s in ("train", "query", "gallery"):
        sub = [r for r in rekaman if r["split"] == s]
        ringkas[s] = {"id": len({r["pid"] for r in sub}), "gambar": len(sub),
                      "kamera": len({r["camid"] for r in sub})}
    ringkas_json = {
        "ringkasan": ringkas,
        "id_val": len(val),
        "id_total": len({r["pid"] for r in rekaman}),
        "kamera_total": len({r["camid"] for r in rekaman}),
        "peta_camid": {str(i): {"scene": s, "cam": c} for (s, c), i in peta_cam.items()},
        "argumen": {"tinggi": a.tinggi, "lebar": a.lebar, "kualitas": a.kualitas,
                    "val_fraction": a.val_fraction, "seed": a.seed},
        "nama_tak_cocok": tak_cocok, "duplikat": duplikat, "gagal": gagal,
    }
    (out / "summary.json").write_text(json.dumps(ringkas_json, indent=2), encoding="utf-8")

    print("\nRingkasan (split berdasarkan identitas):")
    print(f"  {'split':8} {'id':>7} {'gambar':>9} {'kamera':>7}")
    for s, v in ringkas.items():
        print(f"  {s:8} {v['id']:>7} {v['gambar']:>9} {v['kamera']:>7}")
    print(f"  total id {ringkas_json['id_total']}, kamera fisik {ringkas_json['kamera_total']}")
    print(f"Manifest: {out / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
