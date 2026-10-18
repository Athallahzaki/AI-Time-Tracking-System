<script setup>
import { ref, computed, onUnmounted } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import {
  Upload,
  X,
  Camera,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from '@lucide/vue';
import { useEnrollment } from '@/composables/useEnrollment';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import EmployeeCombobox from '@/components/common/EmployeeCombobox.vue';
import { listEmployees } from '@/api/employees';

const { submitEnrollment, isSubmitting, submitError } = useEnrollment();

// Enrollment memilih karyawan dari data master (dok. 12 §3.1), bukan ID ketikan.
// Backend enrollment saat ini masih memakai person_id = ID karyawan.
const route = useRoute();
const selectedUid = ref(typeof route.query.employee === 'string' ? route.query.employee : '');
const selectedEmployee = ref(null);
const comboboxRef = ref(null);
const personId = computed(() => selectedEmployee.value?.employee_id || '');

function onEmployeeSelect(employee) {
  selectedEmployee.value = employee;
}

// Pilihan awal dari ?employee=<uid> (tombol "Daftarkan wajah" di Data Karyawan):
// combobox memuat daftar sendiri, jadi objek karyawan diambil saat sudah ada.
if (selectedUid.value) {
  listEmployees({ status: 'active' })
    .then((items) => {
      selectedEmployee.value = items.find((e) => e.uid === selectedUid.value) || null;
    })
    .catch(() => undefined);
}
const selectedFiles = ref([]);
const previews = ref([]);
const lastResult = ref(null);
const fileInputRef = ref(null);

// Webcam capture state
const isCameraActive = ref(false);
const videoRef = ref(null);
const mediaStream = ref(null);
const cameraError = ref(null);

const isDragging = ref(false);
const uploadError = ref('');
let dragDepth = 0;

const ALLOWED_PHOTO_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
]);

function handleFileChange(event) {
  addFiles(Array.from(event.target.files || []));

  // File yang sama tetap dapat dipilih lagi setelah dihapus.
  event.target.value = '';
}

function addFiles(files) {
  if (isSubmitting.value) return;

  uploadError.value = '';

  const accepted = [];
  let rejected = 0;

  for (const file of files) {
    if (
      !ALLOWED_PHOTO_TYPES.has(file.type) ||
      file.size === 0
    ) {
      rejected++;
      continue;
    }

    accepted.push(file);
  }

  if (rejected) {
    uploadError.value =
      `${rejected} file dilewati. Gunakan foto JPG, PNG, atau WebP yang tidak kosong.`;
  }

  selectedFiles.value = [
    ...selectedFiles.value,
    ...accepted,
  ];

  previews.value = [
    ...previews.value,
    ...accepted.map((file) => URL.createObjectURL(file)),
  ];
}

function isFileDrag(event) {
  return Array.from(event.dataTransfer?.types || [])
    .includes('Files');
}

function handleDragEnter(event) {
  if (!isFileDrag(event) || isSubmitting.value) return;

  dragDepth++;
  isDragging.value = true;
}

function handleDragOver(event) {
  if (!event.dataTransfer) return;

  event.dataTransfer.dropEffect =
    isSubmitting.value ? 'none' : 'copy';
}

function handleDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1);

  if (dragDepth === 0) {
    isDragging.value = false;
  }
}

