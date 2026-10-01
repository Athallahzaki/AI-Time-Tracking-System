"""Autentikasi handshake engine <-> backend (fase 1, P3/E3). Satu-satunya tempat
pesan kanonik HMAC disusun.

Kenapa di `contracts/`: engine dan backend wajib menghitung byte yang SAMA.
Kalau masing-masing menulis ulang format pesannya, perbedaan satu karakter
(spasi, urutan field, `\\n` vs `\\r\\n` di Windows) membuat semua handshake
gagal -- atau lebih buruk, satu sisi diam-diam melonggarkan pemeriksaan supaya
"jalan". `contracts/` adalah satu-satunya kode yang boleh diimpor kedua sisi.

Alur bila autentikasi aktif:

1. engine  -> backend  `auth_challenge {nonce, algorithm: "hmac-sha256"}`
2. backend -> engine   `hello {..., auth: {client_nonce, mac: hello_mac(...)}}`
3. engine memverifikasi; gagal = `ack {accepted: false, reason: "auth_failed"}`
   lalu koneksi ditutup. Berhasil = `hello_ack {..., auth: {mac: hello_ack_mac(...)}}`
4. backend memverifikasi `hello_ack.auth.mac`; gagal = putus (engine palsu).

Yang dilindungi: klien liar di LAN tidak bisa handshake, sehingga tidak bisa
membaca event, menendang backend sah, atau memangkas outbox dengan ACK palsu
(E3). Yang TIDAK dilindungi: kerahasiaan dan integritas aliran setelah
handshake. Untuk itu jaringan privat (VLAN/WireGuard) atau TLS; lihat dokumen 05 §7.

Kunci: string acak panjang di `.env` kedua mesin, dipakai sebagai byte UTF-8
apa adanya. Buat dengan::

    python -c "import secrets; print(secrets.token_hex(32))"
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Union

ALGORITHM = "hmac-sha256"
# Pemisah domain: MAC untuk protokol/versi lain tidak pernah sah di sini.
_LABEL = "ai-time-tracking/engine-protocol/v1"
MIN_KEY_BYTES = 16

KeyLike = Union[str, bytes]


def _key_bytes(key: KeyLike) -> bytes:
    data = key.encode("utf-8") if isinstance(key, str) else bytes(key)
    if len(data) < MIN_KEY_BYTES:
        raise ValueError(
            f"kunci bersama terlalu pendek ({len(data)} byte, minimal {MIN_KEY_BYTES}); "
            "buat dengan secrets.token_hex(32)"
        )
    return data


def _check_nonce(name: str, value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} wajib 64 karakter hex huruf kecil")
    return value


def new_nonce() -> str:
    """32 byte acak kriptografis, hex huruf kecil (cocok dengan $defs/hex256)."""
    return secrets.token_hex(32)


def _mac(key: KeyLike, *parts: str) -> str:
    message = "\n".join((_LABEL,) + parts).encode("utf-8")
    return hmac.new(_key_bytes(key), message, hashlib.sha256).hexdigest()


def hello_mac(key: KeyLike, server_nonce: str, client_nonce: str, client: str, last_event_seq: int) -> str:
    """MAC yang dibawa `hello.auth.mac`. `client` dan `last_event_seq` ikut diikat
    supaya nilai di hello tidak bisa diganti tanpa membatalkan MAC."""
    return _mac(
        key, "hello",
        _check_nonce("server_nonce", server_nonce),
        _check_nonce("client_nonce", client_nonce),
        str(client), str(int(last_event_seq)),
    )


def hello_ack_mac(key: KeyLike, server_nonce: str, client_nonce: str) -> str:
    """MAC yang dibawa `hello_ack.auth.mac`. Label berbeda dari hello, jadi MAC
    backend tidak bisa dipantulkan balik sebagai bukti engine."""
    return _mac(
        key, "hello_ack",
        _check_nonce("server_nonce", server_nonce),
        _check_nonce("client_nonce", client_nonce),
    )


def verify(expected: str, received: object) -> bool:
    """Perbandingan waktu-konstan. Apa pun yang bukan string dianggap gagal."""
    if not isinstance(received, str):
        return False
    return hmac.compare_digest(expected.encode("ascii"), received.encode("ascii", "replace"))
