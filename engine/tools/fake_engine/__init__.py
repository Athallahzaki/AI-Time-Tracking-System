"""Engine palsu: memancarkan protokol dari skenario tertulis.

Tanpa kamera, tanpa GPU, tanpa model. Ia alat pembuka blokir utama — begitu
ada, backend dan frontend jalan penuh kecepatan tanpa menunggu engine
sungguhan.

Dan ia memberi sesuatu yang engine sungguhan tidak bisa: **skenario patologis
sesuai permintaan.** Kamera mati di tengah sesi, identitas tertukar, backend
reconnect minta replay. Di hardware asli kalian menunggu kebetulan; di sini
tinggal menulis file.
"""

from .emitter import Emitter
from .expected import build_expected
from .scenario import Scenario, ScenarioError, from_mapping, load
from .server import FakeEngineServer, Outbox

__all__ = [
    "Emitter",
    "FakeEngineServer",
    "Outbox",
    "Scenario",
    "ScenarioError",
    "build_expected",
    "from_mapping",
    "load",
]
