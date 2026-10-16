<script setup>
import { onMounted, ref } from 'vue';
import { FlaskConical, History, RefreshCw } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getSettingsAudit } from '@/api/settings';
import { apiSources, API_MODE } from '@/api/http';
import { resetMockDb } from '@/api/mock/db';
import { formatDateTime } from '@/lib/format';

// Riwayat perubahan pengaturan (dok. 12 §3.3: perubahan jam istirahat "dicatat").
const items = ref([]);
const loading = ref(false);
const error = ref('');
const expanded = ref({});

async function load() {
  loading.value = true;
  error.value = '';
  try {
    items.value = await getSettingsAudit(100);
  } catch (err) {
    error.value = err?.message || 'Gagal memuat riwayat.';
  } finally {
    loading.value = false;
  }
}
onMounted(load);
defineExpose({ reload: load });

function pretty(value) {
  try {
    return JSON.stringify(JSON.parse(value), null, 1);
  } catch {
    return value;
  }
}

const anyMock = () => API_MODE === 'mock' || Object.values(apiSources).includes('mock');
function resetSimulation() {
  resetMockDb();
  window.location.reload();
}
</script>

<template>
  <div class="space-y-6">
    <Card>
      <CardHeader>
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <div class="rounded-lg bg-slate-100 p-2 text-slate-700"><History class="h-5 w-5" /></div>
            <div>
              <CardTitle class="text-base font-semibold">Riwayat perubahan pengaturan</CardTitle>
              <CardDescription class="text-xs">Siapa mengubah apa dan kapan (nilai lama → baru).</CardDescription>
            </div>
          </div>
          <Button variant="outline" size="sm" :disabled="loading" @click="load">
            <RefreshCw :class="loading && 'animate-spin'" />
            Muat ulang
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <p v-if="error" class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{{ error }}</p>
        <p v-else-if="!items.length && !loading" class="py-6 text-center text-sm text-slate-400">Belum ada perubahan tercatat.</p>
        <ol class="divide-y">
          <li v-for="item in items" :key="item.id" class="py-2.5">
            <button type="button" class="flex w-full items-start justify-between gap-3 text-left" @click="expanded[item.id] = !expanded[item.id]">
              <div>
                <p class="text-sm font-medium text-slate-800">{{ item.setting }}</p>
                <p class="text-xs text-slate-500">oleh <b>{{ item.actor }}</b> · {{ formatDateTime(item.at) }}</p>
              </div>
              <span class="shrink-0 text-[11px] text-indigo-600">{{ expanded[item.id] ? 'Tutup' : 'Rincian' }}</span>
            </button>
            <div v-if="expanded[item.id]" class="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <p class="mb-1 text-[11px] font-semibold text-slate-500">Sebelum</p>
                <pre class="max-h-48 overflow-auto rounded bg-slate-50 p-2 text-[11px] text-slate-700">{{ pretty(item.old_value) }}</pre>
              </div>
              <div>
                <p class="mb-1 text-[11px] font-semibold text-slate-500">Sesudah</p>
                <pre class="max-h-48 overflow-auto rounded bg-emerald-50/60 p-2 text-[11px] text-slate-700">{{ pretty(item.new_value) }}</pre>
              </div>
            </div>
          </li>
        </ol>
      </CardContent>
    </Card>

    <Card v-if="anyMock()" class="border-dashed border-violet-300 bg-violet-50/40">
      <CardContent class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex items-start gap-2 text-sm text-violet-900">
          <FlaskConical class="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Sebagian halaman memakai data simulasi yang disimpan di browser ini. Reset untuk kembali ke data contoh awal.
          </p>
        </div>
        <Button variant="outline" size="sm" class="border-violet-300 bg-white" @click="resetSimulation">Reset data simulasi</Button>
      </CardContent>
    </Card>
  </div>
</template>
