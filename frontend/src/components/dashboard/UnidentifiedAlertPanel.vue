<script setup>

import { useUnidentifiedAlerts } from '@/composables/useUnIdentifiedAlerts';
import { AlertTriangle, Video } from '@lucide/vue';

const { alerts, isLoading, loadError } = useUnidentifiedAlerts();

function severity(elapsedSeconds) {
  return elapsedSeconds >= 300 ? 'severe' : 'moderate';
}

// Butuh CameraFeedCard.vue diberi :id="`camera-${camera.id}`" di root elemennya
// supaya scroll ini benar-benar menuju kartu kamera yang dimaksud.
function scrollToCamera(cameraId) {
  const el = document.getElementById(`camera-${cameraId}`);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
</script>

<template>
  <div class="rounded-xl border bg-white shadow-xs">
    <div class="flex items-center justify-between border-b px-4 py-3">
      <h3 class="text-sm font-semibold text-slate-800">Orang Belum Dikenali</h3>
      <span
        v-if="alerts.length > 0"
        class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700"
      >
        {{ alerts.length }} aktif
      </span>
    </div>

    <div v-if="isLoading" class="px-4 py-6 text-center text-sm text-slate-400">Memuat...</div>

    <div v-else-if="loadError" class="px-4 py-6 text-center text-sm text-red-500">
      Gagal memuat: {{ loadError }}
    </div>

    <div v-else-if="alerts.length === 0" class="px-4 py-6 text-center text-sm text-slate-400">
      Tidak ada yang perlu ditinjau saat ini.
    </div>

    <ul v-else class="divide-y">
      <li
        v-for="a in alerts"
        :key="a.key"
        class="flex items-center gap-3 px-4 py-3"
        :class="severity(a.session_elapsed) === 'severe' ? 'bg-red-50/50' : ''"
      >
        <AlertTriangle
          class="h-4 w-4 shrink-0"
          :class="severity(a.session_elapsed) === 'severe' ? 'text-red-500' : 'text-amber-500'"
        />
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-slate-800">
            Track #{{ a.track_id }} di {{ a.camera_id }}
          </p>
          <p class="text-[11px] text-slate-400">Belum dikenali selama {{ a.formatted_duration }}</p>
        </div>
        <button
          class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
          @click="scrollToCamera(a.camera_id)"
        >
          <Video class="h-3 w-3" />
          Lihat kamera
        </button>
      </li>
    </ul>
  </div>
</template>