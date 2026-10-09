"""
Engine configuration as data.

Two rules govern this module, both from ARCHITECTURE.md §16.

1. No company rule lives here. The engine may only hold *perceptual*
   constants: how long before a track is considered gone, how much evidence
   before an identity is confirmed, what similarity counts as a match. The
   section of the old configs/default_config.yaml that encoded office rules was
   therefore not ported — it is dead, and its replacement is born in
   backend/policy/. config/loader.py enforces this by accepting only the fields
   declared below, and contracts/tools/policy_grep.py enforces it in CI.

2. Every temporal parameter is expressed in SECONDS and converted to frames at
   construction time using the effective fps. The old code hardcoded
   frame_rate=30 and track_buffer=30 inside ByteTrackTracker; at 10 fps that
   buffer silently changes meaning from 1 second to 3 seconds and the Kalman
   motion model is miscalibrated. Converting the unit is behaviour-preserving
   at 30 fps, which is why it belongs to B0; dropping to 10 fps is a separate,
   measured step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union


def resolve_engine_path(raw_path: Union[str, Path]) -> str:
    """
    Resolves a relative file or directory path within the project.

    Checks, in order: the path as given, relative to the engine root, and
    relative to the workspace root.
    """
    p = Path(raw_path)
    if p.exists():
        return str(p.resolve())

    engine_root = Path(__file__).resolve().parents[1]  # engine/
    candidate = engine_root / p
    if candidate.exists():
        return str(candidate.resolve())

    if str(p).startswith("engine/") or str(p).startswith("engine\\"):
        sub_p = Path(*p.parts[1:])
        candidate = engine_root / sub_p
        if candidate.exists():
            return str(candidate.resolve())

    workspace_root = engine_root.parent
    candidate = workspace_root / p
    if candidate.exists():
        return str(candidate.resolve())

    return str(p)


def seconds_to_frames(seconds: float, fps: float) -> int:
    """
    Converts a temporal constant in seconds to whole frames at a given fps.

    Rounds up and never returns less than 1: a buffer of zero frames means a
    track dies the instant it is occluded, which is never what a duration in
    seconds was meant to express.
    """
    if fps <= 0.0:
        raise ValueError(f"fps must be positive, got {fps}")
    if seconds < 0.0:
        raise ValueError(f"duration must not be negative, got {seconds}")
    return max(1, int(math.ceil(seconds * fps)))


@dataclass(frozen=True)
class TrackerConfig:
    """Perceptual constants for the tracker. Nothing here is a company rule."""

    backend: str = "iou"                # "bytetrack" | "iou"
    track_threshold: float = 0.45
    match_threshold: float = 0.8
    track_buffer_seconds: float = 1.0   # was track_buffer=30 frames at 30 fps

    def track_buffer_frames(self, fps: float) -> int:
        return seconds_to_frames(self.track_buffer_seconds, fps)

    def __post_init__(self) -> None:
        if self.backend not in ("bytetrack", "iou"):
            raise ValueError(
                f"Unknown tracker backend '{self.backend}'. "
                f"Expected 'bytetrack' or 'iou'."
            )


@dataclass(frozen=True)
class IngestConfig:
    """
    How frames get in, and on what timeline (ARCHITECTURE.md §5.5).

    `backend` exists for one step only. B4 replaces OpenCV ingest with PyAV so
    that PTS is real rather than derived from a frame index, and a swap that
    large gets measured rather than asserted: the same recording is benched on
    both and the delta is committed. After that, `opencv` goes away.
    """

    backend: str = "pyav"              # "pyav" | "opencv"
    rtsp_transport: str = "tcp"        # UDP corrupts frames silently (§5.5)
    timeout_seconds: float = 8.0       # a dead camera must not hang a thread
    reconnect_attempts: int = 0        # 0 for files; a live camera wants > 0
    reconnect_backoff_seconds: float = 1.0
    max_reconnect_backoff_seconds: float = 30.0
    measure_timeline_fidelity: bool = True

    # Decoder threading. "AUTO" is frame + slice threading, which is what
    # FFmpeg gives OpenCV by default and what a 1080p HEVC stream needs to keep
    # up. Frame threading buffers a few frames inside the decoder, which costs
    # a little delivery latency on a live camera but changes no timestamp: PTS
    # travels with the frame. "SLICE" avoids that buffering if it ever matters;
    # "NONE" is for proving what single-threaded decode actually costs.
    decoder_thread_type: str = "AUTO"    # "AUTO" | "SLICE" | "FRAME" | "NONE"
    decoder_threads: int = 0             # 0 = one per core

    # How a decoded frame becomes a BGR ndarray. Two routes with identical
    # output, kept switchable only because `probe_ingest` measured PyAV 29%
    # behind OpenCV on the same file and a suspect is worth timing rather than
    # arguing about. Default stays on the one B4 shipped so the committed
    # baseline does not move; the switch happens in its own commit if and when
    # the probe says it is worth something (§16).
    colour_conversion: str = "to_ndarray"   # "to_ndarray" | "reformatter"

    # How a NETWORK stream is read. Files ignore this: a file is a pull source
    # and the pipeline sets its pace.
    #
    # "none"   - the pipeline thread pulls packets itself. Correct only while
    #            the pipeline keeps up with the camera; the moment it falls
    #            behind, the server's send queue fills and MediaMTX starts
    #            discarding packets mid-GOP ("reader is too slow"), which hands
    #            the decoder a broken bitstream.
    # "latest" - a reader thread drains and decodes the stream at camera rate
    #            and keeps only the newest decoded frame. A slow pipeline then
    #            skips whole, intact frames instead of corrupting the stream,
    #            and the skip is counted (describe()["live_reader"]).
    live_buffer: str = "none"          # "none" | "latest"
    # P18: "slew" = koreksi bertahap bias offset jam (hanya aktif dengan
    # live_buffer: latest); "none" = offset tetap seperti dibuka.
    offset_correction: str = "slew"
    # Decode di GPU lewat hwaccel FFmpeg (NVDEC). "none" = decode CPU seperti
    # semula. "cuda" = frame di-decode di GPU lalu disalin balik ke RAM untuk
    # konversi BGR; hemat CPU decode, belum hemat PCIe (lihat pyav_source.py).
    hwaccel: str = "none"

    def __post_init__(self) -> None:
        if self.hwaccel not in ("none", "cuda"):
            raise ValueError("ingest.hwaccel must be 'none' or 'cuda'.")
        if self.offset_correction not in ("slew", "none"):
            raise ValueError("ingest.offset_correction must be 'slew' or 'none'.")
        if self.live_buffer not in ("none", "latest"):
            raise ValueError(
                f"Unknown ingest.live_buffer '{self.live_buffer}'. "
                f"Expected 'none' or 'latest'."
            )
        if self.colour_conversion not in ("to_ndarray", "reformatter"):
            raise ValueError(
                f"Unknown ingest.colour_conversion '{self.colour_conversion}'. "
                f"Expected 'to_ndarray' or 'reformatter'."
            )
        if self.decoder_thread_type not in ("AUTO", "SLICE", "FRAME", "NONE"):
            raise ValueError(
                f"Unknown decoder_thread_type '{self.decoder_thread_type}'. "
                f"Expected AUTO, SLICE, FRAME or NONE."
            )
        if self.backend not in ("pyav", "opencv"):
            raise ValueError(
                f"Unknown ingest backend '{self.backend}'. Expected 'pyav' or "
                f"'opencv'."
            )
        if self.timeout_seconds <= 0:
            raise ValueError("ingest.timeout_seconds must be positive.")


@dataclass(frozen=True)
class ZoneConfig:
    """
    Where the door is, per camera, in normalized coordinates (B5, §3.2, §4.2).

    **This is the local path, not the production one.** At runtime `door_region`
    arrives from the backend in `set_cameras` (ENGINE_PROTOCOL.md §3.2) and the
    wire always wins: a camera can be moved without touching a config file, and
    two sources of truth for where the door is would eventually disagree about
    whether somebody left the room. What this section is for is the single-camera
    developer run and the benchmark, where there is no backend to ask — and
    without it the benchmark cannot compute §13.8's cheap false-gap estimate,
    which is defined in terms of the door region.

    Normalized because the engine sees the mainstream and whoever draws the
    region is looking at the dashboard's substream (§6.7.2). In pixels the region
    would land somewhere else at a different resolution, and silently.

    Nothing here is a company rule: a door is a fact about a room, `edge_margin`
    is a fact about geometry, and neither knows what a break is.
    """

    door_regions: dict = field(default_factory=dict)   # camera_id -> [x1,y1,x2,y2]
    edge_margin: float = 0.03

    def __post_init__(self) -> None:
        if not isinstance(self.door_regions, dict):
            raise ValueError(
                "zones.door_regions must be a mapping of camera_id -> "
                "[x1, y1, x2, y2] normalized to 0-1."
            )
        if not (0.0 <= self.edge_margin < 0.5):
            raise ValueError(
                f"zones.edge_margin must be in [0, 0.5), got {self.edge_margin}."
            )
        # Validated here rather than at first use: a malformed region would
        # otherwise surface halfway through a long run, after the recording it
        # was supposed to label is already half processed.
        from ..presence.zones import DoorRegion

        for camera_id, values in self.door_regions.items():
            try:
                DoorRegion.from_sequence(values)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"zones.door_regions['{camera_id}']: {exc}") from exc


@dataclass(frozen=True)
class RecognitionConfig:
    """
    The recognition queue's perceptual constants (B5, §3.2, §5.2).

    `enabled` defaults to **false**, and that is not timidity. B1's baseline was
    measured with no scheduler in the loop; turning one on by default would move
    the numbers every later step is compared against, in the same commit that
    introduced it. It is switched on for the runs that are about it.

    Every other value defaults to `None`, meaning "whatever
    `identity/admission.py` says". Copying those numbers here would give each of
    them two homes and one day two values — and the one in the config file would
    win while the docstring explaining it stayed next to the other.
    """

    enabled: bool = False
    max_age_seconds: Optional[float] = None
    retry_interval_seconds: Optional[float] = None
    reverify_interval_seconds: Optional[float] = None
    per_camera_quota: Optional[int] = None

    # How many requests the frame loop hands out per frame. The loop is still
    # synchronous: until the worker pool of §5.2 exists there is nothing to
    # overlap with, so this is a throttle on bookkeeping, not on GPU work.
    max_requests_per_frame: int = 2

    # --- the recognizer slot --------------------------------------------
    # "none" (default): no face model is loaded, enrollment answers
    # `recognizer_disabled`, every track stays nameless. "onnx_face": SCRFD +
    # AuraFace through onnxruntime (engine/identity/face_onnx.py). Turning it
    # on also requires `enabled: true` — recognition needs the scheduler.
    recognizer: str = "none"
    face_detector_model: Optional[str] = None
    face_embedder_model: Optional[str] = None
    embedding_version: str = "auraface-v1"
    reference_db_path: str = "engine/data/references.sqlite3"
    onnx_providers: Optional[Tuple[str, ...]] = None
    # Batas VRAM arena onnxruntime per sesi (MB). None = tanpa batas (bawaan
    # ORT: arena membesar dan tidak dikembalikan). Di GPU 8 GB yang dipakai
    # bersama PyTorch untuk 5 kamera, batas ini mencegah ORT memakan VRAM.
    onnx_gpu_mem_limit_mb: Optional[int] = None
    face_detection_threshold: float = 0.5
    # SCRFD input canvas (pixels, multiple of 32). Runtime crops are head
    # regions of ~60-150 px, so 640 mostly upscales; 320 is the candidate for
    # 5 cameras (P7) once similarity on real footage is compared at both.
    face_detector_input_size: int = 640
    # P7: "async" = SCRFD + AuraFace berjalan di worker terpisah, loop frame
    # tidak menunggu; "sync" = cara lama (di dalam loop frame), untuk
    # pembanding dan cadangan. `worker_queue` = berapa permintaan boleh antre
    # sebelum ditolak (ditolak = dicoba lagi frame berikutnya, bukan hilang).
    execution: str = "async"
    worker_queue: int = 8
    min_face_px: float = 40.0
    match_threshold: Optional[float] = None
    match_margin: Optional[float] = None

    def __post_init__(self) -> None:
        if self.recognizer not in ("none", "onnx_face"):
            raise ValueError("recognition.recognizer must be 'none' or 'onnx_face'.")
        if self.recognizer != "none" and not self.enabled:
            raise ValueError(
                "recognition.recognizer is set but recognition.enabled is false; "
                "a recognizer without the scheduler would never be asked anything."
            )
        if self.recognizer != "none" and not (self.face_detector_model and self.face_embedder_model):
            raise ValueError(
                "recognition.recognizer=onnx_face needs face_detector_model and face_embedder_model."
            )
        if self.max_requests_per_frame < 0:
            raise ValueError("recognition.max_requests_per_frame must be >= 0.")
        if self.execution not in ("async", "sync"):
            raise ValueError("recognition.execution must be 'async' or 'sync'.")
        if self.worker_queue < 1:
            raise ValueError("recognition.worker_queue must be >= 1.")
        if self.onnx_gpu_mem_limit_mb is not None and self.onnx_gpu_mem_limit_mb < 64:
            raise ValueError("recognition.onnx_gpu_mem_limit_mb must be >= 64 (or unset).")
        if (self.face_detector_input_size < 64 or self.face_detector_input_size > 1280
                or self.face_detector_input_size % 32):
            raise ValueError(
                "recognition.face_detector_input_size must be a multiple of 32 in 64..1280 "
                "(SCRFD strides 8/16/32)."
            )
        for name in ("max_age_seconds", "retry_interval_seconds",
                     "reverify_interval_seconds"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"recognition.{name} must be positive if set.")
        if self.per_camera_quota is not None and self.per_camera_quota < 1:
            raise ValueError("recognition.per_camera_quota must be >= 1 if set.")

    def scheduler_kwargs(self) -> dict:
        """Only the values actually set, so the scheduler's own defaults apply."""
        mapping = {
            "max_age_seconds": self.max_age_seconds,
            "retry_interval_seconds": self.retry_interval_seconds,
            "reverify_interval_seconds": self.reverify_interval_seconds,
            "per_camera_quota": self.per_camera_quota,
        }
        return {key: value for key, value in mapping.items() if value is not None}


