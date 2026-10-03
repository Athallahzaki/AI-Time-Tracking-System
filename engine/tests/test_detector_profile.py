"""engine/tools/detector_profile.py: memisahkan waktu GPU dari waktu CPU."""

from __future__ import annotations

from engine.tools.detector_profile import (GpuSampler, Profile, find_torch_module, parse_smi_line,
                                           summarize_samples)


class Module:            # pengganti torch.nn.Module
    pass


class Net(Module):
    pass


class Inner:
    def __init__(self):
        self.config = {"a": 1}
        self.network = Net()


class Wrapper:           # bentuk pembungkus LibreYOLO: modul tersembunyi dua tingkat
    names = {0: "person"}

    def __init__(self):
        self.model = Inner()

    def __call__(self, *a, **k):
        return None


def test_modul_torch_ditemukan_di_dalam_pembungkus():
    path, module = find_torch_module(Wrapper(), Module)
    assert path == "model.network" and isinstance(module, Net)


def test_tidak_ada_modul():
    assert find_torch_module(object(), Module) == ("", None)


def test_parse_nvidia_smi():
    sample = parse_smi_line("P8, 210, 2370, 9.85, 115.00, 52, 3")
    assert sample.pstate == "P8" and sample.sm_mhz == 210 and sample.sm_max_mhz == 2370
    assert parse_smi_line("rusak") is None


def test_sampler_dengan_runner_tiruan():
    lines = iter(["P0, 2100, 2370, 80, 115, 70, 95"] * 3 + ["P8, 300, 2370, 10, 115, 60, 5"] * 50)
    with GpuSampler(interval=0.001, runner=lambda: next(lines)) as sampler:
        import time
        time.sleep(0.05)
    summary = summarize_samples(sampler.samples)
    assert "P8" in summary["pstates"] and summary["sm_max_mhz"] == 2370


def test_vonis_cpu_bila_forward_kecil():
    """Bentuk yang dicurigai di 4060: forward 15 ms dari 84 ms."""
    p = Profile(param_device="cuda:0", prepare_ms=3, call_ms=81, call_cpu_ms=95,
                forward_fp32_ms=18, forward_fp16_ms=12)
    text = " ".join(p.verdicts())
    assert "PENGHAMBAT DI CPU" in text and "1.50x" in text


def test_vonis_gpu_dan_clock_rendah():
    p = Profile(param_device="cuda:0", prepare_ms=3, call_ms=81, call_cpu_ms=10, forward_fp32_ms=75,
                gpu={"sm_mhz_median": 600, "sm_max_mhz": 2370, "pstates": ["P5"]})
    text = " ".join(p.verdicts())
    assert "PENGHAMBAT DI GPU" in text and "TIDAK NAIK CLOCK" in text


def test_model_di_cpu_langsung_ketahuan():
    p = Profile(param_device="cpu", call_ms=84)
    assert "BUKAN GPU" in p.verdicts()[0]
