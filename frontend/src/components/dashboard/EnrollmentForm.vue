<script setup>
import { ref, computed } from 'vue';
import { Upload, X } from '@lucide/vue';
import { useEnrollment } from '@/composables/useEnrollment';

const { submitEnrollment, isSubmitting, submitError } = useEnrollment();

const personId = ref('');
const selectedFiles = ref([]);
const previews = ref([]);
const lastResult = ref(null);

function handleFileChange(e) {
  const files = Array.from(e.target.files || []);
  selectedFiles.value = files;
  previews.value.forEach((url) => URL.revokeObjectURL(url));
  previews.value = files.map((f) => URL.createObjectURL(f));
}

function removeImage(idx) {
  URL.revokeObjectURL(previews.value[idx]);
  selectedFiles.value.splice(idx, 1);
  previews.value.splice(idx, 1);
}

const canSubmit = computed(
  () =>
    personId.value.trim().length > 0 &&
    selectedFiles.value.length >= 3 &&
    !isSubmitting.value,
);

async function handleSubmit() {
  lastResult.value = null;
  try {
    const result = await submitEnrollment(
      personId.value.trim(),
      selectedFiles.value,
    );
    lastResult.value = result;
    personId.value = '';
    previews.value.forEach((url) => URL.revokeObjectURL(url));
    selectedFiles.value = [];
    previews.value = [];
  } catch {
    // submitError sudah ditangani composable — form dibiarkan terisi supaya bisa dicoba lagi
  }
}
</script>

<template>
  <form
    class="space-y-3 rounded-xl border bg-white p-4 shadow-xs"
    @submit.prevent="handleSubmit"
  >
    <h3 class="text-sm font-semibold text-slate-800">
      Daftarkan Wajah Karyawan
    </h3>

    <div>
      <label class="text-xs font-medium text-slate-600">ID Karyawan *</label>
      <input
        v-model="personId"
        type="text"
        required
        placeholder="mis. 4471"
        class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
      />
    </div>

    <div>
      <label class="text-xs font-medium text-slate-600">
        Foto referensi * (minimal 3, dari beberapa pose berbeda — lihat
        ARCHITECTURE.md §10)
      </label>
      <label
        class="mt-1 flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-md border border-dashed px-4 py-6 text-slate-400 hover:bg-slate-50"
      >
        <Upload class="h-5 w-5" />
        <span class="text-xs">Klik untuk pilih gambar</span>
        <input
          type="file"
          accept="image/*"
          multiple
          class="hidden"
          @change="handleFileChange"
        />
      </label>

      <div v-if="previews.length > 0" class="mt-2 flex flex-wrap gap-2">
        <div v-for="(src, idx) in previews" :key="idx" class="relative">
          <img :src="src" class="h-16 w-16 rounded border object-cover" />
          <button
            type="button"
            class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-white"
            @click="removeImage(idx)"
          >
            <X class="h-3 w-3" />
          </button>
        </div>
      </div>
      <p
        v-if="selectedFiles.length > 0 && selectedFiles.length < 3"
        class="mt-1 text-[11px] text-amber-600"
      >
        Minimal 3 foto disarankan supaya lolos uji keberagaman di backend.
      </p>
    </div>

    <div
      v-if="submitError"
      class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-600"
    >
      {{ submitError }}
    </div>

    <div
      v-if="lastResult"
      class="rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-700"
    >
      Permintaan terkirim untuk {{ lastResult.person_id }} (request_id:
      {{ lastResult.request_id }}). Status diterima/ditolak
      <strong>belum bisa ditampilkan otomatis</strong> di sini — cek daftar di
      bawah setelah beberapa saat, atau tanyakan ke tim backend jalur mana yang
      membawa hasil enroll_result ke frontend.
    </div>

    <button
      type="submit"
      :disabled="!canSubmit"
      class="w-full rounded-md bg-slate-900 px-3 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
    >
      {{ isSubmitting ? 'Mengirim...' : 'Kirim Enrollment' }}
    </button>
  </form>
</template>
