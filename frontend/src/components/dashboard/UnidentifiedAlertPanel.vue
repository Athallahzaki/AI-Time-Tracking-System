<script setup>
import { useUnidentifiedAlerts } from '@/composables/useUnidentifiedAlerts';
import { AlertTriangle, Video } from '@lucide/vue';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

const { alerts, isLoading, loadError } = useUnidentifiedAlerts();

function severity(elapsedSeconds) {
  return elapsedSeconds >= 300 ? 'severe' : 'moderate';
}

// CameraFeedCard memberi id `camera-<id>` pada root-nya, jadi scroll ini
// langsung menuju kartu kamera yang dimaksud.
function scrollToCamera(cameraId) {
  const el = document.getElementById(`camera-${cameraId}`);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
</script>

<template>
  <Card class="gap-0 py-0 shadow-xs">
    <div class="flex items-center justify-between border-b px-4 py-3">
      <h3 class="text-sm font-semibold text-slate-800">Orang Belum Dikenali</h3>
      <Badge
        v-if="alerts.length > 0"
        variant="secondary"
        class="bg-amber-100 text-[11px] text-amber-700"
      >
        {{ alerts.length }} aktif
      </Badge>
    </div>

    <div v-if="isLoading" class="space-y-3 px-4 py-4">
      <Skeleton v-for="n in 2" :key="n" class="h-9 w-full" />
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
      v-else-if="alerts.length === 0"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
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
          :class="
            severity(a.session_elapsed) === 'severe'
              ? 'text-red-500'
              : 'text-amber-500'
          "
        />
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-slate-800">
            Track #{{ a.track_id }} di {{ a.camera_id }}
          </p>
          <p class="text-[11px] text-slate-400">
            Belum dikenali selama {{ a.formatted_duration }}
          </p>
        </div>
        <Button
          variant="outline"
          size="xs"
          class="shrink-0 text-[11px] text-slate-600"
          @click="scrollToCamera(a.camera_id)"
        >
          <Video />
          Lihat kamera
        </Button>
      </li>
    </ul>
  </Card>
</template>
