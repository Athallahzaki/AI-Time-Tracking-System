<script setup>
import { ref, computed, onUnmounted } from 'vue';
import { Upload, X, Camera, RefreshCw, CheckCircle2, AlertCircle, Sparkles } from '@lucide/vue';
import { useEnrollment } from '@/composables/useEnrollment';

const { submitEnrollment, isSubmitting, submitError } = useEnrollment();

const personId = ref('');
const selectedFiles = ref([]);
const previews = ref([]);
const lastResult = ref(null);

// Webcam capture state
const isCameraActive = ref(false);
const videoRef = ref(null);
const mediaStream = ref(null);
const cameraError = ref(null);

function handleFileChange(e) {
  const files = Array.from(e.target.files || []);
  if (files.length === 0) return;
  addFiles(files);
  e.target.value = '';
}

function addFiles(files) {
  selectedFiles.value = [...selectedFiles.value, ...files];
  const newPreviews = files.map((f) => URL.createObjectURL(f));
  previews.value = [...previews.value, ...newPreviews];
}

function removeImage(idx) {
  URL.revokeObjectURL(previews.value[idx]);
  selectedFiles.value.splice(idx, 1);
  previews.value.splice(idx, 1);
}

// Start webcam stream
async function startCamera() {
  cameraError.value = null;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
      audio: false,
    });
    mediaStream.value = stream;
    isCameraActive.value = true;
    setTimeout(() => {
      if (videoRef.value) {
        videoRef.value.srcObject = stream;
      }
    }, 100);
  } catch (err) {
    cameraError.value = 'Tidak dapat mengakses kamera: ' + (err.message || 'Izin ditolak');
  }
}

// Capture current video frame to JPEG file
function captureSnapshot() {
  if (!videoRef.value) return;
  const video = videoRef.value;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => {
    if (!blob) return;
    const filename = `snap_${Date.now()}_${selectedFiles.value.length + 1}.jpg`;
    const file = new File([blob], filename, { type: 'image/jpeg' });
    addFiles([file]);
  }, 'image/jpeg', 0.95);
}

function stopCamera() {
  if (mediaStream.value) {
    mediaStream.value.getTracks().forEach((track) => track.stop());
    mediaStream.value = null;
  }
  isCameraActive.value = false;
  cameraError.value = null;
}

onUnmounted(() => {
  stopCamera();
  previews.value.forEach((url) => URL.revokeObjectURL(url));
});

const canSubmit = computed(
  () =>
    personId.value.trim().length > 0 &&
    selectedFiles.value.length >= 3 &&
    !isSubmitting.value,
);

function translateReason(reason, collidesWith) {
  if (!reason) return 'Ditolak tanpa alasan spesifik';
  if (reason === 'collision') {
    return collidesWith
      ? `Wajah bertabrakan / terdeteksi sangat mirip dengan karyawan ID: ${collidesWith}`
      : 'Wajah bertabrakan dengan karyawan lain yang sudah terdaftar';
  }
  if (reason === 'insufficient_references') {
    return 'Jumlah foto referensi yang valid tidak memenuhi syarat';
  }
  if (reason === 'recognizer_disabled') {
    return 'Modul recognizer wajah pada engine belum dinyalakan di konfigurasi';
  }
  if (reason === 'engine_timeout') {
    return 'Waktu tunggu engine habis saat memproses pendaftaran';
  }
  if (reason === 'no_face') {
    return 'Tidak ada wajah terdeteksi pada foto';
  }
  if (reason === 'too_small') {
    return 'Ukuran wajah terlalu kecil / jarak terlalu jauh';
  }
  if (reason === 'blurry') {
    return 'Foto buram / tidak fokus';
  }
  if (reason === 'extreme_pose') {
    return 'Sudut wajah terlalu miring atau menunduk';
  }
  if (reason === 'bad_lighting') {
    return 'Pencahayaan buruk (terlalu gelap / silau)';
  }
  if (reason === 'multiple_faces') {
    return 'Terdeteksi lebih dari satu wajah dalam satu foto';
  }
  if (typeof reason === 'string' && reason.startsWith('duplicate_of:')) {
    const refId = reason.split(':')[1];
    return `Foto terlalu mirip dengan foto ${refId} (diperlukan variasi pose yang berbeda)`;
  }
  return reason;
}

