<script setup>
import { ref, computed } from 'vue';
import { LayoutGrid, MonitorPlay, Radio } from '@lucide/vue';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDetectionStream } from '@/composables/useDetectionStream';
import CameraFeedCard from './CameraFeedCard.vue';

const { cameras, isConnected, isStreaming } = useDetectionStream();

const viewMode = ref('grid');
const activeCameraId = ref(cameras[0]?.id || 'cam-01');

const activeCamera = computed(
  () => cameras.find((c) => c.id === activeCameraId.value) || cameras[0],
);
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div v-if="viewMode === 'single'" class="flex items-center gap-2.5">
        <Select v-model="activeCameraId">
          <SelectTrigger class="w-75 bg-white text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="cam in cameras" :key="cam.id" :value="cam.id">
              {{ cam.code }}: {{ cam.name }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span
          v-if="isStreaming"
          class="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600 border border-emerald-200"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
          AI Vision Live
        </span>
      </div>
      <div v-else class="flex items-center gap-2.5">
        <span class="text-sm font-medium text-slate-700">
          All Facilities — Live Grid
        </span>
        <span
          v-if="isStreaming"
          class="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600 border border-emerald-200"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
          AI Vision Live
        </span>
      </div>

      <div class="flex items-center gap-1 rounded-lg border bg-white p-1">
        <button
          class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors"
          :class="
            viewMode === 'single'
              ? 'bg-slate-900 text-white'
              : 'text-slate-500 hover:bg-slate-50'
          "
          @click="viewMode = 'single'"
        >
          <MonitorPlay class="h-3.5 w-3.5" />
          Single
        </button>
        <button
          class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors"
          :class="
            viewMode === 'grid'
              ? 'bg-slate-900 text-white'
              : 'text-slate-500 hover:bg-slate-50'
          "
          @click="viewMode = 'grid'"
        >
          <LayoutGrid class="h-3.5 w-3.5" />
          Grid ({{ cameras.length }})
        </button>
      </div>
    </div>

    <CameraFeedCard v-if="viewMode === 'single'" :camera="activeCamera" />

    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
