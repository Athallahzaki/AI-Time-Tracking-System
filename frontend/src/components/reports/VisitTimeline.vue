<script setup>
import IdentitySourceBadge from '@/components/common/IdentitySourceBadge.vue';
import { formatDuration, formatTime } from '@/lib/format';

// Daftar kunjungan satu karyawan pada satu hari, dengan sumber identitas per segmen.
defineProps({
  segments: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
});
</script>

<template>
  <div>
    <p v-if="loading" class="py-3 text-xs text-slate-400">Memuat kunjungan…</p>
    <p v-else-if="error" class="py-3 text-xs text-red-600">{{ error }}</p>
    <p v-else-if="!segments.length" class="py-3 text-xs text-slate-400">Tidak ada rincian kunjungan.</p>
    <ol v-else class="relative space-y-2 border-l border-slate-200 pl-4">
      <li v-for="s in segments" :key="s.visit_id" class="relative">
        <span
          class="absolute top-1.5 -left-[1.3rem] h-2.5 w-2.5 rounded-full border-2 border-white"
          :class="s.identity_source === 'reid' || s.identity_source === 'reid_retro' ? 'bg-violet-500' : 'bg-indigo-500'"
        />
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span class="font-mono font-semibold text-slate-800">{{ formatTime(s.start) }}–{{ s.end ? formatTime(s.end) : 'sekarang' }}</span>
          <span class="text-slate-600">{{ s.location }}</span>
          <span class="text-slate-400">·</span>
          <span class="font-medium text-slate-700">{{ formatDuration(s.seconds) }}</span>
          <IdentitySourceBadge :source="s.identity_source" />
        </div>
      </li>
    </ol>
  </div>
</template>
