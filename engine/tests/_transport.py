"""Alamat uji untuk server engine: unix socket bila ada, TCP lokal bila tidak.

Python di Windows tidak punya `socket.AF_UNIX`, padahal engine di Windows
memang berjalan lewat TCP. Tes protokol (jabat tangan, replay, auth, batas
kirim) tidak bergantung pada jenis soket, jadi di Windows mereka diuji lewat
TCP 127.0.0.1 port acak, bukan dilewati.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Tuple, Union

# ENGINE_TEST_TCP=1 memaksa jalur Windows (TCP) di Linux, untuk mengujinya.
HAS_UNIX = hasattr(socket, "AF_UNIX") and os.environ.get("ENGINE_TEST_TCP") != "1"
Address = Union[str, Tuple[str, int]]


def listen(api: Any, tmp: str, name: str = "engine.sock") -> Address:
    """Panggil api.listen() dan kembalikan alamat untuk connect()."""
    if HAS_UNIX:
        path = str(Path(tmp) / name)
        api.listen(socket_path=path)
        return path
    api.listen(tcp=("127.0.0.1", 0))
    return api._server.getsockname()[:2]


def server_kwargs(tmp: str, name: str = "fake.sock") -> dict:
    """Argumen alamat untuk FakeEngineServer."""
    if HAS_UNIX:
        return {"socket_path": str(Path(tmp) / name)}
    return {"tcp": ("127.0.0.1", 0)}


def bound_address(server: Any, kwargs: dict) -> Address:
    """Alamat FakeEngineServer setelah serve_forever() mengikat soketnya."""
    if "socket_path" in kwargs:
        return kwargs["socket_path"]
    return server._server.getsockname()[:2]


def connect(address: Address, timeout: float = 3.0) -> socket.socket:
    family = socket.AF_UNIX if isinstance(address, str) else socket.AF_INET
    connection = socket.socket(family, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    connection.connect(address)
    return connection
