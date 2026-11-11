<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Activity, Download, Play, RefreshCw, Square } from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { tableClass } from '@/components/ui/table';
import { nativeSelectClass } from '@/components/common/nativeSelect';
import { NotImplementedApiError } from '@/api/http';
import { downloadHealthCsv, getDebugHealth, getDebugLogs } from '@/api/debug';
import { formatDateTime } from '@/lib/format';

// Panel debug Fase 1: keadaan engine sebagai LAJU (bukan total kumulatif),
// supaya engine yang beku terlihat berbeda dari engine yang sepi.
const REFRESH_MS = 10_000;
const STALE_HEALTH_SECONDS = 90; // engine melapor tiap ±30 dtk

const health = ref(null);
const logs = ref([]);
const disabled = ref(false);
const error = ref('');
const loading = ref(false);
const logSource = ref('');
const logLevel = ref('INFO');
const recordingSince = ref(null);
const recordMessage = ref('');
let timer = null;

const healthStale = computed(
  () => health.value && (health.value.health_age_seconds === null || health.value.health_age_seconds > STALE_HEALTH_SECONDS),
);
const identityRates = computed(() =>
  Object.entries(health.value?.identity_per_minute || {}).sort(([a], [b]) => a.localeCompare(b)),
);

const stateClass = { online: 'bg-emerald-100 text-emerald-800', degraded: 'bg-amber-100 text-amber-800', failed: 'bg-red-100 text-red-800' };
const levelClass = { ERROR: 'text-red-700', WARNING: 'text-amber-700', INFO: 'text-slate-500' };
const IMAGE_FLAGS = { image_ir: 'mode IR', image_dark: 'gelap', image_blurry: 'buram', image_frozen: 'beku' };
// null = pemantau kondisi gambar mati di engine (image_condition.enabled: false).
const imageFlags = (metrics) =>
  metrics.image_ir === undefined
    ? null
    : Object.entries(IMAGE_FLAGS).filter(([key]) => metrics[key] === 1).map(([, label]) => label);
const fmt = (value, digits = 1) => (typeof value === 'number' ? value.toFixed(digits) : '–');
const ago = (epoch) => {
  const seconds = Math.max(0, Date.now() / 1000 - epoch);
  if (seconds < 90) return `${Math.round(seconds)} dtk lalu`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} mnt lalu`;
  return `${(seconds / 3600).toFixed(1)} jam lalu`;
};

async function refresh() {
  loading.value = true;
  try {
    [health.value, logs.value] = await Promise.all([getDebugHealth(), getDebugLogs(logSource.value, logLevel.value)]);
    error.value = '';
    disabled.value = false;
  } catch (err) {
    disabled.value = err instanceof NotImplementedApiError;
    error.value = disabled.value ? '' : err?.message || 'Gagal memuat data debug.';
  } finally {
    loading.value = false;
  }
}

function startRecording() {
  recordingSince.value = Date.now() / 1000;
  recordMessage.value = '';
}

async function stopRecording() {
  const from = recordingSince.value;
  recordingSince.value = null;
  try {
    const blob = await downloadHealthCsv(from, Date.now() / 1000);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `rekaman-kesehatan-${new Date(from * 1000).toISOString().slice(0, 19).replace(/:/g, '')}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
    recordMessage.value = 'Rekaman diunduh. Baca dengan scripts/summarize_gladi.py.';
  } catch (err) {
    recordMessage.value = err?.message || 'Gagal mengunduh rekaman.';
  }
}

