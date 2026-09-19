"""CLI `fake_engine`.

    # layani backend lewat unix socket
    python -m engine.tools.fake_engine --scenario berbalik-lama --socket /tmp/engine.sock

    # lihat alirannya begitu saja
    python -m engine.tools.fake_engine --scenario berbalik-lama --stdout | head

    # rekam fixture yang di-commit
    python -m engine.tools.fake_engine --all --record contracts/fixtures

`--speed 10` mempercepat waktu skenario: yang 30 menit selesai dalam 3 menit.
Hanya berpengaruh di mode socket; perekaman tidak menunggu apa pun.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import scenario as scenario_module
from .emitter import Emitter
from .expected import build_expected
from .server import FakeEngineServer

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


def _resolve(name: str) -> Path:
    """Terima path, nama berkas, atau nama logis skenario.

    Berkasnya berprefiks nomor (`02-berbalik-lama.yaml`) supaya urutan bacanya
    jelas, tapi tidak seorang pun akan mengetik nomornya. `--scenario
    berbalik-lama` harus bekerja.
    """
    candidate = Path(name)
    if candidate.exists():
        return candidate

    for suffix in (".yaml", ".yml"):
        candidate = SCENARIO_DIR / f"{name}{suffix}"
        if candidate.exists():
            return candidate

    matches = sorted(SCENARIO_DIR.glob(f"*-{name}.yaml"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(f"`{name}` cocok dengan beberapa berkas: {[m.name for m in matches]}")

    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        if scenario_module.load(path).name == name:
            return path

    available = ", ".join(sorted(scenario_module.load(p).name for p in SCENARIO_DIR.glob("*.yaml")))
    raise SystemExit(f"skenario `{name}` tidak ada. Yang ada: {available}")


def _parse_chaos(raw: Optional[str]) -> Dict[str, float]:
    if not raw:
        return {}
    chaos: Dict[str, float] = {}
    for part in raw.split(","):
        if "=" not in part:
            raise SystemExit(f"--chaos butuh bentuk kunci=nilai, dapat `{part}`")
        key, value = part.split("=", 1)
        chaos[key.strip()] = float(value)
    return chaos


def _record(name: str, messages, expected, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    by_channel: Dict[str, List[dict]] = {}

    for channel, payload in messages:
        if channel == "_harness":
            continue
        by_channel.setdefault(channel, []).append(payload)

    for channel, payloads in sorted(by_channel.items()):
        path = out_dir / f"{name}.{channel}.ndjson"
        path.write_text(
            "\n".join(json.dumps(p, ensure_ascii=False) for p in payloads) + "\n",
            encoding="utf-8",
        )
        written.append(path)

    path = out_dir / f"{name}.expected.json"
    path.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fake_engine", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", help="nama atau path berkas skenario")
    parser.add_argument("--all", action="store_true", help="semua skenario bawaan (untuk --record)")
    parser.add_argument("--socket", help="path unix socket")
    parser.add_argument("--tcp", help="host:port")
    parser.add_argument("--stdout", action="store_true", help="cetak NDJSON ke stdout lalu selesai")
    parser.add_argument("--record", type=Path, help="tulis fixture ke direktori ini")
    parser.add_argument("--channel", choices=["control", "events", "view"],
                        help="batasi keluaran --stdout ke satu kanal")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--view-fps", type=float, default=None,
                        help="timpa view_fps skenario; 0 mematikan kanal view")
    parser.add_argument("--chaos", help="mis. drop_view=0.3")
    parser.add_argument("--list", action="store_true", help="daftar skenario bawaan")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.list:
        for path in sorted(SCENARIO_DIR.glob("*.yaml")):
            loaded = scenario_module.load(path)
            print(f"{loaded.name:<22} {loaded.description}")
        return 0

    if args.all:
        if not args.record:
            raise SystemExit("--all hanya berguna bersama --record")
        paths = sorted(SCENARIO_DIR.glob("*.yaml"))
    elif args.scenario:
        paths = [_resolve(args.scenario)]
    else:
        raise SystemExit("butuh --scenario, --all, atau --list")

    for path in paths:
        loaded = scenario_module.load(path)
        view_fps = loaded.view_fps if args.view_fps is None else args.view_fps
        messages = Emitter(loaded, seed=args.seed, view_fps=view_fps).run()
        expected = build_expected(loaded, messages)

        if args.record:
            for written in _record(loaded.name, messages, expected, args.record):
                print(f"tertulis {written}")
            continue

        if args.stdout:
            for channel, payload in messages:
                if channel == "_harness":
                    continue
                if args.channel and channel != args.channel:
                    continue
                print(json.dumps({**payload, "channel": channel}, ensure_ascii=False))
            continue

        tcp = None
        if args.tcp:
            host, _, port = args.tcp.rpartition(":")
            tcp = (host or "127.0.0.1", int(port))

        server = FakeEngineServer(
            messages=messages,
            socket_path=args.socket,
            tcp=tcp,
            speed=args.speed,
            loop=args.loop,
            seed=args.seed,
            chaos=_parse_chaos(args.chaos),
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