async function handleSubmit() {
  lastResult.value = null;
  try {
    const result = await submitEnrollment(
      personId.value.trim(),
      selectedFiles.value,
    );
    lastResult.value = result;
    if (result.status === 'accepted') {
      personId.value = '';
      previews.value.forEach((url) => URL.revokeObjectURL(url));
      selectedFiles.value = [];
      previews.value = [];
      stopCamera();
    }
  } catch {
    // submitError sudah ditangani oleh composable
  }
}
</script>

<template>
  <form
    class="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-xs"
    @submit.prevent="handleSubmit"
  >
    <div class="flex items-center justify-between border-b border-slate-100 pb-3">
      <div>
        <h3 class="text-base font-semibold text-slate-900">
          Form Pendaftaran Wajah
        </h3>
        <p class="text-xs text-slate-500">
          Daftarkan ID karyawan baru atau perbarui referensi wajah karyawan yang ada.
        </p>
      </div>
      <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
        <Sparkles class="h-4 w-4" />
      </div>
    </div>

    <!-- Employee ID -->
    <div>
      <label class="block text-xs font-semibold text-slate-700">
        ID Karyawan <span class="text-red-500">*</span>
      </label>
      <input
        v-model="personId"
        type="text"
        required
        placeholder="Contoh: EMP_001 atau 4471"
        class="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:border-indigo-500 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
      />
      <p class="mt-1 text-[11px] text-slate-400">
        Jika ID sudah terdaftar, sistem akan otomatis melakukan re-enrollment ke versi berikutnya.
      </p>
    </div>

    <!-- Photo References -->
    <div>
      <div class="flex items-center justify-between">
        <label class="block text-xs font-semibold text-slate-700">
          Foto Referensi Wajah <span class="text-red-500">*</span>
        </label>
        <span class="text-xs font-medium text-slate-500">
          {{ selectedFiles.length }} terpilih (min. 3)
        </span>
      </div>

      <!-- Action buttons: File Upload & Camera Toggle -->
      <div class="mt-2 grid grid-cols-2 gap-2">
        <label
          class="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50/50 py-3 text-xs font-medium text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors"
        >
          <Upload class="h-4 w-4 text-indigo-600" />
          <span>Unggah File Foto</span>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            class="hidden"
            @change="handleFileChange"
          />
        </label>

        <button
          type="button"
          class="flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white py-3 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
          :class="isCameraActive ? 'border-amber-400 bg-amber-50/50 text-amber-800' : ''"
          @click="isCameraActive ? stopCamera() : startCamera()"
        >
          <Camera class="h-4 w-4 text-indigo-600" />
          <span>{{ isCameraActive ? 'Tutup Kamera' : 'Buka Kamera Web' }}</span>
        </button>
      </div>

      <!-- Live Webcam Box -->
      <div v-if="isCameraActive" class="mt-3 overflow-hidden rounded-lg border border-indigo-200 bg-slate-950 p-2 text-center">
        <div class="relative mx-auto aspect-video max-h-60 overflow-hidden rounded-md bg-black">
          <video
            ref="videoRef"
            autoplay
            playsinline
            muted
            class="h-full w-full object-cover"
          />
        </div>
        <div class="mt-2.5 flex items-center justify-center gap-2">
          <button
            type="button"
            class="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-indigo-700"
            @click="captureSnapshot"
          >
            <Camera class="h-3.5 w-3.5" />
            Ambil Foto Sekarang
          </button>
          <button
            type="button"
            class="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700"
            @click="stopCamera"
          >
            Selesai
          </button>
        </div>
      </div>

      <div v-if="cameraError" class="mt-2 rounded-md bg-red-50 p-2.5 text-xs text-red-600">
        {{ cameraError }}
      </div>

      <!-- Image Previews Grid -->
      <div v-if="previews.length > 0" class="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-6">
        <div
          v-for="(src, idx) in previews"
          :key="idx"
          class="group relative aspect-square overflow-hidden rounded-lg border border-slate-200 bg-slate-100"
        >
          <img :src="src" class="h-full w-full object-cover" alt="Preview foto" />
          <span class="absolute bottom-1 left-1 rounded bg-black/60 px-1 py-0.5 text-[9px] font-mono text-white">
            #{{ idx + 1 }}
          </span>
          <button
            type="button"
            class="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-slate-900/80 text-white opacity-90 hover:bg-red-600 hover:opacity-100 transition-opacity"
            title="Hapus foto"
            @click="removeImage(idx)"
          >
            <X class="h-3 w-3" />
          </button>
        </div>
      </div>

      <p
        v-if="selectedFiles.length > 0 && selectedFiles.length < 3"
        class="mt-2 flex items-center gap-1 text-[11px] text-amber-600"
      >
        <AlertCircle class="h-3.5 w-3.5 shrink-0" />
        Tambahkan minimal {{ 3 - selectedFiles.length }} foto lagi dengan variasi sudut/pose berbeda.
      </p>
    </div>

    <!-- Error Banner -->
    <div
      v-if="submitError"
      class="flex items-start gap-2 rounded-lg bg-red-50 p-3 text-xs text-red-700"
    >
      <AlertCircle class="h-4 w-4 shrink-0 text-red-500 mt-0.5" />
      <div>
        <p class="font-medium">Gagal memproses pendaftaran</p>
        <p class="text-[11px] text-red-600 mt-0.5">{{ submitError }}</p>
      </div>
    </div>

    <!-- Final Result Banner -->
    <div
      v-if="lastResult"
      class="rounded-lg p-3 text-xs border"
      :class="lastResult.status === 'accepted'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
        : lastResult.status === 'rejected'
          ? 'border-red-200 bg-red-50 text-red-800'
          : 'border-sky-200 bg-sky-50 text-sky-800'"
    >
      <!-- Accepted -->
      <div v-if="lastResult.status === 'accepted'" class="flex items-start gap-2">
        <CheckCircle2 class="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
        <div>
          <p class="font-semibold text-emerald-900">
            Pendaftaran Karyawan {{ lastResult.person_id }} Berhasil!
          </p>
          <p class="text-[11px] text-emerald-700 mt-0.5">
            Model identitas engine telah memperbarui profil dan referensi wajah karyawan ini.
          </p>
        </div>
      </div>

      <!-- Rejected -->
      <div v-else-if="lastResult.status === 'rejected'" class="space-y-2">
        <div class="flex items-start gap-2">
          <AlertCircle class="h-4 w-4 shrink-0 text-red-600 mt-0.5" />
          <div>
            <p class="font-semibold text-red-900">
              Pendaftaran {{ lastResult.person_id }} Ditolak
            </p>
            <p class="text-[11px] text-red-700 mt-0.5">
              {{ translateReason(lastResult.reason, lastResult.collides_with) }}
            </p>
          </div>
        </div>

        <!-- Detail per foto -->
        <div v-if="lastResult.images && lastResult.images.length > 0" class="mt-2 border-t border-red-200/60 pt-2">
          <p class="text-[11px] font-semibold text-red-900">Evaluasi Kualitas Per Gambar:</p>
          <ul class="mt-1 space-y-1 pl-1 text-[11px]">
            <li
              v-for="img in lastResult.images"
              :key="img.id"
              class="flex items-center gap-1.5"
            >
              <span
                class="inline-block h-2 w-2 rounded-full"
                :class="img.accepted ? 'bg-emerald-500' : 'bg-red-500'"
              />
              <span class="font-mono text-slate-700">{{ img.id }}:</span>
              <span :class="img.accepted ? 'text-emerald-700' : 'text-red-700 font-medium'">
                {{ img.accepted ? 'Memenuhi Syarat' : translateReason(img.reason) }}
              </span>
            </li>
          </ul>
        </div>
      </div>

      <!-- Pending -->
      <div v-else class="flex items-center gap-2 text-sky-800">
        <RefreshCw class="h-4 w-4 shrink-0 animate-spin text-sky-600" />
        <span>Sedang menunggu konfirmasi model engine untuk ID {{ lastResult.person_id }}…</span>
      </div>
    </div>

    <!-- Submit Button -->
    <button
      type="submit"
      :disabled="!canSubmit"
      class="flex w-full items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <RefreshCw v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
      <span>{{ isSubmitting ? 'Memproses Pendaftaran ke Engine...' : 'Kirim Pendaftaran Wajah' }}</span>
    </button>
  </form>
</template>
