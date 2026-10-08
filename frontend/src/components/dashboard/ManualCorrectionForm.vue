<script setup>
import { computed, ref, useId } from 'vue';
import { AlertCircle, CheckCircle2, Loader2 } from '@lucide/vue';
import { apiFetch } from '@/composables/useAuth';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

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
// Select reka-ui tidak menerima value string kosong, jadi opsi "jangan
// kecualikan" memakai sentinel NONE dan dipetakan kembali ke '' di bawah.
const NONE = '__none__';
const GAP_CLASSIFICATIONS = [
  { value: NONE, label: 'Jangan kecualikan kunjungan' },
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

const classificationModel = computed({
  get: () => form.value.new_classification || NONE,
  set: (v) => {
    form.value.new_classification = v === NONE ? '' : v;
  },
});

// id unik per instance form supaya <Label for> selalu menunjuk input yang benar.
const uid = useId();
const fid = (name) => `${uid}-${name}`;

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
        form.value.adjustment_minutes === '' ||
        form.value.adjustment_minutes == null
          ? null
          : Number(form.value.adjustment_minutes),
      notes: form.value.notes || null,
    };

    const res = await apiFetch('/api/attendance/corrections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.status === 401 || res.status === 403) {
      throw new Error('Koreksi butuh login admin.');
    }
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
  <Card class="gap-4 py-4 shadow-xs">
    <CardHeader class="px-4">
      <CardTitle class="text-sm text-slate-800">Koreksi Manual</CardTitle>
    </CardHeader>

    <CardContent class="px-4">
      <form :id="fid('form')" class="space-y-3" @submit.prevent="handleSubmit">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label :for="fid('person')" class="text-xs text-slate-600"
              >ID Karyawan *</Label
            >
            <Input
              :id="fid('person')"
              v-model="form.person_id"
              required
              type="text"
            />
          </div>
          <div class="space-y-1.5">
            <Label :for="fid('date')" class="text-xs text-slate-600"
              >Tanggal *</Label
            >
            <Input :id="fid('date')" v-model="form.date" required type="date" />
          </div>
          <div class="space-y-1.5">
            <Label :for="fid('session')" class="text-xs text-slate-600"
              >Session ID</Label
            >
            <Input :id="fid('session')" v-model="form.session_id" type="text" />
          </div>
          <div class="space-y-1.5">
            <Label :for="fid('gap')" class="text-xs text-slate-600"
              >Visit ID</Label
            >
            <Input
              :id="fid('gap')"
              v-model="form.gap_id"
              type="text"
              placeholder="visit_… (kosongkan jika hanya penyesuaian menit)"
            />
          </div>
        </div>

        <div class="space-y-1.5">
          <Label :for="fid('by')" class="text-xs text-slate-600"
            >Dikoreksi oleh *</Label
          >
          <Input
            :id="fid('by')"
            v-model="form.corrected_by"
            required
            type="text"
            placeholder="Nama HR/supervisor"
          />
        </div>

        <div class="space-y-1.5">
          <Label :for="fid('reason')" class="text-xs text-slate-600"
            >Alasan *</Label
          >
          <Textarea
            :id="fid('reason')"
            v-model="form.reason"
            required
            rows="2"
            class="min-h-14"
          />
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label :for="fid('class')" class="text-xs text-slate-600"
              >Kecualikan kunjungan karena</Label
            >
            <Select v-model="classificationModel">
              <SelectTrigger :id="fid('class')" class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="opt in GAP_CLASSIFICATIONS"
                  :key="opt.value"
                  :value="opt.value"
                >
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label :for="fid('adj')" class="text-xs text-slate-600"
              >Penyesuaian jatah (menit, − = kembalikan)</Label
            >
            <Input
              :id="fid('adj')"
              v-model="form.adjustment_minutes"
              type="number"
              step="0.5"
            />
          </div>
        </div>

        <div class="space-y-1.5">
          <Label :for="fid('notes')" class="text-xs text-slate-600"
            >Catatan tambahan</Label
          >
          <Textarea
            :id="fid('notes')"
            v-model="form.notes"
            rows="2"
            class="min-h-14"
          />
        </div>

        <Alert
          v-if="submitError"
          variant="destructive"
          class="border-red-200 bg-red-50 py-2"
        >
          <AlertCircle />
          <AlertTitle class="text-xs line-clamp-none">{{
            submitError
          }}</AlertTitle>
        </Alert>
        <Alert v-if="submitSuccess" variant="success" class="py-2">
          <CheckCircle2 />
          <AlertTitle class="text-xs line-clamp-none"
            >Koreksi berhasil dicatat.</AlertTitle
          >
        </Alert>
      </form>
    </CardContent>

    <CardFooter class="justify-end gap-2 px-4">
      <Button
        type="button"
        variant="outline"
        size="sm"
        @click="$emit('cancel')"
      >
        Batal
      </Button>
      <Button
        type="submit"
        size="sm"
        :form="fid('form')"
        :disabled="isSubmitting"
      >
        <Loader2 v-if="isSubmitting" class="animate-spin" />
        {{ isSubmitting ? 'Mengirim...' : 'Kirim Koreksi' }}
      </Button>
    </CardFooter>
  </Card>
</template>
