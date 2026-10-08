<script setup>
import { ref, computed, watch } from 'vue';
import { LayoutGrid, MonitorPlay } from '@lucide/vue';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import CameraFeedCard from './CameraFeedCard.vue';

const props = defineProps({
  cameras: { type: Array, required: true },
  isConnected: { type: Boolean, default: false },
  isStreaming: { type: Boolean, default: false },
});

const viewMode = ref('grid');
const activeCameraId = ref(props.cameras[0]?.id || 'cam-01');

watch(
  () => props.cameras.map((camera) => camera.id),
  (ids) => {
    if (ids.length && !ids.includes(activeCameraId.value)) {
      activeCameraId.value = ids[0];
    }
  },
  { immediate: true },
);

// ToggleGroup tipe single mengirim undefined saat item aktif diklik lagi;
// abaikan supaya selalu ada satu mode yang terpilih.
function setViewMode(mode) {
  if (mode) viewMode.value = mode;
}

const activeCamera = computed(
  () =>
    props.cameras.find((c) => c.id === activeCameraId.value) ||
    props.cameras[0],
);
</script>

<template>
  <div class="space-y-3">
    <!-- Section Controls -->
    <div
      class="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between"
    >
      <!-- Left: Camera selector (single mode) or Title (grid mode) -->
      <div
        v-if="viewMode === 'single'"
        class="flex items-center gap-2 w-full sm:w-auto"
      >
        <Select v-model="activeCameraId">
          <SelectTrigger class="w-full bg-white text-xs sm:w-72 sm:text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="cam in cameras" :key="cam.id" :value="cam.id">
              {{ cam.code }}: {{ cam.name }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Badge
          v-if="isStreaming"
          variant="outline"
          class="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-600 sm:text-[11px]"
        >
          <span
            class="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500"
          ></span>
          Live
        </Badge>
      </div>
      <div
        v-else
        class="flex items-center justify-between sm:justify-start gap-2.5"
      >
        <span class="text-xs sm:text-sm font-medium text-slate-700">
          All Facilities — Live Grid
        </span>
        <Badge
          v-if="isStreaming"
          variant="outline"
          class="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-600 sm:text-[11px]"
        >
          <span
            class="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500"
          ></span>
          Live
        </Badge>
      </div>

      <!-- Right: View Mode Toggle -->
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        :model-value="viewMode"
        class="self-end bg-white sm:self-auto"
        @update:model-value="setViewMode"
      >
        <ToggleGroupItem
          value="single"
          aria-label="Tampilan satu kamera"
          class="px-2.5 text-xs data-[state=on]:bg-slate-900 data-[state=on]:text-white"
        >
          <MonitorPlay class="size-3.5" />
          Single
        </ToggleGroupItem>
        <ToggleGroupItem
          value="grid"
          aria-label="Tampilan grid semua kamera"
          class="px-2.5 text-xs data-[state=on]:bg-slate-900 data-[state=on]:text-white"
        >
          <LayoutGrid class="size-3.5" />
          Grid ({{ cameras.length }})
        </ToggleGroupItem>
      </ToggleGroup>
    </div>

    <!-- Feed Content -->
    <CameraFeedCard v-if="viewMode === 'single'" :camera="activeCamera" />

    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
      <CameraFeedCard
        v-for="cam in cameras"
        :key="cam.id"
        :camera="cam"
        compact
        class="cursor-pointer"
        @click="
          activeCameraId = cam.id;
          viewMode = 'single';
        "
      />
    </div>
  </div>
</template>
