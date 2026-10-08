<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import { AlertTriangle, RefreshCw } from '@lucide/vue';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

const events = ref([]);
const isLoading = ref(false);
const loadError = ref(null);
let pollTimer = null;

async function fetchAuditLog() {
  isLoading.value = events.value.length === 0;
  try {
    const res = await fetch('/api/attendance/events?limit=100');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.status !== 'success' || !Array.isArray(json.events)) {
      throw new Error('Bentuk respons /api/attendance/events tidak dikenali');
    }

    // Bentuk ASLI dari SystemState.get_recent_events(): {timestamp, type, payload}.
    // Ini BUKAN {event_id, event_type, details} seperti skema AttendanceEvent di
    // schemas/attendance.py — endpoint ini belum memakai skema itu (tidak ada
    // response_model di route-nya), jadi kita pakai bentuk yang benar-benar
    // dikembalikan, bukan yang didefinisikan skemanya.
    events.value = json.events
      .filter((e) => e.type === 'ManualCorrectionEvent')
      .map((e) => ({ ...e.payload, _loggedAt: e.timestamp }))
      .sort((a, b) => b._loggedAt - a._loggedAt);

    loadError.value = null;
  } catch (err) {
    loadError.value = err?.message || 'Gagal memuat riwayat koreksi';
  } finally {
    isLoading.value = false;
  }
}

function formatDateTime(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

onMounted(() => {
  fetchAuditLog();
  pollTimer = setInterval(fetchAuditLog, 15000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});

defineExpose({ refetch: fetchAuditLog });
</script>

<template>
  <Card class="gap-0 py-0 shadow-xs">
    <div class="flex items-center justify-between border-b px-4 py-3">
      <h3 class="text-sm font-semibold text-slate-800">Riwayat Koreksi</h3>
      <Button
        variant="ghost"
        size="xs"
        class="text-slate-500 hover:text-slate-700"
        :disabled="isLoading"
        @click="fetchAuditLog"
      >
        <RefreshCw :class="isLoading && 'animate-spin'" />
        Refresh
      </Button>
    </div>

    <div v-if="isLoading" class="space-y-3 px-4 py-4">
      <Skeleton v-for="n in 2" :key="n" class="h-10 w-full" />
    </div>
    <div v-else-if="loadError" class="p-4">
      <Alert variant="destructive" class="border-red-200 bg-red-50">
        <AlertTriangle />
        <AlertTitle class="line-clamp-none"
          >Gagal memuat: {{ loadError }}</AlertTitle
        >
      </Alert>
    </div>
    <div
      v-else-if="events.length === 0"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
      Belum ada koreksi tercatat.
    </div>

    <ul v-else class="divide-y">
      <li v-for="c in events" :key="c.correction_id" class="px-4 py-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm font-medium text-slate-800">{{ c.corrected_by }}</p>
          <p class="text-[11px] text-slate-400">
            {{ formatDateTime(c.corrected_at) }}
          </p>
        </div>
        <p class="mt-1 text-xs text-slate-600">{{ c.reason }}</p>
        <div
          class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400"
        >
          <span v-if="c.gap_id"
            >Gap: <strong class="text-slate-600">{{ c.gap_id }}</strong></span
          >
          <span v-if="c.session_id"
            >Sesi:
            <strong class="text-slate-600">{{ c.session_id }}</strong></span
          >
          <span v-if="c.new_classification">
            Klasifikasi baru:
            <strong class="text-slate-600">{{ c.new_classification }}</strong>
          </span>
          <span v-if="c.adjustment_minutes != null">
            Penyesuaian:
            <strong class="text-slate-600">{{ c.adjustment_minutes }}m</strong>
          </span>
        </div>
        <p v-if="c.notes" class="mt-1 text-[11px] text-slate-400">
          Catatan: {{ c.notes }}
        </p>
      </li>
    </ul>
  </Card>
</template>
