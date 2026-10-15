<script setup>
import { computed } from 'vue';
import { identitySourceMeta } from '@/lib/format';

// Label sumber identitas (dok. 12 §3.6): face | tracking | reid | reid_retro.
// Nilai yang belum dikenal ditampilkan netral, bukan error.
const props = defineProps({
  source: { type: String, default: '' },
  short: { type: Boolean, default: false },
});

const meta = computed(() => identitySourceMeta(props.source));
</script>

<template>
  <span
    v-if="meta"
    class="inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold whitespace-nowrap"
    :class="meta.class"
    :title="meta.hint"
  >
    {{ short ? meta.short : meta.label }}
  </span>
</template>
