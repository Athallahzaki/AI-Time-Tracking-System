<script setup>
import { ShieldCheck } from '@lucide/vue';
import { cn } from '@/lib/utils';

// Logo + nama aplikasi. Dipakai di sidebar dan halaman login supaya identitasnya
// identik di kedua tempat. `inverted` untuk latar gelap (panel kiri login).
const props = defineProps({
  inverted: { type: Boolean, default: false },
  class: { type: String, default: '' },
});
</script>

<template>
  <div :class="cn('flex items-center gap-2.5', props.class)">
    <div
      class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
      :class="inverted ? 'bg-white text-slate-900' : 'bg-slate-900 text-white'"
    >
      <ShieldCheck class="h-5 w-5" />
    </div>
    <div class="leading-tight">
      <p
        class="text-sm font-semibold"
        :class="inverted ? 'text-white' : 'text-slate-900'"
      >
        Hotel Murah
      </p>
      <p
        class="text-xs"
        :class="inverted ? 'text-slate-400' : 'text-slate-500'"
      >
        AI Time Tracking
      </p>
    </div>
  </div>
</template>
