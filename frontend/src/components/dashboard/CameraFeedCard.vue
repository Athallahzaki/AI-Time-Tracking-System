<script setup>
import { ref, computed, watch } from 'vue';
import { Circle, Camera, ScanSearch, TriangleAlert } from '@lucide/vue';
import DetectionBox from './DetectionBox.vue';

const props = defineProps({
  camera: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const videoEl = ref(null);

const videoSrc = computed(() => {
  if (!props.camera?.src) return '';
  return props.camera.src.replace(/^\.\/public\//, '/');
});

watch(
  () => props.camera.src,
  () => {
    videoEl.value?.load();
  },
);
</script>

<template>
  <div class="overflow-hidden rounded-xl border bg-white">
    <div
      class="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5"
    >
      <div class="flex items-center gap-2 text-sm font-medium text-slate-800">
        <span class="h-2 w-2 rounded-full bg-green-500"></span>
        {{ camera.code }}: {{ camera.name }}
      </div>
      <div
        v-if="!compact"
        class="flex items-center gap-3 text-xs text-slate-400"
      >
        <span>{{ camera.fps }} FPS</span>
        <span>{{ camera.latency }} Latency</span>
        <span>Model: {{ camera.model }}</span>
      </div>
    </div>

    <div class="relative aspect-video w-full bg-slate-950">
      <video
        ref="videoEl"
        class="h-full w-full object-cover opacity-90"
        autoplay
        muted
        loop
        playsinline
      >
        <source :src="videoSrc" type="video/mp4" />
      </video>

      <div
        class="absolute left-3 top-3 flex items-center gap-1.5 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-white pointer-events-none"
      >
        <Circle class="h-2 w-2 fill-red-500 text-red-500" />
        REC · {{ camera.code }} LIVE STREAM
      </div>

      <div
        class="absolute right-3 top-3 rounded bg-black/60 px-2 py-1 text-[10px] font-medium pointer-events-none"
        :class="
          camera.detections?.length ? 'text-emerald-300' : 'text-slate-300'
        "
      >
        <span v-if="!compact">POSE_ESTIMATION: </span>
        {{ camera.detections?.length ? `ACTIVE (${camera.fps} FPS)` : 'IDLE' }}
      </div>

      <!-- Real-time Bounding Boxes -->
      <DetectionBox
        v-for="(d, i) in camera.detections"
        :key="d.id ?? d.track_id ?? i"
        :detection="d"
        :compact="compact"
      />

      <div
        v-if="!compact"
        class="absolute bottom-3 left-3 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-slate-200 pointer-events-none"
      >
        FOV {{ camera.fov }}
      </div>
      <div
        v-if="compact"
        class="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-white pointer-events-none"
      >
        {{ camera.detections?.length || 0 }} detected
      </div>
    </div>

    <!-- Footer info bar -->
    <div
      v-if="!compact"
      class="flex flex-wrap items-center gap-x-8 gap-y-3 border-t px-4 py-3 text-xs"
    >
      <div>
        <p class="text-slate-400">Stream Status</p>
        <p class="mt-0.5 flex items-center gap-1 font-medium text-slate-700">
          <span class="h-1.5 w-1.5 rounded-full bg-green-500"></span>
          {{ camera.streamStatus }}
        </p>
      </div>
      <div>
        <p class="text-slate-400">Classified Activity</p>
        <p class="mt-0.5 font-medium text-slate-700">{{ camera.activity }}</p>
      </div>
      <div>
        <p class="text-slate-400">Tracking IDs</p>
        <p class="mt-0.5 font-medium text-slate-700">
          {{ camera.trackingIds }}
        </p>
      </div>
      <div>
        <p class="text-slate-400">Max Active Session</p>
        <p class="mt-0.5 font-medium text-slate-700">{{ camera.maxSession }}</p>
      </div>

      <div class="ml-auto flex items-center gap-2">
        <button
          class="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-slate-600 hover:bg-slate-50"
        >
          <Camera class="h-3.5 w-3.5" />
          Snapshot Frame
        </button>
        <button
          class="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-slate-600 hover:bg-slate-50"
        >
          <ScanSearch class="h-3.5 w-3.5" />
          Inspect Bounding Boxes
        </button>
        <button
          class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-medium text-red-500 hover:bg-red-50"
        >
          <TriangleAlert class="h-3.5 w-3.5" />
          Trigger Manual Warning
        </button>
      </div>
    </div>
  </div>
</template>
