# Dokumen Acuan

| Dokumen | Isi |
| --- | --- |
| `CHANGELOG.md` | Semua perubahan per paket, terbaru di atas. Catatan perubahan baru ditulis di sini, bukan file baru di root |
| `ARCHITECTURE.md` | Batas tanggung jawab engine, backend, frontend |
| `ENGINE_PROTOCOL.md` | Kontrak komunikasi TCP NDJSON |
| `PROJECT_STRUCTURE.md` | Struktur folder yang dituju |
| `WORKPLAN.md` | Urutan implementasi dan milestone awal |
| `SETUP-GPU.md` | Requirements per GPU dan pemeriksaan environment |
| `DEMO-1060.md` | Profil demo GTX 1060 |
| `DEMO-REMOTE.md` | Deploy terpisah lewat NetBird + Portainer; uji A/B 4060 |
| `UJI-LAG.md` | Cara mengukur lag kamera dan umur kotak |
| `arsip/` | Catatan lama, disimpan apa adanya; jangan diedit |

Bila dokumen acuan dan implementasi berbeda, jangan memindahkan kebijakan bisnis
ke engine dan jangan membuat import langsung antara engine dan backend.

Catatan: `ARCHITECTURE.md` §5.4 ("jangan bangun ReID dulu") sudah tidak berlaku;
ReID masuk prototype per kesepakatan 8 Oktober 2026 (dokumen 12 §3.6).