@dataclass(frozen=True)
class ReidSettings:
    """ReID berjangkar wajah (dokumen 12 §3.6, dokumen 04 §11). Default MATI.

    Mati berarti tidak ada onnxruntime yang disentuh untuk ReID, tidak ada
    worker, dan tidak ada satu event pun yang berubah. Menyala butuh
    rekognisi wajah (`recognition.recognizer: onnx_face`): galeri ReID hanya
    diisi dari track yang identitasnya berasal dari wajah, jadi tanpa wajah
    ReID hanya bisa membuat kelompok ANON yang tidak pernah selesai.

    Ambang kecocokan (`match_threshold`) adalah konstanta perseptual milik
    model, BUKAN kebijakan. `None` = usulan 0,80 di `identity/reid/merge.py`
    yang belum dikalibrasi; nilai sebenarnya dari MODEL-CARD (`eval_reid.py`
    pada crop berlabel) dan baru diisi setelah EA menyetujui.
    """

    enabled: bool = False
    model_path: str = "engine/models/reid/osnet_reid.onnx"
    model_sha256: Optional[str] = None
    match_threshold: Optional[float] = None
    match_margin: Optional[float] = None
    # Gerbang kualitas crop badan (identity/reid/quality.py).
    min_crop_height_px: float = 96.0
    min_aspect: float = 0.15
    max_aspect: float = 1.0
    edge_margin_px: float = 2.0
    # Embedding berbasis kejadian: track baru, wajah baru terkonfirmasi, lalu
    # paling sering sekali per interval ini per track. Bukan tiap frame.
    embed_interval_seconds: float = 15.0
    max_batch: int = 8
    worker_queue: int = 16
    max_age_seconds: float = 1.0
    onnx_providers: Optional[Tuple[str, ...]] = None
    onnx_gpu_mem_limit_mb: Optional[int] = None
    # Waktu tempuh minimum antar lokasi (detik), bersarang dan simetris:
    #   travel_time_seconds: {lobby: {smoking: 12}, luar: {lobby: 8}}
    # Pasangan yang tidak tercantum memakai default yang sengaja besar (ketat).
    travel_time_seconds: dict = field(default_factory=dict)
    default_travel_time_seconds: float = 30.0
    # Jam lokal (HH:MM) galeri tubuh + kelompok ANON dikosongkan setiap hari.
    # Pakaian berganti antar hari; penampilan kemarin hanya menambah peluang tertukar,
    # dan data penampilan tidak disimpan lebih lama dari perlu. Pilih jam di luar
    # jam operasional (engine tetap jalan, ReID mulai dari galeri kosong).
    daily_purge_time: str = "00:00"

    def __post_init__(self) -> None:
        if self.match_threshold is not None and not -1.0 <= self.match_threshold <= 1.0:
            raise ValueError("reid.match_threshold must be within [-1, 1].")
        if self.match_margin is not None and self.match_margin < 0:
            raise ValueError("reid.match_margin must be >= 0.")
        if self.model_sha256 is not None:
            digest = self.model_sha256.strip().lower()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("reid.model_sha256 must be 64 hex characters (or unset).")
        if self.embed_interval_seconds <= 0:
            raise ValueError("reid.embed_interval_seconds must be > 0.")
        if self.max_batch < 1 or self.worker_queue < 1:
            raise ValueError("reid.max_batch and reid.worker_queue must be >= 1.")
        if self.max_age_seconds <= 0:
            raise ValueError("reid.max_age_seconds must be > 0.")
        if self.onnx_gpu_mem_limit_mb is not None and self.onnx_gpu_mem_limit_mb < 64:
            raise ValueError("reid.onnx_gpu_mem_limit_mb must be >= 64 (or unset).")
        if not isinstance(self.travel_time_seconds, dict):
            raise ValueError("reid.travel_time_seconds must be a mapping location -> {location: seconds}.")
        self.purge_offset_seconds()
        from ..identity.reid.quality import CropRules

        CropRules(self.min_crop_height_px, self.min_aspect, self.max_aspect, self.edge_margin_px)
        self.merge_config()  # validasi waktu tempuh sekarang, bukan saat track pertama

    def purge_offset_seconds(self) -> float:
        """`daily_purge_time` "HH:MM" -> detik sejak 00:00 lokal."""
        text = str(self.daily_purge_time).strip()
        hours, sep, minutes = text.partition(":")
        if not (sep and hours.isdigit() and minutes.isdigit() and len(minutes) == 2
                and 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
            raise ValueError(f"reid.daily_purge_time must be HH:MM (00:00..23:59), got {text!r}.")
        return float(int(hours) * 3600 + int(minutes) * 60)

    def crop_rules(self):
        from ..identity.reid.quality import CropRules

        return CropRules(self.min_crop_height_px, self.min_aspect, self.max_aspect, self.edge_margin_px)

    def merge_config(self):
        """Ke `identity.reid.merge.ReidConfig`; None = default modul itu."""
        from ..identity.reid.merge import ReidConfig

        raw: dict = {
            "default_min_travel_seconds": float(self.default_travel_time_seconds),
            "min_travel_seconds": self.travel_time_seconds,
        }
        if self.match_threshold is not None:
            raw["match_threshold"] = float(self.match_threshold)
        if self.match_margin is not None:
            raw["match_margin"] = float(self.match_margin)
        return ReidConfig.from_mapping(raw)


@dataclass(frozen=True)
class DetectorConfig:
    """Perceptual constants for the object detector."""

    model_path: str = "LibreDFINEn.pt"
    confidence_threshold: float = 0.50
    iou_threshold: float = 0.45
    image_size: int = 640
    device: Union[str, int] = "auto"
    # FP16 through torch.autocast. LibreYOLO's own `half=` predict option is a
    # no-op and its quantize(recipe="fp16") does not cover the D-FINE family,
    # so the flag used to change nothing. Slower on Pascal (GTX 1060).
    half: bool = False
    # Resize the frame to image_size x image_size in the engine (OpenCV,
    # INTER_AREA) before handing it to LibreYOLO, and map boxes back. D-FINE
    # resizes to a square without letterbox anyway; what this removes is
    # LibreYOLO's CPU path through PIL, which copies a full 1080p frame four
    # to five times per inference. Only applied when the frame is at least
    # image_size on both sides. Pixels differ slightly from PIL's resize, so
    # accuracy is to be compared, not assumed (ARCHITECTURE.md §16).
    pre_resize: bool = False
    # cuDNN memilih algoritma konvolusi tercepat sekali untuk ukuran input
    # tetap (640). Frame pertama lebih lambat, sisanya lebih cepat. Ukur dulu.
    cudnn_benchmark: bool = False
    # Putar ulang forward dari CUDA graph yang direkam (LibreYOLO >= 1.6,
    # predict(cuda_graph=...)). D-FINE M di RTX 4060: 57 -> 12,6 ms, karena
    # forward eager terikat peluncuran ±1000 kernel. False / True / "auto".
    cuda_graph: Union[bool, str] = False
    # Pra-proses frame RGB 640x640 (hasil pre_resize) langsung di GPU, bit-identik
    # dengan pra-proses PIL LibreYOLO. Cek: batch_check --fast-preprocess.
    fast_preprocess: bool = False
    # Frame PyAV: swscale langsung YUV -> RGB 640x640 (AREA), tanpa konversi
    # BGR 1080p + cv2.resize. Bench 4060: frame_convert ±16 ms + prepare ±5 ms.
    # Piksel tidak identik dengan cv2 INTER_AREA: cek dengan tools.scaling_check.
    swscale_resize: bool = False
    # Satu detector untuk semua kamera (engine/perception/shared_detector.py):
    # bobot dimuat sekali, inferensi lewat satu thread dispatcher.
    share_across_cameras: bool = True
    # Gabungkan frame beberapa kamera dalam satu panggilan model. Diperiksa
    # pada batch pertama; bila LibreYOLO tidak mendukung, kembali per gambar.
    # Cek kebenaran dan kecepatannya dengan `python -m engine.tools.batch_check`.
    batch_inference: bool = False
    max_batch: int = 8
    batch_wait_ms: float = 4.0

    def __post_init__(self) -> None:
        if self.max_batch < 1:
            raise ValueError("detector.max_batch must be >= 1.")
        if not 0.0 <= self.batch_wait_ms <= 100.0:
            raise ValueError("detector.batch_wait_ms must be within 0..100.")
        if self.cuda_graph not in (False, True, "auto"):
            raise ValueError('detector.cuda_graph must be true, false or "auto".')


@dataclass(frozen=True)
class EngineConfig:
    """
    Top-level engine configuration.

    `strict_mode` is the one setting here that changes behaviour, and it changes
    it from "silently wrong" to "loudly broken". See config/loader.py.
    """

    source_uri: str = "0"
    source_type: str = "opencv"         # opencv | video_file | mock
    detection_interval: int = 1
    target_fps: Optional[float] = None
    auto_warmup: bool = True
    strict_mode: bool = True
    # Batas thread torch/OpenCV/BLAS (engine/runtime/threads.py). 0 = biarkan
    # pustaka memakai semua core (perilaku lama).
    cpu_threads: int = 0
    # Penjadwal (dokumen 04 §14). "free" = perilaku lama: thread tiap kamera
    # berjalan secepat mungkin. "tick" = tahap 1 penjadwal berdetak: semua
    # kamera dilepas bersamaan sekali per detak (runtime/tick_scheduler.py).
    scheduler: str = "free"
    # Detak per detik untuk scheduler "tick". None = pakai target_fps. Pilih DI
    # BAWAH kapasitas terukur; cadangan itulah yang membuat fps tidak berayun.
    tick_fps: Optional[float] = None

    ingest: IngestConfig = field(default_factory=IngestConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    zones: ZoneConfig = field(default_factory=ZoneConfig)
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)
    reid: ReidSettings = field(default_factory=ReidSettings)

    def effective_fps(self, source_fps: float) -> float:
        """
        The fps the pipeline actually runs at — used for every seconds-to-frames
        conversion. target_fps caps the source; it never raises it.
        """
        if self.target_fps is None:
            return source_fps
        if source_fps <= 0.0:
            return self.target_fps
        return min(self.target_fps, source_fps)

    def __post_init__(self) -> None:
        if self.cpu_threads < 0:
            raise ValueError("core.cpu_threads must be >= 0 (0 = tidak dibatasi).")
        if self.scheduler not in ("free", "tick"):
            raise ValueError("core.scheduler must be 'free' or 'tick'.")
        if self.tick_fps is not None and self.tick_fps <= 0:
            raise ValueError("core.tick_fps must be > 0.")
        if self.scheduler == "tick" and not (self.tick_fps or self.target_fps):
            raise ValueError("core.scheduler: tick butuh core.tick_fps atau core.target_fps.")
        if self.detection_interval < 1:
            raise ValueError(
                f"detection_interval must be >= 1, got {self.detection_interval}."
            )
        if self.source_type not in ("opencv", "video_file", "mock"):
            raise ValueError(f"Unknown source_type '{self.source_type}'.")
        if self.reid.enabled and self.recognition.recognizer == "none":
            raise ValueError(
                "reid.enabled butuh recognition.recognizer: onnx_face. Galeri ReID hanya "
                "diisi dari track berwajah; tanpa wajah ReID hanya membuat kelompok ANON "
                "yang tidak pernah selesai."
            )
