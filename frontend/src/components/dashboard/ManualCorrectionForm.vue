<script setup>
import { ref } from 'vue';

const props = defineProps({
  presetPersonId: { type: String, default: '' },
  presetDate: { type: String, default: '' },
  presetSessionId: { type: String, default: '' },
  presetGapId: { type: String, default: '' },
  presetCorrectedBy: { type: String, default: '' },
});

const emit = defineEmits(['submitted', 'cancel']);

// Sesuai backend/schemas/corrections.py. Model jatah: waktu TERLIHAT di ruang
// fasilitas. Koreksi bisa (a) mengecualikan satu kunjungan (Visit ID dari
// panel jatah + klasifikasi) atau (b) menambah/mengurangi menit hari itu
// (angka negatif = mengembalikan jatah). Keduanya butuh ID karyawan.
const GAP_CLASSIFICATIONS = [
  { value: '', label: 'Jangan kecualikan kunjungan' },
  { value: 'misidentified', label: 'Salah orang (bukan karyawan ini)' },
  { value: 'not_free_time', label: 'Bukan free time (tugas kerja)' },
  { value: 'tracking_loss', label: 'Kegagalan tracking' },
  { value: 'camera_failure', label: 'Kamera bermasalah' },
  { value: 'system_event', label: 'Event sistem' },
  { value: 'official_break', label: 'Jam istirahat resmi' },
];

function todayLocal() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const form = ref({
  person_id: props.presetPersonId,
  date: props.presetDate || todayLocal(),
  session_id: props.presetSessionId,
  gap_id: props.presetGapId,
  corrected_by: props.presetCorrectedBy,
  reason: '',
  new_classification: '',
  adjustment_minutes: '',
  notes: '',
});

const isSubmitting = ref(false);
const submitError = ref(null);
const submitSuccess = ref(false);

async function handleSubmit() {
  isSubmitting.value = true;
  submitError.value = null;
  submitSuccess.value = false;
  try {
    const payload = {
      person_id: form.value.person_id || null,
      date: form.value.date || null,
      session_id: form.value.session_id || null,
      gap_id: form.value.gap_id || null,
      corrected_by: form.value.corrected_by,
      reason: form.value.reason,
      new_classification: form.value.new_classification || null,
      adjustment_minutes:
        form.value.adjustment_minutes === ''
          ? null
          : Number(form.value.adjustment_minutes),
      notes: form.value.notes || null,
    };

    const res = await fetch('/api/attendance/corrections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body?.detail || `HTTP ${res.status}`);
    }

    const json = await res.json();
    submitSuccess.value = true;
    emit('submitted', json.correction);
  } catch (err) {
    submitError.value = err?.message || 'Gagal mengirim koreksi';
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <form
    class="space-y-3 rounded-xl border bg-white p-4 shadow-xs"
    @submit.prevent="handleSubmit"
  >
    <h3 class="text-sm font-semibold text-slate-800">Koreksi Manual</h3>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs font-medium text-slate-600">ID Karyawan *</label>
        <input
          v-model="form.person_id"
          required
          type="text"
          class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
        />
      </div>
      <div>
        <label class="text-xs font-medium text-slate-600">Tanggal *</label>
        <input
          v-model="form.date"
          required
          type="date"
          class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
        />
      </div>
      <div>
        <label class="text-xs font-medium text-slate-600">Session ID</label>
        <input
          v-model="form.session_id"
          type="text"
          class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
        />
      </div>
      <div>
        <label class="text-xs font-medium text-slate-600">Visit ID</label>
        <input
          v-model="form.gap_id"
          type="text"
          placeholder="visit_… (kosongkan jika hanya penyesuaian menit)"
          class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
        />
      </div>
    </div>

    <div>
      <label class="text-xs font-medium text-slate-600">Dikoreksi oleh *</label>
      <input
        v-model="form.corrected_by"
        required
        type="text"
        placeholder="Nama HR/supervisor"
        class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
      />
    </div>

    <div>
      <label class="text-xs font-medium text-slate-600">Alasan *</label>
      <textarea
        v-model="form.reason"
        required
        rows="2"
        class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
      ></textarea>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="text-xs font-medium text-slate-600"
          >Kecualikan kunjungan karena</label
        >
        <select
          v-model="form.new_classification"
          class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
        >
          <option
            v-for="opt in GAP_CLASSIFICATIONS"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </option>
        </select>
      </div>
      <div>
        <label class="text-xs font-medium text-slate-600"
          >Penyesuaian jatah (menit, − = kembalikan)</label
        >
        <input
          v-model="form.adjustment_minutes"
          type="number"
          step="0.5"
          class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
        />
      </div>
    </div>

    <div>
      <label class="text-xs font-medium text-slate-600">Catatan tambahan</label>
      <textarea
        v-model="form.notes"
        rows="2"
        class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
      ></textarea>
    </div>

    <div
      v-if="submitError"
      class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-600"
    >
      {{ submitError }}
    </div>
    <div
      v-if="submitSuccess"
      class="rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700"
    >
      Koreksi berhasil dicatat.
    </div>

    <div class="flex items-center justify-end gap-2 pt-1">
      <button
        type="button"
        class="rounded-md border px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        @click="$emit('cancel')"
      >
        Batal
      </button>
      <button
        type="submit"
        :disabled="isSubmitting"
        class="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        {{ isSubmitting ? 'Mengirim...' : 'Kirim Koreksi' }}
      </button>
    </div>
  </form>
</template>