watch([logSource, logLevel], refresh);
onMounted(() => {
  refresh();
  timer = setInterval(refresh, REFRESH_MS);
});
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <DashboardLayout :crumbs="['Sistem', 'Debug']">
    <div class="mx-auto max-w-6xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
            <Activity class="h-6 w-6 text-sky-600" /> Debug
          </h1>
          <p class="text-sm text-slate-500">Keadaan engine, log backend dan browser. Diperbarui tiap 10 detik.</p>
        </div>
        <Button variant="outline" :disabled="loading" @click="refresh">
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" /> Muat ulang
        </Button>
      </div>

      <Card v-if="disabled" class="p-5 text-sm text-slate-600">
        Panel debug sedang mati. Isi <code>DEBUG_PANEL_ENABLED=1</code> di lingkungan backend lalu restart
        backend untuk menyalakannya.
      </Card>
      <p v-else-if="error" role="alert" class="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>

      <template v-if="health && !disabled">
        <Card class="space-y-3 p-5">
          <div class="flex flex-wrap items-center gap-2 text-sm">
            <Badge :class="health.engine_connected ? stateClass.online : stateClass.failed">
              Engine {{ health.engine_connected ? 'tersambung' : 'terputus' }}
            </Badge>
            <Badge :class="healthStale ? stateClass.failed : 'bg-slate-100 text-slate-700'">
              {{
                health.health_age_seconds === null
                  ? 'Belum ada laporan kesehatan'
                  : `Laporan kesehatan ${Math.round(health.health_age_seconds)} dtk lalu${healthStale ? ' (basi)' : ''}`
              }}
            </Badge>
            <span class="text-slate-500">
              antrean {{ health.engine.queue_depth ?? '–' }} · outbox {{ health.engine.outbox_depth ?? '–' }} · disk
              {{ health.engine.disk_free_mb ?? '–' }} MB
            </span>
            <span v-if="health.engine.degraded_components?.length" class="text-amber-700">
              komponen turun: {{ health.engine.degraded_components.join(', ') }}
            </span>
          </div>

          <div :class="tableClass.wrapper">
            <table :class="tableClass.table">
              <caption class="sr-only">Keadaan tiap kamera</caption>
              <thead :class="tableClass.thead">
                <tr>
                  <th :class="tableClass.th">Kamera</th>
                  <th :class="tableClass.th">Status</th>
                  <th :class="tableClass.th">fps</th>
                  <th :class="tableClass.th">Lag (dtk)</th>
                  <th :class="tableClass.th">Frame basi / mnt</th>
                  <th :class="tableClass.th">Gambar</th>
                  <th :class="tableClass.th">Kejadian terakhir</th>
                </tr>
              </thead>
              <tbody :class="tableClass.tbody">
                <tr v-for="cam in health.cameras" :key="cam.camera_id" :class="tableClass.tr">
                  <td :class="tableClass.td" class="font-medium">{{ cam.camera_id }}</td>
                  <td :class="tableClass.td"><Badge :class="stateClass[cam.state]">{{ cam.state }}</Badge></td>
                  <td :class="tableClass.td">{{ fmt(cam.metrics.effective_fps) }}</td>
                  <td :class="tableClass.td">{{ fmt(cam.metrics.lag_seconds, 2) }}</td>
                  <td :class="tableClass.td">{{ fmt(cam.per_minute.frames_dropped_stale) }}</td>
                  <td :class="tableClass.td" class="text-xs">
                    <template v-if="imageFlags(cam.metrics) === null">–</template>
                    <template v-else-if="!imageFlags(cam.metrics).length">normal</template>
                    <Badge v-for="label in imageFlags(cam.metrics) || []" :key="label" :class="stateClass.degraded" class="mr-1">
                      {{ label }}
                    </Badge>
                  </td>
                  <td :class="tableClass.td" class="text-xs text-slate-600">
                    <template v-if="cam.last_event">
                      <b>{{ cam.last_event.type }}</b> · {{ ago(cam.last_event.at) }}
                      <div v-if="cam.last_event.reason" class="break-all">{{ cam.last_event.reason }}</div>
                    </template>
                    <template v-else>–</template>
                  </td>
                </tr>
                <tr v-if="!health.cameras.length">
                  <td :class="tableClass.td" colspan="7" class="text-slate-500">Engine belum melaporkan kamera.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="identityRates.length" class="text-xs text-slate-600">
            <span class="font-semibold text-slate-700">Identitas per menit:</span>
            <span v-for="[name, rate] in identityRates" :key="name" class="ml-3 whitespace-nowrap">
              {{ name }} <b :class="rate > 0 ? 'text-slate-900' : 'text-slate-400'">{{ rate }}</b>
            </span>
          </div>
        </Card>

        <Card class="p-5 text-sm">
          <div class="flex flex-wrap items-center gap-3">
          <span class="font-semibold text-slate-700">Rekam kesehatan</span>
          <Button v-if="recordingSince === null" variant="outline" @click="startRecording">
            <Play class="h-4 w-4" /> Mulai
          </Button>
          <Button v-else variant="outline" @click="stopRecording">
            <Square class="h-4 w-4" /> Hentikan &amp; unduh CSV
          </Button>
          <span v-if="recordingSince !== null" class="text-slate-600">
            Merekam sejak {{ formatDateTime(recordingSince) }}. Boleh berpindah tab; jangan tutup halaman ini.
          </span>
          <span v-else-if="recordMessage" class="flex items-center gap-1 text-slate-600">
            <Download class="h-4 w-4" /> {{ recordMessage }}
          </span>
          </div>
        </Card>

        <Card class="space-y-3 p-5">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold text-slate-700">Log</span>
            <select v-model="logSource" :class="nativeSelectClass" class="max-w-44" aria-label="Sumber log">
              <option value="">Semua sumber</option>
              <option value="backend">Backend</option>
              <option value="frontend">Browser</option>
            </select>
            <select v-model="logLevel" :class="nativeSelectClass" class="max-w-44" aria-label="Tingkat minimum">
              <option value="INFO">INFO ke atas</option>
              <option value="WARNING">WARNING ke atas</option>
              <option value="ERROR">ERROR saja</option>
            </select>
            <span class="text-xs text-slate-500">Log engine menyusul di Fase 2. Hilang saat backend restart.</span>
          </div>
          <div :class="tableClass.wrapper" class="max-h-[28rem] overflow-y-auto">
            <table :class="tableClass.table">
              <caption class="sr-only">Log backend dan browser, terbaru dulu</caption>
              <thead :class="tableClass.thead">
                <tr>
                  <th :class="tableClass.th">Waktu</th>
                  <th :class="tableClass.th">Sumber</th>
                  <th :class="tableClass.th">Tingkat</th>
                  <th :class="tableClass.th">Pesan</th>
                </tr>
              </thead>
              <tbody :class="tableClass.tbody">
                <tr v-for="(entry, index) in logs" :key="index" :class="tableClass.tr">
                  <td :class="tableClass.td" class="whitespace-nowrap text-xs">{{ formatDateTime(entry.ts) }}</td>
                  <td :class="tableClass.td" class="text-xs">{{ entry.source }} · {{ entry.logger }}</td>
                  <td :class="tableClass.td" class="text-xs font-semibold"><span :class="levelClass[entry.level]">{{ entry.level }}</span></td>
                  <td :class="tableClass.td" class="break-all font-mono text-xs">{{ entry.message }}</td>
                </tr>
                <tr v-if="!logs.length">
                  <td :class="tableClass.td" colspan="4" class="text-slate-500">Belum ada log.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      </template>
    </div>
  </DashboardLayout>
</template>
