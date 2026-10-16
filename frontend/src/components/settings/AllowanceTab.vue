<script setup>
import { ref, watch } from 'vue';
import { AlertCircle, CheckCircle2, Clock, Save } from '@lucide/vue';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

// Batas jatah & peringatan — fungsi lama dari SettingsView, dipindah ke tab.
const props = defineProps({
  policy: { type: Object, default: null },
  isSaving: { type: Boolean, default: false },
  error: { type: String, default: null },
  successMessage: { type: String, default: null },
});
const emit = defineEmits(['save']);

const dailyAllowance = ref(30);
const warningThreshold = ref(5);
const localError = ref('');

watch(
  () => props.policy,
  (p) => {
    if (p) {
      dailyAllowance.value = p.daily_free_time_allowance_minutes;
      warningThreshold.value = p.warning_remaining_minutes;
    }
  },
  { immediate: true },
);

function save() {
  const allowance = Number(dailyAllowance.value);
  const warning = Number(warningThreshold.value);
  if (!Number.isFinite(allowance) || allowance <= 0) {
    localError.value = 'Jatah harian harus lebih dari 0 menit.';
    return;
  }
  if (!Number.isFinite(warning) || warning < 0 || warning >= allowance) {
    localError.value = 'Ambang peringatan harus ≥ 0 dan lebih kecil dari jatah harian.';
    return;
  }
  localError.value = '';
  emit('save', allowance, warning);
}
</script>

<template>
  <Card class="max-w-2xl">
    <CardHeader>
      <div class="flex items-center gap-2">
        <div class="rounded-lg bg-indigo-50 p-2 text-indigo-600"><Clock class="h-5 w-5" /></div>
        <div>
          <CardTitle class="text-base font-semibold">Batas jatah free time</CardTitle>
          <CardDescription class="text-xs">Jatah harian per karyawan dan ambang peringatan.</CardDescription>
        </div>
      </div>
    </CardHeader>
    <CardContent class="space-y-4">
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="space-y-1.5">
          <Label for="daily-allowance" class="text-xs font-semibold text-slate-700">Jatah harian (menit)</Label>
          <Input id="daily-allowance" v-model="dailyAllowance" type="number" min="1" max="1440" />
          <p class="text-[11px] text-slate-400">Total waktu terlihat di area rekreasi sebelum dianggap melanggar.</p>
        </div>
        <div class="space-y-1.5">
          <Label for="warning-threshold" class="text-xs font-semibold text-slate-700">Peringatan saat sisa (menit)</Label>
          <Input id="warning-threshold" v-model="warningThreshold" type="number" min="0" />
          <p class="text-[11px] text-slate-400">Status berubah menjadi peringatan saat sisa jatah di bawah angka ini.</p>
        </div>
      </div>
      <div v-if="policy" class="grid gap-1 rounded-lg border border-slate-100 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2">
        <div class="flex justify-between gap-2"><span>Zona waktu</span><span class="font-medium text-slate-800">{{ policy.timezone }}</span></div>
        <div class="flex justify-between gap-2"><span>Kunjungan singkat gratis</span><span class="font-medium text-slate-800">{{ policy.qualification_seconds }} detik</span></div>
      </div>
      <Alert v-if="localError || error" variant="destructive" class="border-red-200 bg-red-50">
        <AlertCircle />
        <AlertTitle class="line-clamp-none">{{ localError || error }}</AlertTitle>
      </Alert>
      <Alert v-if="successMessage" variant="success">
        <CheckCircle2 />
        <AlertTitle class="line-clamp-none">{{ successMessage }}</AlertTitle>
      </Alert>
    </CardContent>
    <CardFooter class="flex justify-end border-t border-slate-100 pt-4">
      <Button :disabled="isSaving" @click="save">
        <Save class="h-4 w-4" />
        {{ isSaving ? 'Menyimpan…' : 'Simpan perubahan' }}
      </Button>
    </CardFooter>
  </Card>
</template>
