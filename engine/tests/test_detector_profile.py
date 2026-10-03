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


def _profil_4060(**extra):
    """Angka asli uji RTX 4060, 3 Okt 18:02."""
    values = dict(param_device="cuda:0", prepare_ms=2.8, call_ms=70.5, call_cpu_ms=69.9,
                  forward_fp32_ms=56.6, forward_fp16_ms=63.5, gpu_busy_ms=29.7, launches_per_forward=992,
                  gpu={"sm_mhz_median": 1485, "sm_max_mhz": 3105, "pstates": ["P0", "P4"], "util_pct_median": 23})
    values.update(extra)
    return Profile(**values)


def test_4060_terikat_peluncuran_kernel_bukan_gpu():
    text = " ".join(_profil_4060().verdicts())
    assert "TERIKAT CPU" in text and "29.7 ms dari forward 56.6 ms" in text and "992 kernel" in text
    assert "AKIBAT GPU menganggur" in text, "clock rendah di sini akibat, bukan sebab"
    assert "PENGHAMBAT DI GPU" not in text and "GPU TIDAK NAIK CLOCK" not in text
    assert "0.89x" in text and "op cast" in text


def test_tanpa_profiler_pakai_utilisasi():
    assert _profil_4060(gpu_busy_ms=None).launch_bound is True


def test_batch_dan_cuda_graph_dilaporkan():
    text = " ".join(_profil_4060(batch_forward_ms_per_image=14.0, cuda_graph_ms=18.0).verdicts())
    assert "satu per satu" in text and "CUDA graph: 18.0 ms (3.14x" in text
    text = " ".join(_profil_4060(cuda_graph_error="RuntimeError: x").verdicts())
    assert "gagal direkam" in text


def test_vonis_gpu_dan_clock_rendah():
    p = Profile(param_device="cuda:0", prepare_ms=3, call_ms=81, call_cpu_ms=10, forward_fp32_ms=75,
                gpu_busy_ms=70, gpu={"sm_mhz_median": 600, "sm_max_mhz": 2370, "pstates": ["P5"],
                                     "util_pct_median": 97})
    text = " ".join(p.verdicts())
    assert "PENGHAMBAT DI GPU" in text and "TIDAK NAIK CLOCK" in text


def test_jumlah_kernel_dan_waktu_sibuk_dari_profiler():
    from types import SimpleNamespace as E

    from engine.tools.detector_profile import gpu_busy

    events = [E(key="aten::cudnn_convolution", count=1120, self_device_time_total=147050.0),
              E(key="aten::addmm", count=710, self_device_time_total=32073.0),
              E(key="cudaLaunchKernel", count=9920, self_device_time_total=0.0),
              E(key="cuLaunchKernel", count=740, self_cuda_time_total=0.0)]
    busy, launches = gpu_busy(events, 10)
    assert busy == 17.9123 and launches == 1066


def test_model_di_cpu_langsung_ketahuan():
    p = Profile(param_device="cpu", call_ms=84)
    assert "BUKAN GPU" in p.verdicts()[0]
