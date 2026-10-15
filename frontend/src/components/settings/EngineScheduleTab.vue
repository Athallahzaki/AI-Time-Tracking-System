<script setup>
import { computed, onMounted, ref } from 'vue';
import { AlertCircle, CheckCircle2, Copy, Cpu, RotateCcw, Save } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { getEngineSchedule, saveEngineSchedule } from '@/api/settings';
import { DAY_KEYS, DAY_LABELS } from '@/api/types';
import { toMinutes } from './timeRanges';

// Jadwal operasional engine (dok. 12 §3.3): yang dimatikan adalah ANALISIS KAMERA
// (set_cameras enabled:false), bukan proses engine. Track yang masih hidup saat
// jadwal mati ditutup dengan alasan schedule_off.
const emit = defineEmits(['changed']);

const schedule = ref(null);
const draft = ref(null);
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const success = ref('');

const timeInputClass =
  'border-input h-8 w-[6.5rem] rounded-md border bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 disabled:opacity-40';

const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(schedule.value?.days));
const errors = computed(() => {
  const out = {};
  if (!draft.value) return out;
  for (const day of DAY_KEYS) {
    const d = draft.value[day];
    if (!d.enabled) continue;
    const start = toMinutes(d.start);
    const end = toMinutes(d.end);
    if (Number.isNaN(start) || Number.isNaN(end)) out[day] = 'Format jam harus HH:MM.';
    else if (start >= end) out[day] = 'Jam nonaktif harus setelah jam aktif.';
  }
  return out;
});
const hasErrors = computed(() => Object.keys(errors.value).length > 0);
const activeHoursPerWeek = computed(() => {
  if (!draft.value) return 0;
  let minutes = 0;
  for (const day of DAY_KEYS) {
    const d = draft.value[day];
    if (d.enabled && !errors.value[day]) minutes += toMinutes(d.end) - toMinutes(d.start);
  }
  return Math.round((minutes / 60) * 10) / 10;
});

async function load() {
  loading.value = true;
  error.value = '';
  try {
    schedule.value = await getEngineSchedule();
    draft.value = JSON.parse(JSON.stringify(schedule.value.days));
  } catch (err) {
    error.value = err?.message || 'Gagal memuat jadwal engine.';
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function copyMondayToWeekdays() {
  for (const day of ['tue', 'wed', 'thu', 'fri']) draft.value[day] = { ...draft.value.mon };
}
function resetDraft() {
  draft.value = JSON.parse(JSON.stringify(schedule.value.days));
}

async function save() {
  if (hasErrors.value) return;
  saving.value = true;
  error.value = '';
  success.value = '';
  try {
    schedule.value = await saveEngineSchedule(JSON.parse(JSON.stringify(draft.value)));
    draft.value = JSON.parse(JSON.stringify(schedule.value.days));
    success.value = 'Jadwal engine disimpan dan langsung berlaku.';
    emit('changed');
  } catch (err) {
    error.value = err?.message || 'Gagal menyimpan jadwal engine.';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Card>
    <CardHeader>
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div class="flex items-center gap-2">
          <div class="rounded-lg bg-slate-100 p-2 text-slate-700"><Cpu class="h-5 w-5" /></div>
          <div>
            <CardTitle class="text-base font-semibold">Jadwal operasional engine</CardTitle>
            <CardDescription class="text-xs">
              Jam analisis kamera aktif per hari. Proses engine tetap hidup; di luar jadwal kamera tidak dianalisis.
            </CardDescription>
          </div>
        </div>
        <div
          v-if="schedule && schedule.now_active !== undefined"
          class="flex items-center gap-2 self-start rounded-full border px-3 py-1 text-xs font-medium"
          :class="schedule.now_active ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-600'"
        >
          <span class="h-2 w-2 rounded-full" :class="schedule.now_active ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'" />
          {{ schedule.now_active ? 'Analisis aktif' : 'Analisis nonaktif' }}
          <span v-if="schedule.next_change_at" class="text-[11px] opacity-80">
            · {{ schedule.now_active ? 'berhenti' : 'mulai' }} {{ schedule.next_change_at }}
          </span>
        </div>
      </div>
    </CardHeader>

    <CardContent class="space-y-4">
      <p v-if="loading && !draft" class="py-6 text-center text-sm text-slate-400">Memuat…</p>

      <div v-if="draft" class="divide-y rounded-lg border">
        <div v-for="day in DAY_KEYS" :key="day" class="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5">
          <div class="flex w-32 items-center gap-2.5">
            <Switch v-model="draft[day].enabled" :aria-label="`Analisis aktif hari ${DAY_LABELS[day]}`" />
            <span class="text-sm font-medium text-slate-800">{{ DAY_LABELS[day] }}</span>
          </div>
          <template v-if="draft[day].enabled">
            <div class="flex items-center gap-2">
              <input v-model="draft[day].start" type="time" :class="timeInputClass" :aria-label="`${DAY_LABELS[day]} aktif`" />
              <span class="text-xs text-slate-400">s.d.</span>
              <input v-model="draft[day].end" type="time" :class="timeInputClass" :aria-label="`${DAY_LABELS[day]} nonaktif`" />
            </div>
            <p v-if="errors[day]" class="w-full text-[11px] text-red-600 sm:w-auto">{{ errors[day] }}</p>
          </template>
          <span v-else class="text-xs text-slate-400">Nonaktif seharian</span>
        </div>
      </div>

      <p v-if="draft" class="text-xs text-slate-500">
        Total analisis aktif: <b>{{ activeHoursPerWeek }} jam/minggu</b>. Rekap email harian sebaiknya dijadwalkan
        setelah jam nonaktif supaya data hari itu lengkap.
      </p>

      <div v-if="error" class="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
        <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />{{ error }}
      </div>
      <div v-if="success" class="flex items-start gap-2 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
        <CheckCircle2 class="mt-0.5 h-3.5 w-3.5 shrink-0" />{{ success }}
      </div>
    </CardContent>

    <CardFooter class="flex flex-col gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:justify-between">
      <Button variant="outline" size="sm" :disabled="!draft" @click="copyMondayToWeekdays">
        <Copy />
        Salin Senin ke Selasa–Jumat
      </Button>
      <div class="flex gap-2">
        <Button variant="ghost" size="sm" :disabled="!dirty || saving" @click="resetDraft">
          <RotateCcw />
          Batalkan perubahan
        </Button>
        <Button size="sm" :disabled="!dirty || hasErrors || saving" @click="save">
          <Save />
          {{ saving ? 'Menyimpan…' : 'Simpan jadwal' }}
        </Button>
      </div>
    </CardFooter>
  </Card>
</template>