function handleDrop(event) {
  dragDepth = 0;
  isDragging.value = false;

  if (isSubmitting.value) return;

  addFiles(Array.from(event.dataTransfer?.files || []));
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
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: 'user',
      },
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
    cameraError.value =
      'Tidak dapat mengakses kamera: ' + (err.message || 'Izin ditolak');
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

  canvas.toBlob(
    (blob) => {
      if (!blob) return;
      const filename = `snap_${Date.now()}_${selectedFiles.value.length + 1}.jpg`;
      const file = new File([blob], filename, { type: 'image/jpeg' });
      addFiles([file]);
    },
    'image/jpeg',
    0.95,
  );
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
    !!selectedEmployee.value &&
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
      selectedUid.value = '';
      selectedEmployee.value = null;
      comboboxRef.value?.reload();
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
  <Card class="gap-5 shadow-xs">
    <CardHeader class="border-b [.border-b]:pb-4">
      <CardTitle class="text-base text-slate-900"
        >Form Pendaftaran Wajah</CardTitle
      >
      <CardDescription class="text-xs">
        Daftarkan ID karyawan baru atau perbarui referensi wajah karyawan yang
        ada.
      </CardDescription>
      <CardAction
        class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600"
      >
        <Sparkles class="h-4 w-4" />
      </CardAction>
    </CardHeader>

    <CardContent>
      <form
        id="enrollment-form"
        class="space-y-4"
        @submit.prevent="handleSubmit"
      >
        <!-- Employee (combobox dari data master) -->
        <div class="space-y-1.5">
          <Label
            for="enroll-person-id"
            class="text-xs font-semibold text-slate-700"
          >
            Karyawan <span class="text-red-500">*</span>
          </Label>
          <EmployeeCombobox
            id="enroll-person-id"
            ref="comboboxRef"
            v-model="selectedUid"
            placeholder="Cari ID atau nama karyawan…"
            @select="onEmployeeSelect"
          />
          <p v-if="selectedEmployee?.enrolled_refs > 0" class="text-[11px] text-amber-700">
            {{ selectedEmployee.name }} sudah punya {{ selectedEmployee.enrolled_refs }} foto referensi;
            pengiriman ini membuat re-enrollment ke versi berikutnya.
          </p>
          <p v-else class="text-[11px] text-slate-400">
            Karyawan belum ada di daftar?
            <RouterLink to="/employees" class="font-medium text-indigo-600 hover:underline">Tambah di Data Karyawan</RouterLink>
            dulu.
          </p>
        </div>

        <!-- Photo References -->
        <div>
          <div class="flex items-center justify-between">
            <Label class="text-xs font-semibold text-slate-700">
              Foto Referensi Wajah <span class="text-red-500">*</span>
            </Label>
            <span class="text-xs font-medium text-slate-500">
              {{ selectedFiles.length }} terpilih (min. 3)
            </span>
            </div>

                <!-- Drag-and-drop sekaligus tombol pemilih file. -->
                <button
                  type="button"
                  :disabled="isSubmitting"
                  class="mt-3 flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-7 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                  :class="
                    isDragging
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                      : 'border-slate-300 bg-slate-50 text-slate-600 hover:border-indigo-400 hover:bg-indigo-50/50'
                  "
                  @click="fileInputRef?.click()"
                  @dragenter.prevent.stop="handleDragEnter"
                  @dragover.prevent.stop="handleDragOver"
                  @dragleave.prevent.stop="handleDragLeave"
                  @drop.prevent.stop="handleDrop"
                >
                  <Upload class="h-7 w-7 text-indigo-600 pointer-events-none" />

                  <span class="text-sm font-semibold pointer-events-none">
                    {{
                      isDragging
                        ? 'Lepaskan foto di sini'
                        : 'Tarik foto ke sini atau klik untuk memilih'
                    }}
                  </span>

                  <span class="text-xs text-slate-500 pointer-events-none">
                    JPG, PNG, atau WebP · Bisa beberapa foto sekaligus
                  </span>

                  <span class="text-xs text-slate-400 pointer-events-none">
                    Minimal 3 foto referensi wajah
                  </span>
                </button>

                <input
                  ref="fileInputRef"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  :disabled="isSubmitting"
                  class="hidden"
                  @change="handleFileChange"
                />

                <p
                  v-if="uploadError"
                  role="alert"
                  class="mt-2 text-xs text-red-600"
                >
                  {{ uploadError }}
                </p>

                <Button
                  type="button"
                  variant="outline"
                  :disabled="isSubmitting"
                  class="mt-3 h-auto w-full py-3 text-xs text-slate-700"
                  :class="
                    isCameraActive &&
                    'border-amber-400 bg-amber-50/50 text-amber-800 hover:bg-amber-50'
                  "
                  @click="isCameraActive ? stopCamera() : startCamera()"
                >
                  <Camera class="text-indigo-600" />
                  {{ isCameraActive ? 'Tutup Kamera' : 'Buka Kamera Web' }}
                </Button>

          <!-- Live Webcam Box -->
          <div
            v-if="isCameraActive"
            class="mt-3 overflow-hidden rounded-lg border border-indigo-200 bg-slate-950 p-2 text-center"
          >
            <div
              class="relative mx-auto aspect-video max-h-60 overflow-hidden rounded-md bg-black"
            >
              <video
                ref="videoRef"
                autoplay
                playsinline
                muted
                class="h-full w-full object-cover"
              />
            </div>
            <div class="mt-2.5 flex items-center justify-center gap-2">
              <Button
                type="button"
                size="sm"
                class="h-8 bg-indigo-600 text-xs hover:bg-indigo-700"
                @click="captureSnapshot"
              >
                <Camera />
                Ambil Foto Sekarang
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                class="h-8 border-slate-700 bg-slate-800 text-xs text-slate-300 hover:bg-slate-700 hover:text-white"
                @click="stopCamera"
              >
                Selesai
              </Button>
            </div>
          </div>

          <Alert
            v-if="cameraError"
            variant="destructive"
            class="mt-2 border-red-200 bg-red-50 py-2"
          >
            <AlertCircle />
            <AlertTitle class="text-xs line-clamp-none">{{
              cameraError
            }}</AlertTitle>
          </Alert>

          <!-- Image Previews Grid -->
          <div
            v-if="previews.length > 0"
            class="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-6"
          >
            <div
              v-for="(src, idx) in previews"
              :key="src"
              class="group relative aspect-square overflow-hidden rounded-lg border border-slate-200 bg-slate-100"
            >
              <img
                :src="src"
                class="h-full w-full object-cover"
                alt="Preview foto"
              />
              <span
                class="absolute bottom-1 left-1 rounded bg-black/60 px-1 py-0.5 font-mono text-[9px] text-white"
              >
                #{{ idx + 1 }}
              </span>
              <Button
                type="button"
                size="icon-xs"
                class="absolute top-1 right-1 size-5 rounded-full bg-slate-900/80 text-white hover:bg-red-600"
                title="Hapus foto"
                aria-label="Hapus foto"
                @click="removeImage(idx)"
              >
                <X />
              </Button>
            </div>
          </div>

          <p
            v-if="selectedFiles.length > 0 && selectedFiles.length < 3"
            class="mt-2 flex items-center gap-1 text-[11px] text-amber-600"
          >
            <AlertCircle class="h-3.5 w-3.5 shrink-0" />
            Tambahkan minimal {{ 3 - selectedFiles.length }} foto lagi dengan
            variasi sudut/pose berbeda.
          </p>
        </div>

        <!-- Error Banner -->
        <Alert
          v-if="submitError"
          variant="destructive"
          class="border-red-200 bg-red-50"
        >
          <AlertCircle />
          <AlertTitle class="text-xs line-clamp-none"
            >Gagal memproses pendaftaran</AlertTitle
          >
          <AlertDescription class="text-[11px]">{{
            submitError
          }}</AlertDescription>
        </Alert>

        <!-- Final Result Banner -->
        <template v-if="lastResult">
          <!-- Accepted -->
          <Alert v-if="lastResult.status === 'accepted'" variant="success">
            <CheckCircle2 class="text-emerald-600" />
            <AlertTitle class="text-xs font-semibold line-clamp-none">
              Pendaftaran Karyawan {{ lastResult.person_id }} Berhasil!
            </AlertTitle>
            <AlertDescription class="text-[11px]">
              Model identitas engine telah memperbarui profil dan referensi
              wajah karyawan ini.
            </AlertDescription>
          </Alert>

          <!-- Rejected -->
          <Alert
            v-else-if="lastResult.status === 'rejected'"
            variant="destructive"
            class="border-red-200 bg-red-50"
          >
            <AlertCircle />
            <AlertTitle class="text-xs font-semibold line-clamp-none">
              Pendaftaran {{ lastResult.person_id }} Ditolak
            </AlertTitle>
            <AlertDescription class="text-[11px]">
              <p>
                {{
                  translateReason(lastResult.reason, lastResult.collides_with)
                }}
              </p>

              <!-- Detail per foto -->
              <div
                v-if="lastResult.images && lastResult.images.length > 0"
                class="mt-1 w-full border-t border-red-200/60 pt-2"
              >
                <p class="font-semibold text-red-900">
                  Evaluasi Kualitas Per Gambar:
                </p>
                <ul class="mt-1 space-y-1 pl-1">
                  <li
                    v-for="img in lastResult.images"
                    :key="img.id"
                    class="flex items-center gap-1.5"
                  >
                    <span
                      class="inline-block h-2 w-2 shrink-0 rounded-full"
                      :class="img.accepted ? 'bg-emerald-500' : 'bg-red-500'"
                    />
                    <span class="font-mono text-slate-700">{{ img.id }}:</span>
                    <span
                      :class="
                        img.accepted
                          ? 'text-emerald-700'
                          : 'font-medium text-red-700'
                      "
                    >
                      {{
                        img.accepted
                          ? 'Memenuhi Syarat'
                          : translateReason(img.reason)
                      }}
                    </span>
                  </li>
                </ul>
              </div>
            </AlertDescription>
          </Alert>

          <!-- Pending -->
          <Alert v-else variant="info">
            <RefreshCw class="animate-spin text-sky-600" />
            <AlertTitle class="text-xs font-normal line-clamp-none">
              Sedang menunggu konfirmasi model engine untuk ID
              {{ lastResult.person_id }}…
            </AlertTitle>
          </Alert>
        </template>
      </form>
    </CardContent>

    <CardFooter>
      <Button
        type="submit"
        form="enrollment-form"
        class="w-full text-xs"
        :disabled="!canSubmit"
      >
        <RefreshCw v-if="isSubmitting" class="animate-spin" />
        {{
          isSubmitting
            ? 'Memproses Pendaftaran ke Engine...'
            : 'Kirim Pendaftaran Wajah'
        }}
      </Button>
    </CardFooter>
  </Card>
</template>
