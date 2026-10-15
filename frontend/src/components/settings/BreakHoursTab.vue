<script setup>
import { computed, onMounted, ref } from 'vue';
import { AlertCircle, CalendarClock, CheckCircle2, Copy, Plus, RotateCcw, Save, Trash2, X } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { cancelPendingBreakHours, getBreakHours, saveBreakHours } from '@/api/settings';
import { DAY_KEYS, DAY_LABELS } from '@/api/types';
import { formatDate } from '@/lib/format';
import { describeRanges, validateRanges } from './timeRanges';

// Jam istirahat resmi per hari (dok. 12 §3.3). Kehadiran di jam ini tidak memotong
// jatah. Perubahan berlaku MULAI BESOK supaya hitungan hari ini tidak berubah di tengah jalan.
const emit = defineEmits(['changed']);

const settings = ref(null);
const draft = ref(null);
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const success = ref('');

const timeInputClass =
  'border-input h-8 w-[6.5rem] rounded-md border bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3';

function cloneDays(days) {
  return JSON.parse(JSON.stringify(days));
}

const baseline = computed(() => settings.value?.pending?.days ?? settings.value?.current?.days ?? null);
const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(baseline.value));
const errorsByDay = computed(() => {
  const out = {};
  if (!draft.value) return out;
  for (const day of DAY_KEYS) out[day] = validateRanges(draft.value[day] || []);
  return out;
});
const hasErrors = computed(() => Object.values(errorsByDay.value).some((list) => list.some(Boolean)));

async function load() {
  loading.value = true;
  error.value = '';
  try {
    settings.value = await getBreakHours();
    draft.value = cloneDays(baseline.value);
  } catch (err) {
    error.value = err?.message || 'Gagal memuat jam istirahat.';
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function addRange(day) {
  const list = draft.value[day];
  const last = list[list.length - 1];
  list.push(last ? { start: last.end, end: last.end } : { start: '12:00', end: '13:00' });
}
function removeRange(day, index) {
  draft.value[day].splice(index, 1);
}
function copyMondayToWeekdays() {
  for (const day of ['tue', 'wed', 'thu', 'fri']) draft.value[day] = cloneDays(draft.value.mon);
}
function resetDraft() {
  draft.value = cloneDays(baseline.value);
}

async function save() {
  if (hasErrors.value) return;
  saving.value = true;
  error.value = '';
  success.value = '';
  try {
    settings.value = await saveBreakHours(cloneDays(draft.value));
    draft.value = cloneDays(baseline.value);
    success.value = `Disimpan. Berlaku mulai ${formatDate(settings.value.pending?.effective_from)}.`;
    emit('changed');
  } catch (err) {
    error.value = err?.message || 'Gagal menyimpan jam istirahat.';
  } finally {
    saving.value = false;
  }
}

async function cancelPending() {
  saving.value = true;
  error.value = '';
  try {
    settings.value = await cancelPendingBreakHours();
    draft.value = cloneDays(baseline.value);
    success.value = 'Jadwal tertunda dibatalkan.';
    emit('changed');
  } catch (err) {
    error.value = err?.message || 'Gagal membatalkan jadwal tertunda.';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Card>
    <CardHeader>
      <div class="flex items-center gap-2">
        <div class="rounded-lg bg-emerald-50 p-2 text-emerald-600"><CalendarClock class="h-5 w-5" /></div>
        <div>
          <CardTitle class="text-base font-semibold">Jam istirahat resmi</CardTitle>
          <CardDescription class="text-xs">
            Kehadiran di area rekreasi pada jam ini tidak memotong jatah. Bisa berbeda per hari (mis. Jumat).
          </CardDescription>
        </div>
      </div>
    </CardHeader>

    <CardContent class="space-y-4">
      <p v-if="loading && !draft" class="py-6 text-center text-sm text-slate-400">Memuat…</p>

      <template v-if="settings">
        <div class="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2.5 text-xs text-sky-900">
          <p>
            <b>Perubahan berlaku mulai besok.</b> Jadwal hari ini tidak berubah supaya hitungan jatah yang
            sedang berjalan tetap konsisten. Setiap perubahan tercatat di tab Riwayat.
          </p>
        </div>

        <div
          v-if="settings.pending"
          class="flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 sm:flex-row sm:items-center sm:justify-between"
        >
          <p>
            Ada jadwal baru yang menunggu, berlaku mulai <b>{{ formatDate(settings.pending.effective_from) }}</b>.
            Editor di bawah menampilkan jadwal baru tersebut.
          </p>
          <Button variant="outline" size="xs" class="border-amber-300 bg-white" :disabled="saving" @click="cancelPending">
            <X />
            Batalkan jadwal baru
          </Button>
        </div>
      </template>

      <div v-if="draft" class="divide-y rounded-lg border">
        <div v-for="day in DAY_KEYS" :key="day" class="grid gap-2 px-3 py-3 sm:grid-cols-[7rem_1fr_12rem] sm:items-start">
          <div class="pt-1.5 text-sm font-medium text-slate-800">{{ DAY_LABELS[day] }}</div>
          <div class="space-y-1.5">
            <p v-if="!draft[day].length" class="pt-1.5 text-xs text-slate-400">Tidak ada jam istirahat resmi</p>
            <div v-for="(range, index) in draft[day]" :key="index" class="space-y-0.5">
              <div class="flex flex-wrap items-center gap-2">
                <input v-model="range.start" type="time" :class="timeInputClass" :aria-label="`${DAY_LABELS[day]} mulai`" />
                <span class="text-xs text-slate-400">s.d.</span>
                <input v-model="range.end" type="time" :class="timeInputClass" :aria-label="`${DAY_LABELS[day]} selesai`" />
                <Button variant="ghost" size="icon-sm" class="text-slate-400 hover:text-red-600" :aria-label="`Hapus rentang ${DAY_LABELS[day]}`" @click="removeRange(day, index)">
                  <Trash2 />
                </Button>
              </div>
              <p v-if="errorsByDay[day]?.[index]" class="text-[11px] text-red-600">{{ errorsByDay[day][index] }}</p>
            </div>
            <Button variant="ghost" size="xs" class="text-indigo-600" @click="addRange(day)">
              <Plus />
              Tambah rentang
            </Button>
          </div>
          <div class="text-[11px] text-slate-400 sm:pt-1.5 sm:text-right">
            Hari ini berlaku: {{ describeRanges(settings?.current?.days?.[day] || []) }}
          </div>
        </div>
      </div>

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
          {{ saving ? 'Menyimpan…' : 'Simpan (berlaku besok)' }}
        </Button>
      </div>
    </CardFooter>
  </Card>
</template>
