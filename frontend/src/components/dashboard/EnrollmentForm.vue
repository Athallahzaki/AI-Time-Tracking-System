<script setup>
import { ref, computed, onUnmounted } from 'vue';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const { submitEnrollment, isSubmitting, submitError } = useEnrollment();

const personId = ref('');
const selectedFiles = ref([]);
const previews = ref([]);
const lastResult = ref(null);
const fileInputRef = ref(null);

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
        <!-- Employee ID -->
        <div class="space-y-1.5">
          <Label
            for="enroll-person-id"
            class="text-xs font-semibold text-slate-700"
          >
            ID Karyawan <span class="text-red-500">*</span>
          </Label>
          <Input
            id="enroll-person-id"
            v-model="personId"
            type="text"
            required
            placeholder="Contoh: EMP_001 atau 4471"
          />
          <p class="text-[11px] text-slate-400">
            Jika ID sudah terdaftar, sistem akan otomatis melakukan
            re-enrollment ke versi berikutnya.
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

          <!-- Action buttons: File Upload & Camera Toggle -->
          <div class="mt-2 grid grid-cols-2 gap-2">
            <Button
              type="button"
              variant="outline"
              class="h-auto border-dashed border-slate-300 bg-slate-50/50 py-3 text-xs text-slate-700 shadow-none hover:bg-slate-100"
              @click="fileInputRef?.click()"
            >
              <Upload class="text-indigo-600" />
              Unggah File Foto
            </Button>
            <input
              ref="fileInputRef"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              class="hidden"
              @change="handleFileChange"
            />

            <Button
              type="button"
              variant="outline"
              class="h-auto py-3 text-xs text-slate-700"
              :class="
                isCameraActive &&
                'border-amber-400 bg-amber-50/50 text-amber-800 hover:bg-amber-50'
              "
              @click="isCameraActive ? stopCamera() : startCamera()"
            >
              <Camera class="text-indigo-600" />
              {{ isCameraActive ? 'Tutup Kamera' : 'Buka Kamera Web' }}
            </Button>
          </div>

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
