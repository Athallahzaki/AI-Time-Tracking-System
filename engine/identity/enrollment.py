"""Enrollment diperketat: gerbang mutu, uji keberagaman, uji tabrakan.

Kualitas enrollment menentukan langit-langit akurasi seluruh sistem. Tidak ada
threshold, fusi, atau uji margin yang bisa memperbaiki referensi yang buruk —
dan itu sebabnya gerbang di sini lebih ketat daripada gerbang saat runtime:
frame buruk merusak satu percobaan, referensi buruk merusak permanen.

Tiga lapis, dan masing-masing menangkap kegagalan yang berbeda:

**Gerbang mutu per gambar** membuang yang terlalu kecil, buram, pose ekstrem,
atau pencahayaannya tidak karuan. Ini lapis yang paling jelas dan paling
mudah.

**Uji keberagaman** membuang referensi yang terlalu mirip satu sama lain. Lima
foto dari sesi yang sama dengan pose identik adalah **satu referensi efektif
yang menyamar jadi lima** — dan yang berbahaya bukan pemborosannya, tapi bahwa
syarat "minimal tiga referensi" jadi terpenuhi di atas kertas oleh satu momen
tunggal.

**Uji tabrakan antar karyawan** adalah yang paling penting dan paling sering
tidak ada. Kalau dua orang mirip masuk roster tanpa diperiksa, mereka akan
tertukar **selamanya**, dan tidak ada yang bisa memperbaikinya di runtime:
margin test akan menolak keduanya, jadi keduanya jadi tidak bisa dikenali sama
sekali. Satu-satunya tempat masalah ini bisa diselesaikan adalah di sini,
sebelum referensinya masuk.

Modul ini tidak mengimpor cv2 dan tidak tahu apa pun tentang format gambar.
Ia menerima **pengukuran** — ukuran bbox, ketajaman, landmark — dan memutuskan.
Yang mengukur adalah `engine/perception/`; yang memutuskan adalah di sini.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .matcher import MatrixMatcher, _normalize
from .ports import ReferenceStore

# Ambang perseptual. Lebih ketat daripada runtime, dengan sengaja.
MIN_FACE_PIXELS = 112          # Tidak boleh perlu di-upscale ke 112x112
MIN_SHARPNESS = 60.0           # Variance of Laplacian
MAX_ABS_YAW = 0.35             # Asimetri hidung terhadap mata, ternormalisasi
MIN_BRIGHTNESS = 40.0
MAX_BRIGHTNESS = 215.0
MIN_CONTRAST = 20.0
MIN_DETECTOR_CONFIDENCE = 0.7  # Runtime memakai 0,5
DUPLICATE_SIMILARITY = 0.90
MIN_ACCEPTED_REFERENCES = 3

# Nilai `reason` yang dikenal protokol. Sengaja bukan enum tertutup di kabel:
# alasan baru akan muncul, dan UI tidak boleh pecah karenanya.
REASON_TOO_SMALL = "too_small"
REASON_BLURRY = "blurry"
REASON_EXTREME_POSE = "extreme_pose"
REASON_BAD_LIGHTING = "bad_lighting"
REASON_NO_FACE = "no_face"
REASON_MULTIPLE_FACES = "multiple_faces"
REASON_LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True)
class ImageCandidate:
    """Satu gambar calon referensi, beserta pengukurannya.

    `embedding` boleh `None` kalau tidak ada wajah yang terdeteksi — gambar itu
    tetap masuk daftar hasil supaya UI bisa menjelaskan kenapa ditolak, bukan
    diam-diam hilang.
    """

    image_id: str
    face_count: int = 0
    embedding: Optional[np.ndarray] = None
    jpeg: bytes = b""
    face_width: float = 0.0
    face_height: float = 0.0
    sharpness: float = 0.0
    brightness: float = 128.0
    contrast: float = 64.0
    detector_confidence: float = 1.0
    landmarks: Optional[Sequence[Sequence[float]]] = None
    camera_id: Optional[str] = None
    captured_at: Optional[str] = None


@dataclass
class ImageVerdict:
    image_id: str
    accepted: bool
    reason: Optional[str] = None
    quality: float = 0.0
    similarity: Optional[float] = None

    def to_message(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": self.image_id, "accepted": self.accepted}
        if self.reason:
            payload["reason"] = self.reason
        if self.accepted:
            payload["quality"] = round(self.quality, 4)
        if self.similarity is not None:
            payload["similarity"] = round(self.similarity, 4)
        return payload


@dataclass
class EnrollmentResult:
    person_id: str
    enrollment_version: int
    accepted: bool
    reason: str
    images: List[ImageVerdict] = field(default_factory=list)
    collides_with: Optional[str] = None
    collision_similarity: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    fused: Optional[np.ndarray] = None

    @property
    def accepted_images(self) -> List[ImageVerdict]:
        return [verdict for verdict in self.images if verdict.accepted]

    def to_message(self, request_id: str, embedding_version: str, ts: str) -> Dict[str, Any]:
        """Bentuk `enroll_result` sesuai kontrak §3.4.

        Hasil per gambar, bukan sekadar sukses/gagal: tanpa itu, orang HRD yang
        mengunggah lima foto dan ditolak tidak punya cara tahu foto mana yang
        salah dan kenapa.
        """
        payload: Dict[str, Any] = {
            "type": "enroll_result", "v": 1, "ts": ts,
            "request_id": request_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "embedding_version": embedding_version,
            "images": [verdict.to_message() for verdict in self.images],
        }
        if self.collides_with is not None:
            payload["collides_with"] = self.collides_with
            payload["collision_similarity"] = round(self.collision_similarity or 0.0, 4)
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


class QualityGate:
    """Gerbang per gambar. Mengembalikan alasan penolakan, atau `None`."""

    def __init__(
        self,
        min_face_pixels: float = MIN_FACE_PIXELS,
        min_sharpness: float = MIN_SHARPNESS,
        max_abs_yaw: float = MAX_ABS_YAW,
        min_brightness: float = MIN_BRIGHTNESS,
        max_brightness: float = MAX_BRIGHTNESS,
        min_contrast: float = MIN_CONTRAST,
        min_detector_confidence: float = MIN_DETECTOR_CONFIDENCE,
    ) -> None:
        self._min_face = min_face_pixels
        self._min_sharpness = min_sharpness
        self._max_yaw = max_abs_yaw
        self._min_brightness = min_brightness
        self._max_brightness = max_brightness
        self._min_contrast = min_contrast
        self._min_confidence = min_detector_confidence

    def evaluate(self, candidate: ImageCandidate) -> Optional[str]:
        if candidate.face_count == 0 or candidate.embedding is None:
            return REASON_NO_FACE
        if candidate.face_count > 1:
            # Bukan kerewelan: tidak ada cara tahu wajah mana yang dimaksud,
            # dan menebak berarti mendaftarkan orang lain atas nama karyawan ini.
            return REASON_MULTIPLE_FACES

        if min(candidate.face_width, candidate.face_height) < self._min_face:
            # Di bawah ini, alignment ke 112x112 harus meng-upscale, dan yang
            # di-embed adalah interpolasi, bukan wajah.
            return REASON_TOO_SMALL

        if candidate.detector_confidence < self._min_confidence:
            return REASON_LOW_CONFIDENCE

        if candidate.sharpness < self._min_sharpness:
            return REASON_BLURRY

        if not (self._min_brightness <= candidate.brightness <= self._max_brightness):
            return REASON_BAD_LIGHTING
        if candidate.contrast < self._min_contrast:
            return REASON_BAD_LIGHTING

        yaw = estimate_yaw(candidate.landmarks)
        if yaw is not None and abs(yaw) > self._max_yaw:
            return REASON_EXTREME_POSE

        return None

    def score(self, candidate: ImageCandidate) -> float:
        """Skor mutu 0–1, dipakai sebagai bobot saat peleburan."""
        size = min(1.0, min(candidate.face_width, candidate.face_height) / (self._min_face * 2))
        sharp = min(1.0, candidate.sharpness / (self._min_sharpness * 4))
        yaw = estimate_yaw(candidate.landmarks)
        frontal = 1.0 if yaw is None else max(0.0, 1.0 - abs(yaw) / self._max_yaw)
        return round(0.4 * size + 0.35 * sharp + 0.25 * frontal, 4)


def estimate_yaw(landmarks: Optional[Sequence[Sequence[float]]]) -> Optional[float]:
    """Yaw kasar dari asimetri lima landmark.

    Urutan landmark SCRFD: mata kiri, mata kanan, hidung, sudut mulut kiri,
    sudut mulut kanan. Kalau hidung jauh dari titik tengah kedua mata relatif
    terhadap jarak antar mata, wajahnya menoleh. Kasar, tapi cukup untuk
    membuang profil ekstrem, dan tidak butuh model tambahan.
    """
    if landmarks is None or len(landmarks) < 3:
        return None

    points = np.asarray(landmarks, dtype=np.float32)
    left_eye, right_eye, nose = points[0], points[1], points[2]

    eye_distance = float(np.linalg.norm(right_eye - left_eye))
    if eye_distance <= 1e-6:
        return None

    midpoint_x = float((left_eye[0] + right_eye[0]) / 2.0)
    return float((nose[0] - midpoint_x) / eye_distance)


class EnrollmentPolicy:
    """Tiga lapis pemeriksaan, dijalankan berurutan."""

    def __init__(
        self,
        matcher: MatrixMatcher,
        gate: Optional[QualityGate] = None,
        duplicate_similarity: float = DUPLICATE_SIMILARITY,
        min_accepted_references: int = MIN_ACCEPTED_REFERENCES,
        collision_similarity: Optional[float] = None,
    ) -> None:
        self._matcher = matcher
        self._gate = gate or QualityGate()
        self._duplicate = duplicate_similarity
        self._min_accepted = min_accepted_references
        # Ambang tabrakan lebih tinggi daripada ambang pengenalan: dua orang
        # yang cukup mirip untuk saling melewati margin test di runtime tidak
        # boleh sama-sama ada di roster sejak awal.
        self._collision = (
            collision_similarity
            if collision_similarity is not None
            else matcher._threshold + matcher._margin
        )

    def evaluate(
        self,
        person_id: str,
        enrollment_version: int,
        candidates: Sequence[ImageCandidate],
    ) -> EnrollmentResult:
        verdicts: List[ImageVerdict] = []
        accepted: List[Tuple[ImageCandidate, ImageVerdict]] = []

        # Lapis 1: mutu per gambar.
        for candidate in candidates:
            reason = self._gate.evaluate(candidate)
            if reason is not None:
                verdicts.append(ImageVerdict(candidate.image_id, False, reason))
                continue
            verdict = ImageVerdict(candidate.image_id, True, quality=self._gate.score(candidate))
            verdicts.append(verdict)
            accepted.append((candidate, verdict))

        # Lapis 2: keberagaman. Dibandingkan hanya terhadap yang sudah lolos,
        # supaya foto buram tidak bisa "memakan" foto bagus sebagai duplikatnya.
        kept: List[Tuple[ImageCandidate, ImageVerdict]] = []
        for candidate, verdict in accepted:
            vector = _normalize(np.asarray(candidate.embedding, dtype=np.float32).reshape(-1))
            duplicate_of: Optional[Tuple[str, float]] = None

            for existing, _ in kept:
                similarity = float(
                    vector @ _normalize(np.asarray(existing.embedding, dtype=np.float32).reshape(-1))
                )
                if similarity > self._duplicate:
                    duplicate_of = (existing.image_id, similarity)
                    break

            if duplicate_of is not None:
                verdict.accepted = False
                verdict.reason = f"duplicate_of:{duplicate_of[0]}"
                verdict.similarity = duplicate_of[1]
                continue

            kept.append((candidate, verdict))

        warnings: List[str] = []
        if kept and not any(candidate.camera_id for candidate, _ in kept):
            # Pas foto studio dan kamera sudut ruangan berbeda pose, jarak,
            # pencahayaan, dan lensa. Tidak ada threshold yang menutup itu.
            warnings.append("no_cctv_reference")

        if len(kept) < self._min_accepted:
            return EnrollmentResult(
                person_id, enrollment_version, False, "insufficient_references",
                verdicts, warnings=warnings,
            )

        fused = _fuse([candidate for candidate, _ in kept], [verdict.quality for _, verdict in kept])

        # Lapis 3: tabrakan antar karyawan.
        match = self._matcher.match(fused)
        if (
            match.runner_up_id is not None or match.person_id is not None
        ):
            rival_id, rival_similarity = _best_other(self._matcher, fused, person_id)
            if rival_id is not None and rival_similarity >= self._collision:
                return EnrollmentResult(
                    person_id, enrollment_version, False, "collision", verdicts,
                    collides_with=rival_id, collision_similarity=rival_similarity,
                    warnings=warnings, fused=fused,
                )

        return EnrollmentResult(
            person_id, enrollment_version, True, "ok", verdicts,
            warnings=warnings, fused=fused,
        )

    def commit(self, result: EnrollmentResult, store: ReferenceStore,
               candidates: Sequence[ImageCandidate]) -> List[int]:
        """Tulis referensi yang diterima ke store. Tidak menulis apa pun kalau ditolak."""
        if not result.accepted:
            return []

        by_id = {candidate.image_id: candidate for candidate in candidates}
        written: List[int] = []

        for verdict in result.accepted_images:
            candidate = by_id[verdict.image_id]
            written.append(
                store.add_reference(
                    person_id=result.person_id,
                    embedding=candidate.embedding,
                    image_jpeg=candidate.jpeg,
                    quality=verdict.quality,
                    enrollment_version=result.enrollment_version,
                    camera_id=candidate.camera_id,
                    captured_at=candidate.captured_at,
                )
            )
        return written


def _fuse(candidates: Sequence[ImageCandidate], weights: Sequence[float]) -> np.ndarray:
    vectors = np.stack(
        [_normalize(np.asarray(c.embedding, dtype=np.float32).reshape(-1)) for c in candidates]
    )
    weight_array = np.asarray([max(w, 1e-6) for w in weights], dtype=np.float32)
    mean = (vectors * weight_array[:, None]).sum(axis=0) / weight_array.sum()
    return _normalize(mean)


def _best_other(matcher: MatrixMatcher, query: np.ndarray, exclude_person: str) -> Tuple[Optional[str], float]:
    """Skor tertinggi terhadap siapa pun SELAIN orang ini.

    Mendaftar ulang karyawan yang sudah ada tidak boleh dianggap bertabrakan
    dengan dirinya sendiri — itu justru tanda foto barunya benar.
    """
    if matcher._matrix is None:
        return None, -1.0

    similarities = matcher._matrix @ _normalize(np.asarray(query, dtype=np.float32).reshape(-1))
    per_person = np.full(len(matcher._people), -1.0, dtype=np.float32)
    np.maximum.at(per_person, matcher._owner_index, similarities)

    best_id: Optional[str] = None
    best = -1.0
    for index, person_id in enumerate(matcher._people):
        if person_id == exclude_person:
            continue
        if float(per_person[index]) > best:
            best = float(per_person[index])
            best_id = person_id

    return best_id, best
